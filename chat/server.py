import os
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
import hashlib
import requests
import yaml
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS

try:
    from . import tool_browse  # type: ignore
except ImportError:
    import tool_browse  # type: ignore

try:
    from . import tool_screenshot  # type: ignore
except ImportError:
    import tool_screenshot  # type: ignore

import collections
import threading
import queue


# ============================================================
# Activity event stream (SSE)
# ============================================================
_EVENT_BUFFER = collections.deque(maxlen=400)
_EVENT_LOCK = threading.Lock()
_EVENT_SUBSCRIBERS = []  # list of queue.Queue
_EVENT_SEQ = 0


def emit_event(kind, message, **extra):
    """Push an event onto the ring buffer + fan out to live SSE subscribers.

    Safe to call from any thread. Never raises; failures are swallowed so
    instrumentation doesn't break the harness.
    """
    global _EVENT_SEQ
    try:
        payload = {
            "kind": kind,
            "message": str(message)[:500],
            "at": utc_now(),
        }
        if extra:
            payload["extra"] = {k: v for k, v in extra.items() if v is not None}
        with _EVENT_LOCK:
            _EVENT_SEQ += 1
            payload["seq"] = _EVENT_SEQ
            _EVENT_BUFFER.append(payload)
            subs = list(_EVENT_SUBSCRIBERS)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass
    except Exception:
        pass


def _subscribe_events():
    q = queue.Queue(maxsize=200)
    with _EVENT_LOCK:
        _EVENT_SUBSCRIBERS.append(q)
        snapshot = list(_EVENT_BUFFER)
    return q, snapshot


def _unsubscribe_events(q):
    with _EVENT_LOCK:
        try:
            _EVENT_SUBSCRIBERS.remove(q)
        except ValueError:
            pass
try:
    from .workspace_scan import GFORGE_HOME, scan_workspace
    from .tool_runtime import (
        axon_runtime_status,
        axon_project_probe,
        run_axon_project_scan,
        run_socraticode_project_scan,
        socraticode_mcp_probe,
        socraticode_runtime_status,
    )
except ImportError:
    from workspace_scan import GFORGE_HOME, scan_workspace
    from tool_runtime import (
        axon_runtime_status,
        axon_project_probe,
        run_axon_project_scan,
        run_socraticode_project_scan,
        socraticode_mcp_probe,
        socraticode_runtime_status,
    )

app = Flask(__name__)
CORS(app)

