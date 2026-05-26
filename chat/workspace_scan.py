import os
import platform
import shutil
import subprocess
from typing import Any

import requests
try:
    from .tool_runtime import (
        axon_project_probe,
        axon_runtime_status,
        socraticode_mcp_probe,
        socraticode_runtime_status,
    )
except ImportError:
    from tool_runtime import (
        axon_project_probe,
        axon_runtime_status,
        socraticode_mcp_probe,
        socraticode_runtime_status,
    )


OLLAMA_API = "http://localhost:11434"
HOME = os.path.expanduser("~")
GFORGE_HOME = os.environ.get("GFORGE_HOME", os.path.join(HOME, ".gforge"))
OLLAMA_HOME = os.environ.get("OLLAMA_HOME", os.path.join(HOME, ".ollama"))
MODELS_ROOT = os.environ.get("GFORGE_MODELS_ROOT", os.path.join(GFORGE_HOME, "models"))
OLLAMA_MODELS_ROOT = os.environ.get("OLLAMA_MODELS", os.path.join(OLLAMA_HOME, "models"))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CODEX_HOME = os.environ.get("CODEX_HOME", os.path.join(HOME, ".codex"))
HARNESS_SKILLS_DIR = os.path.join(GFORGE_HOME, "harness", "skills")
GFORGE_SKILLS_DIR = os.path.join(GFORGE_HOME, "skills")
PROJECT_SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
AGENTS_SKILLS_DIR = os.path.join(HOME, ".agents", "skills")
LLAMA_CPP_DEFAULT = os.path.join(GFORGE_HOME, "tools", "llama.cpp")
LLAMA_CPP_ROOT = os.environ.get("LLAMA_CPP_ROOT") or (
    "/Users/webot/Projects/gguf/llama.cpp"
    if os.path.isdir("/Users/webot/Projects/gguf/llama.cpp")
    else LLAMA_CPP_DEFAULT
)
HF_TOKEN_DEFAULT = os.path.join(GFORGE_HOME, "credentials", "hf-token")
HF_TOKEN_LEGACY_PATH = "/Users/webot/.webot/credentials/hf-token"
HF_TOKEN_PATH_ENV_VARS = ("GFORGE_HF_TOKEN_PATH", "HF_TOKEN_PATH")
HF_TOKEN_VALUE_ENV_VARS = ("GFORGE_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


def _expand_config_path(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path.strip()))


def hf_token_from_env() -> str | None:
    for key in HF_TOKEN_VALUE_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def resolve_hf_token_path() -> str:
    for key in HF_TOKEN_PATH_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            return _expand_config_path(value)
    if os.path.exists(HF_TOKEN_LEGACY_PATH):
        return HF_TOKEN_LEGACY_PATH
    return HF_TOKEN_DEFAULT


def hf_token_ready() -> bool:
    return bool(hf_token_from_env()) or os.path.exists(resolve_hf_token_path())


HF_TOKEN_PATH = resolve_hf_token_path()
FORGE_FLOW_SKILL_PATH = os.path.join(CODEX_HOME, "skills", "webot-flow", "SKILL.md")
GSD_SKILL_PATH = os.path.join(CODEX_HOME, "skills", "gsd", "SKILL.md")
SOCRATICODE_SKILL_PATH = os.path.join(CODEX_HOME, "skills", "socraticode")
AXON_FALLBACK_PATH = os.path.join(HOME, ".local", "bin", "axon")
SOCRATICODE_FALLBACK_PATH = os.path.join(HOME, ".local", "bin", "socraticode")
DEFAULT_MODEL = os.environ.get("GFORGE_DEFAULT_MODEL", "gemma-4-e4b-it")


MODEL_OPTIONS = [
    {
        "id": "google/gemma-4-E4B-it",
        "label": "Gemma 4 E4B",
        "ollamaName": "gemma-4-e4b-it",
        "description": "Default edge model with stronger harness reasoning and broad local compatibility.",
        "requiredRamGb": 8,
        "requiredDiskGb": 10,
        "baseline": True,
        "recommended": True,
    },
    {
        "id": "google/gemma-4-31B-it",
        "label": "Gemma 4 Dense 31B",
        "ollamaName": "gemma4:31b-max",
        "description": "Higher-quality dense model for stronger machines.",
        "requiredRamGb": 28,
        "requiredDiskGb": 24,
        "baseline": False,
        "recommended": False,
    },
    {
        "id": "google/gemma-4-moe-26B-it",
        "label": "Gemma 4 MoE 26B",
        "ollamaName": "gemma-4-moe",
        "description": "Advanced reasoning lane when memory headroom is available.",
        "requiredRamGb": 24,
        "requiredDiskGb": 22,
        "baseline": False,
        "recommended": False,
    },
]


