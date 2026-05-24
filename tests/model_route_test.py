import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import chat.server as server


class FakeOllamaResponse:
    status_code = 200
    text = '{"message":{"content":"ok"}}'

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": "ok"}}


class FakeHfModel:
    def __init__(self, model_id, downloads=0, tags=None, card_data=None):
        self.modelId = model_id
        self.downloads = downloads
        self.tags = tags or []
        self.card_data = card_data or {}
        self.pipeline_tag = "text-generation"
        self.likes = 0


class FakeHfApi:
    def __init__(self, models, exact=None):
        self.models = models
        self.exact = exact

    def model_info(self, repo_id, **_kwargs):
        if self.exact and self.exact.modelId == repo_id:
            return self.exact
        raise RuntimeError("not found")

    def list_models(self, **kwargs):
        limit = kwargs.get("limit") or len(self.models)
        return self.models[:limit]


class ModelRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_values = {
            "GFORGE_DATA_ROOT": server.GFORGE_DATA_ROOT,
            "SESSIONS_FILE": server.SESSIONS_FILE,
            "MODELS_FILE": server.MODELS_FILE,
            "SESSION_ROOT": server.SESSION_ROOT,
            "ERROR_LOG_FILE": server.ERROR_LOG_FILE,
            "MODEL_ROUTE_FILE": server.MODEL_ROUTE_FILE,
            "FORGE_CONTEXT_FILE": server.FORGE_CONTEXT_FILE,
            "LEGACY_SESSIONS_FILE": server.LEGACY_SESSIONS_FILE,
            "LEGACY_MODELS_FILE": server.LEGACY_MODELS_FILE,
            "LEGACY_SESSION_ROOT": server.LEGACY_SESSION_ROOT,
        }
        server.GFORGE_DATA_ROOT = self.tmp.name
        server.SESSIONS_FILE = os.path.join(self.tmp.name, "sessions.json")
        server.MODELS_FILE = os.path.join(self.tmp.name, "models.json")
        server.SESSION_ROOT = os.path.join(self.tmp.name, "session-data")
        server.ERROR_LOG_FILE = os.path.join(self.tmp.name, "logs", "errors.jsonl")
        server.MODEL_ROUTE_FILE = os.path.join(self.tmp.name, "model-route.json")
        server.FORGE_CONTEXT_FILE = os.path.join(self.tmp.name, "forge.md")
        server.LEGACY_SESSIONS_FILE = os.path.join(self.tmp.name, "missing-sessions.json")
        server.LEGACY_MODELS_FILE = os.path.join(self.tmp.name, "missing-models.json")
        server.LEGACY_SESSION_ROOT = os.path.join(self.tmp.name, "missing-session-data")
        server._storage_ready = False
        server.MODEL_PROVISION_JOBS.clear()

    def tearDown(self):
        for key, value in self.old_values.items():
            setattr(server, key, value)
        server._storage_ready = False
        server.MODEL_PROVISION_JOBS.clear()
        self.tmp.cleanup()

    def test_default_model_is_sent_to_ollama_and_recorded(self):
        captured = {}

        def fake_post(url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeOllamaResponse()

        with patch.object(server.requests, "post", fake_post):
            reply = server.call_ollama(server.DEFAULT_MODEL, "Say ok.")

        self.assertEqual(reply, "ok")
        self.assertEqual(server.DEFAULT_MODEL, "gemma-4-e4b-it")
        self.assertEqual(captured["url"], "http://localhost:11434/api/chat")
        self.assertEqual(captured["json"]["model"], "gemma-4-e4b-it")

        with open(server.MODEL_ROUTE_FILE, "r") as f:
            route = json.load(f)

        self.assertEqual(route["model"], "gemma-4-e4b-it")
        self.assertEqual(route["defaultModel"], "gemma-4-e4b-it")

    def test_forge_context_is_created_outside_project_records(self):
        context = server.read_forge_context()

        self.assertTrue(os.path.exists(server.FORGE_CONTEXT_FILE))
        self.assertIn("# forge.md", context)
        self.assertIn("Delete only removes the selected project record", context)
        self.assertFalse(os.path.exists(os.path.join(server.SESSION_ROOT, "forge.md")))

    def test_small_model_policy_detects_default_gemma_size(self):
        workspace = {
            "ollama": {
                "models": [
                    {
                        "name": "gemma-4-e4b-it:latest",
                        "model": "gemma-4-e4b-it:latest",
                        "details": {"parameter_size": "8B"},
                    }
                ]
            }
        }

        with patch.object(server, "scan_workspace", return_value=workspace):
            self.assertTrue(server.small_model_review_required("gemma-4-e4b-it"))

    def test_large_model_policy_skips_extra_review(self):
        workspace = {
            "ollama": {
                "models": [
                    {
                        "name": "gempus4:tuned",
                        "model": "gempus4:tuned",
                        "details": {"parameter_size": "30.7B"},
                    }
                ]
            }
        }

        with patch.object(server, "scan_workspace", return_value=workspace):
            self.assertFalse(server.small_model_review_required("gempus4:tuned"))

    def test_hf_model_search_returns_five_choice_pages(self):
        models = [
            FakeHfModel(f"Qwen/model-{index}", downloads=1000 - index, tags=["gguf"])
            for index in range(8)
        ]
        api = FakeHfApi(models)

        first_page = server.hf_search_results("qwen", api=api)
        second_page = server.hf_search_results("qwen", offset=5, api=api)

        self.assertEqual(len(first_page["results"]), 5)
        self.assertTrue(first_page["hasNext"])
        self.assertFalse(first_page["hasPrevious"])
        self.assertEqual(first_page["nextOffset"], 5)
        self.assertEqual(len(second_page["results"]), 3)
        self.assertFalse(second_page["hasNext"])
        self.assertTrue(second_page["hasPrevious"])
        self.assertEqual(second_page["previousOffset"], 0)

    def test_hf_model_search_pins_exact_repo_match(self):
        exact = FakeHfModel("google/gemma-4-E2B-it", downloads=999, tags=["safetensors"])
        models = [exact, FakeHfModel("google/other-model", downloads=10)]
        api = FakeHfApi(models, exact=exact)

        payload = server.hf_search_results(
            "https://huggingface.co/google/gemma-4-E2B-it",
            api=api,
            installed_models=[{"name": "gemma-4-e2b-it:latest"}],
        )

        self.assertEqual(payload["query"], "google/gemma-4-E2B-it")
        self.assertEqual(payload["results"][0]["repoId"], "google/gemma-4-E2B-it")
        self.assertEqual(payload["results"][0]["suggestedOllamaName"], "gemma-4-e2b-it")
        self.assertTrue(payload["results"][0]["installed"])

    def test_hf_model_search_route_rejects_blank_query(self):
        client = server.app.test_client()
        response = client.get("/api/models/search?q=   ")

        self.assertEqual(response.status_code, 400)

    def test_provision_starts_job_for_missing_ollama_model(self):
        client = server.app.test_client()
        workspace = {"ollama": {"models": []}}
        job = {
            "id": "model_testjob",
            "status": "provisioning",
            "message": "Provisioning queued.",
            "modelName": "zaya1-8b",
            "repoId": "Zyphra/ZAYA1-8B",
        }

        with patch.object(server, "scan_workspace", return_value=workspace), \
             patch.object(server, "start_model_provision_job", return_value=job):
            response = client.post("/api/models/provision", json={
                "repoId": "Zyphra/ZAYA1-8B",
                "ollamaName": "zaya1-8b",
                "createInterface": True,
            })

        payload = response.get_json()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(payload["status"], "provisioning")
        self.assertFalse(payload["runnable"])
        self.assertEqual(payload["jobId"], "model_testjob")
        self.assertNotIn("session_id", payload)

    def test_provision_validation_does_not_register_phantom_model(self):
        client = server.app.test_client()
        workspace = {"ollama": {"models": []}}

        with patch.object(server, "scan_workspace", return_value=workspace):
            response = client.post("/api/models/provision", json={
                "ollamaName": "not-installed-test-model",
                "createInterface": False,
            })

        self.assertEqual(response.status_code, 400)
        registry = server.load_models()
        self.assertFalse(any(
            model.get("name") == "not-installed-test-model"
            for model in registry.get("models", [])
        ))

    def test_provision_reuses_stored_hf_source_for_queued_model(self):
        client = server.app.test_client()
        workspace = {"ollama": {"models": []}}
        server.save_models({
            "models": [{
                "name": "zaya1-8b",
                "source": "Zyphra/ZAYA1-8B",
                "status": "queued",
            }]
        })
        job = {
            "id": "model_stored_source",
            "status": "provisioning",
            "message": "Provisioning queued.",
            "modelName": "zaya1-8b",
            "repoId": "Zyphra/ZAYA1-8B",
        }

        with patch.object(server, "scan_workspace", return_value=workspace), \
             patch.object(server, "start_model_provision_job", return_value=job) as starter:
            response = client.post("/api/models/provision", json={
                "ollamaName": "zaya1-8b",
                "createInterface": False,
            })

        self.assertEqual(response.status_code, 202)
        starter.assert_called_once()
        self.assertEqual(starter.call_args.args[0]["repoId"], "Zyphra/ZAYA1-8B")

    def test_provision_job_imports_direct_gguf_into_ollama(self):
        commands = []

        def fake_snapshot_download(repo_id, local_dir, **_kwargs):
            os.makedirs(local_dir, exist_ok=True)
            with open(os.path.join(local_dir, "model.Q4_K_M.gguf"), "w") as f:
                f.write("gguf")
            return local_dir

        def fake_run(job_id, command, step):
            commands.append((job_id, command, step))
            return "ok"

        workspace_after_create = {"ollama": {"models": [{"name": "zaya1-8b:latest"}]}}

        with patch.object(server, "MODELS_ROOT", self.tmp.name), \
             patch.object(server, "preferred_remote_gguf_file", return_value="model.Q4_K_M.gguf"), \
             patch.object(server, "snapshot_download", side_effect=fake_snapshot_download), \
             patch.object(server, "run_provision_command", side_effect=fake_run), \
             patch.object(server, "scan_workspace", return_value=workspace_after_create):
            job = {
                "id": "model_direct_test",
                "repoId": "Zyphra/ZAYA1-8B",
                "modelName": "zaya1-8b",
                "status": "provisioning",
                "message": "Provisioning queued.",
                "createInterface": True,
                "downloadOnly": False,
                "quantization": "Q4_K_M",
                "steps": [],
            }
            server.MODEL_PROVISION_JOBS[job["id"]] = dict(job)
            server.run_model_provision_job(job["id"])

        finished = server.model_provision_job_snapshot(job["id"])
        self.assertEqual(finished["status"], "installed")
        self.assertTrue(finished["runnable"])
        self.assertIn("session_id", finished)
        self.assertEqual(commands[-1][1][:3], ["ollama", "create", "zaya1-8b"])

        registry = server.load_models()
        [record] = [model for model in registry["models"] if model["name"] == "zaya1-8b"]
        self.assertEqual(record["status"], "installed")
        self.assertTrue(os.path.exists(record["modelfilePath"]))

    def test_registered_uninstalled_model_cannot_start_project(self):
        server.save_models({
            "models": [{
                "name": "zaya1-8b",
                "source": "Zyphra/ZAYA1-8B",
                "status": "queued",
            }]
        })

        response = server.app.test_client().post("/api/sessions", json={
            "project": "Create a gallery site.",
            "model": "zaya1-8b",
            "hasProjectDirectory": False,
            "projectDirectory": "",
        })

        self.assertEqual(response.status_code, 409)
        self.assertIn("not installed in Ollama", response.get_json()["error"])

    def test_selected_model_can_be_saved_to_project(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a local app.",
            "gemma-4",
            requested_id="model-switch-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={session_id})

        client = server.app.test_client()
        response = client.patch(
            f"/api/sessions/{session_id}/model",
            json={"model": "gemma4:31b-max"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["session"]["model"], "gemma4:31b-max")
        self.assertEqual(server.load_sessions()[session_id]["model"], "gemma4:31b-max")

    def test_card_run_persists_selected_model(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a local app.",
            "gemma-4",
            requested_id="model-card-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={session_id})
        result = server.card_result(
            "Intake",
            "Project brief extracted.",
            "Brief details.",
            "Confirm brief.",
            None,
        )

        with patch.object(server, "run_card_action", return_value=result), \
                patch.object(server, "finalize_card_result", return_value=result):
            response = server.app.test_client().post(
                f"/api/sessions/{session_id}/cards/intake/run",
                json={"model": "gemma4:31b-max", "humanVerify": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["session"]["model"], "gemma4:31b-max")
        self.assertEqual(server.load_sessions()[session_id]["model"], "gemma4:31b-max")

    def test_archived_session_message_does_not_call_model(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Archived project.",
            "gemma-4",
            requested_id="archived-message-test",
            has_project_directory=False,
        )
        sessions[session_id]["archivedAt"] = "2026-05-23T00:00:00+00:00"
        server.save_sessions(sessions, create_keys={session_id})

        with patch.object(server, "call_ollama", side_effect=AssertionError("model should not be called")):
            response = server.app.test_client().post(
                f"/api/sessions/{session_id}/messages",
                json={"message": "Keep going", "model": "gemma-4"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Archived projects are read-only", response.get_json()["error"])

    def test_worker_action_parser_allows_only_known_worker_flow(self):
        text = """
Ready to rerun execution.
<<<GFORGE_WORKER_ACTION>>>
action: run_card
card: execution
reason: Repair the generated page with the latest chat instruction.
<<<END_GFORGE_WORKER_ACTION>>>
<<<GFORGE_WORKER_ACTION>>>
action: shell_exec
card: deploy
reason: no
<<<END_GFORGE_WORKER_ACTION>>>
"""

        self.assertEqual(
            server.parse_worker_action_requests(text),
            [{
                "action": "run_card",
                "card": "execution",
                "reason": "Repair the generated page with the latest chat instruction.",
            }],
        )

    def test_session_message_returns_worker_action_request(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Build a landing page.",
            "gemma-4",
            requested_id="worker-action-message-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={session_id})
        reply = """
I will hand this back to the worker.
<<<GFORGE_WORKER_ACTION>>>
action: full_forge
reason: Continue the active Forge flow.
<<<END_GFORGE_WORKER_ACTION>>>
"""

        with patch.object(server, "call_ollama", return_value=reply):
            response = server.app.test_client().post(
                f"/api/sessions/{session_id}/messages",
                json={"message": "keep going", "model": "gemma-4"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["workerActions"], [{"action": "full_forge", "reason": "Continue the active Forge flow."}])
        self.assertNotIn("GFORGE_WORKER_ACTION", payload["reply"])
        self.assertIn("Harness queued worker action", payload["reply"])

    def test_save_sessions_update_keys_preserve_parallel_session_updates(self):
        sessions = {}
        first = server.create_session_record(
            sessions,
            "First parallel project.",
            "gemma-4",
            requested_id="parallel-first",
            has_project_directory=False,
        )
        second = server.create_session_record(
            sessions,
            "Second parallel project.",
            "gemma-4",
            requested_id="parallel-second",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={first, second})

        first_snapshot = server.load_sessions()
        second_snapshot = server.load_sessions()

        first_snapshot[first]["cards"][0]["status"] = "complete"
        server.save_sessions(first_snapshot, update_keys={first})

        second_snapshot[second]["cards"][0]["status"] = "complete"
        server.save_sessions(second_snapshot, update_keys={second})

        on_disk = server.load_sessions()
        self.assertEqual(on_disk[first]["cards"][0]["status"], "complete")
        self.assertEqual(on_disk[second]["cards"][0]["status"], "complete")

    def test_session_event_feed_excludes_global_events(self):
        with server._EVENT_LOCK:
            server._EVENT_BUFFER.clear()
            server._EVENT_SUBSCRIBERS.clear()
            server._EVENT_SEQ = 0

        try:
            server.emit_event("info", "global setup")
            server.emit_event("card-start", "first session", session_id="session-one")
            server.emit_event("card-start", "second session", session_id="session-two")

            q, snapshot = server._subscribe_events(session_filter="session-one")
            try:
                self.assertEqual([event["message"] for event in snapshot], ["first session"])

                server.emit_event("info", "global live")
                server.emit_event("card-end", "second live", session_id="session-two")
                server.emit_event("card-end", "first live", session_id="session-one")

                queued = []
                while not q.empty():
                    queued.append(q.get_nowait())

                self.assertEqual([event["message"] for event in queued], ["first live"])
            finally:
                server._unsubscribe_events(q)
        finally:
            with server._EVENT_LOCK:
                server._EVENT_BUFFER.clear()
                server._EVENT_SUBSCRIBERS.clear()
                server._EVENT_SEQ = 0

    def test_archived_session_card_run_does_not_call_model(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Archived project.",
            "gemma-4",
            requested_id="archived-card-test",
            has_project_directory=False,
        )
        sessions[session_id]["archivedAt"] = "2026-05-23T00:00:00+00:00"
        server.save_sessions(sessions, create_keys={session_id})

        with patch.object(server, "run_card_action", side_effect=AssertionError("card should not run")):
            response = server.app.test_client().post(
                f"/api/sessions/{session_id}/cards/intake/run",
                json={"model": "gemma-4", "humanVerify": False},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Archived projects are read-only", response.get_json()["error"])

    def test_archived_session_plan_does_not_call_model(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Archived project.",
            "gemma-4",
            requested_id="archived-plan-test",
            has_project_directory=False,
        )
        sessions[session_id]["archivedAt"] = "2026-05-23T00:00:00+00:00"
        server.save_sessions(sessions, create_keys={session_id})

        with patch.object(server, "call_ollama", side_effect=AssertionError("model should not be called")):
            response = server.app.test_client().post(
                "/api/plan",
                json={"session_id": session_id, "project": "Plan this", "model": "gemma-4"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("Archived projects are read-only", response.get_json()["error"])

    def test_plan_bounds_tiny_model_prediction_budget(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a tiny model plan.",
            "gemma-3-1b-test",
            requested_id="tiny-plan-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={session_id})
        captured = {}
        workspace = {
            "agentCapacity": {"mode": "single-agent-audit", "maxParallelSubagents": 0},
            "ollama": {
                "models": [{
                    "name": "gemma-3-1b-test:latest",
                    "model": "gemma-3-1b-test:latest",
                    "details": {"parameter_size": "999.89M"},
                }]
            }
        }

        def fake_call(model, prompt, options_override=None):
            captured["model"] = model
            captured["options"] = options_override
            return "Plan ready.", {
                "status": "ok",
                "model": model,
                "elapsedMs": 1,
                "attempts": 1,
                "error": None,
                "timeoutSeconds": server.OLLAMA_REQUEST_TIMEOUT_SECONDS,
            }

        with patch.object(server, "scan_workspace", return_value=workspace), \
             patch.object(server, "call_ollama_with_transport", side_effect=fake_call):
            response = server.app.test_client().post("/api/plan", json={
                "session_id": session_id,
                "project": "Create a tiny model plan.",
                "model": "gemma-3-1b-test",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reply"], "Plan ready.")
        self.assertEqual(captured["options"]["num_predict"], 384)
        self.assertEqual(captured["options"]["temperature"], 0.2)

    def test_plan_surfaces_transport_failure(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a small page.",
            "gemma-4",
            requested_id="plan-transport-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={session_id})
        workspace = {
            "agentCapacity": {"mode": "single-agent-audit", "maxParallelSubagents": 0},
            "ollama": {"models": [{"name": "gemma-4:latest", "details": {"parameter_size": "4.6B"}}]},
        }

        with patch.object(server, "scan_workspace", return_value=workspace), \
             patch.object(server, "call_ollama_with_transport", return_value=("", {
                 "status": "timeout",
                 "model": "gemma-4",
                 "elapsedMs": 1200000,
                 "attempts": 1,
                 "error": "timeout",
                 "timeoutSeconds": 1200,
             })):
            response = server.app.test_client().post("/api/plan", json={
                "session_id": session_id,
                "project": "Create a small page.",
                "model": "gemma-4",
            })

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ollama request timed out", response.get_json()["reply"])

    def test_auto_run_section_waits_when_small_model_review_fails(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a small test page.",
            "gemma-4",
            requested_id="review-gate-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions, create_keys={session_id})

        def fake_action(_session_id, _session, _card_id, _model, _mode, correction=None):
            return server.card_result(
                "Intake",
                "Project brief extracted.",
                "Brief details.",
                "Confirm brief.",
                None,
            )

        failed_review = {
            "required": True,
            "passed": False,
            "summary": "Review found an issue.",
            "findings": ["Acceptance criteria are missing."],
            "fixesNeeded": ["Clarify acceptance criteria."],
        }

        repair_attempt = {
            "attempt": 1,
            "card": "intake",
            "changed": False,
            "action": "No automatic repair available.",
            "reviewSummary": "Review found an issue.",
        }

        with patch.object(server, "run_card_action", fake_action), \
                patch.object(server, "run_research_passes_if_needed", return_value=None), \
                patch.object(server, "small_model_review_required", return_value=True), \
                patch.object(server, "run_completion_review", return_value=failed_review), \
                patch.object(server, "run_post_review_repair", return_value=repair_attempt):
            client = server.app.test_client()
            response = client.post(
                f"/api/sessions/{session_id}/cards/intake/run",
                json={"model": "gemma-4", "humanVerify": False},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        card = next(item for item in payload["session"]["cards"] if item["id"] == "intake")
        self.assertEqual(card["status"], "needs-attention")
        self.assertEqual(payload["result"]["status"], "needs-attention")
        self.assertFalse(payload["result"]["extraReview"]["passed"])
        self.assertEqual(len(payload["result"]["postReviewRepairs"]), 1)

    def test_new_project_can_store_desired_missing_directory(self):
        sessions = {}
        desired_path = os.path.join(self.tmp.name, "desired-new-project")
        session_id = server.create_session_record(
            sessions,
            "Create a small website.",
            "gemma-4",
            requested_id="desired-path-test",
            has_project_directory=False,
            project_directory=desired_path,
        )

        session = sessions[session_id]
        execution_card = next(card for card in session["cards"] if card["id"] == "execution")

        self.assertEqual(session["projectMode"], "new-project")
        self.assertEqual(session["projectDirectory"], desired_path)
        self.assertEqual(execution_card["status"], "active")

    def test_existing_directory_mode_rejects_missing_path(self):
        client = server.app.test_client()
        response = client.post("/api/sessions", json={
            "project": "Use an existing project.",
            "model": "gemma-4",
            "hasProjectDirectory": True,
            "projectDirectory": os.path.join(self.tmp.name, "missing-existing-project"),
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not exist", response.get_json()["error"])

    def test_execution_uses_desired_new_project_path(self):
        desired_path = os.path.join(self.tmp.name, "new-output")
        session = {
            "project": "Create a simple webpage.",
            "model": "gemma-4",
            "projectDirectory": desired_path,
            "projectMode": "new-project",
            "cards": [],
        }
        model_payload = {
            "summary": "Created a simple webpage.",
            "files": [{"path": "index.html", "content": "<!doctype html><title>Created</title>"}],
            "commands": [],
            "notes": [],
            "verification": [],
        }

        with patch.object(server, "call_ollama_execution_payload",
                          return_value=(model_payload, json.dumps(model_payload), {"status": "ok"})):
            result = server.run_execution_card("desired-execution-test", session, "gemma-4", "auto")

        self.assertTrue(os.path.exists(os.path.join(desired_path, "index.html")))
        self.assertEqual(result["workspace"], desired_path)
        self.assertEqual(session["projectDirectory"], desired_path)

    def test_execution_workspace_uses_compact_context_name(self):
        session = {
            "project": (
                "Build a small HTML/CSS single-page Local AI Validation Lab dashboard. "
                "Deliver one HTML page and one linked CSS file."
            ),
            "projectDirectory": "",
            "projectContext": {
                "project": {"name": "Local AI Validation Lab Dashboard"}
            },
        }

        workspace = server.resolve_execution_workspace("compact-workspace-test", session, session["project"])

        self.assertTrue(workspace.endswith("/workspace/local-ai-validation-lab-dashboard"))
        self.assertNotIn("build-a-small-html-css", workspace)

    def test_execution_workspace_fallback_slug_is_short_and_clean(self):
        session = {
            "project": "Build a small HTML/CSS single-page “Local AI Validation Lab” dashboard. Deliver one HTML page and one linked CSS file.",
            "projectDirectory": "",
        }

        workspace = server.resolve_execution_workspace("compact-fallback-test", session, session["project"])
        dirname = os.path.basename(workspace)

        self.assertLessEqual(len(dirname), 52)
        self.assertNotIn("--", dirname)
        self.assertNotIn(".", dirname)

    def test_model_authored_execution_writes_only_model_returned_files(self):
        session_id = "model-authored"
        session = {
            "project": "Create a simple webpage.",
            "model": "gemma-4",
            "projectDirectory": "",
            "projectMode": "new-project",
            "cards": [],
        }
        workspace_dir = os.path.join(server.session_dir(session_id), "workspace")
        model_payload = {
            "summary": "Created a simple webpage.",
            "files": [
                {"path": "index.html", "content": "<!doctype html><title>Model authored</title>"},
                {"path": "styles.css", "content": "body { font-family: sans-serif; }"},
            ],
            "commands": [],
            "notes": ["No built-in task output used."],
            "verification": ["Open index.html."],
        }

        with patch.object(server, "call_ollama_execution_payload",
                          return_value=(model_payload, json.dumps(model_payload), {"status": "ok"})):
            execution = server.execute_model_authored_project(session_id, session, "gemma-4", workspace_dir)

        self.assertTrue(os.path.exists(os.path.join(workspace_dir, "index.html")))
        self.assertTrue(os.path.exists(os.path.join(workspace_dir, "styles.css")))
        self.assertFalse(os.path.exists(os.path.join(workspace_dir, "script.js")))
        self.assertTrue(execution["validation"]["passed"], execution["validation"]["failures"])
        self.assertTrue(execution["validation"]["authenticity"]["modelAuthored"])
        self.assertEqual(execution["validation"]["fileCount"], 2)

    def test_model_authored_execution_accepts_forge_file_blocks(self):
        session_id = "file-blocks"
        session = {
            "project": "Create a simple webpage.",
            "model": "gemma-4",
            "projectDirectory": "",
            "projectMode": "new-project",
            "cards": [],
        }
        workspace_dir = os.path.join(server.session_dir(session_id), "workspace")
        raw = """SUMMARY:
Created a page using the file-block payload.

FILES:
<<<GFORGE_FILE:index.html>>>
<!doctype html><title>File block</title>
<<<END_GFORGE_FILE>>>
<<<GFORGE_FILE:styles.css>>>
body { color: #123456; }
<<<END_GFORGE_FILE>>>

COMMANDS:
- Open index.html.

NOTES:
- No JSON escaping was required.

VERIFICATION:
- Confirm the title is visible.
"""

        with patch.object(server, "call_ollama_with_transport", return_value=(raw, {"status": "ok"})):
            execution = server.execute_model_authored_project(session_id, session, "gemma-4", workspace_dir)

        self.assertTrue(os.path.exists(os.path.join(workspace_dir, "index.html")))
        self.assertTrue(os.path.exists(os.path.join(workspace_dir, "styles.css")))
        self.assertTrue(execution["validation"]["passed"], execution["validation"]["failures"])
        self.assertEqual(execution["commands"], ["Open index.html."])
        self.assertEqual(execution["notes"], ["No JSON escaping was required."])

    def test_execution_stages_requested_workspace_skill_context(self):
        skill_root = os.path.join(self.tmp.name, "skills")
        skill_dir = os.path.join(skill_root, "logo-generator")
        os.makedirs(os.path.join(skill_dir, "references"), exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: logo-generator\n---\n# Logo Generator\nCreate six SVG variants.")
        with open(os.path.join(skill_dir, "references", "design_patterns.md"), "w") as f:
            f.write("# Design Patterns\nUse geometric marks and node networks.")

        workspace_dir = os.path.join(self.tmp.name, "logo-workspace")
        session = {
            "project": "Use skill logo-generator to create a brand mark.",
            "model": "gemma-4",
            "projectDirectory": workspace_dir,
            "projectMode": "new-project",
            "cards": [],
        }
        model_payload = {
            "summary": "Created logo variants.",
            "files": [{"path": "index.html", "content": "<!doctype html><title>Logos</title>"}],
            "commands": [],
            "notes": [],
            "verification": [],
        }
        captured = {}

        def fake_call(_model, prompt, _fallback):
            captured["prompt"] = prompt
            return model_payload, json.dumps(model_payload), {"status": "ok"}

        with patch.object(server, "skill_install_roots", return_value=[("harness", skill_root)]), \
                patch.object(server, "call_ollama_execution_payload", side_effect=fake_call):
            execution = server.execute_model_authored_project("skill-context", session, "gemma-4", workspace_dir)

        staged_skill = os.path.join(workspace_dir, ".gforge", "skills", "logo-generator", "SKILL.md")
        manifest = os.path.join(workspace_dir, ".gforge", "skills", "MANIFEST.md")
        self.assertTrue(os.path.exists(staged_skill))
        self.assertTrue(os.path.exists(manifest))
        self.assertIn("Logo Generator", captured["prompt"])
        self.assertIn("references/design_patterns.md", captured["prompt"])
        self.assertIn("Do not report `/Users/...` skill paths as inaccessible", captured["prompt"])
        self.assertTrue(execution["validation"]["passed"], execution["validation"]["failures"])
        self.assertEqual(execution["validation"]["fileCount"], 1)
        profile = server.project_file_profile(workspace_dir)
        self.assertFalse(any(path.startswith(".gforge/") for path in profile["semanticSamples"]))

    def test_model_file_normalization_rejects_unsafe_paths(self):
        files, rejected = server.normalize_model_files([
            {"path": "../outside.txt", "content": "bad"},
            {"path": "/tmp/outside.txt", "content": "bad"},
            {"path": ".gforge/skills/logo-generator/SKILL.md", "content": "bad"},
            {"path": "ok/readme.md", "content": "# ok"},
            {"path": "empty.txt", "content": ""},
        ])

        self.assertEqual(files, [{"path": "ok/readme.md", "content": "# ok"}])
        self.assertEqual(len(rejected), 4)

    def test_axon_environment_error_is_non_blocking_tool_state(self):
        tool_execution = server.build_axon_tool_execution(
            {"returncode": 1, "stdout": "", "stderr": "ValueError: max_workers must be greater than 0"},
            {"returncode": 0, "stdout": "status", "stderr": ""},
            {"returncode": 0, "stdout": "", "stderr": ""},
        )

        self.assertEqual(tool_execution["status"], "degraded")
        self.assertFalse(tool_execution["blocking"])
        self.assertTrue(tool_execution["requiresAttention"])
        self.assertIn("analyze", tool_execution["reason"])

    def test_html_only_workspace_is_not_axon_indexable(self):
        workspace = os.path.join(self.tmp.name, "html-only")
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, "index.html"), "w") as f:
            f.write("<main>Hello</main>")

        profile = server.project_file_profile(workspace)

        self.assertEqual(profile["semanticFileCount"], 1)
        self.assertEqual(profile["axonIndexableCount"], 0)

    def test_axon_card_skips_html_only_workspace_without_claiming_scan(self):
        workspace = os.path.join(self.tmp.name, "html-only-card")
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, "index.html"), "w") as f:
            f.write("<main>Hello</main>")

        result = server.run_axon_card(
            "tool-test",
            {
                "project": "HTML only page",
                "projectMode": "existing-directory",
                "projectDirectory": workspace,
            },
            server.DEFAULT_MODEL,
            "auto",
        )

        self.assertEqual(result["toolExecution"]["status"], "not-needed")
        self.assertFalse(result["toolExecution"]["requiresAttention"])
        self.assertIn("not run", result["details"])

    def test_tool_attention_blocks_card_completion_visibly(self):
        result = server.card_result(
            "Axon",
            "Axon failed.",
            "details",
            "checkpoint",
            None,
            {
                "toolExecution": {
                    "tool": "axon",
                    "status": "degraded",
                    "blocking": False,
                    "requiresAttention": True,
                    "reason": "Axon analyze failed.",
                }
            },
        )

        with patch.object(server, "run_research_passes_if_needed", return_value=None):
            with patch.object(server, "run_completion_review_if_needed", return_value={"passed": True}):
                finalized = server.finalize_card_result(
                    "tool-test",
                    {"project": "Test"},
                    "axon",
                    server.DEFAULT_MODEL,
                    result,
                    False,
                )

        self.assertEqual(finalized["status"], "needs-attention")
        self.assertIn("Axon analyze failed", finalized["checkpoint"])

    def test_socraticode_card_runs_real_semantic_search(self):
        workspace = os.path.join(self.tmp.name, "semantic-card")
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, "index.html"), "w") as f:
            f.write("<main class='semantic-target'>Hello semantic search</main>")
        with open(os.path.join(workspace, "styles.css"), "w") as f:
            f.write(".semantic-target { color: rebeccapurple; }")

        result = server.run_socraticode_card(
            "tool-test",
            {
                "project": "Find the semantic target styling.",
                "projectMode": "existing-directory",
                "projectDirectory": workspace,
            },
            server.DEFAULT_MODEL,
            "auto",
        )

        self.assertEqual(result["toolExecution"]["status"], "complete", result["details"])
        self.assertFalse(result["toolExecution"]["requiresAttention"])
        self.assertIn("Search results", result["details"])

    def test_axon_card_runs_real_serialized_scan(self):
        workspace = os.path.join(self.tmp.name, "axon-card")
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, "index.js"), "w") as f:
            f.write("export function add(a, b) { return a + b; }\nconsole.log(add(1, 2));\n")

        result = server.run_axon_card(
            "tool-test",
            {
                "project": "Analyze the add function.",
                "projectMode": "existing-directory",
                "projectDirectory": workspace,
            },
            server.DEFAULT_MODEL,
            "auto",
        )

        self.assertEqual(result["toolExecution"]["status"], "complete", result["details"])
        self.assertFalse(result["toolExecution"]["requiresAttention"])
        self.assertIn("Indexing complete", result["details"])

    def test_support_tool_review_does_not_block_verified_deliverable(self):
        review = {
            "passed": False,
            "summary": "Structural analysis failed due to an execution environment error.",
            "findings": ["The overall project was not achieved by this specific step."],
            "fixesNeeded": ["Repair Axon before structural review can be meaningful."],
        }
        result = {
            "toolExecution": {
                "tool": "axon",
                "status": "degraded",
                "blocking": False,
            }
        }

        server.normalize_review_scope("axon", review, result)

        self.assertTrue(review["passed"])
        self.assertEqual(review["fixesNeeded"], [])

    def test_gsd_review_does_not_block_on_future_execution_work(self):
        review = {
            "passed": False,
            "summary": "The JavaScript implementation is incomplete.",
            "findings": [
                "script.js is truncated and README.md has not been created yet."
            ],
            "fixesNeeded": [
                "Complete script.js and create README.md during Project Execution."
            ],
        }

        server.normalize_review_scope("gsd", review, {"details": "Phase plan with execution checkpoints."})

        self.assertTrue(review["passed"])
        self.assertEqual(review["fixesNeeded"], [])

    def test_failed_review_can_be_repaired_before_completion(self):
        session = {
            "project": "Create a tiny page. text: \"HELLO WORLD! LET'S FORGE!\"",
            "projectDirectory": "",
            "projectMode": "new-project",
            "cards": [],
        }
        result = server.card_result(
            "Project Execution",
            "Execution done.",
            "Old details.",
            "Review output.",
            None,
            {"workspace": os.path.join(server.session_dir("repair-pass"), "workspace", "site")},
        )
        failed_review = {
            "required": True,
            "passed": False,
            "summary": "Wrong phrase.",
            "findings": ["Output used Hello World instead of requested text."],
            "fixesNeeded": ["Patch generated files and retest."],
        }
        passed_review = {
            "required": True,
            "passed": True,
            "summary": "Patched output matches the prompt.",
            "findings": [],
            "fixesNeeded": [],
        }

        execution = {
            "summary": "Patched by Gemma.",
            "files": [{"path": "index.html", "bytes": 20}],
            "rejectedFiles": [],
            "verification": ["Inspect output."],
            "validation": {
                "passed": True,
                "failures": [],
                "authenticity": {"modelAuthored": True},
            },
        }

        with patch.object(server, "run_research_passes_if_needed", return_value=None), \
                patch.object(server, "small_model_review_required", return_value=True), \
                patch.object(server, "execute_model_authored_project", return_value=execution), \
                patch.object(server, "run_completion_review", side_effect=[failed_review, passed_review]):
            server.finalize_card_result("repair-pass", session, "execution", "gemma-4", result, False)

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["extraReview"]["passed"])
        self.assertEqual(len(result["postReviewRepairs"]), 1)
        self.assertTrue(result["validation"]["passed"])
        self.assertTrue(result["validation"]["authenticity"]["modelAuthored"])

    def test_passed_validation_downgrades_count_only_extra_review_false_positive(self):
        review_payload = {
            "passed": False,
            "summary": "The execution failed to meet exactly 3 categories; validation data indicates 4 categories were generated.",
            "findings": [
                "Validation data reports actual 4 categories when exactly 3 were requested."
            ],
            "fixesNeeded": ["Regenerate exactly 3 category reports."],
            "confidence": "medium",
        }
        result = {
            "summary": "Generated PDF category reports.",
            "details": "Validation passed and reports open.",
            "validation": {
                "passed": True,
                "failures": [],
                "contentRequirements": [
                    {"item": "categories", "expected": 3, "actual": 4}
                ],
            },
        }

        with patch.object(server, "call_ollama_json", return_value=(review_payload, "{}", {"status": "ok"})):
            review = server.run_completion_review(
                "count-review",
                {"project": "Create 3 categories based on content."},
                "execution",
                "gemma-4",
                result,
            )

        self.assertTrue(review["passed"])
        self.assertEqual(review["fixesNeeded"], [])
        self.assertIn("Deterministic validation is authoritative", " ".join(review["findings"]))

    def test_verification_passed_validation_downgrades_failed_reviewer(self):
        review_payload = {
            "passed": False,
            "summary": "Axon reported a possible issue, so verification should repair.",
            "findings": ["Support-tool concern after deterministic validation passed."],
            "fixesNeeded": ["Patch the deliverable."],
            "confidence": "medium",
        }
        result = {
            "summary": "Verification report generated.",
            "details": "Deterministic validation passed.",
            "validation": {"passed": True, "failures": []},
        }

        with patch.object(server, "call_ollama_json", return_value=(review_payload, "{}", {"status": "ok"})):
            review = server.run_completion_review(
                "verification-review",
                {"project": "Write a Python setup script."},
                "verification",
                "gemma-4",
                result,
            )

        self.assertTrue(review["passed"])
        self.assertEqual(review["fixesNeeded"], [])
        self.assertIn("Verification is read-only", " ".join(review["findings"]))

    def test_verification_prompt_receives_staged_skill_context(self):
        workspace_dir = os.path.join(self.tmp.name, "verification-skill-context")
        os.makedirs(os.path.join(workspace_dir, "artifacts"), exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write("<!doctype html><html><body><h1>Demo</h1></body></html>")
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }
        with open(os.path.join(workspace_dir, "artifacts", "model-execution.json"), "w") as f:
            json.dump(metadata, f)

        session = {
            "project": "Build a polished HTML/CSS page.",
            "projectDirectory": workspace_dir,
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "skill": {"use": "code-writer"},
            },
        }
        captured = {}

        def fake_call(_model, prompt):
            captured["prompt"] = prompt
            return "- Inspect `index.html`."

        skill_context = {
            "root": ".gforge/skills",
            "staged": [{"name": "code-writer", "path": ".gforge/skills/code-writer", "requested": True}],
            "prompt": "Skill Usage Plan: Code Writer owns HTML/CSS implementation and validation.",
        }
        with patch.object(server, "prepare_workspace_skill_context", return_value=skill_context), \
                patch.object(server, "call_ollama", side_effect=fake_call):
            details, validation = server.build_verification_details(
                "verification-skill-context",
                session,
                "auto",
                model="gemma-4",
            )

        self.assertTrue(validation["passed"], validation["failures"])
        self.assertIn("Skill Usage Plan: Code Writer", captured["prompt"])
        self.assertIn("route the work back to the responsible Forge Section", captured["prompt"])
        self.assertIn("## Staged Skill Context", details)
        self.assertIn("code-writer", details)

    def test_verification_repair_never_reruns_execution(self):
        session = {
            "id": "verification-readonly",
            "project": "Write a Python setup script.",
            "model": "gemma-4",
            "projectDirectory": os.path.join(self.tmp.name, "verification-readonly-workspace"),
        }
        os.makedirs(session["projectDirectory"], exist_ok=True)
        result = {
            "summary": "Verification failed review.",
            "details": "Old verification.",
            "validation": {"passed": False, "failures": ["syntax error"]},
        }
        review = {
            "passed": False,
            "summary": "Verification found a broken script.",
            "findings": ["syntax error"],
            "fixesNeeded": ["Fix execution deliverable."],
        }

        with patch.object(server, "build_verification_details", return_value=("rebuilt verification", {"passed": False, "failures": ["syntax error"]})), \
                patch.object(server, "execute_model_authored_project") as execute:
            repair = server.repair_verification_after_review(
                "verification-readonly",
                session,
                result,
                review,
                1,
            )

        execute.assert_not_called()
        self.assertFalse(repair["changed"])
        self.assertNotIn("upstreamArtifact", repair)
        self.assertEqual(result["details"], "rebuilt verification")

    def test_repair_prompt_continues_from_existing_workspace_snapshot(self):
        workspace_dir = os.path.join(self.tmp.name, "repair-workspace")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        os.makedirs(os.path.join(workspace_dir, "artifacts"), exist_ok=True)
        with open(os.path.join(workspace_dir, "output", "index.html"), "w") as f:
            f.write("<!doctype html><article><h2>Existing Article</h2></article>")
        with open(os.path.join(workspace_dir, "artifacts", "validation.json"), "w") as f:
            json.dump({"passed": False, "failures": ["content requirement expected at least 3 articles"]}, f)

        raw_yaml = """---
project:
  name: repair test
  type: code
deliverable:
  format: html
  count: 1
  path_pattern: output/index.html
acceptance:
  - output/index.html contains three articles.
---"""
        session = {
            "project": "Build a news page with the top 3 articles.",
            "projectContext": {
                "project": {"type": "code"},
                "deliverable": {"format": "html", "count": 1, "path_pattern": "output/index.html"},
                "content_requirements": [
                    {"count": 3, "item": "articles", "scope": "whole page", "source": "top 3 articles"}
                ],
                "acceptance": ["output/index.html contains three articles."],
            },
            "projectContextRaw": raw_yaml,
        }
        review = {
            "summary": "The page under-delivered the requested article count.",
            "findings": ["Only one article card was present."],
            "fixesNeeded": ["Add two more article cards without replacing the useful page structure."],
            "validationFailures": ["content requirement expected at least 3 articles"],
            "userNote": "Keep the existing layout and finish the missing articles.",
        }

        prompt = server.build_model_execution_prompt(
            session,
            workspace_dir,
            review=review,
            skill_context={"prompt": ""},
            research={},
        )

        self.assertIn("CONTINUATION REPAIR MODE", prompt)
        self.assertIn("Do not start over", prompt)
        self.assertIn("Starting over is allowed only if", prompt)
        self.assertIn("complete the rest of the original request", prompt)
        self.assertIn("Harness file-inspection output", prompt)
        self.assertIn("output/index.html", prompt)
        self.assertIn("Existing Article", prompt)
        self.assertIn("content requirement expected at least 3 articles", prompt)
        self.assertIn("Keep the existing layout", prompt)

    def test_initial_execution_prompt_omits_repair_mode(self):
        session = {
            "project": "Create one HTML file.",
            "projectContext": {
                "project": {"type": "code"},
                "deliverable": {"format": "html", "count": 1, "path_pattern": "output/index.html"},
                "acceptance": ["output/index.html exists."],
            },
            "projectContextRaw": """---
project:
  type: code
deliverable:
  format: html
  count: 1
  path_pattern: output/index.html
acceptance:
  - output/index.html exists.
---""",
        }

        prompt = server.build_model_execution_prompt(
            session,
            self.tmp.name,
            review=None,
            skill_context={"prompt": ""},
            research={},
        )

        self.assertNotIn("CONTINUATION REPAIR MODE", prompt)
        self.assertNotIn("Harness file-inspection output", prompt)

    def test_skill_alias_resolves_web_browse_to_scrapling(self):
        skills = {
            "scrapling-official": {
                "name": "scrapling-official",
                "key": "scrapling-official",
                "description": "Scrape web pages using Scrapling.",
                "keywords": [],
                "skillFile": "/tmp/SKILL.md",
            }
        }
        session = {
            "project": "Build a page from live news headlines.",
            "projectContext": {"skill": {"use": "web_browse"}},
        }

        self.assertEqual(server.resolve_skill_selection(session, skills), ["scrapling-official"])

    def test_skill_none_is_overridden_by_scraping_request_keywords(self):
        skills = {
            "scrapling-official": {
                "name": "scrapling-official",
                "key": "scrapling-official",
                "description": "Scrape web pages using Scrapling.",
                "keywords": [],
                "skillFile": "/tmp/SKILL.md",
            }
        }
        session = {
            "project": "Create an HTML news ticker using live scraping of article headlines.",
            "projectContext": {"skill": {"use": "none"}},
        }

        self.assertEqual(server.resolve_skill_selection(session, skills), ["scrapling-official"])

    def test_skill_alias_resolves_pdf_request(self):
        skills = {
            "pdf": {
                "name": "pdf",
                "key": "pdf",
                "description": "Use this skill whenever the user wants to do anything with PDF files.",
                "keywords": ["extract pdf text", "fillable pdf", "ocr pdf"],
                "skillFile": "/tmp/SKILL.md",
            }
        }
        session = {
            "project": "Extract tables from this PDF and make the scanned PDF searchable.",
            "projectContext": {"skill": {"use": "none"}},
        }

        self.assertEqual(server.resolve_skill_selection(session, skills), ["pdf"])

    def test_skill_alias_resolves_mcp_builder_request(self):
        skills = {
            "mcp-builder": {
                "name": "mcp-builder",
                "key": "mcp-builder",
                "description": "Guide for creating high-quality MCP servers.",
                "keywords": ["model context protocol", "mcp tools", "fastmcp"],
                "skillFile": "/tmp/SKILL.md",
            }
        }
        session = {
            "project": "Build a TypeScript MCP server with tool schemas and pagination.",
            "projectContext": {"skill": {"use": "none"}},
        }

        self.assertEqual(server.resolve_skill_selection(session, skills), ["mcp-builder"])

    def test_skill_selection_ignores_prior_agent_skill_manifests(self):
        skills = {
            "scrapling-official": {
                "name": "scrapling-official",
                "key": "scrapling-official",
                "description": "Scrape web pages using Scrapling.",
                "keywords": [],
                "skillFile": "/tmp/SKILL.md",
            },
            "ui-ux-pro-max": {
                "name": "ui-ux-pro-max",
                "key": "ui-ux-pro-max",
                "description": "Design responsive webpages.",
                "keywords": [],
                "skillFile": "/tmp/skill.json",
            },
            "axon": {
                "name": "axon",
                "key": "axon",
                "description": "Code graph analysis.",
                "keywords": [],
                "skillFile": "/tmp/SKILL.md",
            },
            "gsd": {
                "name": "gsd",
                "key": "gsd",
                "description": "Project planning workflow.",
                "keywords": [],
                "skillFile": "/tmp/SKILL.md",
            },
        }
        session = {
            "project": "Scrape news headlines and make a modern responsive page across devices.",
            "projectContext": {"skill": {"use": "scrapling-official"}},
            "messages": [
                {"role": "agent", "content": "Staged skills: axon, gsd, socraticode"},
            ],
        }

        self.assertEqual(server.resolve_skill_selection(session, skills), ["scrapling-official", "ui-ux-pro-max"])

    def test_skill_context_prompt_gives_usage_plan_before_manuals(self):
        staged = [
            {"name": "scrapling-official", "key": "scrapling-official", "path": ".gforge/skills/scrapling-official", "requested": True},
            {"name": "ui-ux-pro-max", "key": "ui-ux-pro-max", "path": ".gforge/skills/ui-ux-pro-max", "requested": True},
        ]

        prompt = server.build_skill_context_prompt(self.tmp.name, staged)

        self.assertIn("Skill Usage Plan", prompt)
        self.assertIn("scrapling-official` → web scraping and extraction", prompt)
        self.assertIn("ui-ux-pro-max` → webpage and interface design", prompt)
        self.assertLess(prompt.index("Skill Usage Plan"), prompt.index("Staged skills:"))

    def test_harness_capabilities_include_workspace_git_and_exec_when_available(self):
        with patch.object(server.tool_workspace, "can_clone_repositories", return_value=True), \
                patch.object(server.tool_workspace, "is_gh_authenticated", return_value=True), \
                patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True), \
                patch.object(server.tool_workspace, "can_install_packages", return_value=True):
            can, cannot = server.harness_capabilities()

        self.assertIn("git_clone", can)
        self.assertIn("github_auth", can)
        self.assertIn("shell_exec", can)
        self.assertIn("install_package", can)
        self.assertNotIn("git_clone", cannot)
        self.assertNotIn("shell_exec", cannot)
        self.assertNotIn("install_package", cannot)

    def test_project_context_keeps_github_and_exec_full_scope_when_available(self):
        raw = """Rationale.
<<<CONTEXT_BEGIN>>>
---
project:
  name: repo check
  type: code
  domain: MCP
intent:
  surface_ask: "Clone https://github.com/anthropics/skills and run tests."
  underlying_need: Inspect a repository and validate generated code.
  success_means: Repository context and command results are available in the workspace.
deliverable:
  format: markdown
  count: 1
  path_pattern: report.md
  encoding: gforge_file_block
  partial: false
  scope: A validation report.
  anti_deflection: stub
capabilities_required:
  - emit_files
constraints:
  hard_requirements:
    - Clone the referenced GitHub repo into the workspace references area.
    - Run a workspace-safe validation command.
  tone:
    - concise
skill:
  use: mcp-builder
  staged_path: .gforge/skills/mcp-builder
acceptance:
  - report.md exists.
  - report.md includes command results.
open_questions: []
---
<<<CONTEXT_END>>>
"""
        with patch.object(server.tool_workspace, "can_clone_repositories", return_value=True), \
                patch.object(server.tool_workspace, "is_gh_authenticated", return_value=True), \
                patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True):
            parsed, _yaml_text, errors = server.parse_project_context(
                raw,
                project_text="Clone https://github.com/anthropics/skills and run this command.",
            )

        self.assertEqual(errors, [])
        self.assertIn("git_clone", parsed["capabilities_required"])
        self.assertIn("shell_exec", parsed["capabilities_required"])
        self.assertFalse(parsed["deliverable"]["partial"])
        self.assertEqual(parsed["open_questions"], [])

    def test_project_context_keeps_package_install_full_scope_when_available(self):
        raw = """Rationale.
<<<CONTEXT_BEGIN>>>
---
project:
  name: dependency check
  type: code
  domain: python
intent:
  surface_ask: "Install requests and run the script."
  underlying_need: Use a local package dependency while building the project.
  success_means: The dependency is installed in the workspace and the script result is recorded.
deliverable:
  format: python
  count: 1
  path_pattern: app.py
  encoding: gforge_file_block
  partial: false
  scope: A Python script with installed dependency verification.
  anti_deflection: stub
capabilities_required:
  - emit_files
constraints:
  hard_requirements:
    - Install the requests dependency.
    - Run the script.
  tone:
    - direct
skill:
  use: none
  staged_path: n/a
acceptance:
  - app.py exists.
  - Command output is recorded.
open_questions: []
---
<<<CONTEXT_END>>>
"""
        with patch.object(server.tool_workspace, "can_install_packages", return_value=True), \
                patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True):
            parsed, _yaml_text, errors = server.parse_project_context(
                raw,
                project_text="Install requests and run the script.",
            )

        self.assertEqual(errors, [])
        self.assertIn("install_package", parsed["capabilities_required"])
        self.assertIn("shell_exec", parsed["capabilities_required"])
        self.assertFalse(parsed["deliverable"]["partial"])

    def test_workspace_pip_install_is_targeted_to_workspace(self):
        args, reason = server.tool_workspace.normalize_workspace_command("pip install requests")

        self.assertEqual(reason, "")
        self.assertIn(args[0], {"pip", "pip3"})
        self.assertEqual(args[1:4], ["install", "--target", ".gforge-installs/python"])
        self.assertIn("requests", args)

    def test_workspace_long_running_dependency_and_script_commands_get_bounded_time(self):
        self.assertEqual(
            server.tool_workspace.workspace_command_timeout(["python", "-m", "pip", "install", "pdfplumber"]),
            server.tool_workspace.LONG_WORKSPACE_COMMAND_TIMEOUT,
        )
        self.assertEqual(
            server.tool_workspace.workspace_command_timeout(["python", "scripts/process.py"]),
            server.tool_workspace.LONG_WORKSPACE_COMMAND_TIMEOUT,
        )
        self.assertEqual(
            server.tool_workspace.workspace_command_timeout(["node", "scripts/process.js"]),
            server.tool_workspace.LONG_WORKSPACE_COMMAND_TIMEOUT,
        )
        self.assertEqual(
            server.tool_workspace.workspace_command_timeout(["git", "status"]),
            server.tool_workspace.DEFAULT_WORKSPACE_COMMAND_TIMEOUT,
        )

    def test_system_package_install_remains_missing_capability(self):
        with patch.object(server.tool_workspace, "can_install_packages", return_value=True):
            missing = server.missing_capabilities(server.detect_required_capabilities("brew install ffmpeg"))

        self.assertIn("system_package_install", missing)

    def test_claim_validator_accepts_recorded_workspace_command_run(self):
        workspace_dir = os.path.join(self.tmp.name, "command-run")
        os.makedirs(os.path.join(workspace_dir, "artifacts"), exist_ok=True)
        with open(os.path.join(workspace_dir, "artifacts", "model-execution.json"), "w") as f:
            json.dump({"commandRuns": [{"ok": True, "command": "python -m unittest", "skipped": False}]}, f)

        with patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True):
            failures = server.validate_claims_against_disk(
                "I ran the command and used the output.",
                ["shell_exec"],
                workspace_dir=workspace_dir,
            )

        self.assertEqual(failures, [])

    def test_claim_validator_flags_shell_claim_without_recorded_run(self):
        workspace_dir = os.path.join(self.tmp.name, "missing-command-run")
        os.makedirs(workspace_dir, exist_ok=True)

        with patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True):
            failures = server.validate_claims_against_disk(
                "I ran the command and used the output.",
                ["shell_exec"],
                workspace_dir=workspace_dir,
            )

        self.assertTrue(any("shell_exec" in item for item in failures))

    def test_claim_validator_accepts_recorded_package_install_run(self):
        workspace_dir = os.path.join(self.tmp.name, "package-install-run")
        os.makedirs(os.path.join(workspace_dir, "artifacts"), exist_ok=True)
        with open(os.path.join(workspace_dir, "artifacts", "model-execution.json"), "w") as f:
            json.dump({"commandRuns": [{"ok": True, "command": "pip install --target .gforge-installs/python requests", "skipped": False}]}, f)

        with patch.object(server.tool_workspace, "can_install_packages", return_value=True):
            failures = server.validate_claims_against_disk(
                "I installed the dependency requests.",
                ["install_package"],
                workspace_dir=workspace_dir,
            )

        self.assertEqual(failures, [])

    def test_detects_content_quantity_requirement_from_news_prompt(self):
        requirements = server.detect_content_quantity_requirements(
            "Pick the top 3 articles in each category and build a modern news page."
        )

        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["count"], 3)
        self.assertEqual(requirements[0]["item"], "articles")
        self.assertEqual(requirements[0]["scope"], "in each category")

    def test_project_context_enriches_content_quantity_requirements(self):
        raw = """Rationale.
<<<CONTEXT_BEGIN>>>
---
project:
  name: news page
  type: code
  domain: news
intent:
  surface_ask: "Pick the top 3 articles in each category and build a page."
  underlying_need: A page with repeated article cards.
  success_means: The page contains the requested article count.
deliverable:
  format: html
  count: 1
  path_pattern: output/index.html
  encoding: gforge_file_block
  partial: false
  scope: A single HTML page.
  anti_deflection: stub
capabilities_required:
  - emit_files
constraints:
  hard_requirements:
    - The page is responsive.
  tone:
    - modern
skill:
  use: none
  staged_path: n/a
acceptance:
  - output/index.html exists.
  - output/index.html is valid HTML.
open_questions: []
---
<<<CONTEXT_END>>>
"""
        parsed, _yaml_text, errors = server.parse_project_context(
            raw,
            project_text="Pick the top 3 articles in each category and build a page.",
        )

        self.assertEqual(errors, [])
        self.assertEqual(parsed["deliverable"]["count"], 1)
        self.assertEqual(parsed["content_requirements"][0]["count"], 3)
        self.assertIn("top 3 articles", parsed["content_requirements"][0]["source"].lower())
        self.assertTrue(any("at least 3 articles" in item.lower() for item in parsed["acceptance"]))

    def test_validation_fails_when_content_quantity_is_under_delivered(self):
        workspace_dir = os.path.join(self.tmp.name, "content-under")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        with open(os.path.join(workspace_dir, "output", "index.html"), "w") as f:
            f.write("<!doctype html><article><h2>Only one story</h2></article>")

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "output/index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [
                    {
                        "count": 3,
                        "item": "articles",
                        "scope": "in each category",
                        "source": "top 3 articles in each category",
                    }
                ],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "output/index.html"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["contentRequirements"][0]["actual"], 1)
        self.assertTrue(any("content requirement expected at least 3" in item for item in validation["failures"]))

    def test_html_css_deliverables_pass_integrity_validation(self):
        workspace_dir = os.path.join(self.tmp.name, "html-css-valid")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html>\n"
                "<html><head><title>Demo</title><link rel=\"stylesheet\" href=\"styles.css\"></head>"
                "<body><main><h1>Hello</h1></main></body></html>"
            )
        with open(os.path.join(workspace_dir, "styles.css"), "w") as f:
            f.write("body { margin: 0; color: #123456; } main { min-height: 100vh; }")

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "styles.css"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])

    def test_html_css_bundle_does_not_count_support_css_as_second_html_file(self):
        workspace_dir = os.path.join(self.tmp.name, "html-css-support-count")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><link rel=\"stylesheet\" href=\"styles.css\"></head>"
                "<body><main><article class=\"status-card\">Ready</article></main></body></html>"
            )
        with open(os.path.join(workspace_dir, "styles.css"), "w") as f:
            f.write(".status-card { display: grid; }")

        session = {
            "projectContext": {
                "intent": {
                    "surface_ask": (
                        "Deliver one HTML page and one linked CSS file named styles.css."
                    )
                },
                "deliverable": {"format": "html", "count": 2, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
                "acceptance": ["index.html exists.", "styles.css exists."],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "styles.css"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])

    def test_html_content_counts_ignore_css_selector_text(self):
        workspace_dir = os.path.join(self.tmp.name, "html-css-content-scope")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><link rel=\"stylesheet\" href=\"styles.css\"></head><body>"
                "<main>"
                "<article class=\"status-card status-ok\">Ready</article>"
                "<article class=\"status-card status-warning\">Watch</article>"
                "<article class=\"status-card status-danger\">Blocked</article>"
                "</main></body></html>"
            )
        with open(os.path.join(workspace_dir, "styles.css"), "w") as f:
            f.write(
                "/* Status Cards Grid */\n"
                ".status-card { display: grid; }\n"
                ".status-card:hover { transform: translateY(-1px); }\n"
            )

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [
                    {
                        "count": 3,
                        "item": "status cards",
                        "scope": "The main dashboard body",
                        "source": "3 status cards",
                    }
                ],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "styles.css"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])
        self.assertEqual(validation["contentRequirements"][0]["actual"], 3)

    def test_html_css_context_enrichment_treats_css_as_support_file(self):
        parsed = {
            "project": {"name": "dashboard", "type": "code", "domain": "web"},
            "intent": {
                "surface_ask": "Deliver one HTML page and one linked CSS file named styles.css.",
                "underlying_need": "A small web page.",
                "success_means": "index.html links styles.css.",
            },
            "deliverable": {
                "format": "html",
                "count": 2,
                "path_pattern": "index.html",
                "encoding": "gforge_file_block",
                "partial": False,
                "scope": "One page plus support stylesheet.",
                "anti_deflection": "stub",
            },
            "capabilities_required": ["emit_files"],
            "constraints": {"hard_requirements": []},
            "skill": {"use": "code-writer"},
            "acceptance": ["index.html exists.", "styles.css exists."],
            "open_questions": [],
            "content_requirements": [],
        }

        server.enrich_project_context(
            parsed,
            "Build one HTML page and one linked CSS file named styles.css.",
            model="gemma-4-e4b-it",
        )

        self.assertEqual(parsed["deliverable"]["count"], 1)
        self.assertEqual(parsed["support_files"][0]["format"], "css")
        self.assertEqual(parsed["support_files"][0]["path_pattern"], "styles.css")

    def test_invalid_html_deliverable_blocks_delivery(self):
        workspace_dir = os.path.join(self.tmp.name, "html-invalid")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write("<!doctype html><html><body><main><h1>Broken</h1></section></body></html>")

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("invalid HTML deliverable" in item for item in validation["failures"]))

    def test_html_integrity_allows_common_optional_close_tags(self):
        workspace_dir = os.path.join(self.tmp.name, "html-optional-tags")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write("<!doctype html><html><body><ul><li>One<li>Two</ul><p>First<p>Second</body></html>")

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])

    def test_invalid_css_deliverable_blocks_delivery(self):
        workspace_dir = os.path.join(self.tmp.name, "css-invalid")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "styles.css"), "w") as f:
            f.write("body { color: #123456; .card { display: grid; }")

        session = {
            "projectContext": {
                "deliverable": {"format": "css", "count": 1, "path_pattern": "styles.css"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "styles.css"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("invalid CSS deliverable" in item for item in validation["failures"]))

    def test_valid_javascript_deliverable_passes_syntax_validation(self):
        workspace_dir = os.path.join(self.tmp.name, "js-valid")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "app.js"), "w") as f:
            f.write(
                "export function summarizeStatuses(items = []) {\n"
                "  const counts = { ok: 0, warning: 0, failed: 0 };\n"
                "  for (const item of items) {\n"
                "    if (!item || typeof item.status !== 'string') continue;\n"
                "    if (Object.prototype.hasOwnProperty.call(counts, item.status)) {\n"
                "      counts[item.status] += 1;\n"
                "    }\n"
                "  }\n"
                "  return counts;\n"
                "}\n"
            )

        session = {
            "projectContext": {
                "deliverable": {"format": "javascript", "count": 1, "path_pattern": "app.js"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "app.js"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])

    def test_invalid_javascript_deliverable_blocks_delivery(self):
        workspace_dir = os.path.join(self.tmp.name, "js-invalid")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "app.js"), "w") as f:
            f.write("function broken( {\n  return true;\n")

        session = {
            "projectContext": {
                "deliverable": {"format": "javascript", "count": 1, "path_pattern": "app.js"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "app.js"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("invalid JavaScript deliverable" in item for item in validation["failures"]))

    def test_javascript_validation_fails_clearly_when_node_is_unavailable(self):
        workspace_dir = os.path.join(self.tmp.name, "js-no-node")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "app.js"), "w") as f:
            f.write("const ready = true;\n")

        session = {
            "projectContext": {
                "deliverable": {"format": "javascript", "count": 1, "path_pattern": "app.js"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "app.js"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        with patch.object(server.shutil, "which", return_value=None):
            validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("Node.js `node` is not available" in item for item in validation["failures"]))

    def test_html_js_bundle_does_not_count_support_js_as_second_html_file(self):
        workspace_dir = os.path.join(self.tmp.name, "html-js-support-count")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><script src=\"app.js\" defer></script></head>"
                "<body><button id=\"run\">Run</button><p id=\"status\">Idle</p></body></html>"
            )
        with open(os.path.join(workspace_dir, "app.js"), "w") as f:
            f.write(
                "document.getElementById('run').addEventListener('click', () => {\n"
                "  document.getElementById('status').textContent = 'Ready';\n"
                "});\n"
            )

        session = {
            "projectContext": {
                "intent": {
                    "surface_ask": (
                        "Build one HTML page named index.html and one linked JavaScript file named app.js."
                    )
                },
                "deliverable": {"format": "html", "count": 2, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
                "acceptance": ["index.html exists.", "app.js exists."],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "app.js"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])

    def test_html_list_content_count_handles_sample_system_checks(self):
        workspace_dir = os.path.join(self.tmp.name, "html-js-check-count")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><script src=\"app.js\"></script></head><body>"
                "<button id=\"checkStatusButton\">Check Status</button>"
                "<p id=\"statusLine\">Status: Idle</p>"
                "<ul id=\"systemChecks\">"
                "<li>Database Connection</li>"
                "<li>API Endpoint Health</li>"
                "<li>File System Integrity</li>"
                "</ul>"
                "</body></html>"
            )
        with open(os.path.join(workspace_dir, "app.js"), "w") as f:
            f.write("document.body.classList.add('ready');\n")

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [
                    {
                        "count": 3,
                        "item": "sample system checks",
                        "scope": "unordered list in index.html",
                        "source": "One unordered list with three sample system checks",
                    }
                ],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "app.js"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])
        self.assertEqual(validation["contentRequirements"][0]["actual"], 3)

    def test_no_css_file_contract_allows_inline_styles_but_blocks_css_files(self):
        workspace_dir = os.path.join(self.tmp.name, "html-no-css-file")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><style>.reviewed{outline:1px solid green;}</style>"
                "<script src=\"app.js\"></script></head><body style=\"font-family:sans-serif\">"
                "<button id=\"checkStatusButton\">Check Status</button>"
                "<p id=\"statusLine\">Status: Idle</p>"
                "<ul><li>Database Connection</li><li>API Endpoint Health</li><li>File System Integrity</li></ul>"
                "</body></html>"
            )
        with open(os.path.join(workspace_dir, "app.js"), "w") as f:
            f.write("document.body.classList.add('reviewed');\n")
        with open(os.path.join(workspace_dir, "styles.css"), "w") as f:
            f.write("body { color: red; }\n")

        session = {
            "projectContext": {
                "intent": {"surface_ask": "Build one HTML page and app.js. No CSS file."},
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
                "constraints": {"hard_requirements": ["No CSS file."]},
            }
        }
        valid_metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "app.js"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }
        invalid_metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}, {"path": "app.js"}, {"path": "styles.css"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        valid = server.validate_model_authored_workspace(workspace_dir, valid_metadata, session)
        invalid = server.validate_model_authored_workspace(workspace_dir, invalid_metadata, session)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><link rel=\"stylesheet\" href=\"styles.css\">"
                "<script src=\"app.js\"></script></head><body>"
                "<button id=\"checkStatusButton\">Check Status</button></body></html>"
            )
        linked = server.validate_model_authored_workspace(workspace_dir, valid_metadata, session)

        self.assertTrue(valid["passed"], valid["failures"])
        self.assertFalse(invalid["passed"])
        self.assertTrue(any("CSS file was forbidden" in item for item in invalid["failures"]))
        self.assertFalse(linked["passed"])
        self.assertTrue(any("HTML links" in item for item in linked["failures"]))

    def test_missing_linked_javascript_support_file_blocks_delivery(self):
        workspace_dir = os.path.join(self.tmp.name, "html-js-missing")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "index.html"), "w") as f:
            f.write(
                "<!doctype html><html><head><script src=\"app.js\" defer></script></head>"
                "<body><button id=\"run\">Run</button><p id=\"status\">Idle</p></body></html>"
            )

        session = {
            "projectContext": {
                "deliverable": {"format": "html", "count": 1, "path_pattern": "index.html"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "index.html"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("app.js" in item and "not found" in item for item in validation["failures"]))

    def test_html_js_context_enrichment_treats_javascript_as_support_file(self):
        parsed = {
            "project": {"name": "button demo", "type": "code", "domain": "web"},
            "intent": {
                "surface_ask": "Deliver one HTML page and one linked JavaScript file named app.js.",
                "underlying_need": "A tiny interactive page.",
                "success_means": "index.html links app.js.",
            },
            "deliverable": {
                "format": "html",
                "count": 2,
                "path_pattern": "index.html",
                "encoding": "gforge_file_block",
                "partial": False,
                "scope": "One page plus support script.",
                "anti_deflection": "stub",
            },
            "capabilities_required": ["emit_files"],
            "constraints": {"hard_requirements": []},
            "skill": {"use": "code-writer"},
            "acceptance": ["index.html exists.", "app.js exists."],
            "open_questions": [],
            "content_requirements": [],
        }

        server.enrich_project_context(
            parsed,
            "Build one HTML page and one linked JavaScript file named app.js.",
            model="gemma-4-e4b-it",
        )

        self.assertEqual(parsed["deliverable"]["count"], 1)
        self.assertEqual(parsed["support_files"][0]["format"], "javascript")
        self.assertEqual(parsed["support_files"][0]["path_pattern"], "app.js")
        self.assertFalse(any(item.get("format") == "css" for item in parsed["support_files"]))

    def test_python_script_side_effect_counts_are_validated_in_temp_run(self):
        workspace_dir = os.path.join(self.tmp.name, "script-side-effects")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "setup_structure.py"), "w") as f:
            f.write("from pathlib import Path\nprint('ready')\n")

        session = {
            "projectContext": {
                "deliverable": {"format": "python", "count": 1, "path_pattern": "setup_structure.py"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [
                    {
                        "count": 5,
                        "item": "directories named dir1, dir2, dir3, dir4, dir5",
                        "scope": "at the same root level of the parent directory named test",
                        "source": "creates 5 directories named like dir1, dir2, dir3, dir4, dir5",
                    },
                    {
                        "count": 25,
                        "item": ".txt files with 1 small paragraph on the decided subject",
                        "scope": "5 .txt files in each",
                        "source": "write out 5 .txt files in each",
                    },
                ],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "setup_structure.py"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        def fake_run(tmpdir, commands, **_kwargs):
            root = os.path.join(tmpdir, "test")
            os.makedirs(os.path.join(root, "src"), exist_ok=True)
            for dir_index in range(1, 6):
                dirname = os.path.join(root, f"dir{dir_index}")
                os.makedirs(dirname, exist_ok=True)
                for file_index in range(1, 6):
                    with open(os.path.join(dirname, f"file{file_index}.txt"), "w") as f:
                        f.write("A small paragraph.\n")
            return [{"ok": True, "skipped": False, "command": "python setup_structure.py", "returncode": 0}]

        with patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True), \
                patch.object(server.tool_workspace, "run_workspace_commands", side_effect=fake_run):
            validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])
        self.assertEqual(validation["contentRequirements"][0]["actual"], 5)
        self.assertEqual(validation["contentRequirements"][1]["actual"], 25)
        self.assertEqual(validation["contentRequirements"][0]["mode"], "script_runtime")
        self.assertFalse(os.path.exists(os.path.join(workspace_dir, "test")))

    def test_python_script_runtime_requirements_can_be_inferred_from_acceptance(self):
        workspace_dir = os.path.join(self.tmp.name, "script-side-effect-inferred")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "setup_structure.py"), "w") as f:
            f.write("from pathlib import Path\nprint('ready')\n")

        session = {
            "projectContext": {
                "intent": {
                    "surface_ask": "write a python script i can launch that creates 5 directories named like dir1, dir2, dir3, dir4, dir5 and 5 .txt files in each of the five numbered directories",
                    "success_means": "The script creates the requested test directory structure when run.",
                },
                "deliverable": {"format": "python", "count": 1, "path_pattern": "setup_structure.py"},
                "capabilities_required": ["emit_files"],
                "constraints": {
                    "hard_requirements": [
                        "The script must create five subdirectories named dir1 through dir5.",
                        "The script must create 5 files named *.txt inside each of the five numbered directories.",
                    ]
                },
                "acceptance": [
                    "Executing setup_structure.py results in test/dir1 through test/dir5 and 25 total .txt files."
                ],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "setup_structure.py"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        def fake_run(tmpdir, commands, **_kwargs):
            root = os.path.join(tmpdir, "test")
            os.makedirs(os.path.join(root, "src"), exist_ok=True)
            for dir_index in range(1, 6):
                dirname = os.path.join(root, f"dir{dir_index}")
                os.makedirs(dirname, exist_ok=True)
                for file_index in range(1, 6):
                    with open(os.path.join(dirname, f"file{file_index}.txt"), "w") as f:
                        f.write("A small paragraph.\n")
            return [{"ok": True, "skipped": False, "command": "python setup_structure.py", "returncode": 0}]

        with patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True), \
                patch.object(server.tool_workspace, "run_workspace_commands", side_effect=fake_run):
            validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertTrue(validation["passed"], validation["failures"])
        self.assertTrue(any(item["actual"] == 5 and "director" in item["item"] for item in validation["contentRequirements"]))
        self.assertTrue(any(item["actual"] == 25 and ".txt" in item["item"] for item in validation["contentRequirements"]))
        self.assertFalse(os.path.exists(os.path.join(workspace_dir, "test")))

    def test_python_context_enrichment_detects_script_runtime_counts(self):
        parsed = {
            "project": {"name": "setup script", "type": "code"},
            "intent": {"surface_ask": "", "underlying_need": "", "success_means": ""},
            "deliverable": {"format": "python", "count": 1, "path_pattern": "setup_structure.py"},
            "capabilities_required": ["emit_files"],
            "constraints": {"hard_requirements": []},
            "skill": {"use": "code-writer"},
            "acceptance": ["setup_structure.py exists."],
            "open_questions": [],
            "content_requirements": [],
        }

        server.enrich_project_context(
            parsed,
            "write a python script i can launch that creates 5 directories named like dir1, dir2, dir3, dir4, dir5 and write out 5 .txt files in each of the five numbered directories",
            model="gemma-4-e4b-it",
        )

        self.assertTrue(any("director" in item["item"] and item["minimum_total"] == 5 for item in parsed["content_requirements"]))
        self.assertTrue(any(".txt" in item["item"] and item["minimum_total"] == 25 for item in parsed["content_requirements"]))

    def test_python_script_runtime_failure_blocks_delivery(self):
        workspace_dir = os.path.join(self.tmp.name, "script-runtime-fail")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "setup_structure.py"), "w") as f:
            f.write("from pathlib import Path\nprint('ready')\n")

        session = {
            "projectContext": {
                "deliverable": {"format": "python", "count": 1, "path_pattern": "setup_structure.py"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [
                    {
                        "count": 5,
                        "item": "directories named dir1, dir2, dir3, dir4, dir5",
                        "scope": "at the same root level of the parent directory named test",
                        "source": "creates 5 directories named like dir1, dir2, dir3, dir4, dir5",
                    }
                ],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "setup_structure.py"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        with patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True), \
                patch.object(server.tool_workspace, "run_workspace_commands", return_value=[{
                    "ok": False,
                    "skipped": False,
                    "command": "python setup_structure.py",
                    "returncode": 1,
                    "stderr": "NameError: boom",
                }]):
            validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("script runtime validation failed" in item for item in validation["failures"]))

    def test_python_deliverable_syntax_error_blocks_delivery(self):
        workspace_dir = os.path.join(self.tmp.name, "script-syntax-fail")
        os.makedirs(workspace_dir, exist_ok=True)
        with open(os.path.join(workspace_dir, "setup_structure.py"), "w") as f:
            f.write("def broken(:\n    pass\n")

        session = {
            "projectContext": {
                "deliverable": {"format": "python", "count": 1, "path_pattern": "setup_structure.py"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "setup_structure.py"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("invalid Python deliverable" in item for item in validation["failures"]))

    def test_validation_counts_category_reports_inside_pdf_deliverables(self):
        workspace_dir = os.path.join(self.tmp.name, "pdf-content-count")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        files = []
        for index, category in enumerate(["Automation", "Business", "Technical"], start=1):
            relative_path = f"output/category-{index}.pdf"
            with open(os.path.join(workspace_dir, relative_path), "wb") as f:
                f.write(b"%PDF-1.4\n%%EOF\n")
            files.append({"path": relative_path})

        project_context = {
            "content_requirements": [
                {
                    "count": 3,
                    "item": "categories",
                    "scope": "whole deliverable",
                    "source": "create 3 categories based on content",
                }
            ],
        }

        with patch.object(
            server,
            "extract_pdf_validation_text",
            side_effect=[f"Category Report: {category}" for category in ["Automation", "Business", "Technical"]],
        ):
            failures, results = server.validate_content_quantity_requirements(workspace_dir, files, project_context)

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["actual"], 3)

    def test_validation_fails_when_deliverable_file_count_is_under_delivered(self):
        workspace_dir = os.path.join(self.tmp.name, "file-count-under")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        with open(os.path.join(workspace_dir, "output", "logo-01.svg"), "w") as f:
            f.write("<svg></svg>")

        session = {
            "projectContext": {
                "deliverable": {"format": "svg", "count": 3, "path_pattern": "output/logo-NN.svg"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "output/logo-01.svg"}],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("deliverable.count expected at least 3" in item for item in validation["failures"]))

    def test_pdf_shell_context_gets_workspace_package_install_capability(self):
        parsed = {
            "project": {"name": "PDF report", "type": "doc"},
            "intent": {"surface_ask": "Create PDF reports.", "underlying_need": "", "success_means": ""},
            "deliverable": {"format": "pdf", "count": 3, "path_pattern": "output/report-NN.pdf"},
            "capabilities_required": ["emit_files", "shell_exec", "pdf"],
            "constraints": {"hard_requirements": []},
            "skill": {"use": "pdf"},
            "acceptance": ["Three PDFs exist.", "The PDFs open."],
            "open_questions": [],
        }

        with patch.object(server.tool_workspace, "can_run_workspace_commands", return_value=True), \
                patch.object(server.tool_workspace, "can_install_packages", return_value=True):
            server.enrich_project_context(parsed, "Create three PDF reports.", model="gemma-4")

        self.assertIn("install_package", parsed["capabilities_required"])

    def test_validation_fails_when_workspace_command_failed(self):
        workspace_dir = os.path.join(self.tmp.name, "command-failed")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        with open(os.path.join(workspace_dir, "output", "report.txt"), "w") as f:
            f.write("Report body")

        session = {
            "projectContext": {
                "deliverable": {"format": "txt", "count": 1, "path_pattern": "output/report.txt"},
                "capabilities_required": ["emit_files", "shell_exec"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "output/report.txt"}],
            "commands": ["python scripts/process.py"],
            "commandRuns": [
                {
                    "ok": False,
                    "skipped": False,
                    "command": "python scripts/process.py",
                    "returncode": 1,
                    "stderr": "ModuleNotFoundError: No module named 'pdfplumber'",
                }
            ],
            "summary": "The script ran successfully.",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("workspace command failed" in item for item in validation["failures"]))
        self.assertTrue(any("pdfplumber" in item for item in validation["failures"]))

    def test_validation_fails_for_invalid_pdf_deliverable(self):
        workspace_dir = os.path.join(self.tmp.name, "invalid-pdf")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        with open(os.path.join(workspace_dir, "output", "report.pdf"), "wb") as f:
            f.write(
                b"%PDF-1.7\n"
                b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                b"stream\nThis is not a valid generated PDF structure.\n"
                b"%%EOF"
            )

        session = {
            "projectContext": {
                "deliverable": {"format": "pdf", "count": 1, "path_pattern": "output/report.pdf"},
                "capabilities_required": ["emit_files"],
                "content_requirements": [],
            }
        }
        metadata = {
            "modelAuthored": True,
            "files": [{"path": "output/report.pdf"}],
            "commands": [],
            "commandRuns": [],
            "summary": "",
            "notes": [],
            "verification": [],
        }

        validation = server.validate_model_authored_workspace(workspace_dir, metadata, session)

        self.assertFalse(validation["passed"])
        self.assertTrue(any("invalid PDF deliverable" in item for item in validation["failures"]))

    def test_workspace_yolo_infers_python_import_dependencies(self):
        workspace_dir = os.path.join(self.tmp.name, "dependency-infer")
        os.makedirs(workspace_dir, exist_ok=True)
        session = {
            "projectContext": {
                "deliverable": {"format": "txt", "count": 1, "path_pattern": "output/report.txt"},
                "capabilities_required": ["emit_files", "shell_exec"],
                "content_requirements": [],
            }
        }
        files = [
            {
                "path": "scripts/process.py",
                "content": "import os\nimport pandas\nimport yaml\nfrom bs4 import BeautifulSoup\n",
            }
        ]

        with patch.object(server.tool_workspace, "can_install_packages", return_value=True):
            commands = server.augment_workspace_commands_for_dependencies(
                workspace_dir,
                session,
                files,
                ["python scripts/process.py"],
            )

        self.assertEqual(len(commands), 2)
        self.assertTrue(commands[0].startswith("python -m pip install "))
        self.assertIn("pandas", commands[0])
        self.assertIn("PyYAML", commands[0])
        self.assertIn("beautifulsoup4", commands[0])
        self.assertNotIn(" os", commands[0])
        self.assertEqual(commands[1], "python scripts/process.py")

    def test_execution_quarantines_stale_deliverables_before_retry(self):
        workspace_dir = os.path.join(self.tmp.name, "stale-output")
        os.makedirs(os.path.join(workspace_dir, "output"), exist_ok=True)
        stale_path = os.path.join(workspace_dir, "output", "report.pdf")
        with open(stale_path, "wb") as f:
            f.write(b"%PDF-1.7\nbroken\n%%EOF")
        session = {
            "projectContext": {
                "deliverable": {"format": "pdf", "count": 1, "path_pattern": "output/report.pdf"},
                "capabilities_required": ["emit_files", "shell_exec"],
                "content_requirements": [],
            }
        }

        moved = server.quarantine_existing_deliverables(workspace_dir, session)

        self.assertFalse(os.path.exists(stale_path))
        self.assertEqual(moved[0]["path"], "output/report.pdf")
        self.assertTrue(os.path.exists(os.path.join(workspace_dir, moved[0]["backup"])))


if __name__ == "__main__":
    unittest.main()
