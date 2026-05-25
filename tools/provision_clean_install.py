#!/usr/bin/env python3
"""Post-install provisioning for a clean Gemma Forge install.

The shell launcher installs binaries and Python/Node packages. This script
performs the first-use work that makes the installed toolchain actually usable:
embedding model pull, bundled skill verification, SocratiCode/Qdrant indexing,
and Axon indexing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(os.environ.get("GFORGE_PROJECT_ROOT") or Path(__file__).resolve().parents[1])
GFORGE_HOME = Path(os.environ.get("GFORGE_HOME", Path.home() / ".gforge"))
HARNESS_SKILLS_DIR = GFORGE_HOME / "harness" / "skills"
DEFAULT_EMBEDDING_MODEL = os.environ.get("GFORGE_EMBEDDING_MODEL", "nomic-embed-text:latest")
EXPECTED_SKILLS = (
    "webot-flow",
    "gsd",
    "code-writer",
    "scrapling-official",
    "ui-ux-pro-max",
    "axon",
    "socraticode",
    "pdf",
    "mcp-builder",
)
REQUIRED_SKILL_FILES = {
    "gsd": (
        "workflows/plan-phase.md",
        "agents/gsd-planner.md",
        "templates/roadmap.md",
    ),
}
REQUIRED_SKILL_FILE_SETS = {
    "ui-ux-pro-max": (
        (
            "skill.json",
            "src/ui-ux-pro-max/templates/base/quick-reference.md",
            "src/ui-ux-pro-max/scripts/search.py",
        ),
        (
            "skill.json",
            ".claude/skills/ui-ux-pro-max/SKILL.md",
            ".claude/skills/ui-ux-pro-max/scripts/search.py",
        ),
    ),
}


class ProvisionError(RuntimeError):
    pass


def step(message: str) -> None:
    print(f"[forge provision] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[forge provision warn] {message}", flush=True)


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def ollama_models() -> set[str]:
    result = run(["ollama", "list"], timeout=30)
    if result.returncode != 0:
        raise ProvisionError(result.stderr.strip() or "ollama list failed")
    models: set[str] = set()
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.add(parts[0])
    return models


def model_installed(model: str, models: set[str] | None = None) -> bool:
    names = models if models is not None else ollama_models()
    return any(
        name == model
        or name == f"{model}:latest"
        or name.startswith(f"{model}:")
        for name in names
    )


def skill_missing_reason(name: str) -> str:
    skill_dir = HARNESS_SKILLS_DIR / name
    if not skill_dir.is_dir():
        return "missing directory"
    if not ((skill_dir / "SKILL.md").exists() or (skill_dir / "skill.json").exists()):
        return "missing SKILL.md or skill.json"
    missing = [
        relative_path
        for relative_path in REQUIRED_SKILL_FILES.get(name, ())
        if not (skill_dir / relative_path).exists()
    ]
    if missing:
        return "missing required file(s): " + ", ".join(missing)
    required_sets = REQUIRED_SKILL_FILE_SETS.get(name, ())
    if required_sets and not any(
        all((skill_dir / relative_path).exists() for relative_path in file_set)
        for file_set in required_sets
    ):
        options = [
            "[" + ", ".join(file_set) + "]"
            for file_set in required_sets
        ]
        return "missing required file set: " + " or ".join(options)
    return ""


def skill_ready(name: str) -> bool:
    return not skill_missing_reason(name)


def require_skills() -> None:
    missing = {
        name: reason
        for name in EXPECTED_SKILLS
        if (reason := skill_missing_reason(name))
    }
    if missing:
        details = "; ".join(f"{name} ({reason})" for name, reason in missing.items())
        raise ProvisionError(
            "Bundled skill(s) were not staged deeply enough: " + details
        )
    step("Bundled protocol skills staged.")


def pull_embedding_model(model: str, timeout: int) -> None:
    if not command_available("ollama"):
        raise ProvisionError("ollama is not on PATH; cannot pull embedding model")
    if model_installed(model):
        step(f"Embedding model already installed: {model}")
        return
    step(f"Pulling embedding model: {model}")
    result = run(["ollama", "pull", model], timeout=timeout)
    if result.returncode != 0:
        raise ProvisionError(result.stderr.strip() or result.stdout.strip() or f"ollama pull {model} failed")
    if not model_installed(model):
        raise ProvisionError(f"Embedding model {model} did not appear in ollama list after pull")
    step(f"Embedding model ready: {model}")


def provision_socraticode(timeout: int) -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from chat.tool_runtime import run_socraticode_project_scan, socraticode_runtime_status

    runtime = socraticode_runtime_status(auto_install=True)
    if not runtime.get("ready"):
        docker = runtime.get("docker", {}) if isinstance(runtime.get("docker"), dict) else {}
        detail = runtime.get("reason") or docker.get("error") or "SocratiCode runtime is not ready."
        raise ProvisionError(f"SocratiCode runtime is not ready: {detail}")

    docker = runtime.get("docker", {}) if isinstance(runtime.get("docker"), dict) else {}
    qdrant_before = docker.get("qdrantStatus") or "not created yet"
    step(f"SocratiCode runtime ready; Qdrant before index: {qdrant_before}")
    scan = run_socraticode_project_scan(
        str(PROJECT_ROOT),
        "Gemma Forge launcher installer provisioning SocratiCode Axon readiness",
        timeout=timeout,
    )
    if scan.get("status") != "complete":
        raise ProvisionError(scan.get("reason") or "SocratiCode provisioning did not complete")
    chunks = scan.get("indexedChunks")
    step(f"SocratiCode indexed and searched this checkout; chunks={chunks}")


def provision_axon(timeout: int) -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from chat.tool_runtime import axon_runtime_status, run_axon_project_scan

    runtime = axon_runtime_status()
    if not runtime.get("ready"):
        raise ProvisionError(runtime.get("reason") or "Axon runtime is not ready.")
    scan = run_axon_project_scan(str(PROJECT_ROOT), timeout=timeout)
    if scan.get("status") != "complete":
        raise ProvisionError(scan.get("reason") or "Axon provisioning did not complete")
    step("Axon analyzed this checkout and wrote a project index.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("GFORGE_PROVISION_TIMEOUT", "1200")))
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        default=os.environ.get("GFORGE_ALLOW_DEGRADED_TOOLS", "0").lower() in {"1", "true", "yes", "on"},
        help="Warn instead of failing when SocratiCode or Axon cannot be fully provisioned.",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        default=os.environ.get("GFORGE_SKIP_EMBEDDING_MODEL_PULL", "0").lower() in {"1", "true", "yes", "on"},
    )
    args = parser.parse_args()

    failures: list[str] = []

    for label, action in (
        ("skills", require_skills),
        ("embedding model", lambda: None if args.skip_embedding else pull_embedding_model(args.embedding_model, args.timeout)),
        ("SocratiCode/Qdrant", lambda: provision_socraticode(args.timeout)),
        ("Axon index", lambda: provision_axon(args.timeout)),
    ):
        try:
            action()
        except Exception as error:  # noqa: BLE001 - installer must surface exact failing step.
            message = f"{label}: {error}"
            if args.allow_degraded:
                warn(message)
            else:
                failures.append(message)

    if failures:
        for message in failures:
            print(f"[forge provision fail] {message}", file=sys.stderr, flush=True)
        return 1

    step("Post-install provisioning complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
