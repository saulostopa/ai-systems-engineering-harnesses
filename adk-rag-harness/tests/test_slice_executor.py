import difflib
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from feature_planner.model_router import ModelReply
    from feature_planner.slice_executor import ApprovedSlice, DependencyReceipt, ExecutionBlocked, build_slice_executor
    from feature_planner.workflow import EXECUTE_APPROVED_SLICE, build_workflow


@unittest.skipUnless(HAS_ADK, "requires optional ADK dependencies")
class SliceExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()

        def git(*args):
            return subprocess.check_output(["git", *args], cwd=self.checkout, text=True).strip()

        git("init", "--initial-branch=pilot")
        (self.checkout / "config.ts").write_text("export const enabled = true;\n")
        (self.checkout / "outside.ts").write_text("export const untouched = true;\n")
        lock = self.checkout / "package-lock.json"
        lock.write_text("{}\n")
        git("add", ".")
        git("add", "--force", "package-lock.json")
        git("-c", "user.name=Test", "-c", "user.email=test@example.test", "-c", "commit.gpgsign=false", "commit", "-m", "base")
        deps = self.root / "node_modules"
        deps.mkdir()
        (self.root / "package-lock.json").write_bytes(lock.read_bytes())
        plan = self.root / "execution.json"
        plan.write_text(json.dumps({
            "invocation_id": "e-approved", "status": "accepted",
            "plan": {"slices": [{"id": "config", "scope": ["config.ts"], "depends_on": []}]},
            "slices": [{"slice_id": "config", "verdict": "accept"}],
        }))
        evals = self.root / "eval-results.json"
        evals.write_text(json.dumps({"invocation_id": "e-approved", "planning_evidence_status": "passed"}))
        patch_file = self.root / "approved.patch"
        patch_file.write_text("".join(difflib.unified_diff(
            ["export const enabled = true;\n"], ["export const enabled = false;\n"],
            fromfile="a/config.ts", tofile="b/config.ts",
        )))
        self.policy = ApprovedSlice(
            version=1, user_id="owner", session_id="s-approved", plan_invocation="e-approved",
            slice_id="config", worktree=self.checkout, branch="pilot", base_commit=git("rev-parse", "HEAD"),
            allowed_files=("config.ts",), plan_bundle=self.root, plan_sha256=self.digest(plan.read_bytes()),
            eval_sha256=self.digest(evals.read_bytes()), patch_path=patch_file,
            patch_sha256=self.digest(patch_file.read_bytes()),
            postimages={"config.ts": self.digest(b"export const enabled = false;\n")},
            dependency_dir=deps, dependency_lock_sha256=self.digest(lock.read_bytes()), node_path=Path(sys.executable),
        )

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def test_denies_other_session_mutated_approval_and_file_outside_scope(self):
        with self.assertRaisesRegex(ExecutionBlocked, "sessão"):
            self.policy.prepare("another-user", "s-approved")
        original = self.policy.patch_path.read_bytes()
        malicious = original.replace(b"config.ts", b"outside.ts")
        self.policy.patch_path.write_bytes(malicious)
        with self.assertRaisesRegex(ExecutionBlocked, "conteúdo aprovado"):
            self.policy.prepare("owner", "s-approved")
        rebound = self.policy.model_copy(update={"patch_sha256": self.digest(malicious)})
        with self.assertRaisesRegex(ExecutionBlocked, "fora da aprovação"):
            rebound.prepare("owner", "s-approved")
        self.assertEqual((self.checkout / "outside.ts").read_text(), "export const untouched = true;\n")
        self.assertFalse(list(self.root.glob("*.claimed")))

    def test_allows_only_named_consent_routes_when_directories_are_new(self):
        def create_patch(name):
            content = "export const runtime = 'nodejs';\n"
            patch = f"diff --git a/{name} b/{name}\nnew file mode 100644\n"
            patch += "".join(difflib.unified_diff([], [content], "/dev/null", f"b/{name}"))
            self.policy.patch_path.write_text(patch)
            return self.policy.model_copy(update={
                "new_files": (name,), "allowed_files": (name,),
                "patch_sha256": self.digest(patch.encode()),
                "postimages": {name: self.digest(content.encode())},
            })

        route = "src/app/catalogo/bff/api/consent/decision/route.ts"
        self.assertTrue(create_patch(route)._checked_patch())
        other = "src/app/catalogo/bff/api/consent/unapproved/route.ts"
        with self.assertRaises(ExecutionBlocked):
            create_patch(other)._checked_patch()

    def test_lockfile_checks_distinguish_before_and_after_patch(self):
        checkout_lock = self.checkout / "package-lock.json"
        fixture_lock = self.root / "package-lock.json"
        new_content = b'{"name": "updated"}\n'
        fixture_lock.write_bytes(new_content)
        policy = self.policy.model_copy(update={
            "post_dependency_lock_sha256": self.digest(new_content),
        })
        policy._check_lockfiles(after_apply=False)
        with self.assertRaisesRegex(ExecutionBlocked, "lockfile diverge"):
            policy._check_lockfiles(after_apply=True)
        checkout_lock.write_bytes(new_content)
        policy._check_lockfiles(after_apply=True)
        fixture_lock.write_bytes(b"tampered")
        with self.assertRaisesRegex(ExecutionBlocked, "lockfile diverge"):
            policy._check_lockfiles(after_apply=True)

    def test_dependent_slice_requires_unchanged_passed_receipt(self):
        plan = self.root / "execution.json"
        payload = json.loads(plan.read_text())
        payload["plan"]["slices"].append({
            "id": "layout", "scope": ["outside.ts"], "depends_on": ["config"],
        })
        payload["slices"].append({"slice_id": "layout", "verdict": "accept"})
        plan.write_text(json.dumps(payload))
        parent = self.policy.model_copy(update={"plan_sha256": self.digest(plan.read_bytes())})
        parent.apply("owner", "s-approved", "e-parent-write")
        receipt = self.root / "slice-execution.json"
        receipt.write_text(json.dumps({
            "slice_id": "config", "invocation_id": "e-parent-write", "status": "passed",
            "plan_invocation": parent.plan_invocation, "base_commit": parent.base_commit, "branch": parent.branch,
            "authorized_files": ["config.ts"], "diff_sha256": self.digest(parent.checked_diff()),
        }))
        patch_path = self.root / "layout.patch"
        content = "export const untouched = false;\n"
        patch_path.write_text("".join(difflib.unified_diff(
            ["export const untouched = true;\n"], [content], fromfile="a/outside.ts", tofile="b/outside.ts",
        )))
        child = parent.model_copy(update={
            "slice_id": "layout", "allowed_files": ("outside.ts",), "patch_path": patch_path,
            "patch_sha256": self.digest(patch_path.read_bytes()),
            "postimages": {"outside.ts": self.digest(content.encode())},
        })
        with self.assertRaisesRegex(ExecutionBlocked, "todas as dependências"):
            child.prepare("owner", "s-approved")
        child = child.model_copy(update={
            "dependencies": (DependencyReceipt(artifact=receipt, sha256=self.digest(receipt.read_bytes())),),
        })
        _, proof = child.prepare("owner", "s-approved")
        self.assertEqual(proof[0]["invocation_id"], "e-parent-write")
        (self.checkout / "config.ts").write_text("export const enabled = 'modified';\n")
        with self.assertRaisesRegex(ExecutionBlocked, "diff da dependência mudou"):
            child.prepare("owner", "s-approved")
        (self.checkout / "config.ts").write_text("export const enabled = false;\n")
        child.apply("owner", "s-approved", "e-child-write")
        diff = child.checked_diff()
        self.assertIn(b"outside.ts", diff)
        self.assertNotIn(b"config.ts", diff)

    def test_checkpoint_allows_lineage_overlap_and_only_named_new_component(self):
        plan = self.root / "execution.json"
        payload = json.loads(plan.read_text())
        payload["plan"]["slices"].append({
            "id": "banner", "scope": ["config.ts"], "depends_on": ["config"],
        })
        payload["slices"].append({"slice_id": "banner", "verdict": "accept"})
        plan.write_text(json.dumps(payload))
        parent = self.policy.model_copy(update={"plan_sha256": self.digest(plan.read_bytes())})
        parent.apply("owner", "s-approved", "e-parent-write")
        receipt = self.root / "slice-execution.json"
        receipt.write_text(json.dumps({
            "slice_id": "config", "invocation_id": "e-parent-write", "status": "passed",
            "plan_invocation": parent.plan_invocation, "base_commit": parent.base_commit, "branch": parent.branch,
            "authorized_files": ["config.ts"], "diff_sha256": self.digest(parent.checked_diff()),
        }))
        new = "src/components/Banner.tsx"
        (self.checkout / new).parent.mkdir(parents=True)
        path = self.root / "banner.patch"
        after = b"export const enabled = false;\nexport const banner = true;\n"
        created = b"export const Banner = () => null;\n"
        path.write_bytes(
            b"diff --git a/config.ts b/config.ts\n--- a/config.ts\n+++ b/config.ts\n"
            b"@@ -1 +1,2 @@\n export const enabled = false;\n+export const banner = true;\n"
            + f"diff --git a/{new} b/{new}\nnew file mode 100644\n--- /dev/null\n+++ b/{new}\n".encode()
            + b"@@ -0,0 +1 @@\n+" + created
        )
        child = parent.model_copy(update={
            "slice_id": "banner", "allowed_files": ("config.ts", new), "new_files": (new,),
            "patch_path": path, "patch_sha256": self.digest(path.read_bytes()),
            "postimages": {"config.ts": self.digest(after), new: self.digest(created)},
            "baseline_files": {"config.ts": self.digest(b"export const enabled = false;\n")},
            "dependencies": (DependencyReceipt(artifact=receipt, sha256=self.digest(receipt.read_bytes())),),
        })
        (self.checkout / "config.ts").write_text("export const enabled = 'drift';\n")
        with self.assertRaisesRegex(ExecutionBlocked, "conteúdo da dependência mudou"):
            child.prepare("owner", "s-approved")
        (self.checkout / "config.ts").write_text("export const enabled = false;\n")
        child.apply("owner", "s-approved", "e-banner-write")
        self.assertEqual(child.checked_diff(), path.read_bytes())
        self.assertEqual((self.checkout / new).read_bytes(), created)

    async def test_adk_runs_authorized_slice_and_publishes_verified_diff(self):
        sessions = InMemorySessionService()
        artifacts = InMemoryArtifactService()
        workflow = build_workflow(None, None, executor=build_slice_executor(self.policy))
        await sessions.create_session(app_name="feature_planner", user_id="owner", session_id="s-approved")
        async with Runner(app_name="feature_planner", agent=workflow, session_service=sessions,
                          artifact_service=artifacts) as runner:
            review = AsyncMock(return_value=ModelReply({"verdict": "accept", "finding": "Supported."}))
            with patch("feature_planner.slice_executor.codex", review), patch.object(
                ApprovedSlice, "check", return_value=[{"id": "fixture", "exit_code": 0}],
            ):
                async for _ in runner.run_async(user_id="owner", session_id="s-approved", new_message=types.Content(
                    role="user", parts=[types.Part(text=EXECUTE_APPROVED_SLICE)],
                )):
                    pass
        review.assert_awaited_once()
        check = await artifacts.load_artifact(app_name="feature_planner", user_id="owner",
                    session_id="s-approved", filename="slice-execution.json")
        self.assertIsNotNone(check)
        result = json.loads(check.inline_data.data)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["plan_invocation"], "e-approved")
        self.assertEqual(result["diff_sha256"], self.digest(self.policy.checked_diff()))
        self.assertEqual((self.checkout / "config.ts").read_text(), "export const enabled = false;\n")
        self.assertTrue(list(self.root.glob("*.claimed")))
        with self.assertRaises(ExecutionBlocked):
            self.policy.apply("owner", "s-approved", "e-second")
        (self.checkout / "config.ts").write_text("export const enabled = false;\nexport const changed = 1;\n")
        with self.assertRaisesRegex(ExecutionBlocked, "conteúdo verificado"):
            self.policy.checked_diff()