def _run(command: list[str], timeout: int = 3) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _memory_gb() -> float | None:
    if platform.system() == "Darwin":
        result = _run(["sysctl", "-n", "hw.memsize"])
        if result and result.returncode == 0:
            try:
                return round(int(result.stdout.strip()) / (1024**3), 1)
            except ValueError:
                return None

    meminfo_path = "/proc/meminfo"
    if os.path.exists(meminfo_path):
        with open(meminfo_path, "r") as file:
            for line in file:
                if line.startswith("MemTotal:"):
                    value = line.split()[1]
                    return round(int(value) / (1024**2), 1)

    return None


def _disk_free_gb(path: str) -> float | None:
    target = path if os.path.exists(path) else os.path.dirname(path)
    if not target or not os.path.exists(target):
        target = os.path.expanduser("~")
    try:
        usage = shutil.disk_usage(target)
        return round(usage.free / (1024**3), 1)
    except OSError:
        return None


def _ollama_models() -> list[dict[str, Any]]:
    try:
        response = requests.get(f"{OLLAMA_API}/api/tags", timeout=2)
        response.raise_for_status()
        payload = response.json()
        return payload.get("models", [])
    except requests.RequestException:
        return []


def _is_model_installed(ollama_name: str, installed_models: list[dict[str, Any]]) -> bool:
    names = set()
    for model in installed_models:
        name = model.get("name")
        model_name = model.get("model")
        if name:
            names.add(name)
        if model_name:
            names.add(model_name)

    return (
        ollama_name in names
        or f"{ollama_name}:latest" in names
        or any(name.startswith(f"{ollama_name}:") for name in names)
    )


def scan_workspace() -> dict[str, Any]:
    memory_gb = _memory_gb()
    disk_free_gb = _disk_free_gb(MODELS_ROOT)
    ollama_path = shutil.which("ollama")
    installed_models = _ollama_models()
    ollama_running = bool(installed_models) or _ollama_is_running()
    agent_capacity = _agent_capacity(memory_gb, os.cpu_count())

    model_options = []
    for model in MODEL_OPTIONS:
        ram_ok = memory_gb is None or memory_gb >= model["requiredRamGb"]
        disk_ok = disk_free_gb is None or disk_free_gb >= model["requiredDiskGb"]
        supported = model["baseline"] or (ram_ok and disk_ok)
        reason = ""
        if not supported:
            missing = []
            if not ram_ok:
                missing.append(f"{model['requiredRamGb']} GB RAM")
            if not disk_ok:
                missing.append(f"{model['requiredDiskGb']} GB free disk")
            reason = "Needs " + " and ".join(missing)

        model_options.append(
            {
                **model,
                "selected": model["ollamaName"] == DEFAULT_MODEL,
                "locked": False,
                "supported": supported,
                "disabledReason": reason,
                "installed": _is_model_installed(model["ollamaName"], installed_models),
            }
        )

    if not ollama_path:
        ollama_plan = "Gemma Forge will install Ollama before provisioning models."
    elif not ollama_running:
        ollama_plan = "Gemma Forge found Ollama and will start the local service."
    else:
        ollama_plan = "Gemma Forge found Ollama running and will reuse it."

    return {
        "status": "ready",
        "system": {
            "os": platform.platform(),
            "machine": platform.machine(),
            "cpuCount": os.cpu_count(),
            "memoryGb": memory_gb,
            "diskFreeGb": disk_free_gb,
        },
        "paths": {
            "gforgeHome": GFORGE_HOME,
            "ollamaHome": OLLAMA_HOME,
            "modelsRoot": MODELS_ROOT,
            "ollamaModelsRoot": OLLAMA_MODELS_ROOT,
            "llamaCppRoot": LLAMA_CPP_ROOT,
            "hfTokenPath": HF_TOKEN_PATH,
        },
        "ollama": {
            "installed": bool(ollama_path),
            "path": ollama_path,
            "running": ollama_running,
            "plan": ollama_plan,
            "models": installed_models,
        },
        "tools": _tool_status(),
        "agentCapacity": agent_capacity,
        "modelOptions": model_options,
    }


