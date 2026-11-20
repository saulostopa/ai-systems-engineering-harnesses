import asyncio
import importlib.util
import json
import unittest

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from feature_planner.agent import demo_search
    from feature_planner.workflow import build_workflow


def proposed_slice(slice_id, **overrides):
    return {
        "id": slice_id,
        "outcome": "Filter tasks by status.",
        "acceptance": ["The list shows only tasks with the selected status."],
        "evidence_ids": ["E1"],
        "depends_on": [],
        **overrides,
    }


@unittest.skipUnless(HAS_ADK, "requires the optional ADK dependency")
class FeaturePlannerTests(unittest.IsolatedAsyncioTestCase):
    async def run_plan(self, slices, verifier, on_event=None, mission="Add a task list status filter"):
        async def planner(schema, prompt, data):
            return {"version": 1, "slices": slices}

        sessions = InMemorySessionService()
        artifacts = InMemoryArtifactService()
        async with Runner(
            app_name="feature_planner", agent=build_workflow(demo_search, planner, verifier),
            session_service=sessions, artifact_service=artifacts,
        ) as runner:
            session = await sessions.create_session(app_name="feature_planner", user_id="test")
            async def consume_events():
                async for event in runner.run_async(
                    user_id="test", session_id=session.id,
                    new_message=types.Content(role="user", parts=[types.Part(text=mission)]),
                ):
                    if on_event:
                        on_event(event)

            await asyncio.wait_for(consume_events(), timeout=6)
            persisted = await sessions.get_session(app_name="feature_planner", user_id="test", session_id=session.id)
            artifact = await artifacts.load_artifact(
                app_name="feature_planner", user_id="test", session_id=session.id, filename="workflow-spec.json",
            )
        return persisted.state["feature_planning"], artifact

    async def test_parallel_results_stream_before_join_and_spec_has_real_evidence(self):
        slow_worker_started = asyncio.Event()
        fast_worker_finished = asyncio.Event()

        async def verifier(schema, prompt, data):
            if "slice" in data:
                if data["slice"]["id"] == "pagination":
                    slow_worker_started.set()
                    await fast_worker_finished.wait()
                else:
                    await slow_worker_started.wait()
            return {"verdict": "accept", "finding": "Matches the evidence."}

        def observe(event):
            if (event.content and event.content.parts
                    and event.content.parts[0].text == "filter · 1 · accept"):
                fast_worker_finished.set()

        state, artifact = await self.run_plan(
            [proposed_slice("filter"), proposed_slice("pagination", outcome="Preserve pagination filters.")],
            verifier,
            observe,
        )
        self.assertTrue(fast_worker_finished.is_set())
        self.assertEqual(state["status"], "accepted")
        spec = json.loads(artifact.inline_data.data)
        self.assertEqual(spec["slices"][0]["scope"], ["task-list.md"])
        self.assertEqual(spec["sources"][0]["path"], "task-list.md")
        self.assertGreater(spec["sources"][0]["end_line"], 1)

    async def test_invalid_specs_never_dispatch(self):
        async def verifier(*args):
            self.fail("Invalid specs must never reach a verifier.")

        for slices in (
            [proposed_slice("one", evidence_ids=["E999"])],
            [proposed_slice("one", scope=["../other.md"])],
            [proposed_slice("one", depends_on=["one"])],
            [proposed_slice("one"), proposed_slice("one")],
        ):
            with self.subTest(slices=slices):
                state, artifact = await self.run_plan(slices, verifier)
                self.assertEqual(state["status"], "blocked")
                self.assertIsNone(artifact)

    async def test_retry_is_bounded_and_failed_slice_skips_dependency(self):
        attempts = []

        async def verifier(schema, prompt, data):
            attempts.append((data["slice"]["id"], data["attempt"]))
            return {"verdict": "retry", "finding": "Insufficient support."}

        state, _ = await self.run_plan(
            [proposed_slice("first"), proposed_slice("next", depends_on=["first"])], verifier,
        )
        self.assertEqual(attempts, [("first", 1), ("first", 2)])
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(state["results"]["next"]["verdict"], "skipped")

    async def test_missing_evidence_never_dispatches(self):
        async def verifier(*args):
            self.fail("A request with no evidence must never reach a verifier.")

        state, artifact = await self.run_plan([], verifier, mission="zxxyqqw")
        self.assertEqual(state["status"], "clarify")
        self.assertIsNone(artifact)