CHAT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CHAT_ROOT, ".."))
GFORGE_DATA_ROOT = os.path.join(GFORGE_HOME, "harness")
SESSIONS_FILE = os.path.join(GFORGE_DATA_ROOT, "sessions.json")
MODELS_FILE = os.path.join(GFORGE_DATA_ROOT, "models.json")
SESSION_ROOT = os.path.join(GFORGE_DATA_ROOT, "session-data")
ERROR_LOG_FILE = os.path.join(GFORGE_DATA_ROOT, "logs", "errors.jsonl")
MODEL_ROUTE_FILE = os.path.join(GFORGE_DATA_ROOT, "model-route.json")
FORGE_CONTEXT_FILE = os.path.join(GFORGE_DATA_ROOT, "forge.md")
DEFAULT_FORGE_CONTEXT_SOURCE = os.path.join(PROJECT_ROOT, "forge.md")
WORKSPACE_SKILLS_ROOT = os.path.join(".gforge", "skills")
LEGACY_SESSIONS_FILE = os.path.join(CHAT_ROOT, "sessions.json")
LEGACY_MODELS_FILE = os.path.join(CHAT_ROOT, "models.json")
LEGACY_SESSION_ROOT = os.path.join(CHAT_ROOT, "session-data")
DEFAULT_MODEL = os.environ.get("GFORGE_DEFAULT_MODEL", "gemma-4")
SMALL_MODEL_REVIEW_MAX_B = 8.0
SMALL_TASK_RESEARCH_BUDGET = 2
LARGE_TASK_RESEARCH_BUDGET = 4
POST_REVIEW_REPAIR_ATTEMPTS = 2
AXON_CLI = shutil.which("axon") or os.path.join(os.path.expanduser("~"), ".local", "bin", "axon")
SOCRATICODE_CLI = shutil.which("socraticode")
IGNORED_CODE_DIRS = {
    ".axon",
    ".gforge",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
AXON_INDEXABLE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".py",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}
SEMANTIC_INDEXABLE_EXTENSIONS = AXON_INDEXABLE_EXTENSIONS | {
    ".css",
    ".html",
    ".json",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
}
SKILL_CONTEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".txt",
}
SKILL_COPY_IGNORE_NAMES = {
    ".DS_Store",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
SKILL_CONTEXT_TOTAL_LIMIT = 14000
SKILL_CONTEXT_FILE_LIMIT = 5000
_storage_ready = False

FALLBACK_FORGE_CONTEXT = """# forge.md

Gemma Forge operating context:
- Non-negotiable authenticity rule: do not pre-bake, fake, force, template, or hardcode successful task outputs. Only real verified results count.
- Real verified results mean the selected local Gemma model completes the user's requested task through the harness workflow.
- Scripts, validators, screenshots, and deterministic checks may verify or package results, but they must not replace Gemma 4 doing the requested work.
- If Gemma 4 did not actually complete the requested task, say the run is unverified or failed and repair the orchestration instead of presenting success.
- Do not claim Axon or SocratiCode ran unless the command/tool actually ran. If a tool is skipped, host-assisted, unavailable, or degraded, state that exact status and why.
- Treat every visible conversation as a project workspace, not a global chat.
- The internal record may be stored as a session, but do not expose that as the user-facing concept.
- If the user does not know what to do, translate their intent into the next harness action.
- Explain which control to use only when the harness cannot perform that action from the current message.
- Use Full Forge for end-to-end active-card execution and Forge Section for one protocol card.
- Use the recommended small Gemma 4 model as the first-run default, but honor any available Forge Brain the user selects.
- Ask whether a project directory already exists when the answer changes the workflow.
- Use Human verify when the user wants checkpoints; use auto-run when they want uninterrupted execution.
- Archive finished or paused projects to keep the active list focused.
- Delete only removes the selected project record and its artifacts; never delete or weaken forge.md.
- Link projects only when two project threads need shared context while remaining separately scoped.
- When unsure, give a direct next action and a short reason. Do not assume the user knows Ollama, models, terminals, or project setup.

Axon commands: analyze indexes; status checks index; list lists repos; clean deletes index; query searches graph; context shows symbol context; impact shows blast radius; dead-code lists unused code; cypher runs graph queries; setup configures MCP; watch re-indexes; diff compares branches; mcp starts stdio server; host runs shared host; serve serves MCP; ui launches UI.
SocratiCode commands: codebase_index indexes; codebase_status checks status; codebase_search searches; codebase_update refreshes; codebase_graph_build builds graph; codebase_graph_status checks graph; codebase_graph_circular finds cycles; codebase_remove deletes index.
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_id(value):
    return re.sub(r"[^a-zA-Z0-9_.-]", "-", value).strip("-") or "session"


def normalize_directory_path(path):
    value = (path or "").strip()
    if not value:
        return ""
    return os.path.abspath(os.path.expanduser(value))


def ensure_storage():
    global _storage_ready
    os.makedirs(GFORGE_DATA_ROOT, exist_ok=True)
    os.makedirs(SESSION_ROOT, exist_ok=True)
    os.makedirs(os.path.dirname(ERROR_LOG_FILE), exist_ok=True)
    if not _storage_ready:
        migrate_legacy_storage()
        _storage_ready = True
    ensure_forge_context()


def migrate_legacy_storage():
    if not os.path.exists(SESSIONS_FILE) and os.path.exists(LEGACY_SESSIONS_FILE):
        shutil.copy2(LEGACY_SESSIONS_FILE, SESSIONS_FILE)
    if not os.path.exists(MODELS_FILE) and os.path.exists(LEGACY_MODELS_FILE):
        shutil.copy2(LEGACY_MODELS_FILE, MODELS_FILE)
    if os.path.isdir(LEGACY_SESSION_ROOT) and not os.listdir(SESSION_ROOT):
        shutil.copytree(LEGACY_SESSION_ROOT, SESSION_ROOT, dirs_exist_ok=True)


def default_forge_context():
    try:
        with open(DEFAULT_FORGE_CONTEXT_SOURCE, "r") as f:
            return f.read()
    except OSError:
        return FALLBACK_FORGE_CONTEXT


def ensure_forge_context():
    if os.path.exists(FORGE_CONTEXT_FILE):
        return
    with open(FORGE_CONTEXT_FILE, "w") as f:
        f.write(default_forge_context())


def read_forge_context():
    try:
        ensure_storage()
        with open(FORGE_CONTEXT_FILE, "r") as f:
            return f.read()
    except OSError as error:
        log_error("forge-context", "Could not read forge.md; using bundled fallback.", error)
        return FALLBACK_FORGE_CONTEXT


def skill_install_roots():
    home = os.path.expanduser("~")
    return [
        ("harness", os.path.join(GFORGE_DATA_ROOT, "skills")),
        ("gforge", os.path.join(GFORGE_HOME, "skills")),
        ("project", os.path.join(PROJECT_ROOT, "skills")),
        ("codex", os.path.join(home, ".codex", "skills")),
        ("agents", os.path.join(home, ".agents", "skills")),
    ]


def parse_skill_name(skill_file, fallback):
    try:
        with open(skill_file, "r") as f:
            for _ in range(12):
                line = f.readline()
                if not line:
                    break
                match = re.match(r"\s*name:\s*['\"]?([^'\"\n]+)", line)
                if match:
                    return match.group(1).strip()
    except OSError:
        pass
    return fallback


def discover_installed_skills(max_depth=3):
    skills = {}
    for source, root in skill_install_roots():
        if not os.path.isdir(root):
            continue
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKILL_COPY_IGNORE_NAMES]
            relative_root = os.path.relpath(current_root, root)
            depth = 0 if relative_root == "." else relative_root.count(os.sep) + 1
            if depth >= max_depth:
                dirs[:] = []
            if "SKILL.md" not in files:
                continue
            directory_name = os.path.basename(current_root)
            skill_name = parse_skill_name(os.path.join(current_root, "SKILL.md"), directory_name)
            key = normalize_skill_key(skill_name)
            if key not in skills:
                skills[key] = {
                    "name": skill_name,
                    "key": key,
                    "source": source,
                    "directory": current_root,
                    "skillFile": os.path.join(current_root, "SKILL.md"),
                }
    return skills


def normalize_skill_key(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def session_skill_text(session):
    parts = [session.get("project", "")]
    for message in session.get("messages", []) if isinstance(session, dict) else []:
        parts.append(str(message.get("content", "")))
    return "\n".join(parts).lower()


def requested_skill_keys(session, skills):
    text = session_skill_text(session)
    requested = set()
    for match in re.findall(r"(?:\$|skill\s+)([a-z0-9_.-]+)", text):
        key = normalize_skill_key(match)
        if key in skills:
            requested.add(key)
    for key, info in skills.items():
        name = info["name"].lower()
        spaced = name.replace("-", " ")
        if name in text or spaced in text:
            requested.add(key)
    return sorted(requested)


def skill_copy_ignores(_directory, names):
    ignored = set()
    for name in names:
        if name in SKILL_COPY_IGNORE_NAMES:
            ignored.add(name)
        elif name == ".env" or name.startswith(".env."):
            ignored.add(name)
    return ignored


def safe_workspace_child(root, *parts):
    root_path = os.path.abspath(root)
    child_path = os.path.abspath(os.path.join(root_path, *parts))
    if os.path.commonpath([root_path, child_path]) != root_path:
        raise ValueError("workspace child path escaped the workspace root")
    return child_path


def copy_skill_to_workspace(skill, workspace_dir):
    staged_root = safe_workspace_child(workspace_dir, WORKSPACE_SKILLS_ROOT)
    destination = safe_workspace_child(staged_root, skill["key"])
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    shutil.copytree(skill["directory"], destination, ignore=skill_copy_ignores)
    return destination


def prepare_workspace_skill_context(workspace_dir, session):
    skills = discover_installed_skills()
    staged = []
    staged_root = safe_workspace_child(workspace_dir, WORKSPACE_SKILLS_ROOT)
    os.makedirs(staged_root, exist_ok=True)

    selected_keys = resolve_skill_selection(session, skills)
    prune_workspace_skill_dirs(staged_root, selected_keys)
    for key in selected_keys:
        skill = skills.get(key)
        if not skill:
            continue
        try:
            destination = copy_skill_to_workspace(skill, workspace_dir)
            staged.append({
                "name": skill["name"],
                "key": key,
                "source": skill["source"],
                "path": os.path.relpath(destination, workspace_dir).replace(os.sep, "/"),
                "requested": True,
            })
        except (OSError, ValueError) as error:
            log_error("skill-staging", f"Could not stage skill {skill['name']}.", error)

    write_skill_manifest(workspace_dir, staged)
    return {
        "root": WORKSPACE_SKILLS_ROOT,
        "requested": [item["key"] for item in staged],
        "staged": staged,
        "prompt": build_skill_context_prompt(workspace_dir, staged),
    }


def prune_workspace_skill_dirs(staged_root, keep_keys):
    """
    Remove leftover skill directories from a previous run that aren't in
    the current selection. The skill bundles are copied fresh on each
    staging anyway, so leftovers are pure clutter and they confuse the
    user reading the workspace.
    """
    if not os.path.isdir(staged_root):
        return
    keep = set(keep_keys)
    for entry in os.listdir(staged_root):
        entry_path = os.path.join(staged_root, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry in keep:
            continue
        try:
            shutil.rmtree(entry_path)
        except OSError as error:
            log_error("skill-staging", f"Could not prune stale skill dir {entry}.", error)


def resolve_skill_selection(session, skills):
    """
    Decide which staged skills the workspace should hold.

    Priority order:
      1. projectContext.skill.use (set by the Project Context Writer).
         If the named skill exists in the discovered map, use ONLY that one.
         If skill.use is "none" or "n/a", stage nothing.
      2. Pre-Context-Writer sessions or sessions that failed to populate
         a context: fall back to the legacy substring-based requested
         keys so existing behavior still works.
    """
    if not isinstance(session, dict):
        return []
    context = session.get("projectContext")
    if isinstance(context, dict):
        skill_info = context.get("skill") if isinstance(context.get("skill"), dict) else None
        raw_use = ""
        if skill_info:
            raw_use = str(skill_info.get("use", "")).strip()
        normalized = normalize_skill_key(raw_use) if raw_use else ""
        if normalized in {"", "none", "n-a", "na"}:
            return []
        if normalized in skills:
            return [normalized]
        log_error(
            "skill-staging",
            f"Project Context named a skill that is not installed: {raw_use!r}",
            None,
            {"requested": raw_use, "available": sorted(skills.keys())},
        )
        return []
    return list(requested_skill_keys(session, skills))


def write_skill_manifest(workspace_dir, staged):
    lines = [
        "# Gemma Forge Staged Skills",
        "",
        "These skill references were copied by the harness from the local Gemma Forge install.",
        "Use these relative workspace paths instead of absolute `/Users/...` paths.",
        "",
    ]
    if not staged:
        lines.append("- No staged skills were available.")
    else:
        for skill in staged:
            requested = " requested" if skill.get("requested") else ""
            lines.append(f"- `{skill['name']}` at `{skill['path']}` ({skill['source']}{requested})")
    write_workspace_support_file(workspace_dir, os.path.join(WORKSPACE_SKILLS_ROOT, "MANIFEST.md"), "\n".join(lines))


def build_skill_context_prompt(workspace_dir, staged):
    if not staged:
        return "No Gemma Forge skills are staged for this workspace."

    lines = [
        "Harness-staged skill references are available in the workspace.",
        f"- Skills root: `{WORKSPACE_SKILLS_ROOT}`",
        "- Use the staged skill instructions below when they match the project request.",
        "- Do not report `/Users/...` skill paths as inaccessible when a matching staged skill is listed here.",
        "- Do not claim a script, API, or external model ran unless the harness actually runs it later; list needed commands instead.",
        "- When you generate deliverables from staged skill instructions, say you used the staged skill instructions. Do not describe that as simulated skill execution.",
        "",
        "Staged skills:",
    ]
    for skill in staged:
        marker = "requested" if skill.get("requested") else "available"
        lines.append(f"- `{skill['name']}` at `{skill['path']}` ({marker})")

    remaining = SKILL_CONTEXT_TOTAL_LIMIT
    for skill in [item for item in staged if item.get("requested")]:
        skill_dir = os.path.join(workspace_dir, skill["path"])
        snippets, used = read_skill_prompt_snippets(skill_dir, remaining)
        remaining -= used
        if snippets:
            lines.extend(["", f"## {skill['name']} Skill Context", ""])
            lines.extend(snippets)
        if remaining <= 0:
            break
    return "\n".join(lines)


def read_skill_prompt_snippets(skill_dir, remaining):
    snippets = []
    used = 0
    candidate_paths = [os.path.join(skill_dir, "SKILL.md")]
    for folder in ("references", "assets"):
        folder_path = os.path.join(skill_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [name for name in dirs if name not in SKILL_COPY_IGNORE_NAMES]
            for filename in sorted(files):
                if os.path.splitext(filename)[1].lower() in SKILL_CONTEXT_EXTENSIONS:
                    candidate_paths.append(os.path.join(root, filename))

    for path in candidate_paths:
        if remaining <= 0:
            break
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read(min(SKILL_CONTEXT_FILE_LIMIT, remaining))
        except OSError:
            continue
        if not content.strip():
            continue
        relative_path = os.path.relpath(path, skill_dir).replace(os.sep, "/")
        snippets.append(f"### {relative_path}\n\n```text\n{content}\n```")
        consumed = len(content)
        used += consumed
        remaining -= consumed
    return snippets, used


def write_workspace_support_file(workspace_dir, relative_path, content):
    path = safe_workspace_child(workspace_dir, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def log_error(source, message, error=None, extra=None):
    try:
        ensure_storage()
        event = {
            "time": utc_now(),
            "source": source,
            "message": message,
        }
        if error is not None:
            event["errorType"] = type(error).__name__
            event["error"] = str(error)
            response = getattr(error, "response", None)
            if response is not None:
                event["statusCode"] = response.status_code
                event["response"] = truncate_text(response.text, 700)
        if extra:
            event["extra"] = extra
        with open(ERROR_LOG_FILE, "a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        pass


def read_error_log(limit=100):
    ensure_storage()
    if not os.path.exists(ERROR_LOG_FILE):
        return []
    with open(ERROR_LOG_FILE, "r") as f:
        lines = f.readlines()[-limit:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"time": "", "source": "error-log", "message": line.strip()})
    return events


def record_model_route(model, source):
    try:
        ensure_storage()
        payload = {
            "model": model,
            "source": source,
            "updatedAt": utc_now(),
            "defaultModel": DEFAULT_MODEL,
            "route": "Forge Brain selection -> Flask harness -> Ollama /api/chat",
        }
        with open(MODEL_ROUTE_FILE, "w") as f:
            json.dump(payload, f, indent=4)
    except OSError as error:
        log_error("model-route", "Could not write model route status.", error)


def read_model_route():
    ensure_storage()
    if not os.path.exists(MODEL_ROUTE_FILE):
        return None
    with open(MODEL_ROUTE_FILE, "r") as f:
        return json.load(f)


def normalize_model_name(name):
    value = (name or "").strip()
    return value[:-7] if value.endswith(":latest") else value


def model_name_matches(candidate, selected):
    candidate_names = {
        normalize_model_name(candidate.get("name", "")),
        normalize_model_name(candidate.get("model", "")),
    }
    selected_name = normalize_model_name(selected)
    return (
        selected_name in candidate_names
        or f"{selected_name}:latest" in {candidate.get("name", ""), candidate.get("model", "")}
    )


def parse_parameter_size_b(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([bm])", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    return amount / 1000 if unit == "m" else amount


def selected_model_size_b(model):
    try:
        workspace = scan_workspace()
    except Exception as error:
        log_error("model-size", "Could not scan workspace for model size.", error, {"model": model})
        workspace = {}

    for installed in workspace.get("ollama", {}).get("models", []):
        if model_name_matches(installed, model):
            details = installed.get("details", {})
            size = parse_parameter_size_b(details.get("parameter_size"))
            if size is not None:
                return size

    registry = load_models()
    for registered in registry.get("models", []):
        if model_name_matches(registered, model):
            size = parse_parameter_size_b(
                registered.get("parameter_size")
                or registered.get("parameterSize")
                or registered.get("sizeLabel")
            )
            if size is not None:
                return size

    if normalize_model_name(model) == DEFAULT_MODEL:
        return 4.6
    return None


def small_model_review_required(model):
    size = selected_model_size_b(model)
    if size is not None:
        return size <= SMALL_MODEL_REVIEW_MAX_B

    selected = normalize_model_name(model).lower()
    size_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*b", selected)
    if size_match:
        return float(size_match.group(1)) <= SMALL_MODEL_REVIEW_MAX_B
    return selected in {DEFAULT_MODEL, "gemma-4"}


def project_research_budget(session):
    project = session.get("project", "") if isinstance(session, dict) else ""
    words = re.findall(r"\w+", project)
    large_markers = {
        "contest",
        "deadline",
        "package",
        "release",
        "submission",
        "orchestration",
        "integration",
        "architecture",
        "multi",
        "full",
        "complete",
        "production",
        "install",
        "downloadable",
    }
    is_large = len(words) >= 80 or any(marker in project.lower() for marker in large_markers)
    return {
        "taskSize": "large" if is_large else "small",
        "maxPasses": LARGE_TASK_RESEARCH_BUDGET if is_large else SMALL_TASK_RESEARCH_BUDGET,
    }


def research_budget_text(session):
    budget = project_research_budget(session)
    return (
        f"{budget['maxPasses']} research passes are available as needed "
        f"for this {budget['taskSize']} task."
    )


def card_allows_research(card_id):
    return card_id in {"gsd", "execution", "socraticode", "axon", "verification"}


def parse_json_response(text, fallback):
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        pass

    if not text:
        return fallback

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return fallback

    try:
        return json.loads(text[start:end + 1], strict=False)
    except json.JSONDecodeError:
        return fallback


def listify(value):
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [str(value)]


def bounded_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "pass", "passed"}:
            return True
        if normalized in {"false", "no", "fail", "failed"}:
            return False
    return default


def call_ollama_json(model, prompt, fallback):
    raw, transport = call_ollama_with_transport(model, prompt)
    parsed = parse_json_response(raw, fallback)
    return parsed, raw, transport


def call_ollama_execution_payload(model, prompt, fallback):
    raw, transport = call_ollama_with_transport(model, prompt)
    parsed = parse_json_response(raw, None)
    if isinstance(parsed, dict):
        return parsed, raw, transport
    block_payload = parse_forge_file_payload(raw)
    if block_payload:
        return block_payload, raw, transport
    return fallback, raw, transport


def parse_forge_file_payload(text):
    if not text:
        return None

    file_matches = list(re.finditer(
        r"<<<GFORGE_FILE:([^\n>]+)>>>\s*\n?(.*?)\n?<<<END_GFORGE_FILE>>>",
        text,
        flags=re.DOTALL,
    ))
    if not file_matches:
        return None

    files = []
    for match in file_matches:
        path = match.group(1).strip()
        content = match.group(2).strip()
        if path and content:
            files.append({"path": path, "content": content})
    if not files:
        return None

    return {
        "summary": parse_text_section(text, "SUMMARY", "FILES") or "Model-authored file payload returned.",
        "files": files,
        "commands": parse_bullet_section(text, "COMMANDS"),
        "notes": parse_bullet_section(text, "NOTES"),
        "verification": parse_bullet_section(text, "VERIFICATION"),
    }


def parse_text_section(text, heading, next_heading):
    pattern = rf"^{re.escape(heading)}:\s*(.*?)(?=^{re.escape(next_heading)}:|<<<GFORGE_FILE:|\Z)"
    match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def parse_bullet_section(text, heading):
    pattern = rf"^{re.escape(heading)}:\s*(.*?)(?=^[A-Z][A-Z ]+:|<<<GFORGE_FILE:|\Z)"
    match = re.search(pattern, text, flags=re.DOTALL | re.MULTILINE)
    if not match:
        return []
    items = []
    for line in match.group(1).splitlines():
        value = re.sub(r"^\s*[-*]\s*", "", line).strip()
        if value:
            items.append(value)
    return items


def truncate_text(value, limit):
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "... truncated"

def load_sessions():
    ensure_storage()
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_sessions(sessions):
    ensure_storage()
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions, f, indent=4)


def load_models():
    ensure_storage()
    if os.path.exists(MODELS_FILE):
        with open(MODELS_FILE, "r") as f:
            return json.load(f)
    return {"models": []}


def save_models(registry):
    ensure_storage()
    with open(MODELS_FILE, "w") as f:
        json.dump(registry, f, indent=4)


def session_dir(session_id):
    path = os.path.join(SESSION_ROOT, safe_id(session_id))
    os.makedirs(path, exist_ok=True)
    return path


def write_session_context(session_id, session):
    path = os.path.join(session_dir(session_id), "project-context.md")
    messages = session.get("messages", []) if isinstance(session, dict) else []
    lines = [
        f"# {session.get('project', session_id)}",
        "",
        f"- Project record: `{session_id}`",
        f"- Model: `{session.get('model', DEFAULT_MODEL)}`",
        f"- Updated: {utc_now()}",
        "",
        "## Context",
        "",
    ]
    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        lines.append(f"### {role}")
        lines.append("")
        lines.append(content)
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))

@app.route('/')
def index():
    return send_from_directory(os.path.join(CHAT_ROOT, 'templates'), 'index.html')

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory(os.path.join(CHAT_ROOT, 'static'), path)

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    return jsonify(load_sessions())

@app.route('/api/workspace/status', methods=['GET'])
def workspace_status():
    return jsonify(scan_workspace())

@app.route('/api/errors', methods=['GET'])
def error_log():
    return jsonify({"path": ERROR_LOG_FILE, "events": read_error_log()})

@app.route('/api/model/route', methods=['GET'])
def model_route():
    return jsonify({
        "defaultModel": DEFAULT_MODEL,
        "recommendedModel": DEFAULT_MODEL,
        "currentRoute": "Forge Brain selection -> Flask harness -> Ollama /api/chat",
        "lastCall": read_model_route(),
    })

@app.route('/api/tools/status', methods=['GET'])
def tools_status():
    return jsonify(detect_tool_status())


@app.route('/api/tools/browse', methods=['POST'])
def tools_browse():
    """
    Real harness-side web fetch via scrapling. Body: {url, session_id?, mode?}.

    If session_id is provided, the fetched content is persisted under the
    session's workspace at research/<slug>.md so downstream cards (and the
    claim validator) can see the evidence on disk.
    """
    data = request.json or {}
    url = str(data.get("url", "")).strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"error": "url must start with http(s)://"}), 400
    if not tool_browse.is_available():
        return jsonify({"error": "scrapling is not installed in this Python environment"}), 503

    mode = str(data.get("mode", "request")).strip().lower()
    session_id = str(data.get("session_id", "")).strip()
    result = tool_browse.fetch_url(url, mode=mode if mode in {"request", "browser", "stealth"} else "request")

    artifact = None
    if session_id:
        sessions = load_sessions()
        session = sessions.get(session_id) if isinstance(sessions, dict) else None
        if isinstance(session, dict):
            workspace_dir = resolve_execution_workspace(session_id, session, session.get("project", ""))
            os.makedirs(workspace_dir, exist_ok=True)
            artifact = tool_browse.write_research_artifact(workspace_dir, result)

    return jsonify({"result": result, "artifact": artifact})


@app.route('/api/tools/screenshot', methods=['POST'])
def tools_screenshot():
    """
    Real harness-side screenshot via Playwright. Body:
      {target, mode?, session_id?, viewport?, full_page?}

    `target` is either an http(s):// URL or a local file path.
    `mode` is "auto" | "url" | "local_html"; default "auto" infers from the
    target shape. Saves the PNG under `<workspace>/screenshots/<slug>.png`
    when a `session_id` is provided, otherwise into /tmp.
    """
    data = request.json or {}
    target = str(data.get("target", "")).strip()
    if not target:
        return jsonify({"error": "target (url or local html path) is required"}), 400
    if not tool_screenshot.is_available():
        return jsonify({"error": "playwright is not installed in this Python environment"}), 503

    mode = str(data.get("mode", "auto")).strip().lower()
    if mode not in {"auto", "url", "local_html"}:
        return jsonify({"error": f"unknown screenshot mode {mode!r}"}), 400
    viewport = data.get("viewport") or {}
    width = int(viewport.get("width", 1280))
    height = int(viewport.get("height", 800))
    full_page = bool(data.get("full_page", True))
    session_id = str(data.get("session_id", "")).strip()

    sessions = load_sessions() if session_id else {}
    session = sessions.get(session_id) if isinstance(sessions, dict) else None
    if isinstance(session, dict):
        workspace_dir = resolve_execution_workspace(session_id, session, session.get("project", ""))
        os.makedirs(workspace_dir, exist_ok=True)
    else:
        workspace_dir = os.path.join("/tmp", "gforge-screenshots")
        os.makedirs(workspace_dir, exist_ok=True)

    artifact = tool_screenshot.screenshot_into_workspace(
        workspace_dir, target, mode=mode, viewport=(width, height), full_page=full_page,
    )
    emit_event("screenshot", f"{target} → {artifact.get('path')}",
               ok=artifact.get("ok"), bytes=artifact.get("bytes"), ms=artifact.get("elapsed_ms"))
    return jsonify({"artifact": artifact})


@app.route('/api/events/stream', methods=['GET'])
def events_stream():
    """Server-Sent Events feed of structured harness activity."""
    def generate():
        q, snapshot = _subscribe_events()
        try:
            # Send recent history first so a late connection still sees
            # the last few minutes of activity.
            for event in snapshot[-80:]:
                yield f"data: {json.dumps(event)}\n\n"
            # Then stream live events. Heartbeat every 15s keeps proxies happy.
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            pass
        finally:
            _unsubscribe_events(q)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route('/api/events/recent', methods=['GET'])
def events_recent():
    """Polling fallback if SSE is blocked by a proxy."""
    with _EVENT_LOCK:
        snapshot = list(_EVENT_BUFFER)
    return jsonify({"events": snapshot[-200:]})

@app.route('/api/models', methods=['GET'])
def get_models():
    return jsonify(model_payload())

@app.route('/api/models/import', methods=['POST'])
def import_models():
    payload = model_payload(import_installed=True)
    return jsonify(payload)

@app.route('/api/models/provision', methods=['POST'])
def provision_model():
    data = request.json or {}
    model_name = data.get("ollamaName", "").strip() or DEFAULT_MODEL
    repo_id = data.get("repoId", "").strip()
    create_interface = bool(data.get("createInterface"))
    download_only = bool(data.get("downloadOnly"))
    detected = scan_workspace()
    installed = is_ollama_model_installed(model_name, detected["ollama"]["models"])

    registry = load_models()
    upsert_registry_model(registry, {
        "name": model_name,
        "source": repo_id or "ollama",
        "status": "installed" if installed else "queued",
        "downloadOnly": download_only,
        "createInterface": create_interface,
        "updatedAt": utc_now(),
    })
    save_models(registry)

    if installed:
        result = {
            "status": "skipped",
            "message": f"{model_name} is already installed. Gemma Forge added it to the model registry.",
            "registry": registry,
        }
    else:
        result = {
            "status": "queued",
            "message": (
                f"{model_name} is registered for provisioning. The forge pipeline should download "
                "or convert it before use."
            ),
            "registry": registry,
        }

    if create_interface:
        sessions = load_sessions()
        session_id = create_session_record(
            sessions,
            f"Model interface for {model_name}",
            model_name,
        )
        save_sessions(sessions)
        result["session_id"] = session_id

    return jsonify(result)

@app.route('/api/sessions', methods=['POST'])
def create_session():
    data = request.json or {}
    project = data.get("project", "").strip()
    if not project:
        return jsonify({"error": "Project is required"}), 400

    sessions = load_sessions()
    has_project_directory = data.get("hasProjectDirectory")
    project_directory = normalize_directory_path(data.get("projectDirectory", ""))
    if has_project_directory and not os.path.isdir(project_directory):
        return jsonify({
            "error": (
                "That directory does not exist. Choose 'No, this plan is the project seed' "
                "to let Project Execution create it, or enter an existing directory."
            )
        }), 400

    session_id = create_session_record(
        sessions,
        project,
        data.get("model", DEFAULT_MODEL),
        data.get("session_id"),
        has_project_directory,
        project_directory,
    )
    save_sessions(sessions)
    return jsonify({"session_id": session_id, "session": sessions[session_id]})


@app.route('/api/sessions/<session_id>/model', methods=['PATCH'])
def update_session_model(session_id):
    data = request.json or {}
    sessions = load_sessions()
    if session_id not in sessions or not isinstance(sessions[session_id], dict):
        return jsonify({"error": "Unknown work-harness project"}), 404

    changed = False
    if "model" in data:
        model = normalize_model_name(data.get("model", ""))
        if not model:
            return jsonify({"error": "Model is required."}), 400
        sessions[session_id]["model"] = model
        changed = True
    if "fallbackModel" in data:
        fallback = normalize_model_name(data.get("fallbackModel") or "")
        sessions[session_id]["fallbackModel"] = fallback
        changed = True
    if not changed:
        return jsonify({"error": "model or fallbackModel is required."}), 400

    write_session_context(session_id, sessions[session_id])
    save_sessions(sessions)
    return jsonify({"session": sessions[session_id]})


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    sessions = load_sessions()
    if session_id not in sessions:
        return jsonify({"error": "Unknown project"}), 404

    sessions.pop(session_id)
    session_path = os.path.join(SESSION_ROOT, safe_id(session_id))
    removed_data = False
    if os.path.isdir(session_path):
        shutil.rmtree(session_path)
        removed_data = True
    elif os.path.exists(session_path):
        os.remove(session_path)
        removed_data = True

    updated_sessions = []
    for remaining_id, session in sessions.items():
        if not isinstance(session, dict):
            continue

        bridges = session.get("bridges", [])
        if not bridges:
            continue

        pruned = []
        for bridge in bridges:
            bridge_sessions = [sid for sid in bridge.get("sessions", []) if sid != session_id]
            if len(bridge_sessions) < 2:
                continue

            updated_bridge = dict(bridge)
            updated_bridge["sessions"] = bridge_sessions
            if updated_bridge.get("primary") == session_id:
                updated_bridge["primary"] = bridge_sessions[0]
            pruned.append(updated_bridge)

        if pruned:
            session["bridges"] = pruned
        else:
            session.pop("bridges", None)
        updated_sessions.append(remaining_id)
        write_session_context(remaining_id, session)

    save_sessions(sessions)
    return jsonify({
        "deleted": session_id,
        "sessionDataRemoved": removed_data,
        "updatedSessions": updated_sessions,
        "sessions": sessions,
    })

@app.route('/api/sessions/<session_id>/archive', methods=['PATCH'])
def archive_session(session_id):
    data = request.json or {}
    should_archive = bool(data.get("archived", True))
    sessions = load_sessions()
    if session_id not in sessions or not isinstance(sessions[session_id], dict):
        return jsonify({"error": "Unknown work-harness project"}), 404

    session = sessions[session_id]
    if should_archive:
        session["archivedAt"] = utc_now()
        session.setdefault("messages", []).append({
            "role": "agent",
            "content": "Project archived. It remains available under Archived.",
        })
    else:
        session.pop("archivedAt", None)
        session.setdefault("messages", []).append({
            "role": "agent",
            "content": "Project restored to Active.",
        })

    write_session_context(session_id, session)
    save_sessions(sessions)
    return jsonify({
        "session_id": session_id,
        "archived": should_archive,
        "session": session,
        "sessions": sessions,
    })

@app.route('/api/sessions/link', methods=['POST'])
def link_sessions():
    data = request.json or {}
    session_ids = [sid for sid in data.get("session_ids", []) if sid]
    if len(session_ids) < 2:
        return jsonify({"error": "Select at least two projects to link"}), 400

    sessions = load_sessions()
    missing = [sid for sid in session_ids if sid not in sessions or not isinstance(sessions[sid], dict)]
    if missing:
        return jsonify({"error": f"Unknown work-harness projects: {', '.join(missing)}"}), 400

    bridge_id = f"bridge-{int(time.time())}"
    primary = session_ids[0]
    primary_path = os.path.join(session_dir(primary), "session-bridge.md")
    linked_projects = []
    for sid in session_ids:
        session = sessions[sid]
        linked_projects.append(f"- `{sid}`: {session.get('project', sid)}")
        session.setdefault("bridges", [])
        session["bridges"].append({"bridgeId": bridge_id, "sessions": session_ids, "primary": primary})

    with open(primary_path, "w") as f:
        f.write(
            "\n".join([
                f"# Project Bridge {bridge_id}",
                "",
                "Linked projects:",
                *linked_projects,
                "",
                "Purpose: share project context across selected planning projects while keeping each project scoped.",
            ])
        )

    shortcuts = []
    for sid in session_ids[1:]:
        shortcut_path = os.path.join(session_dir(sid), "session-bridge-shortcut.md")
        with open(shortcut_path, "w") as f:
            f.write(
                "\n".join([
                    f"# Bridge Shortcut {bridge_id}",
                    "",
                    f"Primary bridge: `{os.path.relpath(primary_path, session_dir(sid))}`",
                    f"Primary project: `{primary}`",
                ])
            )
        shortcuts.append(shortcut_path)
        write_session_context(sid, sessions[sid])

    write_session_context(primary, sessions[primary])
    save_sessions(sessions)
    return jsonify({"bridgeId": bridge_id, "primaryPath": primary_path, "shortcuts": shortcuts})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    session_id = data.get("session_id")
    message = data.get("message")
    # Use the selected Forge Brain, or the recommended default.
    model = data.get("model", DEFAULT_MODEL)

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # 1. Try the modern /api/chat endpoint
        ollama_chat_url = "http://localhost:11434/api/chat"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "stream": False
        }
        record_model_route(model, "api-chat")
        
        try:
            response = requests.post(ollama_chat_url, json=payload, timeout=1200)
            if response.status_code == 200:
                reply = response.json().get("message", {}).get("content", "")
                return save_and_respond(session_id, message, reply)
            elif response.status_code == 404:
                # Endpoint not found, try fallback to /api/generate
                pass 
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as error:
            log_error("api-chat", "Ollama /api/chat request failed; trying /api/generate fallback.", error, {"model": model})
            pass

        # 2. Fallback to /api/generate endpoint
        ollama_gen_url = "http://localhost:11434/api/generate"
        gen_payload = {
            "model": model,
            "prompt": message,
            "stream": False
        }
        response = requests.post(ollama_gen_url, json=gen_payload, timeout=1200)
        response.raise_for_status()
        reply = response.json().get("response", "")
        
        return save_and_respond(session_id, message, reply)

    except requests.exceptions.HTTPError as e:
        log_error("api-chat", "Ollama HTTP error.", e, {"model": model})
        if e.response.status_code == 404:
            return jsonify({"error": f"Model '{model}' not found in Ollama. Please check the name in the Forge tab."}), 404
        return jsonify({"error": f"Ollama API error: {str(e)}"}), 500
    except Exception as e:
        log_error("api-chat", "Unexpected chat route error.", e, {"model": model})
        return jsonify({"error": str(e)}), 500

def save_and_respond(session_id, user_msg, assistant_reply):
    sessions = load_sessions()
    if session_id not in sessions:
        sessions[session_id] = []
    if isinstance(sessions[session_id], list):
        sessions[session_id].append({"role": "user", "content": user_msg})
        sessions[session_id].append({"role": "assistant", "content": assistant_reply})
    else:
        sessions[session_id].setdefault("messages", [])
        sessions[session_id]["messages"].append({"role": "user", "content": user_msg})
        sessions[session_id]["messages"].append({"role": "agent", "content": assistant_reply})
    save_sessions(sessions)
    return jsonify({"reply": assistant_reply})

@app.route('/api/sessions/<session_id>/messages', methods=['POST'])
def session_message(session_id):
    data = request.json or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400

    sessions = load_sessions()
    if session_id not in sessions or not isinstance(sessions[session_id], dict):
        return jsonify({"error": "Unknown work-harness project"}), 404

    session = sessions[session_id]
    model = data.get("model") or session.get("model", DEFAULT_MODEL)
    session["model"] = model
    session.setdefault("messages", [])
    session["messages"].append({"role": "user", "content": message})

    reply = call_ollama(model, build_session_prompt(session, message))
    session["messages"].append({"role": "agent", "content": reply})
    write_session_context(session_id, session)
    save_sessions(sessions)
    return jsonify({"reply": reply, "session": session})

@app.route('/api/sessions/<session_id>/cards/<card_id>/run', methods=['POST'])
def run_session_card(session_id, card_id):
    data = request.json or {}
    sessions = load_sessions()
    if session_id not in sessions or not isinstance(sessions[session_id], dict):
        return jsonify({"error": "Start or select a project first."}), 404

    session = sessions[session_id]
    model = data.get("model") or session.get("model", DEFAULT_MODEL)
    session["model"] = model
    human_verify = bool(data.get("humanVerify", True))
    issue_note = data.get("note", "").strip()
    mode = "human verification" if human_verify else "auto run"
    if issue_note:
        session.setdefault("messages", [])
        session["messages"].append({
            "role": "user",
            "content": f"Checkpoint issue for {card_id}: {issue_note}",
        })
    # Build correction context BEFORE the rerun overwrites the card's lastRun.
    # When the user clicked Resolve, this bundles the previous reviewer's
    # findings + the user's note into a structured object the card handler
    # can feed to the model via its "Previous review failed" prompt block.
    correction = build_correction_from_state(session, card_id, issue_note) if issue_note else None
    if correction:
        emit_event("card-start", f"{card_id} starting (resolve: {len(correction.get('findings', []))} findings + user note)",
                   session=session_id, model=model, mode=mode)
    else:
        emit_event("card-start", f"{card_id} starting", session=session_id, model=model, mode=mode)
    result = run_card_action(session_id, session, card_id, model, mode, correction=correction)
    finalize_card_result(session_id, session, card_id, model, result, human_verify)
    update_card_state(session, card_id, result)
    emit_event("card-end", f"{card_id}: {result.get('summary', '')[:200]}",
               session=session_id, status=result.get("status"),
               artifact=result.get("artifact"))
    session.setdefault("messages", [])
    session["messages"].append({
        "role": "agent",
        "content": f"[{result['title']}] {result['summary']}\n\n{result['details']}",
    })
    write_session_context(session_id, session)
    save_sessions(sessions)
    return jsonify({"result": result, "session": session})

@app.route('/api/sessions/<session_id>/cards/<card_id>/verify', methods=['POST'])
def verify_session_card(session_id, card_id):
    data = request.json or {}
    status = data.get("status", "").strip()
    note = data.get("note", "").strip()
    sessions = load_sessions()
    if session_id not in sessions or not isinstance(sessions[session_id], dict):
        return jsonify({"error": "Start or select a project first."}), 404

    session = sessions[session_id]
    model = data.get("model") or session.get("model", DEFAULT_MODEL)
    session["model"] = model
    card = find_card(session, card_id)
    if not card:
        return jsonify({"error": "Unknown protocol card."}), 404

    now = utc_now()
    if status == "verified":
        # Human Verified is the final word — the human is the arbiter.
        # Previously we re-ran the small-model `ensure_completion_review`
        # here, which could flip an explicitly-approved card back to
        # `needs-attention` based on a model second-guessing the human.
        # That defeated the point of Human Verify mode AND stopped the
        # chain mid-flow after a successful Resolve. The reviewer already
        # ran during finalize_card_result when the card itself was run;
        # re-running it on the human's verdict was a double-check that
        # caused more harm than value.
        card["status"] = "complete"
        card["verifiedAt"] = now
        if isinstance(card.get("lastRun"), dict):
            card["lastRun"]["status"] = "complete"
            # Mark the human as the deciding authority so audit can see it.
            card["lastRun"]["humanVerified"] = True
        message = f"{card.get('title', card_id)} checkpoint verified."
        if note:
            message = f"{message} Note: {note}"
        session.setdefault("messages", []).append({"role": "agent", "content": message})
        emit_event("card-verified", f"{card_id} verified by human",
                   session=session_id, card=card_id, note=note or None)
    elif status == "not-verified":
        card["status"] = "needs-attention"
        card["needsAttentionAt"] = now
        if isinstance(card.get("lastRun"), dict):
            card["lastRun"]["status"] = "needs-attention"
        issue = note or "No issue detail provided."
        session.setdefault("messages", []).append({
            "role": "user",
            "content": f"{card.get('title', card_id)} checkpoint was not verified. Issue: {issue}",
        })
    else:
        return jsonify({"error": "Unsupported checkpoint status."}), 400

    write_session_context(session_id, session)
    save_sessions(sessions)
    return jsonify({"session": session, "card": card})

@app.route('/api/plan', methods=['POST'])
def plan():
    data = request.json or {}
    session_id = data.get("session_id")
    project = data.get("project", "").strip()
    checkpoint_mode = data.get("checkpointMode", "human")
    model = data.get("model", DEFAULT_MODEL)

    if not project:
        return jsonify({"error": "Project is required"}), 400

    resource_state = scan_workspace()
    session_for_prompt = {
        "project": project,
        "projectMode": "unknown",
        "projectDirectory": "",
    }
    sessions = load_sessions()
    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        session_for_prompt = sessions[session_id]
        session_for_prompt["model"] = model

    prompt = build_mode_aware_planning_prompt(session_for_prompt, checkpoint_mode, resource_state)
    reply = call_ollama(model, prompt)

    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        sessions[session_id].setdefault("messages", [])
        sessions[session_id]["messages"].append({"role": "agent", "content": reply})
        write_session_context(session_id, sessions[session_id])
        save_sessions(sessions)

    cards = default_cards(session_for_prompt.get("projectMode", "unknown"))
    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        cards = sessions[session_id].get("cards", cards)

    return jsonify({"reply": reply, "cards": cards})


OLLAMA_REQUEST_TIMEOUT_SECONDS = 1200
OLLAMA_KEEP_ALIVE = "30m"
# Honor each Modelfile's own PARAMETER tuning by default. Forcing
# temperature / num_ctx / num_predict from the harness side overrode
# good Modelfile defaults (gemma-4, gempus4:tuned, UnCenOr all set
# temperature=1; gempus4:tuned sets num_ctx=65536 and num_predict=-1).
# Per-call overrides via options_override are still respected, e.g.
# the Project Context Writer's CONTEXT_DELIBERATION_OPTIONS sets
# temperature=0.1 for deterministic schema emission.
OLLAMA_DEFAULT_OPTIONS = {}


def call_ollama_with_transport(model, prompt, options_override=None):
    """
    Call the local Ollama /api/chat endpoint and return (content, transport).

    transport is a dict with keys:
      status: one of "ok" | "empty" | "timeout" | "unreachable" | "http_error"
      model: the model id we asked for
      elapsedMs: how long the call took, including any retry
      attempts: 1 or 2 (single retry on ConnectionError only)
      error: stringified error or None
      timeoutSeconds: the per-request timeout that was in effect

    Pass options_override={"temperature": 0.1, ...} to deviate from
    OLLAMA_DEFAULT_OPTIONS for a single call. Unspecified keys keep
    their defaults.

    On any failure path the function returns an empty content string so
    downstream parsers do not consume a polite English fallback that
    looks like a real response.
    """
    record_model_route(model, "harness-card")
    started = time.time()
    options = dict(OLLAMA_DEFAULT_OPTIONS)
    if isinstance(options_override, dict):
        options.update(options_override)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
    }

    last_error = None
    emit_event("ollama", f"{model} → call", attempt=1)
    for attempt in (1, 2):
        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json=body,
                timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
            elapsed_ms = int((time.time() - started) * 1000)
            emit_event("ollama", f"{model} ← {'ok' if content else 'empty'} ({elapsed_ms} ms)",
                       attempt=attempt, ok=bool(content))
            return content, {
                "status": "ok" if content else "empty",
                "model": model,
                "elapsedMs": elapsed_ms,
                "attempts": attempt,
                "error": None,
                "timeoutSeconds": OLLAMA_REQUEST_TIMEOUT_SECONDS,
            }
        except requests.ConnectionError as error:
            last_error = error
            if attempt == 1:
                time.sleep(2)
                continue
            elapsed_ms = int((time.time() - started) * 1000)
            log_error("call-ollama", "Ollama unreachable after retry.", error, {"model": model})
            return "", {
                "status": "unreachable",
                "model": model,
                "elapsedMs": elapsed_ms,
                "attempts": attempt,
                "error": str(error),
                "timeoutSeconds": OLLAMA_REQUEST_TIMEOUT_SECONDS,
            }
        except requests.Timeout as error:
            elapsed_ms = int((time.time() - started) * 1000)
            log_error(
                "call-ollama",
                "Ollama request timed out.",
                error,
                {"model": model, "timeoutSeconds": OLLAMA_REQUEST_TIMEOUT_SECONDS},
            )
            return "", {
                "status": "timeout",
                "model": model,
                "elapsedMs": elapsed_ms,
                "attempts": attempt,
                "error": str(error),
                "timeoutSeconds": OLLAMA_REQUEST_TIMEOUT_SECONDS,
            }
        except (requests.RequestException, ValueError) as error:
            elapsed_ms = int((time.time() - started) * 1000)
            log_error("call-ollama", "Ollama request failed.", error, {"model": model})
            return "", {
                "status": "http_error",
                "model": model,
                "elapsedMs": elapsed_ms,
                "attempts": attempt,
                "error": str(error),
                "timeoutSeconds": OLLAMA_REQUEST_TIMEOUT_SECONDS,
            }

    elapsed_ms = int((time.time() - started) * 1000)
    return "", {
        "status": "unreachable",
        "model": model,
        "elapsedMs": elapsed_ms,
        "attempts": 2,
        "error": str(last_error) if last_error else "unknown",
        "timeoutSeconds": OLLAMA_REQUEST_TIMEOUT_SECONDS,
    }


def call_ollama(model, prompt):
    """
    Back-compat wrapper used by string-consuming card handlers.

    Returns only the content string. Empty string on any failure; the
    caller can no longer distinguish transport from semantic emptiness,
    which is intentional — paths that need that signal must use
    call_ollama_with_transport directly.
    """
    content, _ = call_ollama_with_transport(model, prompt)
    return content


def build_planning_prompt(project, checkpoint_mode, resource_state):
    capacity = resource_state.get("agentCapacity", {})
    forge_context = read_forge_context()
    research_policy = research_budget_text({"project": project})
    return f"""You are the Gemma Forge planning agent.