def _ollama_is_running() -> bool:
    try:
        response = requests.get(f"{OLLAMA_API}/api/version", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _agent_capacity(memory_gb: float | None, cpu_count: int | None) -> dict[str, Any]:
    if memory_gb is None or cpu_count is None:
        return {
            "maxParallelSubagents": 0,
            "mode": "single-agent-audit",
            "reviewStrategy": (
                "Resource capacity is unknown. Review stages should run as an independent "
                "audit pass by the main agent."
            ),
        }

    memory_slots = max(0, int((memory_gb - 8) // 12))
    cpu_slots = max(0, cpu_count // 4)
    max_parallel = min(6, memory_slots, cpu_slots)

    if max_parallel <= 0:
        return {
            "maxParallelSubagents": 0,
            "mode": "single-agent-audit",
            "reviewStrategy": (
                "Do not spawn subagents. Review each section from an auditor perspective "
                "that assumes the work may be incomplete or incorrect."
            ),
        }

    return {
        "maxParallelSubagents": max_parallel,
        "mode": "parallel-ready",
        "reviewStrategy": (
            f"Up to {max_parallel} subagents can be used when the task benefits from "
            "parallel codebase mapping, implementation, or verification."
        ),
    }


def _skill_install_roots() -> list[str]:
    return [
        HARNESS_SKILLS_DIR,
        GFORGE_SKILLS_DIR,
        PROJECT_SKILLS_DIR,
        os.path.join(CODEX_HOME, "skills"),
        AGENTS_SKILLS_DIR,
    ]


def _skill_ready(name: str) -> bool:
    for root in _skill_install_roots():
        skill_dir = os.path.join(root, name)
        if os.path.exists(os.path.join(skill_dir, "SKILL.md")):
            return True
        if os.path.exists(os.path.join(skill_dir, "skill.json")):
            return True
        if name == "socraticode" and os.path.isdir(skill_dir):
            return True
    return False


def _tool_status() -> dict[str, Any]:
    axon = axon_runtime_status()
    socraticode = socraticode_runtime_status(auto_install=True)
    socraticode_probe = socraticode_mcp_probe(PROJECT_ROOT) if socraticode.get("ready") else {
        "ready": False,
        "stdout": "",
        "stderr": socraticode.get("reason"),
    }
    axon_probe = axon_project_probe(PROJECT_ROOT) if axon.get("ready") else {
        "ready": False,
        "stdout": "",
        "stderr": axon.get("reason"),
    }
    socraticode_skill_ready = _skill_ready("socraticode")
    axon_index_ready = os.path.exists(os.path.join(PROJECT_ROOT, ".axon", "meta.json"))
    docker = socraticode.get("docker", {})
    node = socraticode.get("node", {})

    return {
        "llamaCppReady": os.path.isdir(LLAMA_CPP_ROOT),
        "hfTokenReady": hf_token_ready(),
        "forgeFlowReady": _skill_ready("webot-flow"),
        "gsdReady": _skill_ready("gsd"),
        "socraticodeReady": bool(socraticode.get("ready") and socraticode_probe.get("ready")),
        "socraticodeExecutable": bool(socraticode.get("executable")),
        "socraticodeInstalled": bool(socraticode.get("installed")),
        "socraticodeSkillReady": socraticode_skill_ready,
        "socraticodeMode": socraticode.get("mode", "unavailable"),
        "socraticodePath": socraticode.get("path"),
        "socraticodeReason": socraticode.get("reason"),
        "socraticodeNodeReady": bool(node.get("ready")),
        "socraticodeNodeVersion": node.get("version"),
        "socraticodeDockerReady": bool(docker.get("ready")),
        "socraticodeQdrantRunning": bool(docker.get("qdrantRunning")),
        "socraticodeQdrantStatus": docker.get("qdrantStatus"),
        "socraticodeMcpReady": bool(socraticode_probe.get("ready")),
        "socraticodeMcpStatus": socraticode_probe.get("stdout"),
        "socraticodeMcpError": socraticode_probe.get("stderr"),
        "axonReady": bool(axon.get("ready") and axon_probe.get("ready")),
        "axonExecutable": bool(axon.get("executable")),
        "axonIndexReady": axon_index_ready,
        "axonPath": axon.get("path"),
        "axonVersion": axon.get("version"),
        "axonReason": axon.get("reason"),
        "axonProjectReady": bool(axon_probe.get("ready")),
        "axonProjectStatus": axon_probe.get("stdout"),
        "axonProjectError": axon_probe.get("stderr"),
    }
