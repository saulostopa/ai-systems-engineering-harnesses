import asyncio
import importlib.util
import json
import unittest
from unittest.mock import patch

HAS_ADK = importlib.util.find_spec("google") is not None and importlib.util.find_spec("google.adk") is not None
if HAS_ADK:
    from google.adk.artifacts import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from feature_planner.agent import demo_search
    from feature_planner.evidence import _execution, _postgres_receipt
    from feature_planner.evidence_views import faq, replay, token_report
    from feature_planner.model_clients import _claude_reply
    from feature_planner.model_router import FailureReason, ModelFailure, ModelReply, ModelRouter, RoutingConfig
    from feature_planner.workflow import build_workflow, validate_spec


def proposed_slice(slice_id, **overrides):
    return {
        "id": slice_id,
        "outcome": "Filter tasks by status.",
        "acceptance": ["The list shows only tasks with the selected status."],
        "evidence_ids": ["E1"],
        "depends_on": [],
        **overrides,
    }


def slice_report(evidence_ids=("E1",)):
    return {"findings": [{"observation": "Matches the indexed behavior.", "evidence_ids": list(evidence_ids)}],
            "gaps": []}


@unittest.skipUnless(HAS_ADK, "requires the optional ADK dependency")
class FeaturePlannerTests(unittest.IsolatedAsyncioTestCase):
    async def run_plan(
        self, slices, verifier, on_event=None, mission="Add a task list status filter", router=None,
        search=demo_search if HAS_ADK else None, publisher=None, *, worker=None, max_slices=5,
    ):
        async def model(route, schema, prompt, data):
            if route.model == "planner":
                self.assertIn(f"at most {max_slices}", prompt)
                self.assertEqual(schema.model_json_schema()["properties"]["slices"]["maxItems"], max_slices)
                value = {"version": 1, "slices": slices}
            elif schema.__name__ == "SliceReport":
                value = await worker(data) if worker else slice_report()
            else:
                value = await verifier(schema, prompt, data)
            return ModelReply(value)

        if router is None:
            planner = [{"provider": "ollama", "model": "planner"}]
            review = [{"provider": "ollama", "model": "verifier"}]
            config = RoutingConfig(planner=planner, slice_verifier=review, global_evaluator=review)
            router = ModelRouter(config, {"ollama": model})

        sessions = InMemorySessionService()
        artifacts = InMemoryArtifactService()
        async with Runner(
            app_name="feature_planner", agent=build_workflow(search, router, publisher, max_slices=max_slices),
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
        node_paths = []

        async def verifier(schema, prompt, data):
            if "slice" in data:
                if data["slice"]["id"] == "pagination":
                    slow_worker_started.set()
                    await fast_worker_finished.wait()
                else:
                    await slow_worker_started.wait()
            return {"verdict": "accept", "finding": "Matches the evidence."}

        def observe(event):
            node_paths.append(event.node_info.path or "")
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
        for node in ("attempt_slice", "verify_slice", "record_slice"):
            self.assertTrue(any("slice_investigation" in path and node in path for path in node_paths), node)
        self.assertTrue(any("synthesize_feature" in path for path in node_paths))
        spec = json.loads(artifact.inline_data.data)
        self.assertEqual(spec["slices"][0]["scope"], ["task-list.md"])
        self.assertEqual(spec["sources"][0]["path"], "task-list.md")
        self.assertGreater(spec["sources"][0]["end_line"], 1)

    async def test_model_details_correlate_with_terminal_events_and_omit_free_text(self):
        provider = TracerProvider()
        self.addCleanup(provider.shutdown)
        spans = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(spans))
        completed_events = []

        def observe(event):
            metadata = event.actions.state_delta.get("feature_model_route", {})
            if metadata.get("status") == "succeeded":
                completed_events.append(event)

        async def verify(*args):
            return {"verdict": "accept", "finding": "private review text"}

        with patch("feature_planner.model_trace._TRACER", provider.get_tracer("test")):
            await self.run_plan(
                [proposed_slice("filter", outcome="private planner prose")],
                verify, observe, mission="Add a task list status filter, private mission text",
                search=lambda _: [{"id": "E1", "path": "example.md", "text": "private indexed text"}],
            )

        by_id = {span.attributes["gcp.vertex.agent.event_id"]: span for span in spans.get_finished_spans()}
        self.assertEqual(set(by_id), {event.id for event in completed_events})
        self.assertEqual(len(by_id), 4)
        outputs = {}
        for event in completed_events:
            attrs = by_id[event.id].attributes
            request = json.loads(attrs["gcp.vertex.agent.llm_request"])
            response = json.loads(attrs["gcp.vertex.agent.llm_response"])
            self.assertEqual(attrs["gcp.vertex.agent.invocation_id"], event.invocation_id)
            self.assertNotIn("private ", json.dumps([request, response]))
            expected_refs = [] if request["role"] == "global_evaluator" else ["E1"]
            self.assertEqual(request["evidence_ids"], expected_refs)
            outputs[request["role"]] = response["output"]
        self.assertEqual(outputs["planner"]["slices"][0]["id"], "filter")
        self.assertEqual(outputs["slice_verifier"]["verdict"], "accept")

    @unittest.skipUnless(importlib.util.find_spec("psycopg"), "requires optional Postgres dependency")
    def test_reference_projects_share_query_embedding_but_do_not_expand_write_scope(self):
        from feature_planner.postgres import PostgresSearch

        class SnapshotStore:
            def planning_snapshot(self, project, query, vector, model, top_k, *, docs_top_k=0):
                row = {
                    "path": "app.py" if project == "catalog" else "reference.py",
                    "indexed_text": project, "start_line": 1, "end_line": 2,
                    "chunk_id": 1, "content_hash": "chunk", "file_hash": "file",
                    "embedding_dimensions": 1024, "semantic_rank": 1, "lexical_rank": 1,
                }
                self.calls.append((project, query, vector, model, top_k, docs_top_k))
                return {"chunks": 1, "utf8_bytes": len(project)}, [row]

            calls = []

        class Embedder:
            model_id = "test:embeddings"

        store = SnapshotStore()
        search = PostgresSearch(
            "catalog", store=store, embedder=Embedder(), references=("fipe", "harness", "fipe"), target_top_k=10,
        )
        with patch.object(search, "embed_query", return_value=[0.25]) as embed:
            evidence, receipt = search("port SDK")
        embed.assert_called_once()
        self.assertEqual([call[0] for call in store.calls], ["catalog", "fipe", "harness"])
        # A third of each budget, rounded down, is kept for documentation.
        self.assertEqual([call[-2:] for call in store.calls], [(10, 3), (4, 1), (4, 1)])
        self.assertEqual(receipt["strategy"], "hybrid per collection")
        self.assertEqual([chunk["origin"] for chunk in receipt["retrieved"]], ["target", "reference", "reference"])
        self.assertEqual(receipt["baseline"]["chunks"], 3)
        self.assertEqual(receipt["project_baselines"]["fipe"]["chunks"], 1)
        result = validate_spec({"version": 1, "slices": [proposed_slice("port", evidence_ids=["E1", "E2", "E3"])]}, evidence)
        self.assertEqual(result.slices[0].scope, ["app.py"])

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
        worker_feedback = []

        async def worker(data):
            worker_feedback.append(data["previous_finding"])
            return slice_report()

        async def verifier(schema, prompt, data):
            attempts.append((data["slice"]["id"], data["attempt"]))
            self.assertEqual(data["report"], slice_report())
            return {"verdict": "retry", "finding": "Insufficient support."}

        state, _ = await self.run_plan(
            [proposed_slice("first"), proposed_slice("next", depends_on=["first"])], verifier, worker=worker,
        )
        self.assertEqual(attempts, [("first", 1), ("first", 2)])
        self.assertEqual(worker_feedback, [None, "Insufficient support."])
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(state["results"]["next"]["verdict"], "skipped")

    async def test_missing_evidence_never_dispatches(self):
        async def verifier(*args):
            self.fail("A request with no evidence must never reach a verifier.")

        state, artifact = await self.run_plan([], verifier, mission="zxxyqqw")
        self.assertEqual(state["status"], "clarify")
        self.assertIsNone(artifact)

    async def test_quota_fallback_is_observable_and_scoped_to_the_invocation(self):
        calls = []
        events = []
        chain = [{"provider": "claude-code", "model": "claude-opus-5-5"},
                 {"provider": "codex", "model": "gpt-6-sol"}]

        async def claude(route, schema, prompt, data):
            calls.append((route.provider, schema.__name__))
            return _claude_reply(1, [{"type": "rate_limit_event", "rate_limit_info": {
                "status": "rejected", "errorCode": "credits_required",
            }}])

        async def fallback(route, schema, prompt, data):
            calls.append((route.provider, schema.__name__))
            if schema.__name__ == "WorkflowProposal":
                value = {"version": 1, "slices": [proposed_slice("filter")]}
            elif schema.__name__ == "SliceReport":
                value = slice_report()
            else:
                value = {"verdict": "accept", "finding": "Matches the evidence."}
            return ModelReply(value, {"input_tokens": 120})

        def observe(event):
            metadata = event.actions.state_delta.get("feature_model_route")
            if metadata:
                events.append(metadata)

        config = RoutingConfig(planner=chain, slice_verifier=chain, global_evaluator=chain)
        router = ModelRouter(config, {"claude-code": claude, "codex": fallback})
        for _ in range(2):
            state, _ = await self.run_plan([], None, observe, router=router)
            self.assertEqual(state["status"], "accepted")
        self.assertEqual(calls, [
            ("claude-code", "WorkflowProposal"), ("codex", "WorkflowProposal"),
            ("codex", "SliceReport"), ("codex", "Review"), ("codex", "Review"),
        ] * 2)
        self.assertEqual([event["status"] for event in events], [
            "started", "quota_exhausted", "started", "succeeded",
            "skipped_quota", "started", "succeeded", "skipped_quota", "started", "succeeded",
            "skipped_quota", "started", "succeeded",
        ] * 2)
        self.assertEqual(events[3]["usage"], {"input_tokens": 120})

    async def test_transient_verifier_failure_reuses_worker_report_and_then_uses_configured_fallback(self):
        calls = []
        events = []

        async def primary(route, schema, prompt, data):
            target = data.get("slice", {}).get("id")
            calls.append((route.model, target))
            if route.model == "planner":
                return ModelReply({
                    "version": 1, "slices": [
                        proposed_slice("first"), proposed_slice("next", depends_on=["first"]),
                    ],
                })
            if route.model == "worker":
                return ModelReply(slice_report())
            if route.model == "verifier" and target == "first":
                raise ModelFailure("unavailable", {"output_tokens": 7}, reason=FailureReason.TIMEOUT)
            return ModelReply({"verdict": "accept", "finding": "Supported."})

        async def fallback(route, schema, prompt, data):
            calls.append((route.model, data["slice"]["id"]))
            self.assertEqual(data["report"], slice_report())
            return ModelReply({"verdict": "accept", "finding": "Supported."})

        def observe(event):
            if route := event.actions.state_delta.get("feature_model_route"):
                events.append(route)

        config = RoutingConfig(
            planner=[{"provider": "ollama", "model": "planner"}],
            slice_worker=[{"provider": "ollama", "model": "worker"}],
            slice_verifier=[{"provider": "ollama", "model": "verifier"}, {"provider": "codex", "model": "configured"}],
            global_evaluator=[{"provider": "ollama", "model": "global"}],
        )
        router = ModelRouter(config, {"ollama": primary, "codex": fallback})
        state, _ = await self.run_plan([], None, observe, router=router)
        self.assertEqual(state["status"], "accepted")
        self.assertEqual(calls, [
            ("planner", None), ("worker", "first"), ("verifier", "first"), ("verifier", "first"),
            ("configured", "first"), ("worker", "next"), ("verifier", "next"), ("global", None),
        ])
        first_checks = [e for e in events
                        if e["role"] == "slice_verifier" and e["slice_id"] == "first" and e["status"] != "started"]
        self.assertEqual(
            [(e["attempt"], e["provider_attempt"], e["failure_reason"]) for e in first_checks],
            [(1, 1, "timeout"), (1, 2, "timeout"), (2, 1, None)],
        )
        self.assertEqual([e["usage"].get("output_tokens") for e in first_checks], [7, 7, None])

    async def test_review_roles_fallback_after_turn_limit(self):
        chain = [
            {"provider": "claude-code", "model": "claude-haiku-5-5", "max_turns": 4},
            {"provider": "codex", "model": "gpt-6-sol"},
        ]

        async def fail(*args):
            raise ModelFailure("unavailable", reason=FailureReason.TURN_LIMIT)

        async def fallback(*args):
            return ModelReply({"verdict": "accept", "finding": "Supported."})

        router = ModelRouter(
            RoutingConfig(planner=chain, slice_verifier=chain, global_evaluator=chain),
            {"claude-code": fail, "codex": fallback},
        )
        from feature_planner.workflow import Review

        for role in ("slice_verifier", "global_evaluator", "planner"):
            with self.subTest(role=role):
                outcomes = [attempt async for attempt in router.attempts(role, Review, "", {}, set())
                            if attempt.status != "started"]
                expected = ["unavailable"] if role == "planner" else ["unavailable", "unavailable", "succeeded"]
                self.assertEqual([attempt.status for attempt in outcomes], expected)
                self.assertEqual(outcomes[0].metadata()["max_turns"], 4)

    async def test_verifier_failures_do_not_reinvestigate_or_fallback_for_refusal_or_bad_schema(self):
        for failure, expected_calls in (
            (FailureReason.REFUSAL, 1), (FailureReason.STRUCTURED_OUTPUT_RETRIES_EXHAUSTED, 2),
        ):
            calls = []

            async def primary(route, schema, prompt, data):
                calls.append(route.model)
                if route.model == "planner":
                    return ModelReply({"version": 1, "slices": [proposed_slice("first")]})
                if route.model == "worker":
                    return ModelReply(slice_report())
                kind = "unavailable" if failure == FailureReason.REFUSAL else "invalid_output"
                raise ModelFailure(kind, reason=failure)

            async def unexpected(*args):
                self.fail("This error must stay with the original provider.")

            config = RoutingConfig(
                planner=[{"provider": "ollama", "model": "planner"}],
                slice_worker=[{"provider": "ollama", "model": "worker"}],
                slice_verifier=[{"provider": "ollama", "model": "verifier"}, {"provider": "codex", "model": "configured"}],
                global_evaluator=[{"provider": "codex", "model": "configured"}],
            )
            router = ModelRouter(config, {"ollama": primary, "codex": unexpected})
            with self.subTest(reason=failure):
                state, _ = await self.run_plan([], None, router=router)
                self.assertEqual(state["status"], "needs_review")
                self.assertEqual(calls, ["planner", "worker"] + ["verifier"] * expected_calls)

    async def test_non_quota_failure_does_not_change_provider(self):
        chain = [{"provider": "claude-code", "model": "claude-opus-5-5"},
                 {"provider": "codex", "model": "gpt-6-sol"}]

        async def fail(*args):
            raise ModelFailure("authentication_required")

        async def unexpected(*args):
            self.fail("Authentication errors must not trigger a provider change.")

        config = RoutingConfig(planner=chain, slice_verifier=chain, global_evaluator=chain)
        router = ModelRouter(config, {"claude-code": fail, "codex": unexpected})
        state, artifact = await self.run_plan([], None, router=router)
        self.assertEqual(state["status"], "blocked")
        self.assertIn("Sign in to Claude Code", state["reason"])
        self.assertIsNone(artifact)

    async def test_pilot_evidence_correlates_only_the_chunks_prepared_for_each_stage(self):
        import hashlib

        text = "Filter tasks by status."
        chunk = {"id": "E1", "path": "task-list.md", "start_line": 1, "end_line": 1, "text": text}
        database_ref = {
            "id": "E1", "path": "task-list.md", "start_line": 1, "end_line": 1,
            "embedding_dimensions": 1024, "payload_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }

        def search(query):
            return [chunk], {"backend": "postgres", "retrieved": [database_ref],
                             "baseline": {"chunks": 3, "utf8_bytes": 400}}

        async def verifier(*args):
            return {"verdict": "accept", "finding": "Matches the evidence."}

        class Publisher:
            async def publish(inner_self, ctx, outcome):
                run = _execution(ctx, outcome)
                receipt = _postgres_receipt(run)
                contexts = [attempt["context"] for attempt in receipt["model_attempts"]]
                self.assertEqual([len(context) for context in contexts], [1, 1, 1, 0])
                self.assertTrue(contexts[0][0]["matches_postgres_payload"])
                self.assertNotIn(text, json.dumps(run))
                self.assertIn("| Redução estimada | — | 94 |", token_report(run))
                html = replay(run)
                self.assertIn('["Trechos", "E1"]', html)
                self.assertIn('["E1", "task-list.md:1–1"]', html)
                self.assertTrue(run["slices"][0]["report"]["findings"])
                self.assertIn('id="event-data"', html)
                self.assertIn('lang="pt-BR"', faq(run))
                self.assertEqual(faq(run).count('<details class="panel">'), 8)
                return {"status": "published"}

        state, _ = await self.run_plan([proposed_slice("filter")], verifier, search=search, publisher=Publisher())
        self.assertEqual(state["evidence_bundle"]["status"], "published")

    async def test_limit_is_applied_to_schema_and_dispatch(self):
        async def verifier(*args):
            return {"verdict": "accept", "finding": "Matches the evidence."}

        slices = [proposed_slice(f"slice-{i}") for i in range(6)]
        state, artifact = await self.run_plan(slices[:5], verifier)
        self.assertEqual(state["status"], "accepted")
        self.assertEqual(len(json.loads(artifact.inline_data.data)["slices"]), 5)
        state, artifact = await self.run_plan(slices, verifier)
        self.assertEqual(state["status"], "blocked")
        self.assertIsNone(artifact)
        state, _ = await self.run_plan(slices, verifier, max_slices=6)
        self.assertEqual(state["status"], "accepted")

    async def test_worker_cannot_cite_evidence_outside_its_slice(self):
        async def worker(data):
            return slice_report(["E999"])

        async def verifier(*args):
            self.fail("Invalid worker references must never reach the verifier.")

        state, _ = await self.run_plan([proposed_slice("filter")], verifier, worker=worker)
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(state["results"]["filter"]["attempt"], 2)
        self.assertIsNone(state["results"]["filter"]["report"])
