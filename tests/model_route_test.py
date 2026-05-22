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

    def tearDown(self):
        for key, value in self.old_values.items():
            setattr(server, key, value)
        server._storage_ready = False
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
        self.assertEqual(server.DEFAULT_MODEL, "gemma-4")
        self.assertEqual(captured["url"], "http://localhost:11434/api/chat")
        self.assertEqual(captured["json"]["model"], "gemma-4")

        with open(server.MODEL_ROUTE_FILE, "r") as f:
            route = json.load(f)

        self.assertEqual(route["model"], "gemma-4")
        self.assertEqual(route["defaultModel"], "gemma-4")

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
                        "name": "gemma-4:latest",
                        "model": "gemma-4:latest",
                        "details": {"parameter_size": "4.6B"},
                    }
                ]
            }
        }

        with patch.object(server, "scan_workspace", return_value=workspace):
            self.assertTrue(server.small_model_review_required("gemma-4"))

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

    def test_selected_model_can_be_saved_to_project(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a local app.",
            "gemma-4",
            requested_id="model-switch-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions)

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
        server.save_sessions(sessions)
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

    def test_auto_run_section_waits_when_small_model_review_fails(self):
        sessions = {}
        session_id = server.create_session_record(
            sessions,
            "Create a small test page.",
            "gemma-4",
            requested_id="review-gate-test",
            has_project_directory=False,
        )
        server.save_sessions(sessions)

        def fake_action(_session_id, _session, _card_id, _model, _mode):
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

        with patch.object(server, "call_ollama_execution_payload", return_value=(model_payload, json.dumps(model_payload))):
            result = server.run_execution_card("desired-execution-test", session, "gemma-4", "auto")

        self.assertTrue(os.path.exists(os.path.join(desired_path, "index.html")))
        self.assertEqual(result["workspace"], desired_path)
        self.assertEqual(session["projectDirectory"], desired_path)

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

        with patch.object(server, "call_ollama_execution_payload", return_value=(model_payload, json.dumps(model_payload))):
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

        with patch.object(server, "call_ollama", return_value=raw):
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
            return model_payload, json.dumps(model_payload)

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


if __name__ == "__main__":
    unittest.main()