This is a work harness, not a chat interface.

{forge_context}

Project to plan:
{project}

Use these built-in protocol cards:
- Forge Flow: orient on project state, read project map/context, verify local environment, protect user work.
- GSD: turn project intent into phases, execution steps, success criteria, and verification.
- Project Execution: materialize planned files, run validation, repair failures, retest, and write delivery artifacts.
- SocratiCode: use semantic codebase search when a codebase needs mapping or feature discovery.
- Axon: use structural analysis before refactors, impact checks, dead-code review, and dependency reasoning.

Checkpoint mode: {checkpoint_mode}
System resource mode: {capacity.get("mode", "unknown")}
Subagent capacity: {capacity.get("maxParallelSubagents", 0)}
Review strategy: {capacity.get("reviewStrategy", "Run a careful audit pass before verification.")}
Research policy: {research_policy}
Small-model completion policy: when the active model is {SMALL_MODEL_REVIEW_MAX_B}B parameters or less, every Forge Section receives one extra independent review before it can be marked complete.

If subagent capacity is zero, do not pretend parallel review happened. Instead, review each step as an auditor who assumes the prior implementation may be wrong or incomplete.

Return a concise orchestration plan with:
1. Project intent
2. Active cards
3. Deactivated cards and why
4. Phase plan
5. Verification checkpoints
6. First action
"""


def build_mode_aware_planning_prompt(session, checkpoint_mode, resource_state):
    capacity = resource_state.get("agentCapacity", {})
    project_mode = session.get("projectMode", "unknown")
    project_directory = session.get("projectDirectory", "")
    forge_context = read_forge_context()
    research_policy = research_budget_text(session)
    base = f"""You are the Gemma Forge planning agent.
This is a work harness, not a chat interface.

{forge_context}

Project to plan:
{session.get('project', '')}

Project mode: {project_mode}
Project directory: {project_directory or 'not provided'}
Checkpoint mode: {checkpoint_mode}
System resource mode: {capacity.get("mode", "unknown")}
Subagent capacity: {capacity.get("maxParallelSubagents", 0)}
Review strategy: {capacity.get("reviewStrategy", "Run a careful audit pass before verification.")}
Research policy: {research_policy}
Small-model completion policy: when the active model is {SMALL_MODEL_REVIEW_MAX_B}B parameters or less, every Forge Section receives one extra independent review before it can be marked complete.
"""

    if project_mode == "new-project":
        return base + """
The user does not have a project directory yet. Treat this project record as the project seed.

Use Project Execution after GSD to create the directory, docs, starter files, validation artifacts, repair notes, and delivery notes.
Do not run codebase exploration yet. SocratiCode and Axon stay inactive until files exist.

Return:
1. Project intent
2. More information needed
3. Proposed project directory name
4. Initial folder/file structure
5. First milestone
6. Materialization, validation, repair/retest, and delivery steps
"""

    if project_mode == "existing-directory":
        return base + """
The user already has a project directory. Use Forge Flow first to orient on project files, then decide whether GSD, SocratiCode, and Axon are needed.

Return:
1. Project intent
2. Active cards
3. Directory/documentation checks
4. Phase plan
5. Verification checkpoints
6. First action
"""

    return base + """
The user has not answered whether a project directory exists yet.

First ask: "Do you already have a project directory for this?"

Then explain:
- Yes activates Forge Flow and may activate SocratiCode/Axon.
- No keeps SocratiCode/Axon inactive and uses Intake/GSD to create the project seed.
"""


def build_session_prompt(session, message):
    resource_state = scan_workspace()
    capacity = resource_state.get("agentCapacity", {})
    linked = session.get("bridges", [])
    history = session.get("messages", [])[-10:]
    history_lines = [f"{item.get('role')}: {item.get('content')}" for item in history]
    forge_context = read_forge_context()
    research_policy = research_budget_text(session)
    return f"""You are the Gemma Forge work-harness agent for one self-contained project.

{forge_context}

Project:
{session.get('project', '')}

Linked projects:
{json.dumps(linked, indent=2)}

Resource mode: {capacity.get("mode", "unknown")}
Subagent capacity: {capacity.get("maxParallelSubagents", 0)}
Review strategy: {capacity.get("reviewStrategy", "Run a careful audit pass before verification.")}
Research policy: {research_policy}
Small-model completion policy: when the active model is {SMALL_MODEL_REVIEW_MAX_B}B parameters or less, every Forge Section receives one extra independent review before it can be marked complete.

Available protocol cards:
{json.dumps(session.get('cards', default_cards()), indent=2)}

Recent project context:
{chr(10).join(history_lines)}

User request:
{message}

