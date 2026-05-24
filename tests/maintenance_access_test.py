import json
import os
import tempfile
import unittest

from chat import server, tool_workspace


class MaintenanceAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_model_request_gets_exact_maintenance_targets(self):
        context = server.build_harness_maintenance_targets({
            "project": "Gemma Forge maintenance: set the default Forge Brain model to gemma-4-e4b-it and update the installer.",
            "messages": [],
        })

        paths = {item["path"] for item in context["targets"]}
        self.assertTrue(context["requested"])
        self.assertTrue(context["allowOllama"])
        self.assertIn(os.path.join(server.PROJECT_ROOT, "chat", "server.py"), paths)
        self.assertIn(os.path.join(server.PROJECT_ROOT, "launch_forge.command"), paths)
        self.assertIn(server.MODEL_ROUTE_FILE, paths)

    def test_project_context_enrichment_routes_harness_maintenance(self):
        raw = """
<<<CONTEXT_BEGIN>>>
---
project:
  name: Forge model default
  type: code
  domain: Gemma Forge maintenance
intent:
  surface_ask: "Set the default Forge Brain model to gemma-4-e4b-it."
  underlying_need: Update the harness default model.
  success_means: The default route reports gemma-4-e4b-it.
deliverable:
  format: markdown
  count: 1
  path_pattern: artifacts/maintenance-summary.md
  encoding: gforge_file_block
  partial: false
  scope: Update and verify the requested harness model default.
  anti_deflection: stub
content_requirements: []
capabilities_required:
  - emit_files
constraints:
  hard_requirements:
    - Default model is updated.
  tone:
    - direct
skill:
  use: none
  staged_path: n/a
acceptance:
  - Maintenance actions are recorded.
  - Model route is verified.
open_questions: []
---
<<<CONTEXT_END>>>
"""
        parsed, _yaml_text, errors = server.parse_project_context(
            raw,
            project_text="Gemma Forge maintenance: set the default Forge Brain model to gemma-4-e4b-it.",
        )

        self.assertEqual(errors, [])
        self.assertIn("harness_maintenance", parsed["capabilities_required"])
        self.assertIn("shell_exec", parsed["capabilities_required"])

    def test_maintenance_prompt_names_actions_file_and_targets(self):
        allowed_target = os.path.join(self.tmp.name, "allowed.txt")
        context = {
            "requested": True,
            "manifest": server.MAINTENANCE_TARGETS_MANIFEST,
            "snapshotRoot": server.MAINTENANCE_TARGETS_ROOT,
            "actionsFile": server.MAINTENANCE_ACTIONS_FILE,
            "allowOllama": False,
            "allowDestructive": False,
            "targets": [{
                "path": allowed_target,
                "kind": "file",
                "exists": False,
                "snapshot_root": "references/maintenance-targets/01-allowed",
                "reason": "test target",
            }],
        }

        prompt = server.build_harness_maintenance_context_block(context)

        self.assertIn(server.MAINTENANCE_ACTIONS_FILE, prompt)
        self.assertIn(allowed_target, prompt)
        self.assertIn("copy_file", prompt)

    def test_maintenance_actions_apply_only_to_allowlisted_target(self):
        workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(os.path.join(workspace, "output"), exist_ok=True)
        os.makedirs(os.path.join(workspace, "artifacts"), exist_ok=True)
        allowed_target = os.path.join(self.tmp.name, "allowed.txt")
        blocked_target = os.path.join(self.tmp.name, "blocked.txt")
        source_file = os.path.join(workspace, "output", "replacement.txt")
        with open(source_file, "w") as f:
            f.write("updated")
        with open(os.path.join(workspace, server.MAINTENANCE_ACTIONS_FILE), "w") as f:
            json.dump({
                "actions": [
                    {"type": "copy_file", "source": "output/replacement.txt", "target": allowed_target},
                    {"type": "copy_file", "source": "output/replacement.txt", "target": blocked_target},
                ],
            }, f)
        context = {
            "requested": True,
            "targets": [{"path": allowed_target, "kind": "file", "exists": False}],
            "allowDestructive": False,
            "allowOllama": False,
        }

        result = server.apply_harness_maintenance_actions(workspace, context)

        self.assertEqual(len(result["applied"]), 1)
        with open(allowed_target, "r") as f:
            self.assertEqual(f.read(), "updated")
        self.assertFalse(os.path.exists(blocked_target))
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("allowlist", result["skipped"][0]["reason"])

    def test_ollama_command_requires_maintenance_gate(self):
        args, reason = tool_workspace.normalize_workspace_command("ollama list")
        self.assertIsNone(args)
        self.assertIn("allowlist", reason)

        args, reason = tool_workspace.normalize_workspace_command(
            "ollama list",
            maintenance_targets={"allowOllama": True},
        )
        self.assertEqual(reason, "")
        self.assertEqual(args[:2], ["ollama", "list"])

        args, reason = tool_workspace.normalize_workspace_command(
            "ollama serve",
            maintenance_targets={"allowOllama": True},
        )
        self.assertIsNone(args)
        self.assertIn("not allowed", reason)

        args, reason = tool_workspace.normalize_workspace_command(
            "ollama rm gemma-4-e4b-it",
            maintenance_targets={"allowOllama": True, "allowDestructive": False},
        )
        self.assertIsNone(args)
        self.assertIn("destructive", reason)


@unittest.skipUnless(tool_workspace.can_run_workspace_commands(), "sandbox-exec is unavailable")
class MaintenanceSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_workspace_exec_still_blocks_disallowed_external_writes(self):
        workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(workspace, exist_ok=True)
        blocked_target = os.path.join(self.tmp.name, "blocked-write.txt")
        with open(os.path.join(workspace, "try_write.py"), "w") as f:
            f.write(
                "from pathlib import Path\n"
                f"Path({blocked_target!r}).write_text('nope')\n"
            )

        result = tool_workspace.run_workspace_commands(workspace, ["python try_write.py"])

        self.assertFalse(result[0]["ok"])
        self.assertFalse(os.path.exists(blocked_target))


if __name__ == "__main__":
    unittest.main()