Respond as a project work harness. Keep the answer action-oriented and scoped to this project. If model management is requested, explain whether the model is installed, skipped, queued, or should be imported through Settings.
"""


def detect_tool_status():
    workspace = scan_workspace()
    socraticode = socraticode_runtime_status(auto_install=True)
    socraticode_probe = socraticode_mcp_probe(PROJECT_ROOT) if socraticode.get("ready") else {
        "ready": False,
        "stdout": "",
        "stderr": socraticode.get("reason"),
    }
    axon = axon_runtime_status()
    axon_probe = axon_project_probe(PROJECT_ROOT) if axon.get("ready") else {
        "ready": False,
        "stdout": "",
        "stderr": axon.get("reason"),
    }
    socraticode_tools = workspace.get("tools", {})
    return {
        "forgeFlow": {
            "ready": os.path.exists(os.path.join(PROJECT_ROOT, "project-map.md")),
            "label": "Forge Flow",
            "mode": "local project protocol",
        },
        "gsd": {
            "ready": os.path.exists("/Users/webot/.codex/skills/gsd/SKILL.md"),
            "label": "GSD",
            "mode": "local skill prompt + Gemma planning",
        },
        "socraticode": {
            "ready": bool(socraticode.get("ready") and socraticode_probe.get("ready")),
            "executable": bool(socraticode.get("executable")),
            "installed": bool(socraticode.get("installed")),
            "skillReady": bool(socraticode_tools.get("socraticodeSkillReady")),
            "label": "SocratiCode",
            "path": socraticode.get("path"),
            "mode": socraticode.get("mode"),
            "note": socraticode.get("reason"),
            "runtime": summarize_tool_runtime(socraticode),
            "probe": summarize_probe_result(socraticode_probe),
        },
        "axon": {
            "ready": bool(axon.get("ready") and axon_probe.get("ready")),
            "label": "Axon",
            "mode": "local CLI" if axon.get("ready") else "unavailable",
            "path": axon.get("path"),
            "runtime": summarize_axon_runtime(axon),
            "status": axon_probe.get("stdout") if axon_probe.get("ready") else axon_probe.get("stderr"),
            "probe": summarize_probe_result(axon_probe),
        },
    }


def run_card_action(session_id, session, card_id, model, mode, correction=None):
    """
    Dispatch a card to its handler. `correction` is an optional dict bundling
    both the previous reviewer's structured findings and the user's typed
    "Resolve issue" note. Handlers that support a "previous review failed"
    block (execution, verification) consume it via their own `correction`
    kwarg; other handlers ignore it.
    """
    handlers = {
        "intake": run_intake_card,
        "forge-flow": run_forge_flow_card,
        "gsd": run_gsd_card,
        "execution": run_execution_card,
        "socraticode": run_socraticode_card,
        "axon": run_axon_card,
        "verification": run_verification_card,
        "handoff": run_handoff_card,
    }
    handler = handlers.get(card_id, run_unknown_card)
    if card_id in {"execution", "verification"}:
        return handler(session_id, session, model, mode, correction=correction)
    return handler(session_id, session, model, mode)


def build_correction_from_state(session, card_id, user_note):
    """
    Construct a correction dict that includes BOTH:
      - the structured findings from the most recent extra-review of this card
        (the reviewer's complaint that triggered the Not Verified)
      - the user's typed Resolve-issue note

    Either source may be empty. Returns None when both are empty so the
    caller can skip the correction path entirely.
    """
    user_note = (user_note or "").strip()
    review_summary = ""
    findings = []
    fixes = []
    card = find_card(session, card_id) or {}
    last_run = card.get("lastRun") if isinstance(card.get("lastRun"), dict) else {}
    extra_review = last_run.get("extraReview") if isinstance(last_run.get("extraReview"), dict) else {}
    if extra_review:
        review_summary = str(extra_review.get("summary", "")).strip()
        findings = listify(extra_review.get("findings"))
        fixes = listify(extra_review.get("fixesNeeded"))
    # Also surface deterministic validation failures from the prior run so the
    # model sees them alongside the reviewer's interpretation.
    validation = last_run.get("validation") if isinstance(last_run.get("validation"), dict) else {}
    validation_failures = listify(validation.get("failures")) if validation else []

    if not user_note and not review_summary and not findings and not fixes and not validation_failures:
        return None
    return {
        "summary": review_summary or "(prior reviewer summary not recorded)",
        "findings": findings,
        "fixesNeeded": fixes,
        "validationFailures": validation_failures,
        "userNote": user_note,
        "source": "user-resolve" if user_note else "auto",
    }


def finalize_card_result(session_id, session, card_id, model, result, human_verify):
    research = run_research_passes_if_needed(session_id, session, card_id, model, result)
    if research:
        result["researchPasses"] = research

    review = run_completion_review_if_needed(session_id, session, card_id, model, result)
    if review:
        result["extraReview"] = review

    if review and not review.get("passed"):
        repairs = run_post_review_repairs_if_needed(session_id, session, card_id, model, result, review)
        if repairs:
            result["postReviewRepairs"] = repairs
            review = result.get("extraReview", review)

    if review and not review.get("passed"):
        result["status"] = "needs-attention"
        result["checkpoint"] = small_model_review_checkpoint(review)
        return result

    tool_execution = result.get("toolExecution")
    if isinstance(tool_execution, dict) and tool_execution.get("requiresAttention"):
        result["status"] = "needs-attention"
        result["checkpoint"] = (
            f"{tool_execution.get('tool', 'Tool')} needs attention: "
            f"{tool_execution.get('reason', 'review the tool artifact before continuing.')}"
        )
        return result

    result["status"] = "awaiting-human" if human_verify else "complete"
    if not human_verify:
        if isinstance(tool_execution, dict) and tool_execution.get("status") not in {None, "complete"}:
            result["checkpoint"] = (
                f"Auto-run completed this section with tool status `{tool_execution.get('status')}`. "
                "Review the tool artifact before relying on that tool."
            )
        else:
            result["checkpoint"] = "Auto-run completed this section after required review gates."
    return result


def run_post_review_repairs_if_needed(session_id, session, card_id, model, result, review):
    repairs = []
    current_review = review
    for attempt in range(1, POST_REVIEW_REPAIR_ATTEMPTS + 1):
        if current_review.get("passed"):
            break

        repair = run_post_review_repair(session_id, session, card_id, model, result, current_review, attempt)
        repairs.append(repair)
        if repair.get("changed") and result.get("researchPasses"):
            result.pop("researchPasses", None)
            repair["clearedStaleResearch"] = True

        current_review = run_completion_review(session_id, session, card_id, model, result)
        current_review["afterRepairAttempt"] = attempt
        result["extraReview"] = current_review

        if current_review.get("passed"):
            break

        if not repair.get("changed"):
            break

    if repairs:
        artifact = write_artifact(
            session_id,
            f"{safe_id(card_id)}-post-review-repairs.md",
            build_post_review_repair_artifact(card_id, repairs, result.get("extraReview", review)),
        )
        result["postReviewRepairArtifact"] = artifact
    return repairs


def run_post_review_repair(session_id, session, card_id, model, result, review, attempt):
    if card_id == "execution":
        return repair_execution_after_review(session_id, session, model, result, review, attempt)
    if card_id == "verification":
        return repair_verification_after_review(session_id, session, result, review, attempt)
    return repair_text_section_after_review(session_id, session, card_id, model, result, review, attempt)


def repair_execution_after_review(session_id, session, model, result, review, attempt):
    workspace_dir = normalize_directory_path(result.get("workspace")) or resolve_execution_workspace(
        session_id,
        session,
        session.get("project", ""),
    )

    os.makedirs(workspace_dir, exist_ok=True)
    session["projectMode"] = "existing-directory"
    session["projectDirectory"] = workspace_dir
    execution = execute_model_authored_project(session_id, session, model, workspace_dir, review)
    activate_post_execution_cards(session)

    result["summary"] = "Post-review patch reran model-authored execution and verification packaging."
    result["details"] = build_model_execution_report(workspace_dir, execution)
    result["checkpoint"] = "Open the repaired delivery artifacts and confirm the generated project meets the requested outcome."
    result["artifact"] = write_artifact(session_id, "execution.md", result["details"])
    result["workspace"] = workspace_dir
    result["validation"] = execution.get("validation", {})
    return {
        "attempt": attempt,
        "card": "execution",
        "changed": True,
        "action": "Reran execution with model-authored file outputs and repackaged validation.",
        "reviewSummary": review.get("summary", ""),
        "artifact": result["artifact"],
        "validation": result["validation"],
    }


def repair_verification_after_review(session_id, session, result, review, attempt):
    # Pass the model + the failed-review object so the rebuilt verification
    # actually produces a fresh model checklist that names which findings
    # have / have not been addressed. The previous behaviour passed neither,
    # which left the Checklist section empty and discarded any user-driven
    # correction from the prior call to build_verification_details.
    repair_model = session.get("model", DEFAULT_MODEL)
    details, validation = build_verification_details(
        session_id, session, "post-review repair", repair_model, review,
    )
    upstream_artifact = None
    if isinstance(validation, dict) and validation.get("passed") is False:
        workspace_dir = session.get("projectDirectory", "").strip()
        if workspace_dir and os.path.isdir(workspace_dir):
            execution = execute_model_authored_project(session_id, session, repair_model, workspace_dir, review)
            upstream_details = build_model_execution_report(workspace_dir, execution)
            upstream_artifact = write_artifact(session_id, "execution.md", upstream_details)
            details, validation = build_verification_details(
                session_id, session, "post-review repair", repair_model, review,
            )

    result["summary"] = "Post-review patch rebuilt verification with artifact context and reran deterministic checks."
    result["details"] = details
    result["checkpoint"] = "Inspect the verification report and confirm the generated project meets the requested outcome."
    result["artifact"] = write_artifact(session_id, "verification.md", details)
    result["validation"] = validation
    action = "Rebuilt verification from the actual workspace files, validation artifact, and original user request."
    if upstream_artifact:
        action = "Reran model-authored execution, then rebuilt verification and reran deterministic checks."
    return {
        "attempt": attempt,
        "card": "verification",
        "changed": True,
        "action": action,
        "reviewSummary": review.get("summary", ""),
        "artifact": result["artifact"],
        "upstreamArtifact": upstream_artifact,
        "validation": validation,
    }


def repair_text_section_after_review(session_id, session, card_id, model, result, review, attempt):
    prompt = f"""Gemma Forge post-review patch.

Project:
{session.get('project', '')}

Card: {card_id}
Review summary: {review.get('summary', '')}
Findings:
{json.dumps(listify(review.get('findings')), indent=2)}
Fixes needed:
{json.dumps(listify(review.get('fixesNeeded')), indent=2)}

Current section details:
{truncate_text(result.get('details', ''), 4000)}

Patch this section's artifact so it directly answers the review findings. Keep it concise and actionable."""
    patch_note = call_ollama(model, prompt)
    result["details"] = "\n\n".join([
        result.get("details", ""),
        f"## Post-Review Patch {attempt}",
        patch_note,
    ]).strip()
    result["summary"] = f"{result.get('summary', 'Section completed.')} Post-review patch applied."
    result["artifact"] = write_artifact(session_id, f"{safe_id(card_id)}.md", result["details"])
    return {
        "attempt": attempt,
        "card": card_id,
        "changed": True,
        "action": "Updated the section artifact to address the extra-review findings.",
        "reviewSummary": review.get("summary", ""),
        "artifact": result["artifact"],
    }


def build_post_review_repair_artifact(card_id, repairs, review):
    lines = [
        f"# {card_id} Post-Review Repairs",
        "",
        f"- Attempts: `{len(repairs)}`",
        f"- Final review passed: `{review.get('passed')}`",
        "",
    ]
    for repair in repairs:
        lines.extend([
            f"## Attempt {repair.get('attempt')}",
            "",
            f"- Action: {repair.get('action')}",
            f"- Changed: `{repair.get('changed')}`",
            f"- Artifact: `{repair.get('artifact')}`",
            "",
            "### Review Trigger",
            "",
            repair.get("reviewSummary", ""),
            "",
        ])
        if isinstance(repair.get("validation"), dict):
            lines.extend([
                "### Validation",
                "",
                json.dumps(repair.get("validation"), indent=2),
                "",
            ])
    lines.extend([
        "## Final Extra Review",
        "",
        json.dumps(review, indent=2),
    ])
    return "\n".join(lines)


def run_research_passes_if_needed(session_id, session, card_id, model, result):
    budget = project_research_budget(session)
    research = {
        "policy": "Up to 2 research passes for small tasks and up to 4 for larger tasks.",
        "taskSize": budget["taskSize"],
        "maxPasses": budget["maxPasses"],
        "used": 0,
        "needed": False,
        "items": [],
    }

    if not card_allows_research(card_id):
        research["reason"] = "This card does not normally need a research pass."
        return research

    plan_prompt = f"""You are Gemma Forge research routing.
Project: {session.get('project', '')}
Card: {card_id}
Section summary: {result.get('summary', '')}
Section details:
{truncate_text(result.get('details', ''), 3000)}

Decide whether this section needs extra research before completion.
Use at most {budget['maxPasses']} passes for this {budget['taskSize']} task.
Research can include local project context, implementation assumptions, validation approach, or tool-use questions.
Do not request research for obvious/no-op sections.

Return JSON only:
{{
  "needed": true,
  "passCount": 1,
  "topics": ["specific research question"]
}}
"""
    fallback = {"needed": False, "passCount": 0, "topics": []}
    plan, raw, transport = call_ollama_json(model, plan_prompt, fallback)
    research["plannerTransport"] = transport
    requested = bounded_int(plan.get("passCount") if isinstance(plan, dict) else 0)
    topics = plan.get("topics", []) if isinstance(plan, dict) else []
    if not isinstance(topics, list):
        topics = [str(topics)]
    pass_count = max(0, min(budget["maxPasses"], requested, len(topics)))
    research["needed"] = coerce_bool(plan.get("needed"), False) and pass_count > 0 if isinstance(plan, dict) else False
    research["plannerRaw"] = truncate_text(raw, 1200)

    if not research["needed"]:
        research["reason"] = "Research planner did not request additional passes."
        return research

    for index, topic in enumerate(topics[:pass_count], start=1):
        prompt = f"""Gemma Forge research pass {index} of {pass_count}.
Project: {session.get('project', '')}
Card: {card_id}
Topic: {topic}

Use the current project and section context only. If external internet research would be required, say so plainly instead of inventing facts.

Section details:
{truncate_text(result.get('details', ''), 3000)}

Return a concise research note with:
1. Finding
2. Risk or decision impact
3. How the section should account for it
"""
        note = call_ollama(model, prompt)
        research["items"].append({
            "pass": index,
            "topic": topic,
            "note": note,
        })

    research["used"] = len(research["items"])
    artifact = write_artifact(session_id, f"{safe_id(card_id)}-research.md", build_research_artifact(card_id, research))
    research["artifact"] = artifact
    return research


def build_research_artifact(card_id, research):
    lines = [
        f"# {card_id} Research Passes",
        "",
        f"- Task size: {research.get('taskSize')}",
        f"- Budget: {research.get('maxPasses')}",
        f"- Used: {research.get('used')}",
        "",
    ]
    for item in research.get("items", []):
        lines.extend([
            f"## Pass {item.get('pass')}: {item.get('topic')}",
            "",
            item.get("note", ""),
            "",
        ])
    if not research.get("items"):
        lines.append(research.get("reason", "No research passes were needed."))
    return "\n".join(lines)


def run_completion_review_if_needed(session_id, session, card_id, model, result):
    if not small_model_review_required(model):
        return {
            "required": False,
            "passed": True,
            "model": model,
            "reason": "Selected model is above the small-model review threshold.",
            "thresholdB": SMALL_MODEL_REVIEW_MAX_B,
        }
    return run_completion_review(session_id, session, card_id, model, result)


def ensure_completion_review(session_id, session, card_id, model, card):
    if not small_model_review_required(model):
        return None

    last_run = card.get("lastRun") if isinstance(card, dict) else None
    if not isinstance(last_run, dict):
        return {
            "required": True,
            "passed": False,
            "summary": "No section run exists to review.",
            "findings": ["Run the section before marking it verified."],
            "checkedAt": utc_now(),
        }

    review = last_run.get("extraReview")
    if isinstance(review, dict) and review.get("required") and review.get("passed"):
        return review

    review = run_completion_review(session_id, session, card_id, model, last_run)
    last_run["extraReview"] = review
    return review


def run_completion_review(session_id, session, card_id, model, result):
    responsibility = card_review_responsibility(card_id)
    prompt = f"""You are the independent Gemma Forge completion reviewer.

The selected model is {model}, which is at or below {SMALL_MODEL_REVIEW_MAX_B}B parameters, so this section requires one extra review before it can be marked complete.

Review as an auditor who assumes the section may be wrong or incomplete.

Original project request:
{session.get('project', '')}

Card: {card_id}
Card responsibility: {responsibility}
Section summary: {result.get('summary', '')}
Section details:
{truncate_text(result.get('details', ''), 5000)}

Workspace:
{result.get('workspace') or session.get('projectDirectory', '')}

Validation data:
{json.dumps(result.get('validation', {}), indent=2)}

Research passes:
{json.dumps(result.get('researchPasses', {}), indent=2)}

Post-review repairs:
{json.dumps(result.get('postReviewRepairs', []), indent=2)}

Rules:
- Judge only whether this specific Forge Section met its responsibility. Do not require the section to complete later cards or the full project.
- If validation data exists and says passed is false, return passed false.
- **You CANNOT override a validator-flagged fabrication.** If `validation.failures`
  contains a line starting with "Fabricated-claim guard:" or
  "model-authored execution returned no writable files" or
  "Ollama request timed out", you MUST return `passed: false` and include
  the validator's exact failure text in `findings`. Do not soften it.
- If validation data is absent, do not fail only for that reason. Intake, planning, orientation, research, and handoff sections often do not have executable validation data.
- For execution and verification sections, compare the artifact details and validation data against the original project request. Fail if the delivered or verified phrase, style requirements, or output path do not match the user's request.
- For Axon and SocratiCode support-tool sections, do not judge whether the user-facing project was completed. Judge whether the section used or reported the tool correctly.
- If a support tool is unavailable or fails due to local environment errors, pass the section when the result accurately reports that degraded tool state and does not claim a successful scan.
- If post-review repairs are present, earlier research notes may be stale. Prefer the current section details, current source snippets, and current validation data after the repair.
- Do not ask the user to provide code when a workspace path or artifact path is present. The correct failure is to patch or re-read the generated artifacts.
- Return passed false only for a concrete blocker that must be corrected before this section can be considered complete.
- Look for small implementation issues, missing checks, unsupported claims, unclear artifacts, and next-step risks.
- Do not approve only because the original section sounded confident.
- Return JSON only.

JSON shape:
{{
  "passed": true,
  "summary": "short review result",
  "findings": [],
  "fixesNeeded": [],
  "confidence": "medium"
}}
"""
    fallback = {
        "passed": False,
        "summary": "Small-model review did not return valid JSON.",
        "findings": ["The review response could not be parsed."],
        "fixesNeeded": ["Rerun this section or inspect the artifact manually."],
        "confidence": "low",
    }
    payload, raw, transport = call_ollama_json(model, prompt, fallback)
    if not isinstance(payload, dict):
        payload = fallback
    payload["passed"] = coerce_bool(payload.get("passed"), False)
    payload["transport"] = transport
    normalize_review_scope(card_id, payload, result)

    validation = result.get("validation", {})
    if isinstance(validation, dict) and validation and validation.get("passed") is False:
        payload["passed"] = False
        findings = payload.get("findings")
        if not isinstance(findings, list):
            findings = [str(findings)] if findings else []
        for failure in listify(validation.get("failures")):
            failure_str = str(failure)
            if failure_str and failure_str not in findings:
                findings.append(failure_str)
        if not any("Section validation" in f for f in findings):
            findings.append("Section validation data reports failure.")
        payload["findings"] = findings
        fixes = payload.get("fixesNeeded")
        if not isinstance(fixes, list):
            fixes = [str(fixes)] if fixes else []
        for failure in listify(validation.get("failures")):
            failure_str = str(failure)
            if failure_str.lower().startswith("fabricated-claim guard"):
                fix = "Remove the fabricated claim from summary/notes/verification, or rerun with the missing capability provided externally."
                if fix not in fixes:
                    fixes.append(fix)
        payload["fixesNeeded"] = fixes

    payload["required"] = True
    payload["model"] = model
    payload["thresholdB"] = SMALL_MODEL_REVIEW_MAX_B
    payload["checkedAt"] = utc_now()
    payload["raw"] = truncate_text(raw, 1200)
    artifact = write_artifact(session_id, f"{safe_id(card_id)}-extra-review.md", build_review_artifact(card_id, payload))
    payload["artifact"] = artifact
    return payload


def card_review_responsibility(card_id):
    responsibilities = {
        "intake": "Produce a strict project-context YAML contract: project, intent, deliverable (format/path_pattern/anti_deflection), constraints, skill, acceptance, open_questions.",
        "forge-flow": "Orient on workspace state and local readiness for the current project mode.",
        "gsd": "Produce a practical phase plan with success criteria and verification checkpoints.",
        "execution": "Create or modify planned files, run validation, repair failures, retest, and deliver artifacts.",
        "socraticode": "Prepare or perform semantic codebase mapping when codebase exploration is needed.",
        "axon": "Prepare or perform structural analysis when dependency, impact, or dead-code review is needed.",
        "verification": "Produce or run verification checks for the work currently completed.",
        "handoff": "Summarize verified state, risks, and next action for resumption.",
    }
    return responsibilities.get(card_id, "Complete the stated section work.")


def normalize_review_scope(card_id, review, result=None):
    if review.get("passed") or card_id in {"execution", "verification"}:
        return

    result = result if isinstance(result, dict) else {}
    findings_text = " ".join(
        [str(review.get("summary", ""))]
        + [str(item) for item in listify(review.get("findings"))]
        + [str(item) for item in listify(review.get("fixesNeeded"))]
    ).lower()
    tool_execution = result.get("toolExecution", {})
    if (
        card_id in {"axon", "socraticode"}
        and isinstance(tool_execution, dict)
        and tool_execution.get("blocking") is False
        and tool_execution.get("status") in {"cli-detected", "degraded", "host-assisted", "unavailable", "not-needed"}
    ):
        review["passed"] = True
        review["summary"] = (
            "Support-tool issue recorded as non-blocking because the section accurately reported tool state."
        )
        review["findings"] = listify(review.get("findings"))
        review["findings"].append(
            "Support cards must not invalidate a verified deliverable only because an optional local tool failed."
        )
        review["fixesNeeded"] = []
        return

    validation_only = (
        "validation data" in findings_text
        or "project outcome" in findings_text
        or "full project" in findings_text
        or "smoke test" in findings_text
        or "extra review gate" in findings_text
    )
    future_execution_only = (
        card_id in {"intake", "forge-flow", "gsd", "handoff"}
        and any(marker in findings_text for marker in {
            "implementation artifact",
            "implementation artifacts",
            "javascript",
            "script.js",
            "index.html",
            "styles.css",
            "readme.md",
            "docs/delivery.md",
            "file creation",
            "required files",
            "core functionality",
            "not fully implemented",
            "missing files",
            "truncated",
        })
    )
    section_issue_markers = {
        "missing goal",
        "missing acceptance",
        "unclear",
        "contradiction",
        "unsupported claim",
        "wrong",
        "incomplete brief",
        "missing project",
    }
    has_section_issue = any(marker in findings_text for marker in section_issue_markers)

    if (validation_only or future_execution_only) and not has_section_issue:
        review["passed"] = True
        review["summary"] = (
            "Extra review recorded a non-blocking warning, but this section met its own responsibility."
        )
        review["findings"] = listify(review.get("findings"))
        review["findings"].append(
            "Non-execution sections are not blocked only because later implementation or final validation work is not complete yet."
        )
        review["fixesNeeded"] = []


def build_review_artifact(card_id, review):
    return "\n".join([
        f"# {card_id} Small-Model Extra Review",
        "",
        f"- Required: `{review.get('required')}`",
        f"- Passed: `{review.get('passed')}`",
        f"- Model: `{review.get('model')}`",
        f"- Confidence: `{review.get('confidence', 'unknown')}`",
        "",
        "## Summary",
        "",
        review.get("summary", ""),
        "",
        "## Findings",
        "",
        "\n".join([f"- {item}" for item in listify(review.get("findings"))]) or "- None.",
        "",
        "## Fixes Needed",
        "",
        "\n".join([f"- {item}" for item in listify(review.get("fixesNeeded"))]) or "- None.",
    ])


def small_model_review_checkpoint(review):
    findings = listify(review.get("findings"))
    first = findings[0] if findings else review.get("summary", "Review found a possible issue.")
    return f"Small-model extra review found an issue before completion: {first}"


CONTEXT_REQUIRED_TOP_KEYS = ["project", "intent", "deliverable", "constraints", "skill", "acceptance", "open_questions"]
CONTEXT_BEGIN_MARKER = "<<<CONTEXT_BEGIN>>>"
CONTEXT_END_MARKER = "<<<CONTEXT_END>>>"
CONTEXT_DELIBERATION_OPTIONS = {"temperature": 0.1}


_HARNESS_CAN_DO_BASE = [
    "emit_files",            # write files into the workspace via GFORGE_FILE blocks
    "run_local_skill",       # consume a pre-staged skill from ~/.gforge/harness/skills/
    "call_local_gemma",      # talk to the local Ollama model
    "read_forge_context",    # read forge.md and staged skill files
    "validate_files",        # XML/JSON/YAML validity, file count, path pattern, claim verification
]

_HARNESS_CANNOT_DO_BASE = [
    "git_clone",             # cannot clone arbitrary GitHub / GitLab / Bitbucket repos
    "shell_exec",            # cannot run shell commands on the user's machine
    "install_package",       # cannot npm/pip/brew/apt install
    "external_api",          # cannot call OpenAI/Anthropic/Gemini/Midjourney/etc
    "send_message",          # cannot send email / sms / slack
    "deploy",                # cannot deploy / publish to a registry / push code
    "image_generation",      # raster image gen (svg/html ARE possible, real images are not)
    "video_generation",
    "audio_generation",
    "skill_author",          # NEW skills cannot yet be created mid-session (skill-creator is planned)
]


def harness_capabilities():
    """
    Compute the harness's current CAN / CANNOT lists dynamically.

    Some capabilities are gated on a runtime check (e.g. web_browse only if
    scrapling is importable). This is recomputed every call rather than
    cached at import so an admin can `pip install` a missing tool and have
    the next harness call see it immediately.
    """
    can = list(_HARNESS_CAN_DO_BASE)
    cannot = list(_HARNESS_CANNOT_DO_BASE)
    if tool_browse.is_available():
        can.extend(["web_browse", "web_fetch"])
    else:
        cannot.extend(["web_browse", "web_fetch"])
    if tool_screenshot.is_available():
        can.append("screenshot_capture")
    else:
        cannot.append("screenshot_capture")
    return can, cannot


HARNESS_CAN_DO_DESCRIPTIONS = {
    "emit_files": "write files into the workspace via GFORGE_FILE blocks",
    "run_local_skill": "consume a pre-staged skill from ~/.gforge/harness/skills/",
    "call_local_gemma": "call the local Ollama Gemma model",
    "read_forge_context": "read forge.md and any staged skill files",
    "validate_files": "validate file structure, count, path pattern, and verify claims against disk",
    "web_browse": "fetch / scrape web pages via scrapling (request, browser, or stealth modes)",
    "web_fetch": "GET arbitrary URLs into workspace/research/ files (alias of web_browse)",
    "screenshot_capture": "render a URL or local HTML file via headless Playwright and save a PNG to workspace/screenshots/",
}


# Snapshot at import. The authoritative values come from harness_capabilities()
# which is recomputed each call so newly-installed tools register immediately.
HARNESS_CAN_DO, HARNESS_CANNOT_DO = harness_capabilities()


# Regex patterns that signal a capability is required by the user request.
CAPABILITY_KEYWORDS = {
    "git_clone": [
        r"\bgit\s+clone\b",
        r"\bclone\s+(this\s+|that\s+)?(repo|repository)\b",
        r"\b(install|integrate|pull(\s+in)?)\s+(this|that|the)?\s*(repo|github)\b",
        r"https?://(github|gitlab|bitbucket)\.com/[^/\s]+/[^/\s]+",
    ],
    "web_fetch": [
        r"\bfetch\s+(from\s+)?(url|http|https)\b",
        r"\bdownload\s+(from\s+)?https?://",
        r"\bcurl\s+https?://",
    ],
    "web_browse": [
        r"\bbrowse\s+(the\s+)?(web|internet|sites?)\b",
        r"\b(search|query)\s+(the\s+)?(web|internet|google|bing)\b",
        r"\bresearch\s+\d+\s+(sites?|pages?|articles?|sources?)\b",
        r"\bvisit\s+(the\s+)?(url|site|page|website)\b",
        r"\bgo\s+to\s+\w+\.(com|net|org|io|dev)\b",
    ],
    "shell_exec": [
        r"\brun\s+(this\s+|that\s+)?(command|script|shell|terminal)\b",
        r"\bexecute\s+(this\s+|that\s+)?(command|script)\b",
        r"\b(npm|pip|brew|apt|pnpm|yarn|cargo)\s+install\b",
        r"\bbash\s+-c\b",
    ],
    "install_package": [
        r"\b(install|add)\s+(the\s+)?(package|module|library|dependency)\b",
        r"\b(npm|pip|brew|apt|pnpm|yarn|cargo)\s+(install|add)\b",
    ],
    "external_api": [
        r"\b(openai|anthropic|gemini|google\s+ai|midjourney|dall-?e|stable\s+diffusion|nano\s+banana)\s+(api|call)?\b",
        r"\bapi\s+key\b",
        r"\b(call|hit|use)\s+(the\s+)?(gemini|openai|claude|anthropic)\s+api\b",
    ],
    "image_generation": [
        r"\bgenerate\s+(an?\s+)?(real|raster|photo|jpeg|jpg|png|webp)\s+(image|picture)\b",
        r"\bphotorealistic\s+(image|picture|render)\b",
        r"\b(create|make)\s+a?\s*photo\b",
    ],
    "send_message": [
        r"\bsend\s+(an?\s+)?(email|sms|slack|discord|message|notification)\b",
        r"\bemail\s+(someone|me|us|the\s+team)\b",
        r"\bpost\s+to\s+(slack|discord|twitter|x)\b",
    ],
    "deploy": [
        r"\bdeploy\s+(to|on|onto)\s+(npm|pypi|github|netlify|vercel|aws|cloud|production|staging)\b",
        r"\bpublish\s+to\s+(npm|pypi|github|crates\.io)\b",
        r"\bpush\s+to\s+(production|main|master|origin)\b",
    ],
    "skill_author": [
        r"\bcreate\s+(a\s+|new\s+)?skill\b",
        r"\bauthor\s+(a\s+|new\s+)?skill\b",
        r"\bmake\s+(me\s+)?(a\s+|new\s+)?skill\b",
        r"\bbuild\s+(a\s+|new\s+)?skill\b",
    ],
}


def detect_required_capabilities(text):
    """Scan user text for phrases that imply harness capabilities."""
    if not text:
        return []
    text_lower = text.lower()
    matched = set()
    for capability, patterns in CAPABILITY_KEYWORDS.items():
        for pattern in patterns:
            try:
                if re.search(pattern, text_lower):
                    matched.add(capability)
                    break
            except re.error:
                continue
    return sorted(matched)


def missing_capabilities(required):
    _, cannot = harness_capabilities()
    return [c for c in required if c in cannot]


# Anti-deflection lines per deliverable format. The Context Writer uses these
# as the source of truth so small models see consistent, format-appropriate
# guardrails rather than whatever the model freelances.
ANTI_DEFLECTION_REGISTRY = {
    "svg": (
        "SVG is plain text markup. You CAN write SVG directly inside GFORGE_FILE blocks. "
        "Do NOT redirect to Midjourney / DALL-E / Adobe Firefly / Nano Banana / a human "
        "designer / any external image tool. Hand-write the markup yourself."
    ),
    "html": (
        "HTML is plain text. Write the full document inside GFORGE_FILE blocks, complete "
        "with <!doctype html>, <head>, and <body>. Do NOT say you cannot build a webpage."
    ),
    "css": (
        "CSS is plain text. Write the complete stylesheet inside GFORGE_FILE blocks. "
        "Do NOT defer styling to an external designer."
    ),
    "javascript": (
        "JavaScript is plain text. Write the entire file inside GFORGE_FILE blocks. "
        "Do NOT abbreviate function bodies with comments — write the real code."
    ),
    "typescript": (
        "TypeScript is plain text. Write the full file inside GFORGE_FILE blocks. "
        "Do NOT skip the body because 'the compiler will infer it'."
    ),
    "python": (
        "Python source is plain text. Write the complete file inside GFORGE_FILE blocks. "
        "Do NOT say 'left as an exercise' — write the actual code."
    ),
    "json": (
        "JSON is structured plain text. Emit valid JSON inside GFORGE_FILE blocks. "
        "Do NOT abbreviate fields with '...' or 'etc'. Every key listed must have a real value."
    ),
    "yaml": (
        "YAML is plain text. Write the file inside GFORGE_FILE blocks with real "
        "indentation. Do NOT use placeholders like <fill in>."
    ),
    "markdown": (
        "Markdown is plain text. Write the full document inside GFORGE_FILE blocks. "
        "Do NOT just describe what the document would contain — write the document itself."
    ),
    "shell": (
        "Shell scripts are plain text. Write the script inside GFORGE_FILE blocks. "
        "Do NOT execute the script — the user runs it later."
    ),
    "sql": (
        "SQL is plain text. Write the full schema / queries inside GFORGE_FILE blocks. "
        "The harness does not run them; you do not need a database connection."
    ),
    "dockerfile": (
        "A Dockerfile is plain text. Write the complete file inside GFORGE_FILE blocks. "
        "Do NOT defer to `docker init` or an external generator."
    ),
    "mermaid": (
        "Mermaid is plain-text diagram markup. Write the diagram source inside GFORGE_FILE "
        "blocks. Do NOT try to render the image — the renderer runs separately."
    ),
    "txt": (
        "Plain text deliverable. Write the file content directly inside GFORGE_FILE blocks."
    ),
}

ANTI_DEFLECTION_ALIASES = {
    # When the Writer picks a synonym, map it to a canonical key with a real line.
    "image": "svg",
    "icon": "svg",
    "logo": "svg",
    "graphic": "svg",
    "webpage": "html",
    "website": "html",
    "page": "html",
    "landing": "html",
    "stylesheet": "css",
    "javascript module": "javascript",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "code": "python",
    "script": "shell",
    "bash": "shell",
    "zsh": "shell",
    "config": "yaml",
    "configuration": "yaml",
    "doc": "markdown",
    "documentation": "markdown",
    "readme": "markdown",
    "spec": "markdown",
    "plain text": "txt",
}


def canonical_deliverable_format(fmt):
    """Map raw format string to the canonical anti-deflection registry key."""
    if not fmt:
        return ""
    key = fmt.strip().lower()
    if key in ANTI_DEFLECTION_REGISTRY:
        return key
    if key in ANTI_DEFLECTION_ALIASES:
        return ANTI_DEFLECTION_ALIASES[key]
    # try a few prefix matches (e.g. "html5" -> "html")
    for canonical in ANTI_DEFLECTION_REGISTRY:
        if key.startswith(canonical):
            return canonical
    return ""


def anti_deflection_text_for(fmt):
    canonical = canonical_deliverable_format(fmt)
    return ANTI_DEFLECTION_REGISTRY.get(canonical, "")


def build_project_context_prompt(project, mode, staged_skills, previous_attempt=None, validation_errors=None):
    skills_block = "(none staged)"
    if staged_skills:
        skills_block = "\n".join(
            f"  - {skill['name']} (key: {skill['key']}; path: {skill['path']})"
            for skill in staged_skills
        )

    detected = detect_required_capabilities(project)
    detected_missing = missing_capabilities(detected)
    capability_warning = ""
    if detected_missing:
        capability_warning = (
            "\nThe user's request appears to need capabilities the harness CANNOT do: "
            + ", ".join(detected_missing)
            + ". You MUST list each of these in capabilities_required AND add a blocking "
            "open_question that names the gap. Set deliverable.partial: true and shrink "
            "deliverable.scope to what the harness CAN still deliver without those "
            "capabilities. Do NOT pretend the missing capability will be performed.\n"
        )

    repair_block = ""
    if previous_attempt and validation_errors:
        repair_block = f"""
Previous attempt failed validation. Errors:
{chr(10).join(f"  - {error}" for error in validation_errors)}

Your previous output (do not repeat verbatim, fix the errors):
{previous_attempt[:2000]}
"""

    can_now, cannot_now = harness_capabilities()
    capabilities_block = f"""
Harness capabilities (the next agent only has these):
  CAN do: {", ".join(can_now)}
  CANNOT do: {", ".join(cannot_now)}

If the user's request needs anything in CANNOT, you MUST:
  - list every missing capability in capabilities_required
  - add a blocking item to open_questions naming the gap
  - set deliverable.partial: true
  - shrink deliverable.scope to the part the harness CAN still produce
  - do NOT promise the missing work will be performed
{capability_warning}"""

    return f"""You are the Gemma Forge Project Context Writer.

Your job: take the user's natural-language request, understand what they REALLY need, and produce a strict structured contract that every later card in the harness will follow. The next agents are small local models and will pattern-match against your YAML keys. Make the contract unambiguous.

Take a moment. Reason carefully through six steps in order:

1. RESTATE the user's request literally (quote it, no paraphrase).
2. IDENTIFY THE PRIMARY DELIVERABLE — the FINAL artifact the user wants in hand.
   - Look for the noun phrase being created: "10 logos", "a webpage", "a Python CLI", "a README".
   - PREP work (research, plan, gather, learn, study, review docs, consult sources) is NEVER the deliverable. It is enabling work for the final deliverable.
   - "Research X then make Y" → deliverable is Y. "Read this and then write code" → deliverable is the code.
   - If the user is asking ONLY for research output (a brief, a literature review, a market analysis) with no downstream artifact, then research IS the deliverable.
3. CLASSIFY task_type from the PRIMARY deliverable: code | doc | design_deliverable | analysis | research.
   - Logos / icons / brand marks / SVGs → design_deliverable.
   - Pages / sites / web UIs → code (html/css/js) or design_deliverable depending on emphasis.
   - Scripts / programs / tools / CLIs → code.
   - Reports / briefs / explanations / docs → doc.
   - Research-only outputs (literature reviews, summaries of sources) → research.
4. INFER underlying need (one sentence) AND success_means (what counts as DONE for the PRIMARY deliverable, not for any prep step).
5. PICK deliverable.format from the canonical list (svg | html | css | javascript | typescript | python | json | yaml | markdown | shell | sql | dockerfile | mermaid | txt). The format MUST match the primary deliverable, not a prep step. Logos → svg. Webpages → html. Scripts → python (or shell/javascript). Never "tbd" or "various".

5b. WRITE path_pattern as a SINGLE relative path or simple glob — never a phrase, range, or comma list.
   Correct examples:
     - output/logo-NN.svg          (NN is a placeholder for the index)
     - output/favicon-*.svg
     - index.html
     - src/cli.py
   WRONG examples (do NOT do these):
     - "output/file-01.svg to output/file-10.svg"     (phrase with 'to')
     - "output/a.svg, output/b.svg, output/c.svg"     (comma list)
     - "various .svg files in output/"                (vague)
   Use ONE pattern; the count field handles "how many".
6. EMIT the YAML between the markers. Output a one-paragraph rationale BEFORE the begin marker, then the YAML between markers, then nothing else.

CRITICAL: `deliverable.partial: true` is ONLY for capability gaps. If the user lists multiple steps and the harness CAN do them all, partial is FALSE — the harness will execute the prep steps internally and then produce the primary deliverable in one Execution pass. Multi-step requests are normal; they are NOT partial.

CRITICAL: `image_generation` is ONLY required for RASTER images (jpeg, png, webp, gif, photorealistic renders). Vector formats (svg, mermaid) and document formats (html, css, markdown, code) are PLAIN TEXT — the harness writes them as files. Do NOT put `image_generation` in capabilities_required for an SVG / vector / web / code deliverable. "Logo" / "icon" / "graphic" almost always means SVG; do not flag image_generation for those.

Project request (raw, unedited):
{project}

Harness mode: {mode}

Available staged skills (you may name ONE in skill.use, or "none"):
{skills_block}
{capabilities_block}
{repair_block}
You MUST emit exactly this structure between the two markers (replace each <placeholder>):

{CONTEXT_BEGIN_MARKER}
---
project:
  name: <short noun phrase, no quotes>
  type: <code|doc|design_deliverable|analysis|research>
  domain: <one-line description>
intent:
  surface_ask: <the user's words verbatim, in double-quotes>
  underlying_need: <one sentence>
  success_means: <one sentence describing the verifiable definition of done>
deliverable:
  format: <svg|html|css|javascript|typescript|python|json|yaml|markdown|shell|sql|dockerfile|mermaid|txt>
  count: <integer; how many files of this format the harness should write>
  path_pattern: <relative path, e.g. output/logo-NN.svg or index.html>
  encoding: gforge_file_block
  partial: <true|false; true ONLY if the harness lacks a capability the request needs>
  scope: <one-line description of what the harness will actually deliver (matches partial)>
  anti_deflection: |
    <The harness will overwrite this with a canonical anti-deflection paragraph per
    deliverable.format. Write a one-line stub here; the registry value wins.>
capabilities_required:
  - <one entry per capability the request actually needs, e.g. "emit_files" or "git_clone".
    If the request only needs in-workspace file authoring, this is just ["emit_files"].>
constraints:
  hard_requirements:
    - <bullet, each independently verifiable>
    - <bullet>
  tone:
    - <one-word style cue>
    - <one-word style cue>
skill:
  use: <staged skill key, or "none">
  staged_path: <staged path or "n/a">
acceptance:
  - <verifiable check, e.g. "6 files exist under output/">
  - <verifiable check>
open_questions: <empty list, OR one blocking question per missing capability>
---
{CONTEXT_END_MARKER}

Rules:
- Quote the user verbatim in intent.surface_ask, in double-quotes.
- deliverable.format must be one concrete canonical value from the list above.
- capabilities_required must list every capability the user's request implies.
  If any of those are in the harness CANNOT list, you MUST set partial: true,
  populate open_questions, and shrink scope to the partial deliverable.
- acceptance must contain at least two items, each something a deterministic script could check.
- Do NOT claim the harness will do something it cannot. Be honest about scope.
- Output NOTHING after {CONTEXT_END_MARKER}.
"""


def extract_context_yaml_block(text):
    if not text:
        return None, "model output was empty"
    begin = text.find(CONTEXT_BEGIN_MARKER)
    end = text.find(CONTEXT_END_MARKER, begin + 1)
    if begin == -1 or end == -1 or end <= begin:
        return None, f"missing {CONTEXT_BEGIN_MARKER} / {CONTEXT_END_MARKER} markers"
    inner = text[begin + len(CONTEXT_BEGIN_MARKER):end].strip()
    if inner.startswith("---"):
        inner = inner[3:]
    if inner.endswith("---"):
        inner = inner[:-3]
    inner = inner.strip()
    if not inner:
        return None, "YAML block was empty between markers"
    return inner, None


def parse_project_context(text, project_text=""):
    raw_yaml, marker_error = extract_context_yaml_block(text)
    if marker_error:
        return None, raw_yaml, [marker_error]
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as error:
        return None, raw_yaml, [f"YAML parse error: {error}"]
    if not isinstance(parsed, dict):
        return None, raw_yaml, ["YAML did not parse to a mapping at top level"]

    enrich_project_context(parsed, project_text)
    return parsed, dump_project_context_yaml(parsed), validate_project_context(parsed)


def dump_project_context_yaml(parsed):
    """Round-trip the dict through PyYAML so the artifact reflects enrichment."""
    try:
        return yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True).strip()
    except yaml.YAMLError:
        return yaml.safe_dump(parsed, sort_keys=False).strip()


def enrich_project_context(parsed, project_text):
    """
    Post-process a freshly-parsed Project Context to guarantee correctness:
      - anti_deflection is overwritten with the canonical registry text.
      - capabilities_required is reconciled with detected requirements.
      - partial / scope / open_questions are forced when a capability is missing.
    """
    if not isinstance(parsed, dict):
        return parsed

    deliverable = parsed.get("deliverable")
    if not isinstance(deliverable, dict):
        deliverable = {}
        parsed["deliverable"] = deliverable

    fmt = str(deliverable.get("format", "")).strip().lower()
    canonical_fmt = canonical_deliverable_format(fmt)
    if canonical_fmt and canonical_fmt != fmt:
        deliverable["format"] = canonical_fmt
        fmt = canonical_fmt

    canonical_anti = anti_deflection_text_for(fmt)
    if canonical_anti:
        deliverable["anti_deflection"] = canonical_anti

    declared = parsed.get("capabilities_required")
    if not isinstance(declared, list):
        declared = []
    declared_keys = {str(k).strip() for k in declared if str(k).strip()}

    auto_detected = detect_required_capabilities(project_text or "")
    union = declared_keys.union(auto_detected) | {"emit_files"}

    # Strip false-positive `image_generation` when the deliverable is a
    # text-based format. Logos / icons / banners in SVG are plain text — the
    # harness emits the file directly. Only raster formats (png/jpeg/webp)
    # would actually need image_generation.
    text_based_formats = {"svg", "html", "css", "javascript", "typescript", "python", "shell", "sql", "dockerfile", "json", "yaml", "markdown", "mermaid", "txt"}
    if fmt in text_based_formats:
        union.discard("image_generation")
        union.discard("video_generation")
        union.discard("audio_generation")

    union = sorted(union)
    parsed["capabilities_required"] = union

    missing = missing_capabilities(union)
    open_questions = parsed.get("open_questions") if isinstance(parsed.get("open_questions"), list) else []
    open_questions = [str(q).strip() for q in open_questions if str(q).strip()]

    if missing:
        deliverable["partial"] = True
        if not deliverable.get("scope"):
            deliverable["scope"] = (
                "Only the portion of the request the harness can deliver in-workspace; "
                f"missing capabilities ({', '.join(missing)}) are NOT performed."
            )
        for cap in missing:
            question = (
                f"The request implies `{cap}` but the harness cannot do that yet. "
                "Either reduce scope to the in-workspace portion, or perform that step "
                "manually before continuing."
            )
            if not any(cap in q for q in open_questions):
                open_questions.append(question)
    else:
        # No capability gap → force partial=False. The Writer model sometimes
        # mis-sets partial=True for multi-step requests where every step IS
        # doable; that was the WeBot Agency logos session where the deliverable
        # collapsed to a "research plan" markdown file instead of 10 SVGs.
        deliverable["partial"] = False
        if not deliverable.get("scope"):
            deliverable["scope"] = "Full in-workspace deliverable."
        # If the Writer also set type=research while the deliverable.format is a
        # concrete artifact format (svg/html/etc), the type is wrong — prep work
        # isn't the project type. Repair it.
        project = parsed.get("project") if isinstance(parsed.get("project"), dict) else None
        if project is not None:
            current_type = str(project.get("type", "")).strip().lower()
            fmt = str(deliverable.get("format", "")).strip().lower()
            if current_type == "research" and fmt and fmt not in {"markdown", "txt", "doc"}:
                project["type"] = format_default_task_type(fmt)

    parsed["open_questions"] = open_questions
    return parsed


def format_default_task_type(fmt):
    if fmt == "svg":
        return "design_deliverable"
    if fmt in {"html", "css", "javascript", "typescript", "python", "shell", "sql", "dockerfile", "json", "yaml"}:
        return "code"
    if fmt in {"markdown", "txt"}:
        return "doc"
    if fmt == "mermaid":
        return "design_deliverable"
    return "code"


def validate_project_context(parsed):
    errors = []
    for key in CONTEXT_REQUIRED_TOP_KEYS:
        if key not in parsed:
            errors.append(f"missing top-level key: {key}")
    intent = parsed.get("intent") if isinstance(parsed.get("intent"), dict) else {}
    if not str(intent.get("surface_ask", "")).strip():
        errors.append("intent.surface_ask must quote the user's request verbatim")
    deliverable = parsed.get("deliverable") if isinstance(parsed.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    if not fmt or fmt in {"tbd", "any", "various", "unknown"}:
        errors.append("deliverable.format must be one concrete value (svg/html/markdown/python/etc)")
    if not str(deliverable.get("path_pattern", "")).strip():
        errors.append("deliverable.path_pattern must be set (a relative path)")
    if not str(deliverable.get("anti_deflection", "")).strip():
        errors.append("deliverable.anti_deflection must be set")
    acceptance = parsed.get("acceptance")
    if not isinstance(acceptance, list) or len(acceptance) < 2:
        errors.append("acceptance must be a list with at least 2 verifiable checks")

    caps = parsed.get("capabilities_required")
    if not isinstance(caps, list) or not caps:
        errors.append("capabilities_required must be a non-empty list (at minimum: 'emit_files')")
    else:
        missing = missing_capabilities([str(c).strip() for c in caps])
        open_questions = parsed.get("open_questions")
        if missing and (not isinstance(open_questions, list) or not any(open_questions)):
            errors.append(
                "Request needs capabilities the harness lacks ("
                + ", ".join(missing)
                + ") but open_questions is empty. Populate it so execution does not silently fabricate completion."
            )
        if missing and not bool(deliverable.get("partial")):
            errors.append("deliverable.partial must be true when capabilities_required includes a harness CANNOT entry")
    return errors


def render_project_context_artifact(parsed, raw_yaml, transport, repaired):
    yaml_text = raw_yaml.strip() if raw_yaml else ""
    surface_ask = ""
    intent = parsed.get("intent") if isinstance(parsed, dict) and isinstance(parsed.get("intent"), dict) else {}
    surface_ask = str(intent.get("surface_ask", "")).strip().strip('"')
    deliverable = parsed.get("deliverable") if isinstance(parsed, dict) and isinstance(parsed.get("deliverable"), dict) else {}
    open_questions = parsed.get("open_questions") if isinstance(parsed, dict) else []
    if not isinstance(open_questions, list):
        open_questions = []

    transport_line = (
        f"- Context Writer transport: `{transport.get('status', 'unknown')}` "
        f"in `{transport.get('elapsedMs', 0)} ms`, attempts `{transport.get('attempts', 1)}`"
        if isinstance(transport, dict)
        else "- Context Writer transport: not recorded"
    )

    lines = [
        "---",
        yaml_text,
        "---",
        "",
        "# Project Context",
        "",
        transport_line,
        f"- Repaired: `{bool(repaired)}`",
        "",
        "## What the user said",
        "",
        f"> {surface_ask}" if surface_ask else "> (no surface_ask captured)",
        "",
        "## What this means in harness terms",
        "",
        f"- Deliverable format: `{deliverable.get('format', 'unknown')}`",
        f"- Path pattern: `{deliverable.get('path_pattern', 'unknown')}`",
        f"- Count: `{deliverable.get('count', 'unknown')}`",
        f"- Encoding: `{deliverable.get('encoding', 'unknown')}`",
        "",
        "## Anti-deflection anchor for downstream cards",
        "",
        str(deliverable.get("anti_deflection", "")).strip() or "(none provided)",
        "",
        "## Open questions",
        "",
        "\n".join(f"- {q}" for q in open_questions) if open_questions else "- None.",
    ]
    return "\n".join(lines)


def run_intake_card(session_id, session, model, mode):
    project = session.get("project", "")
    workspace_dir = resolve_execution_workspace(session_id, session, project)
    os.makedirs(workspace_dir, exist_ok=True)
    skill_context = prepare_workspace_skill_context(workspace_dir, session)
    staged_skills = skill_context.get("staged", []) if isinstance(skill_context, dict) else []

    prompt = build_project_context_prompt(project, mode, staged_skills)
    raw, transport = call_ollama_with_transport(model, prompt, options_override=CONTEXT_DELIBERATION_OPTIONS)
    parsed, raw_yaml, errors = parse_project_context(raw, project_text=project)

    repaired = False
    repair_raw = ""
    repair_transport = None
    if errors:
        repair_prompt = build_project_context_prompt(
            project, mode, staged_skills,
            previous_attempt=raw,
            validation_errors=errors,
        )
        repair_raw, repair_transport = call_ollama_with_transport(
            model, repair_prompt, options_override=CONTEXT_DELIBERATION_OPTIONS,
        )
        repair_parsed, repair_yaml, repair_errors = parse_project_context(repair_raw, project_text=project)
        if repair_parsed is not None and not repair_errors:
            parsed = repair_parsed
            raw_yaml = repair_yaml
            errors = []
            repaired = True
        else:
            errors = repair_errors or errors

    if parsed and not errors:
        session["projectContext"] = parsed
        session["projectContextRaw"] = raw_yaml
        details = render_project_context_artifact(parsed, raw_yaml, transport, repaired)
        next_step = (
            f"Confirm the deliverable contract ({parsed.get('deliverable', {}).get('format', 'unknown')} "
            f"at `{parsed.get('deliverable', {}).get('path_pattern', '?')}`) before running execution."
        )
        if parsed.get("open_questions"):
            next_step = "Answer the open_questions in the artifact before running execution."
        artifact = write_artifact(session_id, "intake.md", details)
        return card_result("Project Context", "Structured project contract written.", details, next_step, artifact)

    fallback_lines = [
        "# Project Context (FAILED VALIDATION)",
        "",
        f"- Context Writer transport: `{transport.get('status', 'unknown')}` in `{transport.get('elapsedMs', 0)} ms`",
        f"- Repair transport: `{(repair_transport or {}).get('status', 'n/a')}`",
        "",
        "## Validation errors",
        "",
        "\n".join(f"- {error}" for error in (errors or ["unknown failure"])),
        "",
        "## Raw model output (first attempt, truncated)",
        "",
        "```",
        truncate_text(raw, 3000) or "(empty)",
        "```",
    ]
    if repair_raw:
        fallback_lines.extend([
            "",
            "## Raw model output (repair attempt, truncated)",
            "",
            "```",
            truncate_text(repair_raw, 3000),
            "```",
        ])
    details = "\n".join(fallback_lines)
    session.pop("projectContext", None)
    session.pop("projectContextRaw", None)
    artifact = write_artifact(session_id, "intake.md", details)
    return card_result(
        "Project Context",
        "Context Writer could not produce a valid contract. Rerun this card or rephrase the project request.",
        details,
        "Rerun Project Context with a clearer project description, or edit the saved intake.md and rerun the next card.",
        artifact,
    )


def run_forge_flow_card(session_id, session, model, mode):
    """
    Context-aware workspace orientation. Used to hardcode a check for
    README.md / docs/research.md / docs/orchestration-plan.md / docs/delivery.md
    on every run, which was useless for non-software deliverables (logos,
    banners, single-file scripts) and confusingly always reported "missing".
    Now the card reads the Project Context contract and only checks for
    artifacts the contract actually expects.
    """
    workspace = scan_workspace()
    project_mode = session.get("projectMode", "unknown")
    project_directory = session.get("projectDirectory", "")
    workspace_exists = bool(project_directory) and os.path.isdir(project_directory)

    # Pre-Execution branch: workspace not yet materialised.
    if project_mode == "new-project" and not workspace_exists:
        details = build_pre_execution_orientation(session, workspace, project_directory)
        artifact = write_artifact(session_id, "forge-flow.md", details)
        return card_result(
            "Forge Flow",
            "Pre-execution readiness check complete; workspace will be created during Execution.",
            details,
            "Confirm the readiness facts above. Execution will materialise the workspace.",
            artifact,
        )

    # Post-Execution / existing-directory: orient against the real workspace.
    target_directory = project_directory if workspace_exists else PROJECT_ROOT
    details = build_workspace_orientation(target_directory, session, workspace, mode)
    artifact = write_artifact(session_id, "forge-flow.md", details)
    return card_result(
        "Forge Flow",
        "Workspace orientation complete." + (" Deliverable contract verified against disk." if workspace_exists else ""),
        details,
        "Confirm the deliverable file count + research artifacts match the contract.",
        artifact,
    )


def build_pre_execution_orientation(session, workspace, project_directory):
    """Pre-Execution readiness summary for new-project mode."""
    context = session.get("projectContext") if isinstance(session.get("projectContext"), dict) else None
    deliverable = (context or {}).get("deliverable") if isinstance((context or {}).get("deliverable"), dict) else {}
    capabilities = (context or {}).get("capabilities_required") if isinstance((context or {}).get("capabilities_required"), list) else []
    can_now, cannot_now = harness_capabilities()

    lines = [
        "# Forge Flow — Pre-Execution Readiness",
        "",
        "Workspace will be created by Execution. Readiness inputs the next cards will see:",
        "",
        "## Runtime",
        "",
        f"- Ollama installed: `{workspace['ollama']['installed']}`",
        f"- Ollama running: `{workspace['ollama']['running']}`",
        f"- Selected model: `{session.get('model', DEFAULT_MODEL)}`",
        f"- Subagent mode: `{workspace['agentCapacity']['mode']}`",
        f"- Subagent capacity: `{workspace['agentCapacity']['maxParallelSubagents']}`",
        "",
        "## Project Context Contract",
        "",
        f"- Type: `{(context or {}).get('project', {}).get('type', 'unknown') if isinstance((context or {}).get('project'), dict) else 'unknown'}`",
        f"- Deliverable format: `{deliverable.get('format', 'unknown')}`",
        f"- Deliverable count: `{deliverable.get('count', 'unknown')}`",
        f"- Path pattern: `{deliverable.get('path_pattern', 'unknown')}`",
        f"- Partial scope: `{bool(deliverable.get('partial'))}`",
        "",
        "## Capabilities",
        "",
        f"- Required by request: `{', '.join(capabilities) or '(none)'}`",
        f"- Harness CAN: `{', '.join(can_now)}`",
        f"- Harness CANNOT: `{', '.join(cannot_now)}`",
    ]
    if project_directory:
        lines.extend(["", f"- Requested directory: `{project_directory}`"])
    return "\n".join(lines)


def build_workspace_orientation(target_directory, session, workspace, mode):
    """Post-Execution (or existing-directory) workspace orientation."""
    context = session.get("projectContext") if isinstance(session.get("projectContext"), dict) else None
    deliverable = (context or {}).get("deliverable") if isinstance((context or {}).get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    path_pattern = str(deliverable.get("path_pattern", "")).strip()
    expected_count = deliverable.get("count")
    project_type = (context or {}).get("project", {}).get("type", "") if isinstance((context or {}).get("project"), dict) else ""

    lines = [
        "# Forge Flow Orientation",
        "",
        f"- Mode: `{mode}`",
        f"- Project directory: `{target_directory}`",
        f"- Ollama installed: `{workspace['ollama']['installed']}`",
        f"- Ollama running: `{workspace['ollama']['running']}`",
        f"- Selected model: `{session.get('model', DEFAULT_MODEL)}`",
    ]

    # Deliverable check — matches the contract. The Writer sometimes emits a
    # phrase ("output/foo-01.svg to output/foo-10.svg") rather than a clean
    # glob; pull out the first path-looking token to recover the directory.
    actual_deliverable_files = []
    pattern_dir = ""
    pattern_ext = ""
    if path_pattern:
        first_path_token = next(
            (token for token in re.split(r"\s+|,", path_pattern)
             if "/" in token or token.lower().endswith(("." + (fmt or "")))),
            path_pattern,
        )
        pattern_dir = os.path.dirname(first_path_token) or "."
        pattern_basename = os.path.basename(first_path_token)
        pattern_ext = os.path.splitext(pattern_basename)[1] or (f".{fmt}" if fmt else "")
        full_dir = os.path.join(target_directory, pattern_dir)
        if os.path.isdir(full_dir):
            actual_deliverable_files = sorted(
                f for f in os.listdir(full_dir)
                if (not pattern_ext) or f.lower().endswith(pattern_ext.lower())
            )
    lines.extend([
        "",
        "## Deliverable",
        "",
        f"- Format: `{fmt or 'unknown'}`",
        f"- Path pattern: `{path_pattern or '(no contract)'}`",
        f"- Expected count: `{expected_count if expected_count is not None else 'unknown'}`",
        f"- Files present: `{len(actual_deliverable_files)}`",
    ])
    if actual_deliverable_files:
        lines.append("- Listing:")
        for filename in actual_deliverable_files[:25]:
            lines.append(f"  - `{filename}`")
        if len(actual_deliverable_files) > 25:
            lines.append(f"  - ...and {len(actual_deliverable_files) - 25} more")

    # Research artifacts (scrapling pre-fetch).
    research_dir = os.path.join(target_directory, "research")
    if os.path.isdir(research_dir):
        research_files = sorted(f for f in os.listdir(research_dir) if f.endswith(".md"))
        lines.extend(["", "## Research artifacts (harness-fetched)", ""])
        if research_files:
            for filename in research_files[:12]:
                lines.append(f"- `research/{filename}`")
            if len(research_files) > 12:
                lines.append(f"- ...and {len(research_files) - 12} more")
        else:
            lines.append("- (research dir exists but is empty)")

    # Staged skills.
    staged_skills_dir = os.path.join(target_directory, WORKSPACE_SKILLS_ROOT)
    if os.path.isdir(staged_skills_dir):
        staged = [name for name in sorted(os.listdir(staged_skills_dir)) if os.path.isdir(os.path.join(staged_skills_dir, name))]
        lines.extend(["", "## Staged skills", ""])
        if staged:
            for name in staged:
                lines.append(f"- `{name}`")
        else:
            lines.append("- (none)")

    # Only check for project-style docs when the deliverable type implies they
    # exist. Software projects → README.md; report deliverables → the doc file
    # itself. Design deliverables (logos / icons / banners) do NOT need
    # README.md — that was the old confusing failure mode.
    relevant_docs = forge_flow_relevant_doc_checks(project_type, fmt, target_directory, deliverable)
    if relevant_docs:
        lines.extend(["", "## Relevant docs", ""])
        for name, ready in relevant_docs:
            lines.append(f"- `{name}`: {'ready' if ready else 'missing'}")

    return "\n".join(lines)


def forge_flow_relevant_doc_checks(project_type, fmt, target_directory, deliverable):
    """
    Build a list of (label, exists) tuples for docs that actually matter for
    this deliverable type. Returning an empty list is fine — we no longer
    surface README.md / docs/research.md for a deliverable that does not
    expect them.
    """
    checks = []
    project_type = (project_type or "").lower()
    fmt = (fmt or "").lower()
    if project_type == "code":
        checks.append(("README.md", os.path.exists(os.path.join(target_directory, "README.md"))))
        if fmt == "python":
            checks.append(("requirements.txt OR pyproject.toml",
                          os.path.exists(os.path.join(target_directory, "requirements.txt"))
                          or os.path.exists(os.path.join(target_directory, "pyproject.toml"))))
        elif fmt in {"javascript", "typescript"}:
            checks.append(("package.json", os.path.exists(os.path.join(target_directory, "package.json"))))
    elif project_type == "research":
        path = str((deliverable or {}).get("path_pattern", "")).strip() or "docs/research.md"
        checks.append((path, os.path.exists(os.path.join(target_directory, path))))
    elif project_type == "doc":
        path = str((deliverable or {}).get("path_pattern", "")).strip()
        if path:
            checks.append((path, os.path.exists(os.path.join(target_directory, path))))
    # design_deliverable / analysis / unknown → no extra doc check beyond the
    # deliverable file count we already showed above.
    return checks


def run_execution_card(session_id, session, model, mode, correction=None):
    project = session.get("project", "")
    workspace_dir = resolve_execution_workspace(session_id, session, project)

    os.makedirs(workspace_dir, exist_ok=True)
    session["projectMode"] = "existing-directory"
    session["projectDirectory"] = workspace_dir
    # User-driven Resolve: feed the prior reviewer findings + user note to the
    # model via the existing `review` channel that build_model_execution_prompt
    # already renders into a "Previous review failed:" block.
    execution = execute_model_authored_project(
        session_id, session, model, workspace_dir, review=correction,
    )
    activate_post_execution_cards(session)

    details = build_model_execution_report(workspace_dir, execution)
    artifact = write_artifact(session_id, "execution.md", details)
    return card_result(
        "Project Execution",
        "Gemma-authored execution output was written and packaged for verification.",
        details,
        "Open the delivery artifacts and confirm the generated project meets the requested outcome.",
        artifact,
        {"workspace": workspace_dir, "validation": execution.get("validation", {})},
    )


def resolve_execution_workspace(session_id, session, project):
    requested = normalize_directory_path(session.get("projectDirectory", ""))
    if requested:
        return requested
    return os.path.join(session_dir(session_id), "workspace", safe_id(project[:80]).lower())


def run_gsd_card(session_id, session, model, mode):
    resource_state = scan_workspace()
    details = call_ollama(
        model,
        build_planning_prompt(session.get("project", ""), mode, resource_state),
    )
    artifact = write_artifact(session_id, "gsd-plan.md", details)
    return card_result(
        "GSD Planning",
        "Phase plan generated from the project record.",
        details,
        "Review the phases and verify each phase has a testable done condition.",
        artifact,
    )


def run_socraticode_card(session_id, session, model, mode):
    if session.get("projectMode") == "new-project":
        details = "\n".join([
            "# SocratiCode",
            "",
            "Tool status: `not-needed`",
            "",
            "SocratiCode was not run because this project does not have a project directory or code files yet.",
        ])
        artifact = write_artifact(session_id, "socraticode-brief.md", details)
        return card_result(
            "SocratiCode",
            "Semantic search deferred until code exists.",
            details,
            "Create or connect a project directory before running SocratiCode.",
            artifact,
            {
                "toolExecution": {
                    "tool": "socraticode",
                    "status": "not-needed",
                    "blocking": False,
                    "requiresAttention": False,
                    "reason": "No project directory exists yet.",
                }
            },
        )

    target_directory = session.get("projectDirectory") if os.path.isdir(session.get("projectDirectory", "")) else PROJECT_ROOT
    profile = project_file_profile(target_directory)
    if profile["semanticFileCount"] == 0:
        details = build_socraticode_details(
            target_directory,
            profile,
            {
                "tool": "socraticode",
                "status": "not-needed",
                "blocking": False,
                "requiresAttention": False,
                "reason": "No semantic-searchable project files were found.",
            },
            "",
        )
        artifact = write_artifact(session_id, "socraticode-brief.md", details)
        return card_result(
            "SocratiCode",
            "Semantic search skipped because no searchable files were found.",
            details,
            "Create or connect code/documentation files before relying on SocratiCode.",
            artifact,
            {
                "toolExecution": {
                    "tool": "socraticode",
                    "status": "not-needed",
                    "blocking": False,
                    "requiresAttention": False,
                    "reason": "No semantic-searchable project files were found.",
                    "profile": profile,
                }
            },
        )

    runtime = socraticode_runtime_status(auto_install=True)
    if not runtime.get("ready"):
        tool_execution = {
            "tool": "socraticode",
            "status": "unavailable",
            "blocking": False,
            "requiresAttention": True,
            "reason": runtime.get("reason", "SocratiCode runtime is not ready."),
            "profile": profile,
            "runtime": summarize_tool_runtime(runtime),
        }
        details = build_socraticode_details(target_directory, profile, tool_execution, "")
        artifact = write_artifact(session_id, "socraticode-brief.md", details)
        return card_result(
            "SocratiCode",
            "Semantic search support is unavailable in this environment.",
            details,
            "Continue if execution and verification artifacts are sufficient; repair SocratiCode before relying on semantic search.",
            artifact,
            {"toolExecution": tool_execution},
        )

    search_query = session.get("project", "").strip() or "project structure implementation entry points"
    scan = run_socraticode_project_scan(target_directory, search_query)
    tool_execution = {
        "tool": "socraticode",
        "status": scan.get("status", "degraded"),
        "blocking": False,
        "requiresAttention": bool(scan.get("requiresAttention")),
        "reason": scan.get("reason", "SocratiCode scan completed."),
        "profile": profile,
        "indexedChunks": scan.get("indexedChunks"),
        "runtime": summarize_tool_runtime(scan.get("runtime", runtime)),
        "commands": summarize_mcp_commands(scan.get("commands", {})),
    }
    brief = build_socraticode_scan_brief(session, target_directory, profile, scan, mode)
    details = build_socraticode_details(target_directory, profile, tool_execution, brief)
    artifact = write_artifact(session_id, "socraticode-brief.md", details)
    summary = "SocratiCode indexed and searched the project."
    checkpoint = "Review the SocratiCode search results and confirm the mapped files are relevant."
    if tool_execution["status"] != "complete":
        summary = "SocratiCode semantic scan failed or is degraded."
        checkpoint = "Repair SocratiCode runtime, Docker/Qdrant, or project files, then rerun this section."
    return card_result(
        "SocratiCode",
        summary,
        details,
        checkpoint,
        artifact,
        {"toolExecution": tool_execution},
    )


def summarize_tool_runtime(runtime):
    runtime = runtime if isinstance(runtime, dict) else {}
    docker = runtime.get("docker", {}) if isinstance(runtime.get("docker"), dict) else {}
    node = runtime.get("node", {}) if isinstance(runtime.get("node"), dict) else {}
    return {
        "ready": bool(runtime.get("ready")),
        "installed": bool(runtime.get("installed")),
        "executable": bool(runtime.get("executable")),
        "mode": runtime.get("mode"),
        "path": runtime.get("path"),
        "reason": runtime.get("reason"),
        "nodeReady": bool(node.get("ready")),
        "nodeVersion": node.get("version"),
        "dockerReady": bool(docker.get("ready")),
        "qdrantRunning": bool(docker.get("qdrantRunning")),
        "qdrantStatus": docker.get("qdrantStatus"),
    }


def summarize_axon_runtime(runtime):
    runtime = runtime if isinstance(runtime, dict) else {}
    return {
        "ready": bool(runtime.get("ready")),
        "executable": bool(runtime.get("executable")),
        "path": runtime.get("path"),
        "version": runtime.get("version"),
        "reason": runtime.get("reason"),
    }


def summarize_probe_result(probe):
    probe = probe if isinstance(probe, dict) else {}
    return {
        "ready": bool(probe.get("ready")),
        "returncode": probe.get("returncode"),
        "stdout": truncate_text(probe.get("stdout", ""), 600),
        "stderr": truncate_text(probe.get("stderr", ""), 600),
    }


def summarize_mcp_result(result):
    if not isinstance(result, dict):
        return {"available": False, "returncode": None}
    text = result.get("text", "")
    stderr = result.get("stderr", "")
    return {
        "available": True,
        "returncode": 0 if text else 1,
        "stdout": truncate_text(text, 600),
        "stderr": truncate_text(stderr, 400),
    }


def summarize_mcp_commands(commands):
    if not isinstance(commands, dict):
        return {}
    return {name: summarize_mcp_result(result) for name, result in commands.items()}


def build_socraticode_scan_brief(session, target_directory, profile, scan, mode):
    commands = scan.get("commands", {}) if isinstance(scan, dict) else {}
    lines = [
        "## Real SocratiCode Run",
        "",
        f"- Mode: `{mode}`",
        f"- Search query: `{session.get('project', '').strip() or 'project structure implementation entry points'}`",
        f"- Indexed chunks: `{scan.get('indexedChunks')}`",
        f"- Runtime status: `{scan.get('status')}`",
        "",
    ]
    for name in ["index", "status", "search", "graphStatus"]:
        result = commands.get(name)
        lines.extend([
            f"### {name}",
            "",
            format_mcp_output(result, f"SocratiCode {name} output unavailable."),
            "",
        ])
    lines.extend([
        "## Semantic Samples",
        "",
        "\n".join([f"- `{path}`" for path in profile.get("semanticSamples", [])]) or "- None.",
        "",
        f"Project directory: `{target_directory}`",
    ])
    return "\n".join(lines)


def format_mcp_output(result, unavailable="Unavailable."):
    if not isinstance(result, dict):
        return unavailable
    parts = []
    if result.get("text"):
        parts.append(result["text"])
    if result.get("stderr"):
        parts.append(result["stderr"])
    return "\n".join(parts) if parts else unavailable


def build_socraticode_host_brief(session, target_directory, profile, mode):
    search_seed = session.get("project", "").strip() or "project structure and implementation plan"
    sample_text = "\n".join([f"- `{path}`" for path in profile.get("semanticSamples", [])]) or "- None."
    return "\n".join([
        "## Host-Assisted Command Brief",
        "",
        "The Flask harness cannot call SocratiCode MCP tools directly. Use these host-side calls when semantic search is required:",
        "",
        f"- `codebase_status(projectPath=\"{target_directory}\")` - verify index, watcher, and graph state.",
        f"- `codebase_index(projectPath=\"{target_directory}\", extraExtensions=\".html,.css\")` - index a new or missing project.",
        f"- `codebase_update(projectPath=\"{target_directory}\", extraExtensions=\".html,.css\")` - refresh changed files.",
        f"- `codebase_search(projectPath=\"{target_directory}\", query=\"{search_seed}\")` - search for relevant implementation context.",
        f"- `codebase_graph_build(projectPath=\"{target_directory}\", extraExtensions=\".html,.css\")` - build dependency graph when imports matter.",
        f"- `codebase_graph_status(projectPath=\"{target_directory}\")` - verify graph readiness.",
        f"- `codebase_graph_circular(projectPath=\"{target_directory}\")` - check circular dependencies.",
        "",
        f"Mode: `{mode}`",
        "",
        "Semantic-searchable sample files:",
        sample_text,
    ])


def build_socraticode_details(target_directory, profile, tool_execution, brief):
    lines = [
        "# SocratiCode",
        "",
        f"Project directory: `{target_directory}`",
        f"Tool status: `{tool_execution['status']}`",
        f"Blocking delivery: `{tool_execution['blocking']}`",
        f"Needs tool attention: `{tool_execution.get('requiresAttention', False)}`",
        f"Reason: {tool_execution.get('reason', '')}",
        "",
        "## File Profile",
        "",
        f"- Semantic/code-like files: `{profile.get('semanticFileCount', 0)}`",
        f"- Axon-indexable files: `{profile.get('axonIndexableCount', 0)}`",
        "",
        "## Semantic Samples",
        "",
        "\n".join([f"- `{path}`" for path in profile.get("semanticSamples", [])]) or "- None.",
        "",
        brief or "No SocratiCode command brief was needed.",
    ]
    return "\n".join(lines)


def run_axon_card(session_id, session, model, mode):
    if session.get("projectMode") == "new-project":
        details = "\n".join([
            "# Axon Structural Analysis",
            "",
            "Tool status: `not-needed`",
            "",
            "Axon was not run because this project does not have a project directory or code graph yet.",
        ])
        artifact = write_artifact(session_id, "axon-analysis.md", details)
        return card_result(
            "Axon",
            "Structural analysis deferred until code exists.",
            details,
            "Create or connect a project directory before running Axon.",
            artifact,
            {
                "toolExecution": {
                    "tool": "axon",
                    "status": "not-needed",
                    "blocking": False,
                    "reason": "No project directory exists yet.",
                    "requiresAttention": False,
                }
            },
        )

    target_directory = session.get("projectDirectory") if os.path.isdir(session.get("projectDirectory", "")) else PROJECT_ROOT
    profile = project_file_profile(target_directory)
    if profile["axonIndexableCount"] == 0:
        details = "\n".join([
            "# Axon Structural Analysis",
            "",
            f"Project directory: `{target_directory}`",
            "Tool status: `not-needed`",
            "Blocking delivery: `False`",
            "",
            "Axon was not run because the directory has no Axon-indexable source files.",
            "This commonly happens for HTML-only outputs where the project is still valid but Axon cannot build a useful structural graph.",
            "",
            "## Files Found",
            "",
            f"- Semantic/code-like files: `{profile['semanticFileCount']}`",
            f"- Axon-indexable files: `{profile['axonIndexableCount']}`",
            "",
            "## Sample Files",
            "",
            "\n".join([f"- `{path}`" for path in profile["semanticSamples"]]) or "- None.",
        ])
        artifact = write_artifact(session_id, "axon-analysis.md", details)
        return card_result(
            "Axon",
            "Axon skipped because this workspace has no graphable source files.",
            details,
            "Use verification and visual/source review for this workspace; add JS/Python/etc. files before relying on Axon.",
            artifact,
            {
                "toolExecution": {
                    "tool": "axon",
                    "status": "not-needed",
                    "blocking": False,
                    "reason": "No Axon-indexable source files were found.",
                    "requiresAttention": False,
                    "profile": profile,
                }
            },
        )

    scan = run_axon_project_scan(target_directory)
    commands = scan.get("commands", {}) if isinstance(scan.get("commands"), dict) else {}
    analyze = commands.get("analyze")
    status = commands.get("status")
    dead_code = commands.get("deadCode")
    tool_execution = {
        "tool": "axon",
        "status": scan.get("status", "degraded"),
        "blocking": False,
        "requiresAttention": bool(scan.get("requiresAttention")),
        "reason": scan.get("reason", "Axon structural scan completed."),
        "commands": {
            "analyze": summarize_command_result(analyze),
            "status": summarize_command_result(status),
            "deadCode": summarize_command_result(dead_code),
        },
        "runtime": summarize_axon_runtime(scan.get("runtime", {})),
    }
    summary = "Structural status and dead-code scan complete."
    checkpoint = "Review Axon's findings before refactors or impact-sensitive changes."
    if tool_execution["status"] == "degraded":
        summary = "Axon structural analysis failed and needs attention."
        checkpoint = "Repair Axon or adjust the project files, then rerun this section before relying on structural analysis."
    elif tool_execution["status"] == "unavailable":
        summary = "Axon is unavailable in this environment."
        checkpoint = "Install or repair Axon before relying on structural analysis."

    tool_execution["profile"] = profile
    details = build_axon_details(target_directory, profile, tool_execution, analyze, status, dead_code)
    artifact = write_artifact(session_id, "axon-analysis.md", details)
    return card_result(
        "Axon",
        summary,
        details,
        checkpoint,
        artifact,
        {"toolExecution": tool_execution},
    )


def build_axon_details(target_directory, profile, tool_execution, analyze, status, dead_code):
    lines = [
        "# Axon Structural Analysis",
        "",
        f"Project directory: `{target_directory}`",
        f"Tool status: `{tool_execution['status']}`",
        f"Blocking delivery: `{tool_execution['blocking']}`",
        f"Needs tool attention: `{tool_execution.get('requiresAttention', False)}`",
        f"Reason: {tool_execution.get('reason', '')}",
        "",
        "## File Profile",
        "",
        f"- Semantic/code-like files: `{profile.get('semanticFileCount', 0)}`",
        f"- Axon-indexable files: `{profile.get('axonIndexableCount', 0)}`",
        "",
        "## Axon-Indexable Samples",
        "",
        "\n".join([f"- `{path}`" for path in profile.get("axonSamples", [])]) or "- None.",
        "",
        "## Analyze",
        "",
        format_command_output(analyze, "Axon analyze unavailable."),
        "",
        "## Status",
        "",
        format_command_output(status, "Axon status unavailable."),
        "",
        "## Dead Code",
        "",
        format_command_output(dead_code, "Dead-code report unavailable."),
    ]
    return "\n".join(lines)


def build_axon_tool_execution(analyze, status, dead_code):
    commands = {
        "analyze": summarize_command_result(analyze),
        "status": summarize_command_result(status),
        "deadCode": summarize_command_result(dead_code),
    }
    if analyze is None and status is None and dead_code is None:
        return {
            "tool": "axon",
            "status": "unavailable",
            "blocking": False,
            "requiresAttention": True,
            "reason": "Axon CLI was not available.",
            "commands": commands,
        }

    failures = [
        name
        for name, result in {"analyze": analyze, "status": status, "deadCode": dead_code}.items()
        if isinstance(result, dict) and result.get("returncode") not in (0, None)
    ]
    if failures:
        return {
            "tool": "axon",
            "status": "degraded",
            "blocking": False,
            "requiresAttention": True,
            "reason": f"Axon command(s) failed: {', '.join(failures)}.",
            "commands": commands,
        }

    return {
        "tool": "axon",
        "status": "complete",
        "blocking": False,
        "requiresAttention": False,
        "reason": "Axon commands completed.",
        "commands": commands,
    }


def summarize_command_result(result):
    if not isinstance(result, dict):
        return {"available": False, "returncode": None}
    return {
        "available": True,
        "returncode": result.get("returncode"),
        "skipped": bool(result.get("skipped")),
        "reason": result.get("reason", ""),
        "stdout": truncate_text(result.get("stdout", ""), 600),
        "stderr": truncate_text(result.get("stderr", ""), 600),
    }


def run_verification_card(session_id, session, model, mode, correction=None):
    details, validation = build_verification_details(session_id, session, mode, model, correction)
    artifact = write_artifact(session_id, "verification.md", details)
    return card_result(
        "Verification",
        "Verification report generated from the actual workspace artifacts.",
        details,
        "Run or inspect the verification report and mark the section Verified or Not Verified.",
        artifact,
        {"validation": validation},
    )


def build_verification_details(session_id, session, mode, model=None, correction=None):
    context = build_verification_context(session)
    correction_block = ""
    if isinstance(correction, dict):
        user_note = str(correction.get("userNote", "")).strip()
        findings = listify(correction.get("findings"))
        fixes = listify(correction.get("fixesNeeded"))
        if user_note or findings or fixes:
            correction_block = (
                "\nThe last run of this section was marked Not Verified. Address these before passing it again:\n"
                + json.dumps({
                    "userNote": user_note,
                    "reviewerFindings": findings,
                    "reviewerFixes": fixes,
                }, indent=2)
                + "\n"
            )
    checklist = ""
    if model:
        checklist = call_ollama(model, f"""Gemma Forge Verification card.
Project: {session.get('project', '')}
Mode: {mode}
Workspace: {context.get('workspace')}
Deterministic validation:
{json.dumps(context.get('validation', {}), indent=2)}
Files found:
{json.dumps(context.get('filesFound', {}), indent=2)}
{correction_block}
Produce a short verification checklist from these actual artifacts. If auto-run is enabled, list the checks already run and any remaining manual inspection. If a correction block is present above, the checklist MUST explicitly say whether each user/reviewer item has now been satisfied.""")

    details = build_verification_report(session_id, session, mode, context, checklist)
    return details, context.get("validation", {})


def derive_verification_paths(session, workspace_dir):
    """
    Compute the list of paths the Verification card should check for, based
    on the Project Context Writer's contract:

    - Always include `artifacts/validation.json` (the deterministic check).
    - If the contract has a concrete path_pattern, derive the directory and
      list files in it that match the deliverable format. If the pattern is
      a single file, just that one.
    - For project type "code", also include README.md if it exists (it's
      conventional but not required).

    This deliberately AVOIDS the old hardcoded `styles.css / script.js /
    README.md / docs/delivery.md` list that produced misleading "missing"
    findings whenever the contract didn't promise those files.
    """
    paths = ["artifacts/validation.json"]
    context = session.get("projectContext") if isinstance(session, dict) else None
    if not isinstance(context, dict):
        return paths

    deliverable = context.get("deliverable") if isinstance(context.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    path_pattern = str(deliverable.get("path_pattern", "")).strip()
    project_type = ""
    if isinstance(context.get("project"), dict):
        project_type = str(context["project"].get("type", "")).strip().lower()

    # Tolerate range/phrase path_patterns by extracting the first path-looking
    # token (same forgiving parse Forge Flow uses).
    first_path_token = path_pattern
    if path_pattern:
        for token in re.split(r"\s+|,", path_pattern):
            if "/" in token or (fmt and token.lower().endswith("." + fmt)):
                first_path_token = token
                break

    if first_path_token:
        pattern_dir = os.path.dirname(first_path_token) or ""
        pattern_basename = os.path.basename(first_path_token)
        ext = os.path.splitext(pattern_basename)[1] or (f".{fmt}" if fmt else "")
        scan_dir = os.path.join(workspace_dir, pattern_dir) if pattern_dir else workspace_dir
        if os.path.isdir(scan_dir):
            try:
                listed = sorted(os.listdir(scan_dir))
            except OSError:
                listed = []
            for filename in listed:
                if ext and not filename.lower().endswith(ext.lower()):
                    continue
                rel = os.path.join(pattern_dir, filename) if pattern_dir else filename
                paths.append(rel.replace(os.sep, "/"))
        else:
            # Pattern looks like a single file path; just include it as-is so
            # we can report "missing" if Execution did not produce it.
            paths.append(first_path_token.replace(os.sep, "/"))

    # For software projects, README.md is conventional. We include it only
    # when project_type=="code", so SVG / report / brief deliverables don't
    # see a misleading "README.md: missing" line.
    if project_type == "code":
        paths.append("README.md")

    # Dedupe preserving order.
    seen = set()
    deduped = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def build_verification_context(session):
    project = session.get("project", "")
    workspace_dir = session.get("projectDirectory", "").strip()
    context = {
        "workspace": workspace_dir,
        "workspaceExists": bool(workspace_dir and os.path.isdir(workspace_dir)),
        "project": project,
        "filesFound": {},
        "validation": {
            "passed": False,
            "failures": ["project workspace does not exist"],
            "checkedAt": utc_now(),
        },
        "storedValidation": {},
        "snippets": {},
    }

    if not context["workspaceExists"]:
        return context

    # Contract-aware file check. The Project Context Writer's contract names
    # the exact path_pattern + format the model was asked to deliver; THAT is
    # what we check for, not a hardcoded list of "every web project ships
    # styles.css and script.js" (which created false-positive "missing"
    # findings that biased the small-model reviewer toward Not Verified).
    relevant_paths = derive_verification_paths(session, workspace_dir)
    snippet_extensions = {".html", ".htm", ".css", ".js", ".md", ".txt", ".json", ".yaml", ".yml", ".svg", ".py"}
    for relative_path in relevant_paths:
        path = os.path.join(workspace_dir, relative_path)
        exists = os.path.exists(path)
        context["filesFound"][relative_path] = exists
        if exists and os.path.isfile(path) and os.path.splitext(relative_path)[1].lower() in snippet_extensions:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    context["snippets"][relative_path] = truncate_text(f.read(), 2200)
            except OSError:
                pass

    execution_path = os.path.join(workspace_dir, "artifacts", "model-execution.json")
    if os.path.exists(execution_path):
        try:
            with open(execution_path, "r") as f:
                context["storedValidation"] = json.load(f)
        except (OSError, json.JSONDecodeError) as error:
            context["storedValidation"] = {"error": str(error)}
    context["validation"] = validate_model_authored_workspace(workspace_dir, context.get("storedValidation", {}), session)
    return context


def build_verification_report(session_id, session, mode, context, checklist):
    validation = context.get("validation", {})
    lines = [
        "# Verification",
        "",
        f"- Session: `{session_id}`",
        f"- Mode: `{mode}`",
        f"- Workspace: `{context.get('workspace')}`",
        f"- Workspace exists: `{context.get('workspaceExists')}`",
        f"- Deterministic validation passed: `{validation.get('passed')}`",
        "",
        "## Original Project Request",
        "",
        session.get("project", ""),
        "",
        "## Deterministic Artifact Check",
        "",
        json.dumps(validation, indent=2),
        "",
        "## Files Inspected",
        "",
    ]
    files_found = context.get("filesFound", {})
    if files_found:
        lines.extend([f"- `{path}`: {'found' if found else 'missing'}" for path, found in files_found.items()])
    else:
        lines.append("- No workspace files found.")

    stored_validation = context.get("storedValidation", {})
    if stored_validation:
        lines.extend([
            "",
            "## Stored Execution Validation",
            "",
            json.dumps(stored_validation, indent=2),
        ])

    snippets = context.get("snippets", {})
    if snippets:
        lines.extend(["", "## Source Snippets", ""])
        for relative_path, snippet in snippets.items():
            language = os.path.splitext(relative_path)[1].lstrip(".") or "text"
            lines.extend([
                f"### {relative_path}",
                "",
                f"```{language}",
                snippet,
                "```",
                "",
            ])

    lines.extend([
        "## Checklist",
        "",
        checklist or "- Deterministic checks above are the verification source of truth.",
    ])
    return "\n".join(lines)


def run_handoff_card(session_id, session, model, mode):
    details = call_ollama(model, f"""Gemma Forge Handoff card.
Project: {session.get('project', '')}
Recent messages: {json.dumps(session.get('messages', [])[-8:], indent=2)}

Write a concise handoff:
1. What is known
2. What has been verified
3. Open risks
4. Next action""")
    artifact = write_artifact(session_id, "handoff.md", details)
    return card_result(
        "Handoff",
        "Project handoff generated.",
        details,
        "Confirm the handoff has enough context to resume safely.",
        artifact,
    )


def run_unknown_card(session_id, session, model, mode):
    return card_result(
        "Unknown Card",
        "No runner is registered for this card.",
        "This card has no Gemma Forge action yet.",
        "Choose a different card.",
        None,
    )


def card_result(title, summary, details, checkpoint, artifact, extra=None):
    payload = {
        "title": title,
        "summary": summary,
        "details": details,
        "checkpoint": checkpoint,
        "artifact": artifact,
        "ranAt": utc_now(),
        "status": "awaiting-human",
    }
    if extra:
        payload.update(extra)
    return payload


def update_card_state(session, card_id, result):
    for card in session.get("cards", []):
        if card.get("id") == card_id:
            card["lastRun"] = result
            card["status"] = result.get("status", "awaiting-human")
            return


def find_card(session, card_id):
    for card in session.get("cards", []):
        if card.get("id") == card_id:
            return card
    return None


def write_artifact(session_id, filename, content):
    path = os.path.join(session_dir(session_id), filename)
    with open(path, "w") as f:
        f.write(content)
    return path


def run_local_command(command, timeout=1200, cwd=None):
    try:
        result = subprocess.run(
            command,
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        return {"returncode": 1, "stdout": "", "stderr": str(error)}


def skipped_command_result(reason):
    return {
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "skipped": True,
        "reason": reason,
    }


def project_file_profile(project_directory, max_depth=5, sample_limit=20):
    profile = {
        "exists": bool(project_directory and os.path.isdir(project_directory)),
        "axonIndexableCount": 0,
        "semanticFileCount": 0,
        "axonSamples": [],
        "semanticSamples": [],
    }
    if not profile["exists"]:
        return profile

    root_path = os.path.abspath(project_directory)
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [name for name in dirs if name not in IGNORED_CODE_DIRS]
        relative_root = os.path.relpath(root, root_path)
        depth = 0 if relative_root == "." else relative_root.count(os.sep) + 1
        if depth > max_depth:
            dirs[:] = []
            continue

        for filename in files:
            extension = os.path.splitext(filename)[1].lower()
            relative_path = os.path.relpath(os.path.join(root, filename), root_path)
            if extension in SEMANTIC_INDEXABLE_EXTENSIONS:
                profile["semanticFileCount"] += 1
                if len(profile["semanticSamples"]) < sample_limit:
                    profile["semanticSamples"].append(relative_path)
            if extension in AXON_INDEXABLE_EXTENSIONS:
                profile["axonIndexableCount"] += 1
                if len(profile["axonSamples"]) < sample_limit:
                    profile["axonSamples"].append(relative_path)
    return profile


def format_command_output(result, unavailable="Unavailable."):
    if not isinstance(result, dict):
        return unavailable
    if result.get("skipped"):
        return f"Skipped: {result.get('reason', 'Command was not run.')}"
    parts = []
    if result.get("stdout"):
        parts.append(result["stdout"])
    if result.get("stderr"):
        parts.append(result["stderr"])
    return "\n".join(parts) if parts else "No output."


def execute_model_authored_project(session_id, session, model, workspace_dir, review=None):
    fallback = {
        "summary": "Gemma did not return a valid file payload.",
        "files": [],
        "commands": [],
        "notes": ["Execution failed before files could be written."],
        "verification": ["Rerun Project Execution after checking the local model."],
    }
    skill_context = prepare_workspace_skill_context(workspace_dir, session)
    research = prepare_workspace_research(workspace_dir, session)
    payload, raw, transport = call_ollama_execution_payload(
        model,
        build_model_execution_prompt(session, workspace_dir, review, skill_context, research),
        fallback,
    )
    if not isinstance(payload, dict):
        payload = fallback

    files, rejected = normalize_model_files(payload.get("files", []))
    written = []
    for item in files:
        path = write_project_file(workspace_dir, item["path"], item["content"])
        written.append({
            "path": item["path"],
            "sha256": file_sha256(path),
            "bytes": os.path.getsize(path),
        })

    metadata = {
        "model": model,
        "modelAuthored": True,
        "requestedProject": session.get("project", ""),
        "summary": payload.get("summary", ""),
        "files": written,
        "rejectedFiles": rejected,
        "commands": listify(payload.get("commands")),
        "notes": listify(payload.get("notes")),
        "verification": listify(payload.get("verification")),
        "skillContext": {
            "root": skill_context.get("root"),
            "staged": [
                {
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "requested": item.get("requested"),
                }
                for item in skill_context.get("staged", [])
            ],
        },
        "raw": truncate_text(raw, 5000),
        "transport": transport,
        "createdAt": utc_now(),
    }
    write_project_file(workspace_dir, "artifacts/model-execution.json", json.dumps(metadata, indent=2))

    # Auto-screenshot any HTML deliverable so the handoff + verification card
    # has visual proof the page actually renders. Best-effort; failures here
    # are logged but never block validation.
    screenshots = capture_html_screenshots(workspace_dir, written) if tool_screenshot.is_available() else []
    metadata["screenshots"] = screenshots
    if screenshots:
        write_project_file(workspace_dir, "artifacts/model-execution.json", json.dumps(metadata, indent=2))

    validation = validate_model_authored_workspace(workspace_dir, metadata, session)
    write_project_file(workspace_dir, "artifacts/validation.json", json.dumps(validation, indent=2))

    return {
        "summary": metadata["summary"],
        "files": written,
        "rejectedFiles": rejected,
        "commands": metadata["commands"],
        "notes": metadata["notes"],
        "verification": metadata["verification"],
        "validation": validation,
        "screenshots": screenshots,
        "metadata": metadata,
    }


def capture_html_screenshots(workspace_dir, written_files):
    """Best-effort post-Execution screenshot capture for every HTML file the
    model produced. Returns a list of artifact dicts (or empty list)."""
    shots = []
    if not isinstance(written_files, list):
        return shots
    for item in written_files:
        if not isinstance(item, dict):
            continue
        rel_path = str(item.get("path", "")).strip()
        if not rel_path.lower().endswith((".html", ".htm")):
            continue
        full_path = os.path.join(workspace_dir, rel_path)
        if not os.path.isfile(full_path):
            continue
        try:
            artifact = tool_screenshot.screenshot_into_workspace(
                workspace_dir, full_path, mode="local_html",
            )
            artifact["of"] = rel_path
            shots.append(artifact)
        except Exception as error:
            log_error("tool-screenshot", f"auto-screenshot failed for {rel_path}", error)
    return shots


def build_research_context_block(research):
    """Render the research dict produced by prepare_workspace_research as a
    block the Execution prompt can read. Empty string when nothing fetched."""
    if not isinstance(research, dict):
        return ""
    fetched = research.get("fetched") or []
    if not fetched:
        reason = research.get("skipped_reason") or ""
        if reason:
            return f"\nResearch step skipped: {reason}\n"
        return ""
    lines = [
        "",
        "Harness-fetched research (already on disk via scrapling — cite by path, do NOT claim you fetched these yourself).",
        "The harness picks the fastest scrapling mode that works and escalates when needed:",
        "  - request  : fast HTTP GET, no JS rendered. Best for plain HTML / Markdown pages.",
        "  - browser  : Playwright headless, JS rendered. Used when request returns thin content.",
        "  - stealth  : anti-bot bypass (Cloudflare Turnstile, etc). Used when browser is blocked.",
        "Each artifact below names the mode that produced its content.",
        "",
    ]
    for item in fetched:
        path = item.get("path") or "(no path)"
        title = item.get("title") or "(no title)"
        status = item.get("status")
        url = item.get("url") or "(no url)"
        ok = item.get("ok")
        mode = item.get("mode") or "?"
        marker = "ok" if ok else "FAIL"
        lines.append(f"- [{marker} {status} via {mode}] {path}  —  {title}  ({url})")
    lines.append("")
    return "\n".join(lines)


def prepare_workspace_research(workspace_dir, session):
    """
    If the user's project text contains URLs AND web_browse is part of the
    contract's capabilities_required, the harness fetches them up front using
    scrapling. The fetched pages land at <workspace>/research/<slug>.md and
    a manifest is returned so the Execution prompt can list them.
    """
    if not tool_browse.is_available():
        return {"fetched": [], "skipped_reason": "scrapling not installed"}

    project_text = session.get("project", "") if isinstance(session, dict) else ""
    context = session.get("projectContext") if isinstance(session, dict) else None
    caps_required = (
        context.get("capabilities_required")
        if isinstance(context, dict) and isinstance(context.get("capabilities_required"), list)
        else []
    )
    wants_browse = any(c in {"web_browse", "web_fetch"} for c in caps_required)
    urls = tool_browse.extract_urls(project_text or "", limit=8)

    if not wants_browse and not urls:
        return {"fetched": [], "skipped_reason": "no browse capability required and no URLs in request"}
    if not urls:
        return {"fetched": [], "skipped_reason": "browse capability required but no URLs in user text"}

    fetched = []
    for url in urls:
        emit_event("browse", f"fetch {url}", mode="auto")
        try:
            result = tool_browse.fetch_url(url, mode="auto")
            artifact = tool_browse.write_research_artifact(workspace_dir, result)
            fetched.append(artifact)
            emit_event("browse", f"{url} ← {result.get('mode')} status={result.get('status')} chars={len(result.get('text') or '')}",
                       ok=result.get("ok"))
        except Exception as error:  # broad — scrapling can raise many ad-hoc types
            log_error("tool-browse", f"fetch_url failed for {url}", error)
            emit_event("error", f"browse failed: {url} — {error}")
            fetched.append({"url": url, "ok": False, "error": str(error)})
    return {"fetched": fetched, "skipped_reason": None}


def build_execution_context_block(session):
    context = session.get("projectContext") if isinstance(session, dict) else None
    raw_yaml = session.get("projectContextRaw") if isinstance(session, dict) else None
    if not isinstance(context, dict) or not raw_yaml:
        return ""

    deliverable = context.get("deliverable") if isinstance(context.get("deliverable"), dict) else {}
    anti_deflection = str(deliverable.get("anti_deflection", "")).strip()
    fmt = str(deliverable.get("format", "")).strip()
    path_pattern = str(deliverable.get("path_pattern", "")).strip()
    count = deliverable.get("count")
    acceptance = context.get("acceptance") if isinstance(context.get("acceptance"), list) else []

    example_path = path_pattern or "output/file.txt"
    if count and isinstance(count, int) and count > 1 and "NN" in example_path:
        example_path = example_path.replace("NN", "01")

    parts = [
        "",
        "PROJECT CONTEXT CONTRACT (binding spec for this run):",
        "```",
        raw_yaml.strip(),
        "```",
        "",
        "How to satisfy the contract:",
        f"- deliverable.format = `{fmt}` — produce files of this format only.",
        f"- deliverable.path_pattern = `{path_pattern}` — every file you write must match this pattern.",
    ]
    if count:
        parts.append(f"- deliverable.count = `{count}` — write exactly this many files of the format.")

    parts.extend([
        "",
        "OUTPUT FORMAT — read this carefully, follow it exactly:",
        "",
        "Wrap EACH file in literal text delimiters. These are the delimiters, NOT a markdown",
        "code fence. Do NOT use triple-backtick code fences. Do NOT write ```gforge_file_block.",
        "Do NOT use any JSON envelope. Emit raw text in this exact shape:",
        "",
        f"<<<GFORGE_FILE:{example_path}>>>",
        f"<the complete {fmt} file content goes here, with real newlines, no escaping>",
        "<<<END_GFORGE_FILE>>>",
        "",
        "If the contract requires more than one file, repeat the same delimiter pair for",
        f"each file. The text `<<<GFORGE_FILE:` and `<<<END_GFORGE_FILE>>>` are the only",
        "things the harness's parser recognizes. Everything outside the delimiters is ignored",
        "except the SUMMARY: / NOTES: / VERIFICATION: sections you may add at the end.",
    ])

    if anti_deflection:
        parts.extend(["", "ANTI-DEFLECTION ANCHOR (read twice before responding):", anti_deflection])

    parts.extend([
        "",
        "DELIVERABLE-FIRST RULE:",
        "- The contract above defines the PRIMARY deliverable. You MUST produce the actual files",
        "  matching deliverable.format and deliverable.path_pattern — not a plan, brief, or",
        "  description of those files. A markdown 'plan to make 10 SVGs' does NOT satisfy a",
        "  contract whose deliverable.format is svg with count 10.",
        "- If the user mentioned prep steps (research, learn, review, gather), treat them as",
        "  enabling work that informs the primary deliverable, not as separate outputs. Use any",
        "  Harness-fetched research listed below as context for the deliverable.",
        "- Write the real file content. Do NOT write '# Outline' / '# Plan' / '# Research summary'",
        "  in place of the actual deliverable.",
    ])

    partial = bool(deliverable.get("partial"))
    scope = str(deliverable.get("scope", "")).strip()
    caps_req = context.get("capabilities_required") if isinstance(context.get("capabilities_required"), list) else []
    _, cannot_now = harness_capabilities()
    cannot = [c for c in (str(c).strip() for c in caps_req) if c in cannot_now]
    # Only show the partial-scope warning when there is a REAL capability gap.
    # A request being multi-step is not a gap. Bare partial:true with no missing
    # capabilities used to mislead the model into deflecting.
    if cannot:
        parts.extend([
            "",
            "PARTIAL SCOPE WARNING (harness capability gap):",
            f"- Scope you must produce: {scope or 'in-workspace files only'}",
            "- The following capabilities the user implied are NOT available; do NOT claim you performed them:",
        ])
        for cap in cannot:
            parts.append(f"  * {cap}")
        parts.extend([
            "- In your SUMMARY / NOTES / VERIFICATION sections you MUST explicitly state which",
            "  parts of the request were NOT performed and why, citing the missing capability.",
            "- Do NOT write 'installed', 'cloned', 'researched', 'integrated', or 'configured' for",
            "  anything the harness cannot do. The harness will validate your claims against disk.",
        ])
        parts.append(
            "- STILL produce the primary deliverable for the part the harness CAN do. Do not "
            "downgrade the deliverable to a plan or description."
        )

    if acceptance:
        parts.extend(["", "Acceptance checks the harness will run after you respond:"])
        parts.extend(f"- {item}" for item in acceptance)
    parts.append("")
    return "\n".join(parts)


def build_model_execution_prompt(session, workspace_dir, review=None, skill_context=None, research=None):
    review_block = ""
    if review:
        review_payload = {
            "summary": review.get("summary", ""),
            "findings": listify(review.get("findings")),
            "fixesNeeded": listify(review.get("fixesNeeded")),
        }
        validation_failures = listify(review.get("validationFailures"))
        if validation_failures:
            review_payload["validationFailures"] = validation_failures
        user_note = str(review.get("userNote", "")).strip()
        user_note_section = ""
        if user_note:
            user_note_section = f"""

USER CORRECTION (the human ran Not Verified and typed this — treat it as the authoritative steer):
> {user_note}
"""
        review_block = f"""
Previous review failed. You are re-running this section to fix the issues below.

Reviewer findings (structured):
{json.dumps(review_payload, indent=2)}
{user_note_section}
Address every item in fixesNeeded AND the user's correction. Do NOT repeat the previous output verbatim — produce a new payload that satisfies the original contract AND the corrections above.
"""
    skill_block = (skill_context or {}).get("prompt", "No Gemma Forge skills are staged for this workspace.")

    context_block = build_execution_context_block(session)
    research_block = build_research_context_block(research)

    return f"""You are Gemma Forge Project Execution.

You are the selected local Gemma model. You must do the user's requested task yourself.
Do not assume a built-in demo task. Do not return placeholder files.
{context_block}
Original project request (raw, for reference only — follow the contract above):
{session.get('project', '')}

Workspace root:
{workspace_dir}
{review_block}

Gemma Forge skill context:
{skill_block}
{research_block}
After your file blocks you may optionally add these sections (each prefix in ALL CAPS at the start of a line):

SUMMARY:
one or two sentences about what you produced.

NOTES:
- short implementation notes (optional)

VERIFICATION:
- specific checks that prove the contract was satisfied (optional)

Rules:
- Every file path must be relative to the workspace root and must match deliverable.path_pattern from the contract.
- Do not use absolute paths or parent directory traversal.
- Do not write into `.gforge/`; it is reserved for harness-provided support context.
- Include complete file contents, not patches.
- Do NOT wrap files in markdown code fences. Use only the `<<<GFORGE_FILE:...>>>` / `<<<END_GFORGE_FILE>>>` delimiters shown in the contract above.
"""


def normalize_model_files(files):
    normalized = []
    rejected = []
    if not isinstance(files, list):
        return normalized, [{"path": "", "reason": "files was not a list"}]

    for item in files:
        if not isinstance(item, dict):
            rejected.append({"path": "", "reason": "file item was not an object"})
            continue
        raw_path = str(item.get("path", "")).strip()
        content = item.get("content")
        safe_path = safe_workspace_relative_path(raw_path)
        if not safe_path:
            rejected.append({"path": raw_path, "reason": "unsafe or empty relative path"})
            continue
        if not isinstance(content, str) or not content.strip():
            rejected.append({"path": raw_path, "reason": "content was empty"})
            continue
        normalized.append({"path": safe_path, "content": content})

    return normalized, rejected


def safe_workspace_relative_path(path):
    if not path or os.path.isabs(path):
        return None
    normalized = os.path.normpath(path).replace("\\", "/")
    if normalized in {".", ""} or normalized.startswith("../") or normalized == "..":
        return None
    if normalized == ".gforge" or normalized.startswith(".gforge/"):
        return None
    return normalized


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


CLAIM_PATTERNS = [
    # (capability, regex, "what to check on disk")

    # Repo-shaped: explicit URL or owner/name slash form.
    ("git_clone", re.compile(r"https?://(?:github|gitlab|bitbucket)\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE), "repo_clone"),
    ("git_clone", re.compile(r"\b(install|cloned?|pulled|downloaded|integrated|set\s+up)\s+(the\s+)?(?:repo|repository|tool|library|package|generator)[^.\n]*?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE), "repo_clone"),

    # Generic "integrated / set up the external tool" — small models phrase it this way.
    ("git_clone", re.compile(r"\bintegrated\s+(the\s+)?(external|github|cloned|installed|provided)\s+(tool|repo|repository|library|package|generator)(?:'s|s)?\b", re.IGNORECASE), "repo_clone"),
    ("git_clone", re.compile(r"\bset\s+up\s+(the\s+)?(external|github|provided)\s+(tool|repo|repository|library|package|generator)\b", re.IGNORECASE), "repo_clone"),
    ("git_clone", re.compile(r"\butili[sz]ed?\s+(the\s+)?(external|provided)\s+(tool|repo|repository|library|package|generator)\b", re.IGNORECASE), "repo_clone"),
    ("git_clone", re.compile(r"\b(successfully\s+)?(installed|cloned|downloaded|integrated)\s+(the\s+)?external\s+(tool|repo|repository|library|package|generator)\b", re.IGNORECASE), "repo_clone"),

    # Hyphenated-identifier form: "installed Custom-SVG-Logo-Generator" or "installed foo-bar from baz".
    ("git_clone", re.compile(r"\b(installed|cloned|downloaded|integrated|set\s+up)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_.]*-[A-Za-z][A-Za-z0-9_.-]*)\b", re.IGNORECASE), "repo_clone"),

    # Web research / browse claims.
    ("web_browse", re.compile(r"\bresearch(ed)?\s+(\d+)\s+(sites?|pages?|articles?|sources?|references?)", re.IGNORECASE), "research_artifact"),
    ("web_browse", re.compile(r"\b(gathered|reviewed|browsed|searched|consulted)\s+(\d+)\s+(sites?|sources?|references?|pages?|urls?)", re.IGNORECASE), "research_artifact"),
    ("web_browse", re.compile(r"\b(visited|fetched|scraped)\s+(\d+\s+)?(websites?|pages?|urls?)", re.IGNORECASE), "research_artifact"),

    # Skill-author claims.
    ("skill_author", re.compile(r"\b(created?|authored?|built|wrote)\s+(a\s+)?(?:new\s+)?skill\b(?:[^.\n]*?(?:called|named)\s+[\"']?([A-Za-z0-9_.-]+))?", re.IGNORECASE), "skill_bundle"),
    ("skill_author", re.compile(r"\badded?\s+(a\s+)?new\s+skill\s+(?:called|named)\s+[\"']?([A-Za-z0-9_.-]+)", re.IGNORECASE), "skill_bundle"),

    # Shell exec / installer claims.
    ("shell_exec", re.compile(r"\b(ran|executed|invoked)\s+(the\s+|that\s+)?(?:command|script|installer|build)\b", re.IGNORECASE), "command_log"),
    ("install_package", re.compile(r"\b(installed|added)\s+(the\s+)?(?:dependency|package|module|library)\s+([A-Za-z0-9_.@/-]+)", re.IGNORECASE), "package_evidence"),
    ("install_package", re.compile(r"\b(npm|pip|brew|apt|pnpm|yarn|cargo)\s+(install|add)\b", re.IGNORECASE), "package_evidence"),

    # External API calls.
    ("external_api", re.compile(r"\b(called|invoked|hit|queried)\s+(the\s+)?(?:openai|anthropic|gemini|nano\s*banana|midjourney|dall-?e|stable\s+diffusion)\s+api\b", re.IGNORECASE), "external_call_evidence"),
    ("external_api", re.compile(r"\bgenerated\s+(an?\s+)?(photo|raster\s+image|jpeg|png|jpg)\b", re.IGNORECASE), "external_call_evidence"),

    # Send-message claims.
    ("send_message", re.compile(r"\b(sent|posted|emailed)\s+(an?\s+)?(email|message|notification|slack|discord)\b", re.IGNORECASE), "message_evidence"),

    # Deploy claims.
    ("deploy", re.compile(r"\b(deployed|published|pushed)\s+(to\s+)?(npm|pypi|github|netlify|vercel|production|main|master)\b", re.IGNORECASE), "deploy_evidence"),
]


def collect_claim_text(metadata):
    parts = []
    if isinstance(metadata, dict):
        for key in ("summary",):
            val = metadata.get(key)
            if isinstance(val, str):
                parts.append(val)
        for key in ("notes", "verification", "commands"):
            val = metadata.get(key)
            if isinstance(val, list):
                parts.extend(str(v) for v in val)
            elif isinstance(val, str):
                parts.append(val)
    return "\n".join(parts)


def validate_claims_against_disk(claim_text, capabilities_required, workspace_dir=None):
    """
    Walk known claim patterns. For each match, emit a failure UNLESS:
      - the capability is in HARNESS_CAN_DO (we can do it; trust the claim)
      - OR the model explicitly populated `capabilities_required` with this entry
        AND there is concrete evidence on disk (we don't synthesize evidence checks
        for every capability; the gating happens upstream via partial scope).
    The cheap, high-value cases — git_clone / skill_author / web_browse — get
    real disk checks here.
    """
    failures = []
    seen = set()
    if not claim_text:
        return failures
    can_now, _ = harness_capabilities()
    can_now_set = set(can_now)
    for capability, pattern, evidence_kind in CLAIM_PATTERNS:
        for match in pattern.finditer(claim_text):
            if capability in can_now_set:
                continue
            # Honest disclaimers like "was not performed", "lacks the capability"
            # should never be flagged as fabrications.
            if claim_in_negation_context(claim_text, match.span()):
                continue
            # If the matched URL has a real research/<slug>.md artifact on disk,
            # treat the mention as substantiated.
            quote = match.group(0)
            m_url = re.search(r"https?://[^\s,)>'\"]+", quote)
            if m_url and workspace_dir and url_already_fetched(workspace_dir, m_url.group(0).rstrip(".,;:)>]'\"")):
                continue
            evidence_ok, detail = check_claim_evidence(evidence_kind, match, claim_text)
            if evidence_ok:
                continue
            # Dedupe identical fabrication quotes — the same URL is often repeated
            # across summary + notes + verification, but a single flag is enough.
            dedupe_key = (capability, quote.strip().lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            failures.append(
                f"Fabricated-claim guard: model said \"{quote[:160]}\" but the harness "
                f"cannot `{capability}` and there is no on-disk evidence ({detail}). "
                "Remove the claim or shrink scope honestly."
            )
    return failures


GENERIC_NON_EVIDENCE_TOKENS = {
    "tool", "tools", "repo", "repos", "repository", "repositories",
    "library", "libraries", "package", "packages", "module", "modules",
    "generator", "generators", "external", "the", "this", "that",
    "installed", "cloned", "downloaded", "integrated", "successfully",
    "setup", "instructions", "instruction",
}


# When one of these phrases appears within ±150 chars of a claim match, treat
# the claim as honestly disclaimed rather than fabricated. Small models often
# correctly say "the harness could not install X" — we must not flag that.
NEGATION_CONTEXT_PATTERNS = [
    re.compile(r"\b(?:not|never|cannot|can\s?not|can'?t|could\s?not|couldn'?t|wasn'?t|was\s+not|did\s?not|didn'?t)\s+(?:performed|done|executed|completed|installed|cloned|run|invoked|created|authored|built|fetched|researched|integrated|contacted|reached)\b", re.IGNORECASE),
    re.compile(r"\b(?:lacks?|missing|without|absent)\s+(?:the\s+)?(?:capability|capabilities|ability|tool|tools|permission)\b", re.IGNORECASE),
    re.compile(r"\b(?:was|were|is|are)\s+(?:not\s+performed|blocked|skipped|deferred|bypassed)\b", re.IGNORECASE),
    re.compile(r"\bunable\s+to\b", re.IGNORECASE),
    re.compile(r"\b(?:harness|environment|system)\s+(?:cannot|lacks?|could\s?not)\b", re.IGNORECASE),
    re.compile(r"\bbypass(?:ed|ing)?\s+(?:due\s+to|because)\b", re.IGNORECASE),
    re.compile(r"\b(?:dependency|requirement)\s+on\s+(?:external\s+)?(?:tool|installation|skill|api)\s+(?:was|were|is)\s+(?:bypassed|skipped|not\s+performed|blocked)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+performed\b", re.IGNORECASE),
    re.compile(r"\bcapability\s+limitations?\b", re.IGNORECASE),
    re.compile(r"\bin\s+(?:lieu|absence|stead)\s+of\b", re.IGNORECASE),
]


def claim_in_negation_context(claim_text, match_span, window=150):
    if not claim_text or not match_span:
        return False
    start, end = match_span
    snippet = claim_text[max(0, start - window):min(len(claim_text), end + window)]
    return any(pat.search(snippet) for pat in NEGATION_CONTEXT_PATTERNS)


def url_already_fetched(workspace_dir, url):
    """If <workspace>/research/<slug>.md exists for this URL, the model's
    mention of the URL is backed by a real on-disk artifact."""
    if not url or not workspace_dir:
        return False
    try:
        slug = tool_browse.url_slug(url)
    except Exception:
        return False
    research_path = os.path.join(workspace_dir, "research", f"{slug}.md")
    return os.path.isfile(research_path)


def check_claim_evidence(kind, match, claim_text):
    """
    Best-effort filesystem check that a load-bearing claim has evidence.
    Returns (ok, detail). Errs on the side of returning False (fabrication
    suspected) — generic words like 'tool', 'library', 'repo' are NEVER
    treated as evidence tokens.
    """
    home = os.path.expanduser("~")
    if kind == "repo_clone":
        tail = match.group(0)
        token = None
        m_url = re.search(r"https?://(?:github|gitlab|bitbucket)\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", tail, re.IGNORECASE)
        if m_url:
            token = m_url.group(1).split("/")[-1]
        else:
            tokens = re.findall(r"([A-Za-z0-9][A-Za-z0-9_.-]{3,})", tail)
            # Prefer a hyphenated proper noun (like "Custom-SVG-Logo-Generator").
            # Drop generic words. If nothing concrete remains, that's the signal
            # this is a fabrication.
            concrete = [t for t in tokens if t.lower() not in GENERIC_NON_EVIDENCE_TOKENS]
            hyphenated = [t for t in concrete if "-" in t]
            token = (hyphenated[-1] if hyphenated else (concrete[-1] if concrete else None))
        if not token:
            return False, "claim names no concrete tool/repo identifier; only generic words like 'tool' or 'library'"
        for root in (
            os.path.expanduser("~/Projects"),
            os.path.expanduser("~/.gforge"),
            "/tmp",
            os.path.expanduser("~/Downloads"),
            home,
        ):
            if not os.path.isdir(root):
                continue
            try:
                entries = os.listdir(root)
            except OSError:
                continue
            for entry in entries:
                if token.lower() in entry.lower():
                    full = os.path.join(root, entry)
                    if os.path.isdir(full):
                        return True, f"directory match at {full}"
        return False, f"no directory matching `{token}` found"

    if kind == "skill_bundle":
        m_name = None
        groups = match.groups()
        skill_verbs = {"created", "create", "authored", "author", "built", "wrote", "write", "added", "add", "made", "make", "skill", "new", "called", "named"}
        for g in groups:
            if not g or not isinstance(g, str):
                continue
            candidate = g.strip().strip(".,;:'\"")
            if not candidate or candidate.lower() in skill_verbs:
                continue
            if candidate.lower() in GENERIC_NON_EVIDENCE_TOKENS:
                continue
            if not re.match(r"^[A-Za-z0-9_.-]{2,}$", candidate):
                continue
            m_name = candidate
            break
        if not m_name:
            return False, "claim says a skill was created but no concrete skill name is given"
        for root in (
            os.path.join(GFORGE_DATA_ROOT, "skills"),
            os.path.join(GFORGE_HOME, "skills"),
            os.path.join(PROJECT_ROOT, "skills"),
        ):
            if not os.path.isdir(root):
                continue
            candidate = os.path.join(root, normalize_skill_key(m_name))
            if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "SKILL.md")):
                return True, f"skill exists at {candidate}"
        return False, f"no skill directory matching `{m_name}` was created"

    if kind == "research_artifact":
        # Look for any markdown research artifact with >= N citations
        try:
            n = int(match.group(2))
        except (ValueError, IndexError, TypeError):
            n = 1
        # We don't know which workspace dir to look in here without
        # threading it through; settle for the cheap "no research file exists
        # anywhere named research/sources/citations" check via the claim text itself.
        return False, f"harness has no web-fetch tool; claim of researching {n} sources cannot be substantiated"

    if kind in ("command_log", "package_evidence", "external_call_evidence", "message_evidence", "deploy_evidence"):
        return False, f"harness cannot {kind.replace('_', ' ')}; no tool runtime is present"

    return False, f"unhandled claim evidence kind: {kind}"


def validate_model_authored_workspace(workspace_dir, metadata, session):
    failures = []
    files = metadata.get("files", []) if isinstance(metadata, dict) else []
    transport = metadata.get("transport") if isinstance(metadata, dict) else None
    transport_status = transport.get("status") if isinstance(transport, dict) else None

    if transport_status and transport_status != "ok":
        failures.append(transport_failure_message(transport))
    elif not files:
        failures.append("model-authored execution returned no writable files")

    project_context = session.get("projectContext") if isinstance(session, dict) else {}
    capabilities_required = (
        project_context.get("capabilities_required")
        if isinstance(project_context, dict) and isinstance(project_context.get("capabilities_required"), list)
        else []
    )
    claim_text = collect_claim_text(metadata)
    claim_failures = validate_claims_against_disk(claim_text, capabilities_required, workspace_dir=workspace_dir)
    failures.extend(claim_failures)

    for item in files:
        relative_path = item.get("path", "")
        safe_path = safe_workspace_relative_path(relative_path)
        if not safe_path:
            failures.append(f"unsafe file path in execution metadata: {relative_path}")
            continue
        path = os.path.join(workspace_dir, safe_path)
        if not os.path.exists(path):
            failures.append(f"missing model-authored file: {safe_path}")
            continue
        expected_sha = item.get("sha256")
        actual_sha = file_sha256(path)
        if expected_sha and expected_sha != actual_sha:
            failures.append(f"file changed after model-authored write: {safe_path}")

    authenticity = {
        "model": metadata.get("model") if isinstance(metadata, dict) else session.get("model", DEFAULT_MODEL),
        "source": "model-authored-execution",
        "modelAuthored": bool(metadata.get("modelAuthored")) if isinstance(metadata, dict) else False,
        "rule": "Only the selected local Gemma model completing the requested task through the harness counts as a real verified result.",
    }
    if not authenticity["modelAuthored"]:
        failures.append("authenticity gate failed: no model-authored execution metadata was found")

    result_payload = {
        "passed": not failures,
        "failures": failures,
        "authenticity": authenticity,
        "fileCount": len(files),
        "transport": transport if isinstance(transport, dict) else None,
        "checkedAt": utc_now(),
    }
    emit_event(
        "validation",
        f"validation {'passed' if not failures else 'FAILED'} ({len(files)} files)",
        passed=bool(not failures),
        failures=len(failures),
    )
    return result_payload


def transport_failure_message(transport):
    status = transport.get("status", "unknown")
    model = transport.get("model", "")
    timeout_seconds = transport.get("timeoutSeconds")
    elapsed_ms = transport.get("elapsedMs")
    attempts = transport.get("attempts")
    if status == "timeout":
        return (
            f"Ollama request timed out after {timeout_seconds}s for `{model}`; "
            "the model never returned a payload. This is a transport failure, "
            "not a schema or file-writing failure."
        )
    if status == "unreachable":
        return (
            f"Ollama at localhost:11434 was unreachable for `{model}` after "
            f"{attempts or 1} attempt(s). Confirm `ollama serve` is running."
        )
    if status == "empty":
        return (
            f"Ollama returned an empty response for `{model}` in {elapsed_ms}ms. "
            "The model produced no tokens — check the prompt size and num_predict budget."
        )
    if status == "http_error":
        error_text = transport.get("error") or "unknown HTTP error"
        return f"Ollama HTTP error for `{model}`: {error_text}"
    return f"Ollama transport failure ({status}) for `{model}`"


def build_model_execution_report(workspace_dir, execution):
    validation = execution.get("validation", {})
    metadata = execution.get("metadata", {}) if isinstance(execution.get("metadata"), dict) else {}
    transport = metadata.get("transport") if isinstance(metadata.get("transport"), dict) else validation.get("transport")
    transport_lines = ["- No transport telemetry recorded."]
    if isinstance(transport, dict):
        transport_lines = [
            f"- Status: `{transport.get('status', 'unknown')}`",
            f"- Model: `{transport.get('model', '')}`",
            f"- Elapsed: `{transport.get('elapsedMs', 0)} ms`",
            f"- Attempts: `{transport.get('attempts', 1)}`",
            f"- Timeout: `{transport.get('timeoutSeconds', 0)} s`",
        ]
        if transport.get("error"):
            transport_lines.append(f"- Error: `{transport.get('error')}`")
    screenshots = execution.get("screenshots") or []
    screenshot_lines = []
    if screenshots:
        screenshot_lines = ["", "## Screenshots (auto-captured)", ""]
        for shot in screenshots:
            if not isinstance(shot, dict):
                continue
            ok = "ok" if shot.get("ok") else "FAIL"
            of = shot.get("of") or "(target)"
            path = shot.get("path") or "(no path)"
            size = shot.get("bytes") or 0
            ms = shot.get("elapsed_ms") or 0
            screenshot_lines.append(f"- [{ok}] of `{of}` → `{path}` ({size} bytes, {ms} ms)")

    return "\n".join([
        "# Project Execution",
        "",
        f"- Workspace: `{workspace_dir}`",
        f"- Model-authored files: `{len(execution.get('files', []))}`",
        f"- Validation passed: `{validation.get('passed')}`",
        "",
        "## Ollama Transport",
        "",
        *transport_lines,
        "",
        "## Summary",
        "",
        execution.get("summary", ""),
        "",
        "## Files Written",
        "",
        "\n".join([f"- `{item.get('path')}` ({item.get('bytes')} bytes)" for item in execution.get("files", [])]) or "- None.",
        "",
        "## Rejected Files",
        "",
        "\n".join([f"- `{item.get('path')}`: {item.get('reason')}" for item in execution.get("rejectedFiles", [])]) or "- None.",
        *screenshot_lines,
        "",
        "## Verification Suggested By Gemma",
        "",
        "\n".join([f"- {item}" for item in execution.get("verification", [])]) or "- None provided.",
        "",
        "## Validation",
        "",
        json.dumps(validation, indent=2),
    ])


def write_project_file(root, relative_path, content):
    path = os.path.join(root, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def activate_post_execution_cards(session):
    project_directory = session.get("projectDirectory", "")
    has_code = directory_has_code(project_directory)
    workspace_exists_now = bool(project_directory) and os.path.isdir(project_directory)
    for card in session.get("cards", []):
        # Forge Flow may have run early with a "Workspace Pending" artifact.
        # If Execution has now materialised a real workspace, give Forge Flow
        # a chance to re-orient against it.
        if card.get("id") == "forge-flow":
            prev_status = card.get("status")
            if prev_status in {"pending", "inactive"}:
                card["status"] = "active"
                card["summary"] = "Orient on the model-authored project directory and verify readiness."
            elif prev_status == "complete" and workspace_exists_now:
                last_run = card.get("lastRun") if isinstance(card.get("lastRun"), dict) else None
                was_pending_artifact = bool(last_run and "Workspace Pending" in (last_run.get("details") or ""))
                if was_pending_artifact:
                    card["status"] = "active"
                    card["summary"] = "Re-orient on the now-created workspace before downstream cards run."
        if card.get("id") == "socraticode" and card.get("status") in {"inactive", "pending", "conditional"}:
            card["status"] = "active" if has_code else "inactive"
            card["summary"] = (
                "Map the model-authored project for semantic review."
                if has_code
                else "Hidden because the model-authored output does not appear to contain code yet."
            )
        if card.get("id") == "axon" and card.get("status") in {"inactive", "pending", "conditional"}:
            card["status"] = "active" if has_code else "inactive"
            card["summary"] = (
                "Run structural analysis against the model-authored project."
                if has_code
                else "Hidden because the model-authored output does not appear to contain code yet."
            )


def create_session_record(
    sessions,
    project,
    model,
    requested_id=None,
    has_project_directory=None,
    project_directory="",
):
    ensure_storage()
    session_id = requested_id or f"session_{int(time.time() * 1000)}"
    while session_id in sessions:
        session_id = f"session_{int(time.time() * 1000)}"

    project_mode = "existing-directory" if has_project_directory else "new-project"
    if has_project_directory is None:
        project_mode = "unknown"

    sessions[session_id] = {
        "project": project,
        "model": model,
        "mode": "work-harness",
        "projectMode": project_mode,
        "projectDirectory": project_directory.strip(),
        "createdAt": utc_now(),
        "messages": [
            {"role": "agent", "content": "What project are we planning?"},
            {"role": "user", "content": project},
        ],
        "cards": default_cards(project_mode, project_directory.strip(), project),
        "bridges": [],
    }
    write_session_context(session_id, sessions[session_id])
    return session_id


def model_payload(import_installed=False):
    registry = load_models()
    detected = scan_workspace()
    if import_installed:
        for model in detected["ollama"]["models"]:
            upsert_registry_model(registry, ollama_model_to_registry(model))
        save_models(registry)

    return {
        "registry": registry,
        "detected": detected["ollama"]["models"],
        "defaultModel": DEFAULT_MODEL,
    }


def ollama_model_to_registry(model):
    details = model.get("details", {})
    return {
        "name": model.get("name") or model.get("model"),
        "model": model.get("model") or model.get("name"),
        "source": "ollama",
        "status": "installed",
        "size": model.get("size"),
        "family": details.get("family"),
        "quantization": details.get("quantization_level"),
        "updatedAt": utc_now(),
    }


def upsert_registry_model(registry, model):
    registry.setdefault("models", [])
    name = model.get("name") or model.get("model")
    for index, existing in enumerate(registry["models"]):
        if existing.get("name") == name or existing.get("model") == name:
            registry["models"][index] = {**existing, **model}
            return
    registry["models"].append(model)


def is_ollama_model_installed(model_name, installed_models):
    names = set()
    for model in installed_models:
        if model.get("name"):
            names.add(model["name"])
        if model.get("model"):
            names.add(model["model"])
    return (
        model_name in names
        or f"{model_name}:latest" in names
        or any(name.startswith(f"{model_name}:") for name in names)
    )


def default_cards(project_mode="unknown", project_directory="", project=""):
    cards = [
        {
            "id": "intake",
            "title": "Project Context",
            "skill": "Project Context Writer",
            "status": "active",
            "summary": "Translate the user's request into a strict YAML deliverable contract that every later card consumes.",
        },
        {
            "id": "forge-flow",
            "title": "Forge Flow",
            "skill": "forge-flow",
            "status": "active",
            "summary": "Orient on project state, verify workspace readiness, and preserve user work.",
        },
        {
            "id": "gsd",
            "title": "GSD Planning",
            "skill": "gsd",
            "status": "active",
            "summary": "Break the project into phases with success criteria and verification steps.",
        },
        {
            "id": "execution",
            "title": "Project Execution",
            "skill": "materializer",
            "status": "active",
            "summary": "Create planned files, validate, repair, retest, and deliver artifacts.",
        },
        {
            "id": "socraticode",
            "title": "SocratiCode",
            "skill": "semantic code search",
            "status": "conditional",
            "summary": "Activate when a codebase needs semantic exploration or feature discovery.",
        },
        {
            "id": "axon",
            "title": "Axon",
            "skill": "structural code intelligence",
            "status": "conditional",
            "summary": "Activate before refactors or when impact/dead-code analysis is needed.",
        },
        {
            "id": "verification",
            "title": "Verification",
            "skill": "checkpoint protocol",
            "status": "active",
            "summary": "Pause for human verification or continue automatically by section setting.",
        },
        {
            "id": "handoff",
            "title": "Handoff",
            "skill": "project memory",
            "status": "active",
            "summary": "Summarize what changed, what was verified, and the next action.",
        },
    ]

    if project_mode == "new-project":
        for card in cards:
            if card["id"] == "forge-flow":
                # Stay active: the forge-flow handler has a dedicated "new-project"
                # branch that writes a "Workspace Pending" orientation artifact, so
                # the card has real work to do even before Execution creates the dir.
                # Marking it 'pending' here previously caused the UI's plan iterator
                # to silently skip it (planRunnableStatuses excludes pending), which
                # left the card visible-but-never-run.
                card["summary"] = "Note the workspace will be created during Execution; emit an orientation artifact now."
            if card["id"] in {"socraticode", "axon"}:
                card["status"] = "inactive"
                card["summary"] = "Inactive until a project directory and code files exist."

    if project_mode == "existing-directory":
        has_code = directory_has_code(project_directory)
        for card in cards:
            if card["id"] == "execution":
                card["status"] = "conditional"
                card["summary"] = "Run only when the plan requires modifying or creating project files."
            if card["id"] == "forge-flow":
                card["summary"] = "Orient on the selected project directory, verify readiness, and preserve user work."
            if card["id"] in {"socraticode", "axon"}:
                if has_code:
                    card["status"] = "active"
                    if card["id"] == "socraticode":
                        card["summary"] = "Map the existing codebase semantically before planning implementation work."
                    else:
                        card["summary"] = "Run structural analysis before implementation, review, or impact-sensitive work."
                else:
                    card["status"] = "inactive"
                    card["summary"] = "Hidden because the selected directory does not appear to contain code yet."

    return cards


def directory_has_code(project_directory):
    if not project_directory or not os.path.isdir(project_directory):
        return False

    for root, dirs, files in os.walk(project_directory):
        dirs[:] = [name for name in dirs if name not in IGNORED_CODE_DIRS]
        depth = os.path.relpath(root, project_directory).count(os.sep)
        if depth > 3:
            dirs[:] = []
        for filename in files:
            if os.path.splitext(filename)[1].lower() in SEMANTIC_INDEXABLE_EXTENSIONS:
                return True
    return False

def main():
    ensure_storage()
    app.run(port=int(os.environ.get("GFORGE_PORT", "5005")), debug=False)


if __name__ == "__main__":
    main()
