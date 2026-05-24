import os
import json
import ast
import shlex
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import requests
import yaml
from urllib.parse import unquote
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS

try:
    from huggingface_hub import HfApi, snapshot_download
except ImportError:  # pragma: no cover - dependency is declared for installs.
    HfApi = None
    snapshot_download = None

try:
    from . import tool_browse  # type: ignore
except ImportError:
    import tool_browse  # type: ignore

try:
    from . import tool_screenshot  # type: ignore
except ImportError:
    import tool_screenshot  # type: ignore

try:
    from . import tool_workspace  # type: ignore
except ImportError:
    import tool_workspace  # type: ignore

import collections
import contextlib
import contextvars
import threading
import queue


# ============================================================
# Activity event stream (SSE) — per-session filtered
# ============================================================
_EVENT_BUFFER = collections.deque(maxlen=400)
_EVENT_LOCK = threading.Lock()
# Each subscriber is a tuple (queue, session_filter). session_filter=None
# means "global subscriber, receives everything". A non-None filter only
# receives events whose session_id matches, so selected project terminals
# do not replay unrelated global harness events.
_EVENT_SUBSCRIBERS = []
_EVENT_SEQ = 0
EVENT_LOG_FILENAME = "terminal-events.jsonl"

# ContextVar lets nested calls (ollama, browse, screenshot, validation)
# inherit the session_id of the card / endpoint they were invoked from
# without every call site having to pass it explicitly. Wrap a request
# handler in event_session_scope(session_id) and every emit_event inside
# that scope auto-stamps the session_id onto the event.
_event_session_ctx = contextvars.ContextVar("event_session_id", default=None)


@contextlib.contextmanager
def event_session_scope(session_id):
    token = _event_session_ctx.set(session_id)
    try:
        yield
    finally:
        _event_session_ctx.reset(token)


def emit_event(kind, message, **extra):
    """Push an event onto the ring buffer + fan out to matching SSE subscribers.

    Safe to call from any thread. Never raises; failures are swallowed so
    instrumentation doesn't break the harness.

    session_id resolves in this order:
      1. explicit session_id=... in extra
      2. extra["session"] (legacy convention used by older call sites)
      3. ContextVar set by event_session_scope(...)
      4. None (event is global — delivered to every subscriber)
    """
    global _EVENT_SEQ
    try:
        explicit_sid = extra.pop("session_id", None)
        legacy_sid = extra.get("session")
        session_id = explicit_sid or legacy_sid or _event_session_ctx.get()

        payload = {
            "kind": kind,
            "message": str(message)[:500],
            "at": utc_now(),
            "session_id": session_id,
        }
        if extra:
            payload["extra"] = {k: v for k, v in extra.items() if v is not None}
        with _EVENT_LOCK:
            _EVENT_SEQ += 1
            payload["seq"] = _EVENT_SEQ
            _EVENT_BUFFER.append(payload)
            subs = list(_EVENT_SUBSCRIBERS)
        _persist_session_event(payload)
        for q, q_filter in subs:
            # Deliver if: subscriber is global (no filter), OR event/session match.
            if q_filter is None or q_filter == session_id:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass
    except Exception:
        pass


def _persist_session_event(payload):
    session_id = payload.get("session_id")
    if not session_id:
        return
    try:
        path = os.path.join(session_dir(session_id), EVENT_LOG_FILENAME)
        with open(path, "a") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass


def _load_session_event_log(session_id, limit=200):
    if not session_id:
        return []
    try:
        path = os.path.join(SESSION_ROOT, safe_id(session_id), EVENT_LOG_FILENAME)
        if not os.path.exists(path):
            return []
        events = []
        with open(path, "r") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
        return events[-limit:]
    except Exception:
        return []


def _session_record_event_fallback(session_id):
    if not session_id:
        return []
    try:
        session = load_sessions().get(session_id)
    except Exception:
        session = None
    if not isinstance(session, dict):
        return []

    events = []
    for index, card in enumerate(session.get("cards", [])):
        if not isinstance(card, dict):
            continue
        last_run = card.get("lastRun")
        if not isinstance(last_run, dict):
            continue
        title = last_run.get("title") or card.get("title") or card.get("id") or "Card"
        summary = last_run.get("summary") or card.get("summary") or "Section completed."
        events.append({
            "kind": "card-end",
            "message": f"{title}: {summary}",
            "at": last_run.get("ranAt") or utc_now(),
            "session_id": session_id,
            "seq": -(1000 - index),
            "extra": {
                "restored": True,
                "status": last_run.get("status") or card.get("status"),
                "artifact": last_run.get("artifact"),
            },
        })
        review = last_run.get("extraReview")
        if isinstance(review, dict) and review.get("required"):
            review_status = "passed" if review.get("passed") else "needs attention"
            events.append({
                "kind": "review",
                "message": f"{title} review {review_status}",
                "at": review.get("checkedAt") or last_run.get("ranAt") or utc_now(),
                "session_id": session_id,
                "seq": -(500 - index),
                "extra": {
                    "restored": True,
                    "confidence": review.get("confidence"),
                },
            })
    return sorted(events, key=lambda event: event.get("at") or "")


def _event_dedupe_key(event):
    seq = event.get("seq")
    if seq:
        return ("seq", seq)
    return (
        event.get("session_id"),
        event.get("kind"),
        event.get("message"),
        event.get("at"),
    )


def _dedupe_events(events):
    deduped = []
    seen = set()
    for event in events:
        key = _event_dedupe_key(event)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _subscribe_events(session_filter=None):
    q = queue.Queue(maxsize=200)
    with _EVENT_LOCK:
        _EVENT_SUBSCRIBERS.append((q, session_filter))
        buffered = [
            e for e in _EVENT_BUFFER
            if session_filter is None
            or e.get("session_id") == session_filter
        ]
    if session_filter:
        persisted = _load_session_event_log(session_filter)
        restored = _session_record_event_fallback(session_filter) if not persisted else []
        snapshot = _dedupe_events(restored + persisted + buffered)
    else:
        snapshot = buffered
    return q, snapshot


def _unsubscribe_events(q):
    with _EVENT_LOCK:
        _EVENT_SUBSCRIBERS[:] = [
            (existing_q, existing_filter)
            for existing_q, existing_filter in _EVENT_SUBSCRIBERS
            if existing_q is not q
        ]
try:
    from .workspace_scan import GFORGE_HOME, HF_TOKEN_PATH, LLAMA_CPP_ROOT, MODELS_ROOT, scan_workspace
    from .tool_runtime import (
        axon_runtime_status,
        axon_project_probe,
        run_axon_project_scan,
        run_socraticode_project_scan,
        socraticode_mcp_probe,
        socraticode_runtime_status,
    )
except ImportError:
    from workspace_scan import GFORGE_HOME, HF_TOKEN_PATH, LLAMA_CPP_ROOT, MODELS_ROOT, scan_workspace
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
SOURCE_INPUTS_ROOT = os.path.join("references", "input")
SOURCE_INPUTS_MANIFEST = os.path.join("references", "source-inputs.md")
SOURCE_INPUTS_MAX_FILES = int(os.environ.get("GFORGE_SOURCE_INPUTS_MAX_FILES", "400"))
SOURCE_INPUTS_MAX_BYTES = int(os.environ.get("GFORGE_SOURCE_INPUTS_MAX_BYTES", str(250 * 1024 * 1024)))
MAINTENANCE_TARGETS_ROOT = os.path.join("references", "maintenance-targets")
MAINTENANCE_TARGETS_MANIFEST = os.path.join("references", "maintenance-targets.md")
MAINTENANCE_ACTIONS_FILE = os.path.join("artifacts", "maintenance-actions.json")
MAINTENANCE_BACKUP_ROOT = os.path.join(GFORGE_DATA_ROOT, "maintenance-backups")
MAINTENANCE_MAX_FILES = int(os.environ.get("GFORGE_MAINTENANCE_MAX_FILES", "500"))
MAINTENANCE_MAX_BYTES = int(os.environ.get("GFORGE_MAINTENANCE_MAX_BYTES", str(8 * 1024 * 1024)))
LEGACY_SESSIONS_FILE = os.path.join(CHAT_ROOT, "sessions.json")
LEGACY_MODELS_FILE = os.path.join(CHAT_ROOT, "models.json")
LEGACY_SESSION_ROOT = os.path.join(CHAT_ROOT, "session-data")
DEFAULT_MODEL = os.environ.get("GFORGE_DEFAULT_MODEL", "gemma-4-e4b-it")
HF_MODEL_SEARCH_PAGE_SIZE = 5
HF_MODEL_SEARCH_MAX_OFFSET = 250
HF_MODEL_SEARCH_MAX_QUERY_CHARS = 120
LLAMA_CPP_BIN = os.environ.get("LLAMA_CPP_BIN", os.path.join(LLAMA_CPP_ROOT, "build", "bin"))
MODEL_PROVISION_LOCK = threading.Lock()
MODEL_PROVISION_JOBS = {}
MODEL_PROVISION_QUANTIZATION = os.environ.get("GFORGE_MODEL_QUANTIZATION", "Q4_K_M")
MODEL_PROVISION_TIMEOUT_SECONDS = int(os.environ.get("GFORGE_MODEL_PROVISION_TIMEOUT_SECONDS", "7200"))
MODEL_PROVISION_SYSTEM_PROMPT = os.environ.get("GFORGE_MODEL_SYSTEM_PROMPT", "You are a helpful assistant.")
MODEL_PROVISION_TEMPLATE = """{{ if .System }}<start_of_turn>system
{{ .System }}<end_of_turn>
{{ end }}{{ if .Prompt }}<start_of_turn>user
{{ .Prompt }}<end_of_turn>
{{ end }}<start_of_turn>model
{{ .Response }}<end_of_turn>"""
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
SOURCE_INPUT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
SOURCE_INPUT_SKIP_FILES = {
    ".DS_Store",
    "Thumbs.db",
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
SKILL_CONTEXT_FOCUSED_FILE_LIMIT = 3200
SKILL_PROMPT_ENTRYPOINTS = {
    "gsd": [
        "workflows/plan-phase.md",
        "agents/gsd-planner.md",
        "templates/roadmap.md",
        "workflows/execute-phase.md",
        "workflows/verify-work.md",
        "references/checkpoints.md",
    ],
    "ui-ux-pro-max": [
        "src/ui-ux-pro-max/templates/base/quick-reference.md",
        "src/ui-ux-pro-max/templates/base/skill-content.md",
    ],
}
SKILL_FOCUSED_MARKERS = {
    "workflows/plan-phase.md": [
        "<downstream_consumer>",
        "<deep_work_rules>",
    ],
    "workflows/execute-phase.md": [
        "<runtime_compatibility>",
        "<process>",
    ],
    "workflows/verify-work.md": [
        "<success_criteria>",
        "<process>",
    ],
    "src/ui-ux-pro-max/templates/base/skill-content.md": [
        "### Step 2: Generate Design System (REQUIRED)",
        "### Pre-Delivery Checklist",
    ],
}
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


def compact_slug(value, max_length=52, fallback="workspace"):
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        return fallback
    if len(slug) <= max_length:
        return slug
    words = [word for word in slug.split("-") if word]
    kept = []
    current = ""
    for word in words:
        candidate = "-".join(kept + [word])
        if len(candidate) > max_length:
            break
        kept.append(word)
        current = candidate
    return current or slug[:max_length].strip("-") or fallback


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
    """Read the skill's `name` field from either SKILL.md (YAML-frontmatter
    style) or skill.json (Claude/Cursor/Windsurf bundle style). Falls back
    to the directory name if neither parses."""
    try:
        if skill_file.endswith(".json"):
            with open(skill_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for field in ("name", "displayName", "id"):
                    value = data.get(field)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            return fallback
        with open(skill_file, "r") as f:
            for _ in range(12):
                line = f.readline()
                if not line:
                    break
                match = re.match(r"\s*name:\s*['\"]?([^'\"\n]+)", line)
                if match:
                    return match.group(1).strip()
    except (OSError, json.JSONDecodeError):
        pass
    return fallback


def parse_skill_metadata(skill_file):
    """Read optional description / keywords from SKILL.md frontmatter or skill.json."""
    metadata = {"description": "", "keywords": []}
    try:
        if skill_file.endswith(".json"):
            with open(skill_file, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return metadata
            description = data.get("description")
            if isinstance(description, str):
                metadata["description"] = description.strip()
            keywords = data.get("keywords", [])
            if isinstance(keywords, list):
                metadata["keywords"] = [str(item).strip() for item in keywords if str(item).strip()]
            return metadata

        with open(skill_file, "r") as f:
            content = f.read(12000)
        if not content.startswith("---"):
            return metadata
        end = content.find("\n---", 3)
        if end == -1:
            return metadata
        frontmatter = content[3:end].strip()
        data = yaml.safe_load(frontmatter)
        if not isinstance(data, dict):
            return metadata
        description = data.get("description")
        if isinstance(description, str):
            metadata["description"] = description.strip()
        keywords = data.get("keywords", [])
        if isinstance(keywords, list):
            metadata["keywords"] = [str(item).strip() for item in keywords if str(item).strip()]
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        pass
    return metadata


def discover_installed_skills(max_depth=3):
    """Walk every skill install root and surface anything that LOOKS like a
    skill bundle. A skill is recognised if its directory contains EITHER:
      - SKILL.md  (Codex / Anthropic skills convention)
      - skill.json (Claude/Cursor/Windsurf/etc. bundle convention)
    Without this, bundles that ship only skill.json (ui-ux-pro-max, etc.)
    were invisible to the harness and the Project Context Writer had no
    way to pick them. First-seen wins per normalized key, so duplicates
    across roots don't multi-stage."""
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
            skill_file = None
            if "SKILL.md" in files:
                skill_file = os.path.join(current_root, "SKILL.md")
            elif "skill.json" in files:
                skill_file = os.path.join(current_root, "skill.json")
            if not skill_file:
                continue
            directory_name = os.path.basename(current_root)
            skill_name = parse_skill_name(skill_file, directory_name)
            skill_metadata = parse_skill_metadata(skill_file)
            key = normalize_skill_key(skill_name)
            if key not in skills:
                skills[key] = {
                    "name": skill_name,
                    "key": key,
                    "source": source,
                    "directory": current_root,
                    "skillFile": skill_file,
                    "description": skill_metadata.get("description", ""),
                    "keywords": skill_metadata.get("keywords", []),
                }
    return skills


def normalize_skill_key(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def normalize_skill_phrase(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


USER_FACING_SKILL_SOURCES = {"harness", "gforge", "project"}
CORE_HARNESS_SKILL_KEYS = {
    "axon",
    "gsd",
    "code-writer",
    "logo-generator",
    "mcp-builder",
    "pdf",
    "scrapling-official",
    "socraticode",
    "ui-ux-pro-max",
    "webot-flow",
}
SKILL_CATALOG_ORDER = [
    "scrapling-official",
    "ui-ux-pro-max",
    "code-writer",
    "socraticode",
    "axon",
    "gsd",
    "pdf",
    "mcp-builder",
    "logo-generator",
    "webot-flow",
]


SKILL_SELECTION_ALIASES = {
    "scrapling-official": [
        "scrapling",
        "web_browse",
        "web browse",
        "web browsing",
        "browse web",
        "browse the web",
        "web_fetch",
        "web fetch",
        "fetch url",
        "fetch urls",
        "fetch page",
        "fetch pages",
        "download page",
        "download pages",
        "website content",
        "site content",
        "live web",
        "live data",
        "live scraping",
        "live news",
        "latest news",
        "current news",
        "online research",
        "internet research",
        "deep research",
        "deep web research",
        "detailed search",
        "detailed web search",
        "detailed source search",
        "source gathering",
        "source collection",
        "collect sources",
        "gather sources",
        "find sources",
        "find articles",
        "gather articles",
        "collect articles",
        "public web research",
        "public data search",
        "open web research",
        "online investigation",
        "web investigation",
        "competitive research",
        "market research",
        "data mining",
        "web data mining",
        "data harvesting",
        "web harvesting",
        "information harvesting",
        "harvest data",
        "harvest sources",
        "harvest articles",
        "gather web data",
        "collect web data",
        "find everything about",
        "pull from websites",
        "grab website content",
        "look across websites",
        "search public sites",
        "news scraping",
        "news articles",
        "news headlines",
        "headlines",
        "article scraping",
        "scrape",
        "scraper",
        "scraping",
        "web scrape",
        "web scraper",
        "web scraping",
        "crawl",
        "crawler",
        "crawling",
        "web crawl",
        "web crawling",
        "extract data",
        "extract website data",
        "data extraction",
        "web extraction",
        "css selector",
        "xpath",
        "spider",
        "spiders",
        "spider framework",
        "javascript rendering",
        "js rendering",
        "dynamic site",
        "dynamic sites",
        "dynamic website",
        "dynamic websites",
        "anti bot",
        "anti-bot",
        "bot bypass",
        "cloudflare",
        "turnstile",
        "stealth",
        "stealthy",
        "stealth browser",
        "browser fetch",
        "research articles",
        "research sources",
        "research sites",
        "research pages",
        "render javascript",
        "rendered page",
        "headless browser",
        "browser automation",
        "adaptive scraping",
        "adaptive selectors",
        "anti bot bypass",
        "cloudflare bypass",
        "turnstile bypass",
        "crawl site",
        "crawl website",
        "multi page crawl",
        "site crawl",
        "web spider",
        "scraping pipeline",
        "extract structured data from website",
    ],
    "logo-generator": [
        "logo",
        "logos",
        "brand mark",
        "brandmark",
        "icon",
        "icons",
        "svg logo",
        "logo design",
        "logo concepts",
        "logo options",
        "logo variants",
        "identity mark",
        "company mark",
        "product mark",
        "brand symbol",
        "app icon",
        "badge",
        "emblem",
        "monogram",
        "logotype",
        "mark system",
        "branding concepts",
        "brand concepts",
        "visual mark",
        "symbol design",
        "wordmark",
        "showcase",
        "brand identity",
        "visual identity",
    ],
    "code-writer": [
        "code writer",
        "code generation",
        "write code",
        "implement code",
        "build code",
        "create code",
        "write a script",
        "build a script",
        "create a script",
        "make a script",
        "make a tool",
        "build a tool",
        "create a tool",
        "make a utility",
        "build a utility",
        "little program",
        "small program",
        "working program",
        "working code",
        "automation script",
        "automate this",
        "automate a task",
        "process files",
        "process a file",
        "processes files",
        "process data",
        "processes data",
        "transform data",
        "transforms data",
        "convert data",
        "converts data",
        "validate data",
        "validates data",
        "parse file",
        "parse files",
        "python script",
        "python cli",
        "python command line",
        "python utility",
        "javascript module",
        "js module",
        "typescript module",
        "ts module",
        "html css js",
        "html css javascript",
        "single page app",
        "web app",
        "api client",
        "parser",
        "data parser",
        "unit test",
        "unit tests",
        "test suite",
        "sql query",
        "shell script",
        "bash script",
        "cli tool",
        "command line tool",
        "command line utility",
        "runnable code",
    ],
    "ui-ux-pro-max": [
        "ui",
        "ux",
        "ui ux",
        "ui/ux",
        "interface",
        "webpage",
        "web page",
        "webpage design",
        "website design",
        "responsive page",
        "responsive webpage",
        "responsive website",
        "responsive",
        "across devices",
        "present nicely",
        "make it look good",
        "make it look professional",
        "make it polished",
        "visual polish",
        "polish the page",
        "clean layout",
        "beautiful page",
        "good looking page",
        "mobile friendly",
        "phone friendly",
        "tablet friendly",
        "desktop friendly",
        "easy to use",
        "user friendly",
        "user experience",
        "screen design",
        "page design",
        "front end",
        "front-end",
        "frontend",
        "visual design",
        "presentation design",
        "make the ui better",
        "improve the interface",
        "improve the design",
        "modern page",
        "modern webpage",
        "frontend design",
        "front-end design",
        "design system",
        "wireframe",
        "layout",
        "typography",
        "color palette",
        "accessibility",
        "dashboard design",
        "landing page design",
        "app design",
        "app shell",
        "admin dashboard",
        "saas dashboard",
        "product page",
        "pricing page",
        "onboarding flow",
        "form flow",
        "mobile layout",
        "mobile responsive",
        "desktop layout",
        "component library",
        "component system",
        "style guide",
        "visual hierarchy",
        "interaction design",
        "usability",
        "ux audit",
        "ui audit",
        "design audit",
        "data visualization",
        "data visualisation",
        "chart design",
        "charts",
        "graph design",
        "empty states",
        "loading states",
        "error states",
    ],
    "axon": [
        "axon",
        "knowledge graph",
        "code graph",
        "call graph",
        "dead code",
        "blast radius",
        "impact analysis",
        "circular dependencies",
        "dependency graph",
        "what calls this",
        "what calls",
        "who calls",
        "what breaks if",
        "what will break",
        "trace dependencies",
        "trace calls",
        "dependency map",
        "map dependencies",
        "architecture graph",
        "architecture map",
        "find unused code",
        "unused code",
        "remove dead stuff",
        "cleanup dead code",
        "safe refactor",
        "refactor safety",
        "change impact",
        "rename impact",
        "blast radius check",
        "affected code",
        "call chain",
        "execution flow",
        "symbol graph",
        "structural graph",
        "structural analysis",
        "dependency tracing",
        "refactor impact",
        "affected tests",
        "affected files",
        "architectural impact",
        "code communities",
        "community detection",
        "shortest path",
        "graph query",
        "cypher",
        "code coupling",
        "mcp server for code",
    ],
    "pdf": [
        "pdf",
        ".pdf",
        "portable document format",
        "read pdf",
        "extract pdf",
        "extract pdf text",
        "pdf text",
        "pdf table",
        "pdf tables",
        "pdf form",
        "fillable pdf",
        "fill pdf",
        "merge pdf",
        "combine pdf",
        "split pdf",
        "rotate pdf",
        "crop pdf",
        "watermark pdf",
        "encrypt pdf",
        "decrypt pdf",
        "ocr pdf",
        "scanned pdf",
        "searchable pdf",
        "scan document",
        "scanned document",
        "document ocr",
        "ocr document",
        "read scanned pages",
        "read scanned documents",
        "pull text from document",
        "pull text from pdf",
        "extract tables from document",
        "make searchable",
        "searchable document",
        "read the form",
        "fill the form",
        "fill out pdf",
        "paper form",
        "digital form",
        "document pages",
        "combine documents",
        "split document",
        "create pdf",
        "generate pdf",
        "qpdf",
        "pypdf",
        "pdfplumber",
        "reportlab",
    ],
    "mcp-builder": [
        "mcp",
        "model context protocol",
        "mcp builder",
        "mcp server",
        "build mcp",
        "build an mcp",
        "create mcp",
        "create an mcp",
        "implement mcp",
        "mcp tool",
        "mcp tools",
        "tool schema",
        "tool schemas",
        "mcp resource",
        "mcp resources",
        "mcp prompt",
        "mcp prompts",
        "stdio transport",
        "streamable http",
        "fastmcp",
        "python mcp",
        "typescript mcp",
        "node mcp",
        "mcp sdk",
        "agent tool server",
        "tool server",
        "local tool server",
        "make tools for agent",
        "agent tools",
        "expose api as tools",
        "wrap api as tools",
        "connect api to agent",
        "connect service to agent",
        "server for tools",
        "tool endpoint",
        "tool transport",
        "resources server",
        "prompt server",
        "codex tool server",
        "claude tool server",
        "external api integration",
        "api connector",
        "tool evaluation",
        "tool eval",
    ],
    "socraticode": [
        "socraticode",
        "semantic search",
        "semantic code search",
        "semantic codebase search",
        "codebase search",
        "codebase exploration",
        "codebase context",
        "context artifacts",
        "index codebase",
        "index this repo",
        "index the repo",
        "where is implemented",
        "where this lives",
        "find where",
        "find in the code",
        "find in this repo",
        "search the repo",
        "search this repo",
        "search the code",
        "search codebase",
        "locate code",
        "locate function",
        "locate files",
        "find the function",
        "find the module",
        "find implementation",
        "where does this happen",
        "where is this handled",
        "how is this wired",
        "how this works in code",
        "explain this repo",
        "inspect the codebase",
        "look through the code",
        "find relevant files",
        "relevant files",
        "understand codebase",
        "understand this repo",
        "map codebase",
        "navigate codebase",
        "repository exploration",
        "repo exploration",
        "api schema search",
        "database schema search",
        "dependency context",
        "codebase_graph",
        "codebase_search",
        "codebase_status",
    ],
    "gsd": [
        "gsd",
        "get shit done",
        "phase plan",
        "phase planning",
        "project plan",
        "execution plan",
        "plan the work",
        "break down the work",
        "break this down",
        "task breakdown",
        "step by step plan",
        "execution strategy",
        "work plan",
        "delivery plan",
        "sanity plan",
        "finish plan",
        "organize the project",
        "project roadmap",
        "turn this into tasks",
        "orchestration plan",
        "roadmap",
        "milestone",
        "milestones",
        "workstreams",
        "planning workflow",
        "autonomous planning",
        "verification plan",
        "acceptance criteria",
        "break this into phases",
        "plan phase",
        "execute phase",
        "review backlog",
    ],
    "webot-flow": [
        "webot flow",
        "forge flow",
        "handoff",
        "current state",
        "active state",
        "project map",
        "backup",
        "state backup",
        "state check",
        "check current state",
        "orient on state",
        "orient on repo",
        "repo orientation",
        "handoff update",
        "handoff summary",
        "protect live",
        "protect user work",
        "pre edit backup",
        "before editing",
        "before commit",
        "wrap up",
        "wrap this up",
        "verify before done",
        "verification handshake",
        "repo state",
        "working tree",
        "do not touch live",
        "handoff notes",
    ],
}

SKILL_ALIAS_SUPPRESSIONS = {
    # These are meaningful inside the MCP skill manual, but too generic as
    # standalone routing triggers. "auth middleware" should route to
    # SocratiCode/Axon, not MCP Builder, unless MCP/tool/server language is
    # present too.
    "mcp-builder": {
        "auth",
        "oauth",
        "pagination",
        "connector",
        "actionable errors",
        "tool naming",
        "api tools",
        "evals",
    },
}

SCRAPLING_BROAD_RESEARCH_ALIASES = {
    "competitive research",
    "data harvesting",
    "data mining",
    "deep research",
    "detailed search",
    "harvest data",
    "information harvesting",
    "market research",
}
SCRAPLING_WEB_CONTEXT_TERMS = {
    "article",
    "articles",
    "browser",
    "headlines",
    "internet",
    "news",
    "online",
    "open web",
    "page",
    "pages",
    "public",
    "site",
    "sites",
    "source",
    "sources",
    "url",
    "urls",
    "web",
    "website",
    "websites",
}
CODEBASE_CONTEXT_TERMS = {
    "code",
    "codebase",
    "function",
    "implementation",
    "module",
    "repo",
    "repository",
    "source code",
}


def description_skill_aliases(description):
    """Pull high-signal use-case phrases out of a skill description."""
    if not description:
        return []
    aliases = []
    for match in re.finditer(r"use when(?: asked to| the user wants to)?[:\s]+(.+)", description, re.IGNORECASE):
        use_when = match.group(1).split(".", 1)[0]
        for part in re.split(r";|,|\bor\b|\band\b|\(|\)|\d+\.", use_when):
            phrase = normalize_skill_phrase(part)
            if len(phrase) >= 4:
                aliases.append(phrase)
    return aliases


def skill_aliases(info):
    aliases = set()
    key = info.get("key") or normalize_skill_key(info.get("name", ""))
    name = str(info.get("name", "")).strip()
    for value in (key, name, name.replace("-", " "), name.replace("_", " ")):
        if str(value).strip():
            aliases.add(str(value).strip())
    aliases.update(SKILL_SELECTION_ALIASES.get(key, []))
    aliases.update(str(item).strip() for item in info.get("keywords", []) if str(item).strip())
    aliases.update(description_skill_aliases(str(info.get("description", ""))))
    suppressed = {normalize_skill_phrase(item) for item in SKILL_ALIAS_SUPPRESSIONS.get(key, set())}
    aliases = {alias for alias in aliases if normalize_skill_phrase(alias) not in suppressed}
    return sorted(aliases, key=lambda item: (normalize_skill_phrase(item), len(item)))


def normalized_phrase_matches_text(normalized_text, phrase):
    if not phrase:
        return False
    if not normalized_text:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return bool(re.search(pattern, normalized_text))


def skill_alias_matches_text(text, alias):
    return normalized_phrase_matches_text(normalize_skill_phrase(text), normalize_skill_phrase(alias))


def skill_alias_context_allows(text, key, alias):
    phrase = normalize_skill_phrase(alias)
    if key != "scrapling-official" or phrase not in SCRAPLING_BROAD_RESEARCH_ALIASES:
        return True
    normalized_text = normalize_skill_phrase(text)
    has_code_context = any(normalized_phrase_matches_text(normalized_text, term) for term in CODEBASE_CONTEXT_TERMS)
    has_web_context = any(normalized_phrase_matches_text(normalized_text, term) for term in SCRAPLING_WEB_CONTEXT_TERMS)
    return not (has_code_context and not has_web_context)


def skill_is_user_facing(info):
    key = info.get("key") or normalize_skill_key(info.get("name", ""))
    source = str(info.get("source", "")).strip().lower()
    return key in CORE_HARNESS_SKILL_KEYS or source in USER_FACING_SKILL_SOURCES


def user_facing_skills(skills):
    return {
        key: info
        for key, info in (skills or {}).items()
        if skill_is_user_facing({**info, "key": key})
    }


def ordered_skill_keys(skills):
    keys = list((skills or {}).keys())
    preferred = [key for key in SKILL_CATALOG_ORDER if key in skills]
    rest = sorted(key for key in keys if key not in preferred)
    return preferred + rest


def resolve_skill_reference(value, skills):
    raw = str(value or "").strip()
    if not raw:
        return None, None
    normalized = normalize_skill_key(raw)
    if normalized in skills:
        return normalized, "exact"
    raw_phrase = normalize_skill_phrase(raw)
    for key, info in skills.items():
        for alias in skill_aliases(info):
            if normalize_skill_phrase(alias) == raw_phrase:
                return key, "alias"
    return None, None


def session_skill_text(session):
    parts = [session.get("project", "")]
    for message in session.get("messages", []) if isinstance(session, dict) else []:
        # Only user text should drive skill selection. Agent messages include
        # prior artifacts and staged-skill manifests, which caused reruns to
        # self-poison by selecting support skills merely because a previous
        # agent mentioned them.
        if str(message.get("role", "")).lower() != "user":
            continue
        parts.append(str(message.get("content", "")))
    return "\n".join(parts).lower()


def session_user_source_text(session):
    if not isinstance(session, dict):
        return ""
    parts = [str(session.get("project", ""))]
    for message in session.get("messages", []) if isinstance(session.get("messages"), list) else []:
        if str(message.get("role", "")).lower() == "user":
            parts.append(str(message.get("content", "")))
    return "\n".join(parts)


def requested_skill_keys(session, skills):
    """Scan project text + chat history for skill matches. Matches by:
      1. Explicit `$skill-name` or `skill <name>` mentions.
      2. The skill's literal name (`logo-generator` or `logo generator`).
      3. Built-in aliases for bundled harness skills.
      4. Any keywords / use-case phrases declared by the bundle metadata.
    Returns a sorted list of keys."""
    skills = user_facing_skills(skills)
    text = session_skill_text(session)
    requested = set()
    for match in re.findall(r"(?:\$|skill\s+)([a-z0-9_.-]+)", text):
        key, _reason = resolve_skill_reference(match, skills)
        if key in skills:
            requested.add(key)
    for key, info in skills.items():
        if any(
            skill_alias_matches_text(text, alias) and skill_alias_context_allows(text, key, alias)
            for alias in skill_aliases(info)
        ):
            requested.add(key)
            continue
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


def prepare_workspace_skill_context(workspace_dir, session, extra_keys=None):
    skills = discover_installed_skills()
    staged = []
    staged_root = safe_workspace_child(workspace_dir, WORKSPACE_SKILLS_ROOT)
    os.makedirs(staged_root, exist_ok=True)

    selected_keys = resolve_skill_selection(session, skills)
    for key in extra_keys or []:
        normalized = normalize_skill_key(key)
        if normalized in skills and normalized not in selected_keys:
            selected_keys.append(normalized)
    emit_event(
        "skill",
        "skill call selection: " + (", ".join(selected_keys) if selected_keys else "none"),
        selected=selected_keys,
        available=len(skills),
    )
    prune_workspace_skill_dirs(staged_root, selected_keys)
    for key in selected_keys:
        skill = skills.get(key)
        if not skill:
            continue
        try:
            destination = copy_skill_to_workspace(skill, workspace_dir)
            relative_destination = os.path.relpath(destination, workspace_dir).replace(os.sep, "/")
            emit_event(
                "skill",
                f"skill call {skill['name']} -> {relative_destination}",
                skill=key,
                source=skill["source"],
            )
            staged.append({
                "name": skill["name"],
                "key": key,
                "source": skill["source"],
                "path": relative_destination,
                "description": skill.get("description", ""),
                "keywords": skill.get("keywords", []),
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
         - Real installed skill name / alias → include it first.
         - "none" / "n/a" → respect only when the deterministic matcher
           does not see a skill need in the user's text.
         - Garbage (capability name, hallucinated value) → log + fall
           through to the keyword matcher rather than staging nothing.
      2. Keyword matcher: scan project text + chat history for skill
         names / aliases. Stages every match. This is the legacy
         "drop a skill in and it shows up" path.
    """
    if not isinstance(session, dict):
        return []
    skills = user_facing_skills(skills)

    context_pick = None
    context_none = False
    context = session.get("projectContext")
    if isinstance(context, dict):
        skill_info = context.get("skill") if isinstance(context.get("skill"), dict) else None
        raw_use = ""
        if skill_info:
            raw_use = str(skill_info.get("use", "")).strip()
        normalized = normalize_skill_key(raw_use) if raw_use else ""
        if normalized in {"none", "n-a", "na"}:
            context_none = True
        resolved_key, resolved_reason = resolve_skill_reference(raw_use, skills)
        if resolved_key:
            context_pick = resolved_key
            if normalized and normalized != resolved_key:
                emit_event(
                    "skill",
                    f"Project Context skill.use {raw_use!r} resolved to {skills[resolved_key]['name']}",
                    requested=raw_use,
                    skill=resolved_key,
                    reason=resolved_reason,
                )
        elif normalized and not context_none:
            log_error(
                "skill-staging",
                f"Project Context named a skill that is not installed: {raw_use!r} "
                f"— falling back to keyword matcher",
                None,
                {"requested": raw_use, "available": sorted(skills.keys())},
            )

    # Keyword matcher runs to (a) add more relevant skills alongside
    # whatever Context Writer picked, and (b) substitute when Context
    # Writer's pick was invalid or empty. Project text "use any skills
    # you have to help" or "ui/ux design" etc. drives this.
    keyword_picks = list(requested_skill_keys(session, skills))

    if context_none:
        if keyword_picks:
            emit_event(
                "skill",
                "Project Context skill.use 'none' overridden by request keywords: "
                + ", ".join(keyword_picks),
                selected=keyword_picks,
            )
            return keyword_picks
        return []

    if context_pick:
        # Combine Context Writer's deliberate pick with keyword picks,
        # preserving order and de-duplicating.
        seen = set()
        combined = []
        for key in [context_pick, *keyword_picks]:
            if key and key not in seen:
                seen.add(key)
                combined.append(key)
        return combined
    return keyword_picks


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


SKILL_ROLE_GUIDANCE = {
    "scrapling-official": {
        "role": "web scraping and extraction, advanced browser, crawling, and web acquisition",
        "guidance": [
            "Use this when the request asks to scrape, crawl, browse, fetch, research live pages, extract headlines/articles, render JavaScript, or handle dynamic/anti-bot sites.",
            "It is the first browser/scraping option in Gemma Forge: request fetch first, browser rendering when content is thin, stealth when blocked.",
            "For advanced users, route adaptive selectors, spider/crawl workflows, Cloudflare/Turnstile language, and structured extraction to this skill.",
            "The harness can fetch URLs with Scrapling before execution and will list fetched `research/*.md` artifacts later in this prompt; treat those artifacts as available source material.",
            "Do not say live scraping is impossible when `web_browse`/`web_fetch` is in CAN do or when research artifacts are listed. Build from the fetched artifacts and cite their workspace paths.",
            "Do not use this for local-only tasks with no URL, site, web research, or scraping requirement.",
        ],
    },
    "ui-ux-pro-max": {
        "role": "webpage and interface design, UI/UX systems, layouts, states, charts, and accessibility",
        "guidance": [
            "Use this when the deliverable is a webpage, landing page, dashboard, app shell, product page, UI, visual layout, responsive design, typography, color, spacing, chart/data display, accessibility, or UX flow.",
            "Treat it as a full design suite, not a light styling hint: use it for layout systems, visual hierarchy, state design, component patterns, palette/font pairing, UX guidelines, dashboards, and polished responsive presentation.",
            "Apply its guidance directly inside the generated HTML/CSS/JS deliverable; do not produce a separate design plan unless the contract asks for one.",
            "For a news/page request, this skill is the design layer: structure, layout, visual hierarchy, responsive behavior, and polished presentation.",
            "Do not use this for non-visual scripts, raw data transforms, or codebase graph analysis unless the output is a user-facing interface.",
        ],
    },
    "logo-generator": {
        "role": "SVG logo and icon generation",
        "guidance": [
            "Use this when the request asks for a logo, icon, brand mark, wordmark, or SVG design variants.",
            "Generate actual SVG markup in GFORGE_FILE blocks; do not redirect to an external image generator.",
        ],
    },
    "code-writer": {
        "role": "source-code implementation for Python, JavaScript, TypeScript, HTML/CSS, SQL, and shell",
        "guidance": [
            "Use when the primary deliverable is a script, CLI, module, test, parser, small web app, API client, SQL file, shell script, or other source-code artifact.",
            "This is the implementation layer: write complete runnable files, keep dependencies minimal, add error handling, and include a simple validation path.",
            "Pair with UI/UX Pro Max for interface design, Scrapling for web acquisition, SocratiCode for existing-codebase discovery, and Axon for structural graph/impact analysis.",
            "Do not use this as a substitute for SocratiCode/Axon when the request is primarily to find, understand, or map an existing codebase.",
        ],
    },
    "axon": {
        "role": "structural code graph, call graph, dependency, impact, and dead-code analysis",
        "guidance": [
            "Use when the task is about structure: dead code, call graph, dependency graph, circular dependencies, blast radius, impact analysis, what calls a symbol, affected tests/files, code communities, or graph queries.",
            "Axon is higher-level than simple text search; it should be inactive for ordinary webpage/content generation, one-off scripts, or docs unless the user explicitly asks for codebase structure.",
            "When both semantic discovery and structural impact matter, pair SocratiCode for finding relevant files with Axon for graph/impact reasoning.",
        ],
    },
    "pdf": {
        "role": "PDF reading, extraction, forms, conversion, and generation",
        "guidance": [
            "Use this whenever the request mentions a PDF, .pdf file, PDF form, OCR, page splitting/merging/rotation, text/table extraction, or creating a PDF deliverable.",
            "For PDF forms, inspect whether fields are fillable before writing form-filling code; follow the staged `forms.md` and `scripts/` workflow.",
            "Prefer the staged references for tool choice: pypdf for basic manipulation, pdfplumber for extraction, reportlab for creation, qpdf/poppler for command-line operations, and OCR only for scanned PDFs.",
        ],
    },
    "mcp-builder": {
        "role": "MCP server design, implementation, and evaluation",
        "guidance": [
            "Use this when the user asks to create, update, review, or evaluate a Model Context Protocol server, tool schema, resource, prompt, transport, or API connector.",
            "Check the staged reference docs before implementation: best practices first, then the TypeScript or Python guide that matches the project.",
            "Design tools around real user workflows, authentication, pagination, structured outputs, and actionable errors; include evaluation when the request asks for quality or correctness.",
        ],
    },
    "webot-flow": {
        "role": "project orientation and verification workflow",
        "guidance": [
            "Use this when the task touches an existing project, repository state, handoff docs, backups, or verification discipline.",
            "Read the staged project-state instructions before making claims about current state, and report blockers instead of pretending a step succeeded.",
        ],
    },
    "socraticode": {
        "role": "semantic codebase search, indexing, context artifacts, and dependency orientation",
        "guidance": [
            "Use when the task asks to understand or navigate an existing codebase, find relevant files, locate where a feature lives, index a repo, search schemas/specs/context artifacts, or orient before code changes.",
            "SocratiCode is higher-level codebase intelligence; it should be inactive for simple fresh-file generation with no existing codebase to inspect.",
            "For exact strings or known filenames, direct search is acceptable; for concepts, architecture, or unknown implementation locations, use SocratiCode first.",
            "When the MCP is degraded, report degraded/unavailable instead of pretending semantic search ran.",
        ],
    },
    "gsd": {
        "role": "GSD planning, orchestration, phase routing, roadmap, and verification workflow",
        "guidance": [
            "Use when the task asks for GSD, phase planning, roadmaps, milestones, workstreams, autonomous planning, execution routing, or verification strategy.",
            "GSD should enforce counts, source inputs, tool routing, acceptance criteria, and review gates. It must not allow fewer outputs than the user requested.",
            "Do not turn an execution deliverable into a plan unless the Project Context contract says the deliverable is a plan.",
        ],
    },
}


def skill_role_guidance(skill_key):
    return SKILL_ROLE_GUIDANCE.get(skill_key, {
        "role": "supporting instructions",
        "guidance": [
            "Use only the parts of this staged skill that directly support the current Project Context contract.",
            "If it does not apply to the deliverable, ignore it rather than discussing it.",
        ],
    })


def build_skill_capability_catalog_prompt(skills):
    catalog = user_facing_skills(skills)
    if not catalog:
        return "- No user-facing skills are installed."
    lines = [
        "Installed user-facing skill capability catalog:",
        "- Pick skills for capability fit, not because a word sounds nearby.",
        "- Higher-level code intelligence tools should stay inactive for simple file/content generation.",
        "- Advanced technical phrasing should activate the exact skill(s) below when it matches their role.",
    ]
    for key in ordered_skill_keys(catalog):
        skill = catalog[key]
        role = skill_role_guidance(key)
        aliases = skill_prompt_alias_preview(skill, limit=10)
        alias_text = ", ".join(aliases) if aliases else "(none)"
        description = truncate_text(skill.get("description", ""), 260) if skill.get("description") else ""
        lines.append(f"- `{key}` — {role.get('role', 'supporting instructions')}.")
        if description:
            lines.append(f"  Use when: {description}")
        lines.append(f"  Trigger language: {alias_text}")
        guidance = role.get("guidance", [])
        if guidance:
            lines.append(f"  Routing rule: {guidance[0]}")
            if len(guidance) > 1:
                lines.append(f"  Boundary: {guidance[-1]}")
    return "\n".join(lines)


def build_skill_usage_plan(staged):
    if not staged:
        return []
    lines = [
        "Skill Usage Plan (read before the manuals):",
        "- These staged skills are local instructions and harness capabilities selected for this project. They are not inaccessible `/Users/...` paths.",
        "- Use each skill for its named role below. If a staged skill does not fit the Project Context contract, ignore it quietly.",
        "- Do not claim a command, scraper, screenshot, API, or deployment ran unless the harness event/research/screenshot artifacts show that it ran.",
    ]
    for skill in staged:
        key = skill.get("key", "")
        role = skill_role_guidance(key)
        lines.append(f"- `{skill.get('name', key)}` → {role.get('role', 'supporting instructions')}.")
        for item in role.get("guidance", []):
            lines.append(f"  * {item}")
    return lines


def build_skill_context_prompt(workspace_dir, staged):
    if not staged:
        return "No Gemma Forge skills are staged for this workspace."

    lines = [
        "Harness-staged skill references are available in the workspace.",
        f"- Skills root: `{WORKSPACE_SKILLS_ROOT}`",
        "- Use the staged skill instructions below when they match the project request.",
        "- Do not report `/Users/...` skill paths as inaccessible when a matching staged skill is listed here.",
        "- Do not claim a script, API, or external model ran unless the harness actually runs it later; use the COMMANDS section only for workspace-safe commands required by the contract.",
        "- When you generate deliverables from staged skill instructions, say you used the staged skill instructions. Do not describe that as simulated skill execution.",
        "",
        *build_skill_usage_plan(staged),
        "",
        "Staged skills:",
    ]
    for skill in staged:
        marker = "requested" if skill.get("requested") else "available"
        lines.append(f"- `{skill['name']}` at `{skill['path']}` ({marker})")

    requested_skills = [item for item in staged if item.get("requested")]
    remaining = SKILL_CONTEXT_TOTAL_LIMIT
    for index, skill in enumerate(requested_skills):
        skill_dir = os.path.join(workspace_dir, skill["path"])
        slots_left = max(1, len(requested_skills) - index)
        skill_budget = max(1, remaining // slots_left)
        snippets, used = read_skill_prompt_snippets(skill_dir, min(remaining, skill_budget))
        remaining -= used
        if snippets:
            lines.extend(["", f"## {skill['name']} Skill Context", ""])
            lines.extend(snippets)
        if remaining <= 0:
            break
    return "\n".join(lines)


def add_unique_skill_prompt_path(paths, seen, skill_dir, relative_path):
    path = os.path.join(skill_dir, relative_path)
    normalized = os.path.abspath(path)
    if normalized in seen or not os.path.isfile(path):
        return
    seen.add(normalized)
    paths.append(path)


def skill_prompt_candidate_paths(skill_dir):
    skill_key = normalize_skill_key(os.path.basename(os.path.abspath(skill_dir)))
    candidate_paths = []
    seen = set()

    add_unique_skill_prompt_path(candidate_paths, seen, skill_dir, "OUTPUT.md")
    has_skill_md = os.path.isfile(os.path.join(skill_dir, "SKILL.md"))
    if has_skill_md:
        add_unique_skill_prompt_path(candidate_paths, seen, skill_dir, "SKILL.md")
    else:
        add_unique_skill_prompt_path(candidate_paths, seen, skill_dir, "skill.json")

    for relative_path in SKILL_PROMPT_ENTRYPOINTS.get(skill_key, []):
        add_unique_skill_prompt_path(candidate_paths, seen, skill_dir, relative_path)

    for folder in ("references", "reference", "assets"):
        folder_path = os.path.join(skill_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [name for name in dirs if name not in SKILL_COPY_IGNORE_NAMES]
            for filename in sorted(files):
                if os.path.splitext(filename)[1].lower() in SKILL_CONTEXT_EXTENSIONS:
                    relative_path = os.path.relpath(os.path.join(root, filename), skill_dir)
                    add_unique_skill_prompt_path(candidate_paths, seen, skill_dir, relative_path)
    return candidate_paths


def skill_json_prompt_summary(path):
    try:
        with open(path, "r", errors="replace") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    lines = ["Skill metadata from skill.json:"]
    for field in ("name", "displayName", "description", "version", "repository"):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            lines.append(f"- {field}: {value.strip()}")
    keywords = data.get("keywords")
    if isinstance(keywords, list):
        keyword_text = ", ".join(str(item).strip() for item in keywords if str(item).strip())
        if keyword_text:
            lines.append(f"- keywords: {keyword_text}")
    install = data.get("install")
    if isinstance(install, str) and install.strip():
        lines.append(f"- install: {install.strip()}")
    return "\n".join(lines)


def focused_skill_file_content(path, relative_path, limit):
    try:
        with open(path, "r", errors="replace") as f:
            raw = f.read()
    except OSError:
        return ""
    markers = SKILL_FOCUSED_MARKERS.get(relative_path)
    if not markers:
        return raw[:limit]

    parts = []
    intro = raw[:min(700, max(0, limit // 4))]
    if intro.strip():
        parts.append(intro)
    used = len("\n\n".join(parts))
    for marker_index, marker in enumerate(markers):
        remaining = limit - used
        if remaining <= 0:
            break
        index = raw.find(marker)
        if index == -1:
            continue
        markers_left = max(1, len(markers) - marker_index)
        excerpt_limit = max(350, remaining // markers_left)
        start = max(0, index - 350)
        end = min(len(raw), index + excerpt_limit)
        excerpt = f"\n\n[focused excerpt around {marker}]\n{raw[start:end]}"
        excerpt = excerpt[:min(remaining, excerpt_limit)]
        parts.append(excerpt)
        used = len("\n\n".join(parts))
    return "\n\n".join(parts)[:limit]


def read_skill_prompt_snippets(skill_dir, remaining):
    snippets = []
    used = 0
    for path in skill_prompt_candidate_paths(skill_dir):
        if remaining <= 0:
            break
        relative_path = os.path.relpath(path, skill_dir).replace(os.sep, "/")
        if relative_path == "skill.json":
            content = skill_json_prompt_summary(path)
        else:
            file_limit = min(SKILL_CONTEXT_FILE_LIMIT, remaining)
            if relative_path in SKILL_FOCUSED_MARKERS:
                file_limit = min(SKILL_CONTEXT_FOCUSED_FILE_LIMIT, file_limit)
            content = focused_skill_file_content(path, relative_path, file_limit)
        content = content[:min(SKILL_CONTEXT_FILE_LIMIT, remaining)]
        if not content.strip():
            continue
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
        return 8.0
    return None


def small_model_review_required(model):
    size = selected_model_size_b(model)
    if size is not None:
        return size <= SMALL_MODEL_REVIEW_MAX_B

    selected = normalize_model_name(model).lower()
    size_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*b", selected)
    if size_match:
        return float(size_match.group(1)) <= SMALL_MODEL_REVIEW_MAX_B
    return selected in {DEFAULT_MODEL, "gemma-4", "gemma4:e4b", "gemma-4-e4b-it"}


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


def call_ollama_json(model, prompt, fallback, options_override=None):
    raw, transport = call_ollama_with_transport(model, prompt, options_override=options_override)
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


WORKER_ACTION_BEGIN = "<<<GFORGE_WORKER_ACTION>>>"
WORKER_ACTION_END = "<<<END_GFORGE_WORKER_ACTION>>>"
WORKER_ACTION_PATTERN = re.compile(
    rf"{re.escape(WORKER_ACTION_BEGIN)}\s*(.*?)\s*{re.escape(WORKER_ACTION_END)}",
    flags=re.DOTALL,
)
WORKER_ACTION_CARDS = {"intake", "forge-flow", "gsd", "execution", "socraticode", "axon", "verification", "handoff"}


def parse_worker_action_requests(text):
    """
    Extract bounded chat-to-worker requests.

    The model can ask the browser harness to run the existing card flow, but it
    cannot invent arbitrary tools or endpoints. The client decides when to call
    the normal /cards/<id>/run or Full Forge flow from this structured request.
    """
    if not text:
        return []

    actions = []
    for match in WORKER_ACTION_PATTERN.finditer(text):
        fields = {}
        for raw_line in match.group(1).splitlines():
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            fields[key.strip().lower()] = value.strip()

        action = re.sub(r"[\s-]+", "_", fields.get("action", "").strip().lower())
        card = fields.get("card", "").lower()
        reason = truncate_text(fields.get("reason", ""), 220)

        if action == "full_forge":
            actions.append({"action": "full_forge", "reason": reason})
        elif action == "run_card" and card in WORKER_ACTION_CARDS:
            actions.append({"action": "run_card", "card": card, "reason": reason})

    return actions[:1]


def strip_worker_action_blocks(text):
    if not text:
        return ""
    return WORKER_ACTION_PATTERN.sub("", text).strip()


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

def save_sessions(sessions, create_keys=None, update_keys=None):
    """Race-safe save.

    The bug this prevents: a long-running request (card run, chat
    message, anything that takes seconds-to-minutes) does:
        sessions = load_sessions()      # snapshot at request start
        ... model call takes 30-60s ...
        # MEANWHILE: user deletes session X in the UI
        save_sessions(sessions)         # writes the whole in-memory dict
    The naive write resurrects X because the snapshot still has it.

    This version re-reads disk RIGHT before writing. Callers should pass
    `update_keys` for the project records they actually mutated; other
    on-disk records are kept as-is so parallel project runs cannot roll
    each other backward with stale snapshots. Keys that vanished from disk
    while the request ran (i.e. were deleted) are NOT resurrected.

    `create_keys`: iterable of session_ids that are legitimately NEW
    creates (passed by create_session). Those bypass the on-disk
    intersection and get written even though disk doesn't know them.
    `update_keys`: iterable of existing session_ids this request changed.
    If omitted, save_sessions preserves the previous broad merge behavior
    for compatibility, but request handlers should be explicit.

    For deletes, use `write_sessions_full(sessions)` from the
    delete_session endpoint — that's the one place where the
    in-memory dict IS the authoritative post-delete state.
    """
    ensure_storage()
    create_keys = set(create_keys or [])
    update_keys = None if update_keys is None else set(update_keys or [])
    on_disk = {}
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r") as f:
                on_disk = json.load(f)
        except (OSError, json.JSONDecodeError):
            on_disk = {}
    merged = {}
    for sid, disk_record in on_disk.items():
        # Disk is authoritative for existence. Explicitly updated records
        # win; untouched records stay as the latest on-disk version.
        if update_keys is None:
            merged[sid] = sessions.get(sid, disk_record)
        elif sid in update_keys and sid in sessions:
            merged[sid] = sessions[sid]
        else:
            merged[sid] = disk_record
    for sid in create_keys:
        if sid in sessions:
            merged[sid] = sessions[sid]
    with open(SESSIONS_FILE, "w") as f:
        json.dump(merged, f, indent=4)
    return merged


def write_sessions_full(sessions):
    """Unconditional full-replace write. Use ONLY for delete_session,
    where the in-memory dict is the authoritative post-delete state.
    Everything else should use save_sessions() for race safety."""
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
    """Server-Sent Events feed of structured harness activity.

    Pass `?session_id=session_xxx` to filter to one session's events.
    Omit the param to subscribe to everything (legacy / setup screen).
    """
    session_filter = request.args.get("session_id", "").strip() or None

    def generate():
        q, snapshot = _subscribe_events(session_filter=session_filter)
        try:
            for event in snapshot[-80:]:
                yield f"data: {json.dumps(event)}\n\n"
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
    """Polling fallback if SSE is blocked by a proxy. Honors session_id filter."""
    session_filter = request.args.get("session_id", "").strip() or None
    with _EVENT_LOCK:
        buffered = [
            e for e in _EVENT_BUFFER
            if session_filter is None
            or e.get("session_id") == session_filter
        ]
    if session_filter:
        persisted = _load_session_event_log(session_filter)
        restored = _session_record_event_fallback(session_filter) if not persisted else []
        snapshot = _dedupe_events(restored + persisted + buffered)
    else:
        snapshot = buffered
    return jsonify({"events": snapshot[-200:]})

@app.route('/api/models', methods=['GET'])
def get_models():
    return jsonify(model_payload())

@app.route('/api/models/import', methods=['POST'])
def import_models():
    payload = model_payload(import_installed=True)
    return jsonify(payload)


@app.route('/api/models/search', methods=['GET'])
def search_hf_models():
    query = normalize_hf_model_query(request.args.get("q", ""))
    if not query:
        return jsonify({"error": "Search text is required."}), 400

    offset = clamp_int(
        request.args.get("offset", 0),
        0,
        HF_MODEL_SEARCH_MAX_OFFSET,
        0,
    )

    try:
        detected = scan_workspace()
        installed_models = detected.get("ollama", {}).get("models", [])
        payload = hf_search_results(query, offset=offset, installed_models=installed_models)
    except Exception as error:
        log_error("hf-model-search", "Hugging Face model search failed.", error, {"query": query, "offset": offset})
        return jsonify({"error": "Hugging Face search failed. Check the query or network connection."}), 502

    return jsonify(payload)


@app.route('/api/models/provision', methods=['POST'])
def provision_model():
    data = request.json or {}
    model_name = normalize_model_name(data.get("ollamaName", "").strip() or DEFAULT_MODEL)
    repo_id = normalize_hf_model_query(data.get("repoId", ""))
    create_interface = bool(data.get("createInterface"))
    download_only = bool(data.get("downloadOnly"))

    validation_error = validate_ollama_model_name(model_name)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    detected = scan_workspace()
    installed = is_ollama_model_installed(model_name, detected["ollama"]["models"])

    registry = load_models()
    existing_record = next(
        (model for model in registry.get("models", []) if model_name_matches(model, model_name)),
        None,
    )
    if not repo_id and existing_record:
        stored_source = normalize_hf_model_query(existing_record.get("source", ""))
        if stored_source and stored_source != "ollama":
            repo_id = stored_source

    if installed:
        upsert_registry_model(registry, {
            "name": model_name,
            "source": repo_id or "ollama",
            "status": "installed",
            "downloadOnly": download_only,
            "createInterface": create_interface,
            "updatedAt": utc_now(),
        })
        save_models(registry)
        result = {
            "status": "skipped",
            "runnable": True,
            "message": f"Ready: {model_name} is installed in Ollama and can be used as a Forge Brain.",
            "registry": registry,
        }
    else:
        if not repo_id:
            return jsonify({
                "error": "Choose a Hugging Face repo before provisioning a model that is not already installed in Ollama.",
                "registry": registry,
            }), 400
        repo_error = validate_hf_repo_id(repo_id)
        if repo_error:
            return jsonify({
                "error": repo_error,
                "registry": registry,
            }), 400
        if snapshot_download is None:
            return jsonify({
                "error": "huggingface_hub is not installed, so Gemma Forge cannot download Hugging Face models.",
                "registry": registry,
            }), 503

        job = start_model_provision_job({
            "repoId": repo_id,
            "modelName": model_name,
            "createInterface": create_interface,
            "downloadOnly": download_only,
            "quantization": normalize_quantization(data.get("quantization")),
        })
        registry = load_models()
        result = {
            "status": job["status"],
            "runnable": False,
            "message": job["message"],
            "registry": registry,
            "jobId": job["id"],
            "job": job,
        }

    if create_interface and installed:
        sessions = load_sessions()
        session_id = create_session_record(
            sessions,
            f"Model interface for {model_name}",
            model_name,
        )
        save_sessions(sessions, create_keys={session_id})
        result["session_id"] = session_id

    return jsonify(result), 200 if installed else 202


@app.route('/api/models/provision/<job_id>', methods=['GET'])
def model_provision_job_status(job_id):
    job = model_provision_job_snapshot(job_id)
    if not job:
        return jsonify({"error": "Provisioning job was not found."}), 404
    return jsonify({"job": job, "registry": load_models()})

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

    model = normalize_model_name(data.get("model", DEFAULT_MODEL))
    readiness = selected_model_readiness(model)
    if not readiness["ready"]:
        return model_not_ready_response(readiness)

    session_id = create_session_record(
        sessions,
        project,
        model,
        data.get("session_id"),
        has_project_directory,
        project_directory,
    )
    save_sessions(sessions, create_keys={session_id})
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
        readiness = selected_model_readiness(model)
        if not readiness["ready"]:
            return model_not_ready_response(readiness)
        sessions[session_id]["model"] = model
        changed = True
    if "fallbackModel" in data:
        fallback = normalize_model_name(data.get("fallbackModel") or "")
        if fallback:
            readiness = selected_model_readiness(fallback)
            if not readiness["ready"]:
                return model_not_ready_response(readiness)
        sessions[session_id]["fallbackModel"] = fallback
        changed = True
    if not changed:
        return jsonify({"error": "model or fallbackModel is required."}), 400

    write_session_context(session_id, sessions[session_id])
    save_sessions(sessions, update_keys={session_id})
    return jsonify({"session": sessions[session_id]})


def session_is_archived(session):
    return bool(isinstance(session, dict) and session.get("archivedAt"))


def archived_session_response():
    return jsonify({
        "error": "Archived projects are read-only. Restore the project before running cards or sending messages.",
    }), 409


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

    # delete_session is the one place where the in-memory dict IS the
    # authoritative post-state (we just popped the deleted key). Use the
    # full-replace writer so the deletion actually takes — the race-safe
    # save_sessions would re-read disk and resurrect the deleted key.
    write_sessions_full(sessions)
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
    sessions = save_sessions(sessions, update_keys={session_id})
    return jsonify({
        "session_id": session_id,
        "archived": should_archive,
        "session": sessions.get(session_id, session),
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
    save_sessions(sessions, update_keys=session_ids)
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

    readiness = selected_model_readiness(model)
    if not readiness["ready"]:
        return model_not_ready_response(readiness)

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
    # Deleted sessions must stay deleted. Previously this helper silently
    # lazy-created an empty list for any unknown session_id, which meant a
    # stale browser tab or cached client POST to /api/chat with the id of
    # a session the user had just deleted would resurrect it as a ghost
    # entry in sessions.json (with no on-disk session-data dir). Now we
    # refuse the write and return 404 — matches the modern
    # /api/sessions/<id>/messages endpoint's behavior.
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    sessions = load_sessions()
    if session_id not in sessions:
        return jsonify({"error": "Unknown or deleted project. Start a new project to chat."}), 404
    if isinstance(sessions[session_id], list):
        sessions[session_id].append({"role": "user", "content": user_msg})
        sessions[session_id].append({"role": "assistant", "content": assistant_reply})
    else:
        sessions[session_id].setdefault("messages", [])
        sessions[session_id]["messages"].append({"role": "user", "content": user_msg})
        sessions[session_id]["messages"].append({"role": "agent", "content": assistant_reply})
    save_sessions(sessions, update_keys={session_id})
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
    if session_is_archived(session):
        return archived_session_response()

    model = data.get("model") or session.get("model", DEFAULT_MODEL)
    readiness = selected_model_readiness(model)
    if not readiness["ready"]:
        return model_not_ready_response(readiness)
    session["model"] = model
    session.setdefault("messages", [])
    session["messages"].append({"role": "user", "content": message})

    # event_session_scope stamps the session_id onto every emit_event
    # called inside (ollama call, chat-write, etc.) so they only route to
    # this session's terminal subscriber.
    with event_session_scope(session_id):
        workspace_dir = (session.get("projectDirectory") or "").strip()
        skill_context = None
        if workspace_dir and os.path.isdir(workspace_dir):
            skill_context = prepare_workspace_skill_context(workspace_dir, session)

        reply = call_ollama(model, build_session_prompt(session, message, skill_context))
        worker_actions = parse_worker_action_requests(reply)
        if worker_actions:
            reply = strip_worker_action_blocks(reply)

        # Chat replies can now materialize files into the project workspace
        # using the same GFORGE_FILE pipeline as the Execution card. The model
        # is told in the prompt that it can emit blocks; here we parse + write
        # them if the project has a workspace on disk.
        materialization_summary = ""
        if workspace_dir and os.path.isdir(workspace_dir):
            payload = parse_forge_file_payload(reply)
            if isinstance(payload, dict) and payload.get("files"):
                files, rejected = normalize_model_files(payload.get("files", []))
                written = []
                for item in files:
                    try:
                        path = write_project_file(workspace_dir, item["path"], item["content"])
                        written.append({
                            "path": item["path"],
                            "sha256": file_sha256(path),
                            "bytes": os.path.getsize(path),
                        })
                    except Exception as write_err:
                        rejected.append({"path": item.get("path", ""), "reason": str(write_err)})

                link_failures = validate_local_link_targets(workspace_dir, written) if written else []
                emit_event(
                    "chat-write",
                    f"chat materialized {len(written)} file(s) into workspace",
                    wrote=len(written),
                    rejected=len(rejected),
                    linkFailures=len(link_failures),
                )

                lines = ["", "---", "**Harness wrote these files to the workspace:**"]
                for w in written:
                    abs_path = os.path.join(workspace_dir, w["path"])
                    from urllib.parse import quote
                    href = "file://" + quote(abs_path, safe="/:")
                    lines.append(f"- [`{w['path']}`]({href}) ({w['bytes']} bytes)")
                if rejected:
                    lines.append("")
                    lines.append("**Rejected (unsafe path or write error):**")
                    for r in rejected:
                        lines.append(f"- `{r.get('path','?')}` — {r.get('reason','')}")
                if link_failures:
                    lines.append("")
                    lines.append("**⚠ Link-target validation failures:**")
                    for f in link_failures:
                        lines.append(f"- {f}")
                materialization_summary = "\n".join(lines)
            elif "<<<GFORGE_FILE:" in reply:
                # Model tried to emit but the parser couldn't recover any blocks
                # (malformed delimiters, missing END, etc.). Surface that so the
                # user knows why nothing landed on disk.
                materialization_summary = (
                    "\n\n---\n**⚠ The model tried to emit GFORGE_FILE blocks but none "
                    "could be parsed.** Check the reply for malformed delimiters."
                )

    if materialization_summary:
        reply = reply + materialization_summary
    if worker_actions:
        action = worker_actions[0]
        if action.get("action") == "full_forge":
            action_label = "Full Forge"
        else:
            action_label = f"Forge Section `{action.get('card')}`"
        reply = (
            reply.rstrip()
            + "\n\n---\n"
            + f"**Harness queued worker action:** {action_label}."
        )

    session["messages"].append({"role": "agent", "content": reply})
    write_session_context(session_id, session)
    save_sessions(sessions, update_keys={session_id})
    return jsonify({"reply": reply, "session": session, "workerActions": worker_actions})

@app.route('/api/sessions/<session_id>/cards/<card_id>/run', methods=['POST'])
def run_session_card(session_id, card_id):
    data = request.json or {}
    sessions = load_sessions()
    if session_id not in sessions or not isinstance(sessions[session_id], dict):
        return jsonify({"error": "Start or select a project first."}), 404

    session = sessions[session_id]
    if session_is_archived(session):
        return archived_session_response()

    model = data.get("model") or session.get("model", DEFAULT_MODEL)
    readiness = selected_model_readiness(model)
    if not readiness["ready"]:
        return model_not_ready_response(readiness)
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
    correction = build_correction_from_state(session, card_id, issue_note) if issue_note else None
    # event_session_scope stamps session_id onto every emit_event called
    # inside (including nested ollama, browse, screenshot, validation
    # events from card handlers) so the SSE subscriber filter routes them
    # only to the matching session's terminal.
    with event_session_scope(session_id):
        if correction:
            emit_event("card-start", f"{card_id} starting (resolve: {len(correction.get('findings', []))} findings + user note)",
                       session=session_id, model=model, mode=mode)
        else:
            emit_event("card-start", f"{card_id} starting", session=session_id, model=model, mode=mode)
        result = run_card_action(session_id, session, card_id, model, mode, correction=correction)
        finalize_card_result(session_id, session, card_id, model, result, human_verify, correction=correction)
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
    save_sessions(sessions, update_keys={session_id})
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
    if session_is_archived(session):
        return archived_session_response()

    model = data.get("model") or session.get("model", DEFAULT_MODEL)
    readiness = selected_model_readiness(model)
    if not readiness["ready"]:
        return model_not_ready_response(readiness)
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
    save_sessions(sessions, update_keys={session_id})
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

    readiness = selected_model_readiness(model)
    if not readiness["ready"]:
        return model_not_ready_response(readiness)

    sessions = load_sessions()
    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        if session_is_archived(sessions[session_id]):
            return archived_session_response()

    resource_state = scan_workspace()
    session_for_prompt = {
        "project": project,
        "projectMode": "unknown",
        "projectDirectory": "",
    }
    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        session_for_prompt = sessions[session_id]
        session_for_prompt["model"] = model

    prompt = build_mode_aware_planning_prompt(session_for_prompt, checkpoint_mode, resource_state)
    planning_options = planning_model_options(model)
    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        with event_session_scope(session_id):
            reply, transport = call_ollama_with_transport(model, prompt, options_override=planning_options)
    else:
        reply, transport = call_ollama_with_transport(model, prompt, options_override=planning_options)

    if not reply:
        reply = transport_failure_message(transport)

    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        sessions[session_id].setdefault("messages", [])
        sessions[session_id]["messages"].append({"role": "agent", "content": reply})
        write_session_context(session_id, sessions[session_id])
        save_sessions(sessions, update_keys={session_id})

    cards = default_cards(session_for_prompt.get("projectMode", "unknown"))
    if session_id and session_id in sessions and isinstance(sessions[session_id], dict):
        cards = sessions[session_id].get("cards", cards)

    return jsonify({"reply": reply, "cards": cards})


OLLAMA_REQUEST_TIMEOUT_SECONDS = 1200
OLLAMA_KEEP_ALIVE = "30m"
# Harness-wide temperature for card work in the flow. Some Modelfile defaults
# are too high for instruction-following, and the model
# drifted on structured outputs (e.g. small-model reviewer generating
# the project's files in the review step). 0.6 keeps prose / code natural
# enough without the drift.
# Per-call overrides via options_override still apply, e.g. the Project
# Context Writer + small-model reviewer use CONTEXT_DELIBERATION_OPTIONS
# (temperature=0.1) for fully deterministic structured-output paths.
# num_ctx / num_predict are NOT overridden here — those stay at each
# Modelfile's defaults (gempus4:tuned's 65536 ctx, etc.).
OLLAMA_DEFAULT_OPTIONS = {"temperature": 0.3}
PLANNING_MODEL_OPTIONS = {"temperature": 0.2, "num_predict": 768}
TINY_MODEL_MAX_B = 1.5


def planning_model_options(model):
    options = dict(PLANNING_MODEL_OPTIONS)
    size = selected_model_size_b(model)
    if size is not None and size <= TINY_MODEL_MAX_B:
        options["num_predict"] = 384
    return options


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


def build_gsd_context_prompt_block(session):
    if not isinstance(session, dict):
        session = {"project": str(session or "")}
    context = session.get("projectContext") if isinstance(session.get("projectContext"), dict) else {}
    raw_yaml = session.get("projectContextRaw") if isinstance(session.get("projectContextRaw"), str) else ""
    if not raw_yaml and context:
        raw_yaml = dump_project_context_yaml(context)
    source_inputs = context.get("source_inputs") if isinstance(context.get("source_inputs"), list) else []
    tool_plan = context.get("tool_plan") if isinstance(context.get("tool_plan"), list) else []
    gsd_directives = context.get("gsd_directives") if isinstance(context.get("gsd_directives"), dict) else {}
    skill_plan = context.get("skill_plan") if isinstance(context.get("skill_plan"), list) else []
    lines = [
        "GSD operating context (binding):",
        f"- Selected model: `{session.get('model', DEFAULT_MODEL)}`",
        "- Do not rephrase the user request as the plan. Convert intent into executable phases with tool routing and verification gates.",
        "- Every stated count is a hard gate. A plan that delivers fewer items than requested is wrong.",
        "- Every staged skill is an operational instruction source. Use it when it fits; ignore it quietly when it does not.",
        "- For web research, Scrapling is the first browser/scraping option. Research must create/cite workspace artifacts.",
        "- For local file/directory references, Execution must use imported workspace-relative source paths and command evidence.",
        "- Use the GSD suite perspective: discovery/map-codebase/research-phase/plan-phase/execute-phase/verify-work/audit/review as applicable, not a shallow bullet list.",
        "",
    ]
    if raw_yaml:
        lines.extend(["Project Context contract:", "```yaml", raw_yaml.strip(), "```", ""])
    if source_inputs:
        lines.append("Source inputs that GSD must route:")
        for item in source_inputs:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('original_path')}` ({item.get('kind')}) -> workspace import before execution")
        lines.append("")
    if skill_plan:
        lines.append("Skill plan:")
        for item in skill_plan:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('skill')}`: {item.get('role')} at `{item.get('staged_path')}`")
        lines.append("")
    if tool_plan:
        lines.append("Tool plan:")
        for item in tool_plan:
            if isinstance(item, dict):
                lines.append(f"- {item.get('step')}: `{item.get('tool')}` with evidence `{item.get('evidence')}`")
        lines.append("")
    if gsd_directives:
        lines.extend(["GSD directives:", "```json", json.dumps(gsd_directives, indent=2), "```", ""])
    return "\n".join(lines)


def build_gsd_skill_context_section(skill_context_prompt):
    if not skill_context_prompt:
        return ""
    return (
        "GSD Skill Context (staged instructions for this planning pass):\n"
        f"{skill_context_prompt}\n"
    )


def build_planning_prompt(project, checkpoint_mode, resource_state, gsd_skill_context=None):
    session = project if isinstance(project, dict) else {"project": project}
    project_text = session.get("project", "")
    capacity = resource_state.get("agentCapacity", {})
    forge_context = read_forge_context()
    research_policy = research_budget_text(session)
    gsd_context = build_gsd_context_prompt_block(session)
    skill_context_section = build_gsd_skill_context_section(gsd_skill_context)
    return f"""You are the Gemma Forge planning agent.
This is a work harness, not a chat interface.

{forge_context}

Project to plan:
{project_text}

{gsd_context}

{skill_context_section}

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
    gsd_context = build_gsd_context_prompt_block(session)
    base = f"""You are the Gemma Forge planning agent.
This is a work harness, not a chat interface.

{forge_context}

Project to plan:
{session.get('project', '')}

{gsd_context}

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


def build_session_prompt(session, message, skill_context=None):
    resource_state = scan_workspace()
    capacity = resource_state.get("agentCapacity", {})
    linked = session.get("bridges", [])
    history = session.get("messages", [])[-10:]
    history_lines = [f"{item.get('role')}: {item.get('content')}" for item in history]
    forge_context = read_forge_context()
    research_policy = research_budget_text(session)
    workspace_dir = (session.get("projectDirectory") or "").strip()
    workspace_exists = bool(workspace_dir) and os.path.isdir(workspace_dir)

    # Tell the chat agent it CAN materialize files into the project workspace.
    # This is the same GFORGE_FILE pipeline the Execution card uses — the
    # harness parses any blocks in your reply and writes them to disk.
    if workspace_exists:
        # Build a short listing of what's already in the workspace so the
        # model knows what's there and can reference real files instead of
        # asking the user "what's in your folder?".
        try:
            top = sorted(os.listdir(workspace_dir))[:40]
        except OSError:
            top = []
        existing = "\n".join(f"- {name}" for name in top) or "(empty)"
        file_emission_block = f"""

You CAN write files into this project's workspace directly from chat.

Workspace root (already exists on disk): {workspace_dir}

Files currently in the workspace root:
{existing}

If the user asks you to add, edit, or create a file, emit it as a
GFORGE_FILE block in your reply — the harness will materialize it to disk:

    <<<GFORGE_FILE:relative/path/to/file.ext>>>
    <complete file contents — no abbreviation, no triple-backtick fence>
    <<<END_GFORGE_FILE>>>

Rules:
- Paths are relative to the workspace root above. Do NOT use absolute paths or `..`.
- Include the FULL file contents, not patches.
- If you reference a file via HTML href / src / url() or markdown link, the
  deterministic validator checks that the target exists on disk. Either
  emit it as its own GFORGE_FILE block or do not link to it.
- After the GFORGE_FILE blocks, write a short plain-English summary of what
  you did and why (so the user reading the chat sees a recap). The harness
  appends a clickable file list automatically — do not write `file://` URLs
  yourself.
- If the user only asked a question (no file change needed), just answer.
  Do not fabricate file blocks just to look productive.

Do NOT respond with "I'm just an agent, I can't create files" — you CAN
in this project. The harness materializes whatever GFORGE_FILE blocks you
emit into the workspace above."""
    else:
        file_emission_block = """

This project does not have a workspace directory on disk yet. Run the
Project Execution card first to create one. For now, answer the user's
question in plain text — file emission is disabled until the workspace
exists."""

    skill_block = (skill_context or {}).get("prompt") or (
        "No Gemma Forge skills are staged for this chat turn."
    )
    worker_action_block = f"""

Worker handoff:
- You are the conversational project agent. The protocol-card worker is the
  only layer that actually runs Forge Flow, GSD, Project Execution,
  SocratiCode, Axon, Verification, and Handoff.
- If the user explicitly asks you to continue, rerun, fix, verify, audit with a
  tool card, or run a specific Forge Section, you may ask the harness to trigger
  the existing worker flow. Do not claim it has run yet; say the harness will
  run it.
- Emit at most one worker action block, and only one of these forms:

{WORKER_ACTION_BEGIN}
action: full_forge
reason: short reason
{WORKER_ACTION_END}

{WORKER_ACTION_BEGIN}
action: run_card
card: intake|forge-flow|gsd|execution|socraticode|axon|verification|handoff
reason: short reason
{WORKER_ACTION_END}

- Do not use this block for ordinary questions. Do not invent card names or
  arbitrary shell/tool actions."""

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

Gemma Forge skill context for this chat turn:
{skill_block}

Recent project context:
{chr(10).join(history_lines)}
{file_emission_block}
{worker_action_block}

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
    kwarg. Tool cards (axon, socraticode) get it so they can honor a
    user-typed override note ("I've seen these findings, advance the chain")
    that a re-run of the tool itself can't satisfy. Other handlers ignore it.
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
    if card_id in {"execution", "verification", "axon", "socraticode"}:
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


def finalize_card_result(session_id, session, card_id, model, result, human_verify, correction=None):
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

    # User override path — only applies to tool cards (axon, socraticode)
    # because re-running those tools never changes their deterministic
    # findings, so without an override the chain would loop on Resolve.
    # For execution/verification, the correction flows into the model
    # prompt and a re-run can actually fix things, so no override needed.
    user_override_note = ""
    if isinstance(correction, dict):
        user_override_note = str(correction.get("userNote", "")).strip()
    override_applies = (
        user_override_note
        and card_id in {"axon", "socraticode"}
    )

    if review and not review.get("passed"):
        if override_applies:
            # User reviewed the findings + explicitly chose to advance.
            # Mark the reviewer as overridden so the audit trail keeps both
            # the original verdict AND the user's deciding note.
            review["userOverridden"] = True
            review["userOverrideNote"] = user_override_note
        else:
            result["status"] = "needs-attention"
            result["checkpoint"] = small_model_review_checkpoint(review)
            return result

    tool_execution = result.get("toolExecution")
    if isinstance(tool_execution, dict) and tool_execution.get("requiresAttention"):
        if override_applies:
            tool_execution["requiresAttention"] = False
            tool_execution.setdefault("userOverride", user_override_note)
        else:
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

    result["summary"] = "Post-review continuation repair updated model-authored execution and verification packaging."
    result["details"] = build_model_execution_report(workspace_dir, execution)
    result["checkpoint"] = "Open the repaired delivery artifacts and confirm the generated project meets the requested outcome."
    result["artifact"] = write_artifact(session_id, "execution.md", result["details"])
    result["workspace"] = workspace_dir
    result["validation"] = execution.get("validation", {})
    return {
        "attempt": attempt,
        "card": "execution",
        "changed": True,
        "action": "Ran continuation repair with current workspace context, reviewer blockers, and validation packaging.",
        "reviewSummary": review.get("summary", ""),
        "artifact": result["artifact"],
        "validation": result["validation"],
    }


def repair_verification_after_review(session_id, session, result, review, attempt):
    # Verification is intentionally read-only. It may rebuild the verification
    # report from the current artifacts, but it must never rerun Project
    # Execution or rewrite deliverables. A failed deterministic check should
    # return needs-attention for the Execution card / user, not mutate files
    # from inside Verification.
    repair_model = session.get("model", DEFAULT_MODEL)
    details, validation = build_verification_details(
        session_id, session, "post-review repair", repair_model, review,
    )

    result["summary"] = "Post-review patch rebuilt verification from existing artifacts only."
    result["details"] = details
    result["checkpoint"] = "Inspect the verification report and confirm the generated project meets the requested outcome."
    result["artifact"] = write_artifact(session_id, "verification.md", details)
    result["validation"] = validation
    action = "Rebuilt verification from the actual workspace files, validation artifact, and original user request."
    return {
        "attempt": attempt,
        "card": "verification",
        "changed": False,
        "action": action,
        "reviewSummary": review.get("summary", ""),
        "artifact": result["artifact"],
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
    # Tool cards (socraticode + axon) — their card output is a mechanical
    # log of what an external process actually did. The small-model
    # reviewer judging that report (and then triggering a model-rewrite
    # repair loop) burns minutes of inference for zero functional gain,
    # because rewriting the report doesn't change what the tool found.
    # Trust the tool's own status reporting; skip the meta-review.
    if card_id in {"socraticode", "axon"}:
        return {
            "required": False,
            "passed": True,
            "model": model,
            "reason": (
                f"Tool card '{card_id}' reports its own real-tool execution "
                "status; no small-model review needed."
            ),
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

YOUR ONLY JOB IS TO RETURN A JSON OBJECT EVALUATING THE PRIOR SECTION'S OUTPUT.
You are NOT the author. You are NOT the executor. You do NOT write code, files,
HTML, JSON deliverables, or "Generated Files" sections here. If you find yourself
about to write ```json ... ``` content that looks like the project's deliverable,
STOP — that work belongs to the Execution card, not the review step. Your output
is a SHORT JUDGMENT, nothing more.

The selected model is {model}, which is at or below {SMALL_MODEL_REVIEW_MAX_B}B parameters, so this section requires one extra review before it can be marked complete.

Review as an auditor who assumes the section may be wrong or incomplete.

Original project request (CONTEXT ONLY — do not execute it):
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
- If validation data exists and says passed is true, do not fail because a
  count is greater than the requested minimum. `deliverable.count` and
  content quantity checks are deterministic contract gates; treat reviewer
  disagreement about file count, path pattern, PDF validity, or content
  quantity as a warning unless you can name a specific artifact mismatch not
  covered by validation.
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
    # Reviewer runs at low temperature (same as Context Writer) so the small
    # model doesn't drift off the JSON instruction and start generating the
    # project's actual files in the reviewer step. 0.1 keeps it
    # deterministic and JSON-focused.
    payload, raw, transport = call_ollama_json(
        model, prompt, fallback, options_override=CONTEXT_DELIBERATION_OPTIONS,
    )
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

    if (
        isinstance(validation, dict)
        and validation
        and validation.get("passed") is True
        and card_id == "verification"
        and not payload.get("passed")
    ):
        payload["passed"] = True
        payload["summary"] = (
            "Verification reviewer concern was downgraded because deterministic validation passed."
        )
        findings = listify(payload.get("findings"))
        findings.append(
            "Verification is read-only: when deterministic validation passes, reviewer concerns are reported as warnings and must not trigger deliverable repair."
        )
        payload["findings"] = findings
        payload["fixesNeeded"] = []

    if (
        isinstance(validation, dict)
        and validation
        and validation.get("passed") is True
        and not payload.get("passed")
        and review_conflicts_with_passed_validation(payload)
    ):
        payload["passed"] = True
        payload["summary"] = (
            "Reviewer count concern was downgraded because deterministic validation passed."
        )
        findings = listify(payload.get("findings"))
        findings.append(
            "Deterministic validation is authoritative for file count, path pattern, PDF integrity, and content quantity gates when it passes."
        )
        payload["findings"] = findings
        payload["fixesNeeded"] = []

    payload["required"] = True
    payload["model"] = model
    payload["thresholdB"] = SMALL_MODEL_REVIEW_MAX_B
    payload["checkedAt"] = utc_now()
    payload["raw"] = truncate_text(raw, 1200)
    artifact = write_artifact(session_id, f"{safe_id(card_id)}-extra-review.md", build_review_artifact(card_id, payload))
    payload["artifact"] = artifact
    return payload


def review_conflicts_with_passed_validation(review):
    text = " ".join(
        [str(review.get("summary", ""))]
        + [str(item) for item in listify(review.get("findings"))]
        + [str(item) for item in listify(review.get("fixesNeeded"))]
    ).lower()
    if not text:
        return False
    validation_markers = {
        "validation",
        "deterministic",
        "deliverable.count",
        "content requirement",
        "file count",
        "path pattern",
        "pdf",
    }
    count_markers = {
        "actual",
        "at least",
        "count",
        "exactly",
        "expected",
        "file",
        "files",
        "generated",
        "report",
        "reports",
        "category",
        "categories",
        "wrote",
    }
    if not any(marker in text for marker in validation_markers):
        return False
    if not any(marker in text for marker in count_markers):
        return False

    # Keep genuine artifact/content mismatches blocking. This guard is only for
    # reviewer re-interpretations of gates the deterministic validator already
    # passed, such as treating "at least 3 categories" as "exactly 3".
    concrete_blockers = {
        "broken link",
        "does not match the requested text",
        "incorrect phrase",
        "runtime error",
        "syntax error",
        "wrong phrase",
        "wrong text",
    }
    return not any(marker in text for marker in concrete_blockers)


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
    "import_source_inputs",  # copy user-referenced local files/directories into the workspace
    "harness_maintenance",   # controlled updates to explicit Gemma Forge install/runtime targets
    "run_local_skill",       # consume a pre-staged skill from ~/.gforge/harness/skills/
    "call_local_gemma",      # talk to the local Ollama model
    "read_forge_context",    # read forge.md and staged skill files
    "validate_files",        # XML/JSON/YAML validity, file count, path pattern, claim verification
]

_HARNESS_CANNOT_DO_BASE = [
    "system_package_install", # cannot brew/apt/sudo/global system install
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
    if tool_workspace.can_clone_repositories():
        can.append("git_clone")
        if tool_workspace.is_gh_authenticated():
            can.append("github_auth")
    else:
        cannot.append("git_clone")
    if tool_workspace.can_run_workspace_commands():
        can.append("shell_exec")
    else:
        cannot.append("shell_exec")
    if tool_workspace.can_install_packages():
        can.append("install_package")
    else:
        cannot.append("install_package")
    return can, cannot


HARNESS_CAN_DO_DESCRIPTIONS = {
    "emit_files": "write files into the workspace via GFORGE_FILE blocks",
    "import_source_inputs": "copy explicit local file/directory references into workspace/references/input/ before execution",
    "harness_maintenance": "apply controlled Gemma Forge maintenance actions only to allowlisted install/runtime targets",
    "run_local_skill": "consume a pre-staged skill from ~/.gforge/harness/skills/",
    "call_local_gemma": "call the local Ollama Gemma model",
    "read_forge_context": "read forge.md and any staged skill files",
    "validate_files": "validate file structure, count, path pattern, and verify claims against disk",
    "web_browse": "fetch / scrape web pages via scrapling (request, browser, or stealth modes)",
    "web_fetch": "GET arbitrary URLs into workspace/research/ files (alias of web_browse)",
    "screenshot_capture": "render a URL or local HTML file via headless Playwright and save a PNG to workspace/screenshots/",
    "git_clone": "clone GitHub/GitLab/Bitbucket repositories into workspace/references/repos/ using git or authenticated gh when available",
    "github_auth": "use the host GitHub CLI authentication for GitHub clone operations; never print tokens",
    "shell_exec": "run bounded validation/build commands inside the workspace sandbox; no deploy, push, system install, or path escape",
    "install_package": "install project dependencies inside the workspace sandbox with npm/pnpm/yarn or pip --target .gforge-installs/python",
}


# Snapshot at import. The authoritative values come from harness_capabilities()
# which is recomputed each call so newly-installed tools register immediately.
HARNESS_CAN_DO, HARNESS_CANNOT_DO = harness_capabilities()


# Regex patterns that signal a capability is required by the user request.
CAPABILITY_KEYWORDS = {
    "harness_maintenance": [
        r"\b(gemma\s+forge|forge\s+harness|forge\s+brain|forge\s+engine|harness)\b.*\b(add|change|default|fix|install|patch|remove|repair|route|set|stage|update)\b",
        r"\b(add|change|default|fix|install|patch|remove|repair|route|set|stage|update)\b.*\b(gemma\s+forge|forge\s+harness|forge\s+brain|forge\s+engine|harness)\b",
        r"\b(add|remove|update|stage)\s+(a\s+|the\s+)?(forge\s+)?skill\b",
        r"\b(set|change|confirm|make)\s+(the\s+)?default\s+(forge\s+brain\s+)?model\b",
        r"\b(context\s+writer|project\s+context|gsd\s+planning|skill\s+routing|clean[-\s]?install|installer|provision(?:ing)?)\b.*\b(gemma\s+forge|harness|forge)\b",
    ],
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
        r"\b(scrape|scraping|crawl|crawling)\s+(the\s+)?(web|internet|sites?|websites?|pages?|articles?|sources?|news|headlines|data)\b",
        r"\bextract\s+(data|content|articles?|headlines?)\s+from\s+(the\s+)?(web|internet|sites?|websites?|pages?|urls?)\b",
        r"\b(live|latest|current|real[-\s]?time)\s+(news|headlines|articles?|web\s+data|site\s+data)\b",
        r"\bnews\s+(feed|ticker|headlines?|articles?)\b",
        r"\b(headlines?|articles?)\s+from\s+(the\s+)?(web|internet|sites?|websites?|urls?)\b",
    ],
    "shell_exec": [
        r"\brun\s+(this\s+|that\s+)?(command|script|shell|terminal)\b",
        r"\brun\s+(the\s+)?(script|tests?|test suite|build)\b",
        r"\brun\s+[A-Za-z0-9_.-]+\.(py|js|sh|bash|zsh)\b",
        r"\bexecute\s+(this\s+|that\s+)?(command|script)\b",
        r"\b(npm|pip|pip3|pnpm|yarn)\s+(install|add)\b",
        r"\bpython3?\s+-m\s+pip\s+install\b",
        r"\bbash\s+-c\b",
    ],
    "install_package": [
        r"\b(install|add)\s+(the\s+)?(package|module|library|dependency)\b",
        r"\binstall\s+[A-Za-z0-9_.@/-]{2,}\b",
        r"\b(npm|pip|pip3|pnpm|yarn)\s+(install|add)\b",
        r"\bpython3?\s+-m\s+pip\s+install\b",
    ],
    "system_package_install": [
        r"\b(brew|apt|apt-get|sudo|yum|dnf|pacman)\s+(install|add)\b",
        r"\bcargo\s+install\b",
        r"\b(global|system(?:-wide)?)\s+(install|package|dependency)\b",
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


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "dozen": 12,
}

CONTENT_QUANTITY_ITEMS = (
    "articles?", "headlines?", "stories?", "cards?", "options?", "variants?",
    "concepts?", "sections?", "categories?", "topics?", "images?",
    "screenshots?", "logos?", "icons?", "features?", "examples?",
    "products?", "items?", "entries?", "slides?", "charts?", "tables?",
    "rows?",
)
CONTENT_QUANTITY_ITEM_PATTERN = "|".join(CONTENT_QUANTITY_ITEMS)
COUNT_TOKEN_PATTERN = r"\d+|" + "|".join(NUMBER_WORDS.keys())


def parse_positive_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        parsed = int(text)
        return parsed if parsed > 0 else None
    return NUMBER_WORDS.get(text)


def normalize_quantity_item(item):
    text = re.sub(r"[^a-z0-9]+", " ", str(item or "").lower()).strip()
    singular_aliases = {
        "articles": "article",
        "headlines": "headline",
        "stories": "story",
        "checks": "check",
        "cards": "card",
        "options": "option",
        "variants": "variant",
        "concepts": "concept",
        "sections": "section",
        "categories": "category",
        "topics": "topic",
        "images": "image",
        "screenshots": "screenshot",
        "logos": "logo",
        "icons": "icon",
        "features": "feature",
        "examples": "example",
        "products": "product",
        "items": "item",
        "entries": "entry",
        "slides": "slide",
        "charts": "chart",
        "tables": "table",
        "rows": "row",
    }
    words = text.split()
    if len(words) > 1:
        tail = words[-1]
        if tail in singular_aliases:
            return singular_aliases[tail]
        if tail in set(singular_aliases.values()):
            return tail
    if text in singular_aliases:
        return singular_aliases[text]
    if text.endswith("ies"):
        return text[:-3] + "y"
    if text.endswith("es") and len(text) > 3:
        return text[:-2]
    if text.endswith("s") and len(text) > 3:
        return text[:-1]
    return text


def content_quantity_scope(tail):
    tail = re.split(r"[.;\n]", str(tail or ""), maxsplit=1)[0]
    tail = re.split(r"\b(?:take|use|make|create|build|write|add|include|page needs|needs to)\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]
    match = re.search(
        r"\b(?:in|for|under|per)\s+(?:each|every|all)?\s*(?:[a-z0-9-]+\s+){0,3}"
        r"(?:category|categories|topic|topics|section|sections|group|groups|type|types|page|pages)\b",
        tail,
        re.IGNORECASE,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip(" ,")
    return "whole deliverable"


def add_content_requirement(requirements, seen, count, item, source, tail):
    parsed_count = parse_positive_int(count)
    if not parsed_count or parsed_count <= 1:
        return
    item_clean = re.sub(r"\s+", " ", str(item or "").lower()).strip()
    source_clean = re.sub(r"\s+", " ", str(source or "")).strip(" ,")
    scope = content_quantity_scope(tail)
    key = (parsed_count, normalize_quantity_item(item_clean), scope.lower())
    if key in seen:
        return
    seen.add(key)
    requirements.append({
        "count": parsed_count,
        "item": item_clean,
        "scope": scope,
        "source": source_clean,
        "minimum_total": parsed_count,
    })


SCRIPT_RUNTIME_QUANTITY_ITEM_PATTERN = r"(?:\.[a-z0-9]{1,12}\s+)?(?:files?|directories?|subdirectories?|folders?|subfolders?|dirs?)"


def add_script_runtime_requirement(requirements, seen, count, item, source, tail):
    parsed_count = parse_positive_int(count)
    if not parsed_count or parsed_count <= 1:
        return
    item_clean = re.sub(r"\s+", " ", str(item or "").lower()).strip()
    source_clean = re.sub(r"\s+", " ", str(source or "")).strip(" ,")
    scope = re.sub(r"\s+", " ", str(tail or "").strip(" ,")) or "script runtime output"
    if item_clean in {"file", "files"}:
        extension_match = re.search(r"\.([a-z0-9]{1,12})\b", f"{source_clean} {scope}", re.IGNORECASE)
        if extension_match:
            item_clean = f".{extension_match.group(1).lower()} files"
    minimum_total = parsed_count

    if "file" in item_clean and re.search(r"\beach\b", f"{source_clean} {scope}", re.IGNORECASE):
        container_match = re.search(
            rf"\beach\b[^.!?\n]{{0,80}}\b(?P<count>{COUNT_TOKEN_PATTERN})\s+"
            r"(?:numbered\s+)?(?:directories|subdirectories|folders|subfolders|dirs)\b",
            f"{source_clean} {scope}",
            re.IGNORECASE,
        )
        if container_match:
            container_count = parse_positive_int(container_match.group("count"))
            if container_count:
                minimum_total = parsed_count * container_count
        else:
            prior_container_counts = [
                parse_positive_int(req.get("minimum_total")) or parse_positive_int(req.get("count"))
                for req in requirements
                if "director" in str(req.get("item", "")) or "folder" in str(req.get("item", "")) or "dir" == str(req.get("item", ""))
            ]
            prior_container_counts = [value for value in prior_container_counts if value]
            if prior_container_counts:
                minimum_total = parsed_count * max(prior_container_counts)

    key = (parsed_count, minimum_total, item_clean, scope.lower())
    if key in seen:
        return
    seen.add(key)
    requirements.append({
        "count": parsed_count,
        "item": item_clean,
        "scope": scope,
        "source": source_clean,
        "minimum_total": minimum_total,
        "validation_mode": "script_runtime",
    })


def detect_script_runtime_quantity_requirements(text):
    """Extract file/directory counts that a generated script must create when run."""
    if not text:
        return []

    source_text = str(text)
    requirements = []
    seen = set()
    pattern = re.compile(
        rf"\b(?:create|creates|created|make|makes|made|generate|generates|generated|"
        rf"write|writes|written|produce|produces|produced|add|adds|populate|populates|"
        rf"contain|contains|containing|include|includes|including)?\s*"
        rf"(?P<count>{COUNT_TOKEN_PATTERN})\s+(?P<item>{SCRIPT_RUNTIME_QUANTITY_ITEM_PATTERN})\b"
        rf"(?P<tail>(?:\.(?!\s|$)|[^.!?\n]){{0,180}})",
        re.IGNORECASE,
    )
    overlapping_pattern = re.compile(rf"(?=({pattern.pattern}))", re.IGNORECASE)
    for match in overlapping_pattern.finditer(source_text):
        full_source = (match.group(1) or "").strip(" ,")
        add_script_runtime_requirement(
            requirements,
            seen,
            match.group("count"),
            match.group("item"),
            full_source,
            match.group("tail") or "",
        )
    return requirements


def script_runtime_quantity_requirements_from_context(project_context):
    if not isinstance(project_context, dict):
        return []
    deliverable = project_context.get("deliverable") if isinstance(project_context.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    if fmt not in SCRIPT_RUNTIME_FORMATS:
        return []

    chunks = []
    intent = project_context.get("intent") if isinstance(project_context.get("intent"), dict) else {}
    for key in ("surface_ask", "underlying_need", "success_means"):
        if intent.get(key):
            chunks.append(str(intent.get(key)))
    constraints = project_context.get("constraints") if isinstance(project_context.get("constraints"), dict) else {}
    hard = constraints.get("hard_requirements") if isinstance(constraints.get("hard_requirements"), list) else []
    chunks.extend(str(item) for item in hard)
    acceptance = project_context.get("acceptance") if isinstance(project_context.get("acceptance"), list) else []
    chunks.extend(str(item) for item in acceptance)
    return detect_script_runtime_quantity_requirements("\n".join(chunks))


def detect_content_quantity_requirements(text):
    """Extract repeated content-item counts from raw user text.

    `deliverable.count` remains file count. This detects counts inside the
    deliverable, such as "top 3 articles in each category" or "three design
    options", so the model and validator can treat them as binding content
    requirements.
    """
    if not text:
        return []

    source_text = str(text)
    requirements = []
    seen = set()
    patterns = [
        re.compile(
            rf"\b(?:top|first|latest|best|pick|choose|select|show|display|include|"
            rf"create|generate|make|build|write|produce|add)\s+(?:the\s+)?"
            rf"(?P<count>{COUNT_TOKEN_PATTERN})\s+(?P<item>{CONTENT_QUANTITY_ITEM_PATTERN})\b"
            rf"(?P<tail>[^.!?\n]{{0,120}})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?P<count>{COUNT_TOKEN_PATTERN})\s+(?P<item>{CONTENT_QUANTITY_ITEM_PATTERN})\b"
            rf"(?P<tail>\s+(?:in|for|under|per)\s+[^.!?\n]{{1,100}})?",
            re.IGNORECASE,
        ),
    ]

    for pattern in patterns:
        for match in pattern.finditer(source_text):
            tail = match.group("tail") or ""
            full_source = (match.group(0) or "").split(",", 1)[0]
            add_content_requirement(
                requirements,
                seen,
                match.group("count"),
                match.group("item"),
                full_source,
                tail,
            )

    return requirements


def content_requirement_line(requirement):
    count = parse_positive_int(requirement.get("count")) or parse_positive_int(requirement.get("minimum_total"))
    item = str(requirement.get("item", "items")).strip() or "items"
    scope = str(requirement.get("scope", "whole deliverable")).strip() or "whole deliverable"
    source = str(requirement.get("source", "")).strip()
    suffix = f" Source: {source}" if source else ""
    prefix = "Exactly" if content_requirement_uses_exact_count(requirement) else "At least"
    return f"{prefix} {count} {item} inside the deliverable ({scope}).{suffix}"


def merge_content_quantity_requirements(existing, detected):
    merged = []
    seen = set()
    for item in listify(existing) + listify(detected):
        if not isinstance(item, dict):
            continue
        count = parse_positive_int(item.get("count")) or parse_positive_int(item.get("minimum_total"))
        item_name = str(item.get("item", "")).strip().lower()
        if not count or count <= 1 or not item_name:
            continue
        requirement = {
            "count": count,
            "item": item_name,
            "scope": str(item.get("scope", "whole deliverable")).strip() or "whole deliverable",
            "source": str(item.get("source", "")).strip(),
            "minimum_total": parse_positive_int(item.get("minimum_total")) or count,
        }
        if item.get("validation_mode"):
            requirement["validation_mode"] = str(item.get("validation_mode")).strip()
        key = (
            requirement["count"],
            normalize_quantity_item(requirement["item"]),
            requirement["scope"].lower(),
            requirement["source"].lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(requirement)
    return merged


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
    "pdf": (
        "PDF is a binary deliverable. Do NOT emit fake PDF bytes in GFORGE_FILE blocks. "
        "Write a workspace-safe generator or extraction script inside GFORGE_FILE blocks, "
        "then list a simple `python ...` command in COMMANDS so the harness creates real "
        "`.pdf` files on disk. Use the staged PDF skill guidance and reportlab/pypdf/"
        "pdfplumber where appropriate. If your script imports non-stdlib PDF libraries, "
        "include a workspace package install command such as `python -m pip install "
        "pypdf pdfplumber reportlab` before running the script."
    ),
    "shell": (
        "Shell scripts are plain text. Write the script inside GFORGE_FILE blocks. "
        "If the contract requires running it, list one simple workspace-safe command "
        "in COMMANDS so the harness sandbox can attempt it after writing files."
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
    "report": "markdown",
    "pdf report": "pdf",
    "portable document format": "pdf",
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


LOCAL_SOURCE_PATH_PATTERN = re.compile(
    r"""(?P<quoted>["'`](?:file://|~|/)[^"'`\r\n]+["'`])"""
    r"""|(?P<bare>(?:file://|~|/)[^\s,;]+)""",
    re.IGNORECASE,
)


def normalize_local_source_path_candidate(raw):
    candidate = str(raw or "").strip()
    if not candidate:
        return ""
    if candidate[0:1] in {"'", '"', "`"} and candidate[-1:] == candidate[0:1]:
        candidate = candidate[1:-1]
    candidate = candidate.strip().rstrip(".,;:)>]}")
    if candidate.startswith("file://"):
        candidate = re.sub(r"^file://(?:localhost)?", "", candidate, flags=re.IGNORECASE)
        candidate = unquote(candidate)
    candidate = os.path.expandvars(os.path.expanduser(candidate))
    return os.path.abspath(candidate)


def detect_local_source_paths(text, limit=16):
    """
    Detect explicit local file/directory references in user text.

    The harness imports these into the workspace before execution so the
    model sees stable relative paths instead of inaccessible host paths.
    """
    found = []
    seen = set()
    for match in LOCAL_SOURCE_PATH_PATTERN.finditer(str(text or "")):
        raw = match.group("quoted") or match.group("bare") or ""
        path = normalize_local_source_path_candidate(raw)
        if not path or not os.path.exists(path):
            continue
        try:
            key = os.path.realpath(path)
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "original_path": path,
            "kind": "directory" if os.path.isdir(path) else "file",
            "exists": True,
        })
        if len(found) >= limit:
            break
    return found


def build_source_inputs_contract(project_text):
    entries = []
    for item in detect_local_source_paths(project_text or ""):
        entry = dict(item)
        entry["workspace_root"] = f"{SOURCE_INPUTS_ROOT}/<imported-source>"
        entry["import_policy"] = (
            "Harness copies this source into the workspace before Execution; "
            "downstream agents must use the workspace-relative copy."
        )
        entries.append(entry)
    return entries


def source_inputs_prompt_block(project_text):
    entries = build_source_inputs_contract(project_text)
    if not entries:
        return "Detected local source paths: none."
    lines = [
        "Detected local source paths in the user's request:",
        "These are SOURCE MATERIAL, not the final deliverable. The harness will copy them into the workspace before Execution.",
    ]
    for item in entries:
        lines.append(f"- {item['kind']}: `{item['original_path']}`")
    lines.extend([
        "Context Writer rules for these paths:",
        "- Add `import_source_inputs` to capabilities_required.",
        "- Add `shell_exec` when the files must be inspected, parsed, OCR'd, converted, summarized, or validated.",
        "- Add source_inputs entries so later agents know these paths are binding inputs.",
        "- Do not invent filenames; downstream agents must use the copied workspace paths listed in `references/source-inputs.md`.",
    ])
    return "\n".join(lines)


def build_agent_digest(parsed, project_text, model=None):
    deliverable = parsed.get("deliverable") if isinstance(parsed.get("deliverable"), dict) else {}
    source_inputs = parsed.get("source_inputs") if isinstance(parsed.get("source_inputs"), list) else []
    content_requirements = parsed.get("content_requirements") if isinstance(parsed.get("content_requirements"), list) else []
    capabilities = parsed.get("capabilities_required") if isinstance(parsed.get("capabilities_required"), list) else []
    skill_plan = parsed.get("skill_plan") if isinstance(parsed.get("skill_plan"), list) else []
    perspectives = [
        "Intent perspective: satisfy the user's final artifact request, not a prep-step summary unless that is the requested artifact.",
        "Tool perspective: use staged skills, imported source paths, research artifacts, and workspace exec only for the roles they actually cover.",
        "Verifier perspective: every user-stated count, source reference, and file path is a hard gate that must be backed by disk evidence.",
    ]
    if source_inputs:
        perspectives.append("Source perspective: inspect the imported workspace copies before synthesizing or reporting on their content.")
    if any(c in {"web_browse", "web_fetch"} for c in capabilities):
        perspectives.append("Research perspective: use Scrapling as the first browser/scraping option and cite harness-fetched research artifacts.")
    if skill_plan:
        perspectives.append("Skill perspective: follow the staged skill manuals as operational guidance, not decorative context.")
    if "harness_maintenance" in capabilities:
        perspectives.append("Maintenance perspective: inspect allowlisted Gemma Forge target snapshots, then request precise maintenance actions only for those targets.")
    return {
        "selected_model": model or DEFAULT_MODEL,
        "model_profile": "local Gemma/Ollama model; prompts must be explicit, file paths concrete, and validation evidence simple.",
        "primary_deliverable": {
            "format": deliverable.get("format"),
            "count": deliverable.get("count"),
            "path_pattern": deliverable.get("path_pattern"),
        },
        "binding_counts": content_requirements,
        "binding_source_inputs": source_inputs,
        "perspectives": perspectives,
    }


def build_tool_plan(parsed):
    capabilities = parsed.get("capabilities_required") if isinstance(parsed.get("capabilities_required"), list) else []
    source_inputs = parsed.get("source_inputs") if isinstance(parsed.get("source_inputs"), list) else []
    skill_plan = parsed.get("skill_plan") if isinstance(parsed.get("skill_plan"), list) else []
    plan = []
    if source_inputs:
        plan.append({
            "step": "import local source material",
            "tool": "Gemma Forge source importer",
            "evidence": SOURCE_INPUTS_MANIFEST,
            "instruction": "Use copied workspace-relative inputs, never invented filenames or original absolute paths in commands.",
        })
    if any(c in {"web_browse", "web_fetch"} for c in capabilities):
        plan.append({
            "step": "fetch live web sources",
            "tool": "scrapling-official",
            "evidence": "research/*.md",
            "instruction": "Scrapling is the first browser/scraping path: request, then browser, then stealth if needed.",
        })
    if "harness_maintenance" in capabilities:
        plan.append({
            "step": "maintain Gemma Forge target files",
            "tool": "Gemma Forge maintenance allowlist",
            "evidence": MAINTENANCE_ACTIONS_FILE,
            "instruction": "Inspect references/maintenance-targets snapshots and emit only validated actions for allowlisted targets.",
        })
    for skill in skill_plan:
        if not isinstance(skill, dict):
            continue
        plan.append({
            "step": f"use staged skill {skill.get('skill')}",
            "tool": skill.get("staged_path"),
            "evidence": skill.get("staged_path"),
            "instruction": skill.get("role"),
        })
    if "shell_exec" in capabilities:
        plan.append({
            "step": "run workspace command evidence",
            "tool": "sandboxed workspace exec",
            "evidence": "artifacts/model-execution.json commandRuns",
            "instruction": "Use simple commands to inspect/process/validate workspace files; do not claim command results without commandRun evidence.",
        })
    return plan


def build_gsd_directives(parsed):
    deliverable = parsed.get("deliverable") if isinstance(parsed.get("deliverable"), dict) else {}
    source_inputs = parsed.get("source_inputs") if isinstance(parsed.get("source_inputs"), list) else []
    content_requirements = parsed.get("content_requirements") if isinstance(parsed.get("content_requirements"), list) else []
    capabilities = parsed.get("capabilities_required") if isinstance(parsed.get("capabilities_required"), list) else []
    return {
        "planner_standard": "Plan as an operator, not a summarizer: bind intent, tools, source material, counts, and verification before execution.",
        "counts_are_hard_gates": bool(parse_positive_int(deliverable.get("count")) and parse_positive_int(deliverable.get("count")) > 1 or content_requirements),
        "source_inputs_are_hard_gates": bool(source_inputs),
        "research_routing": (
            "If web research is required, Scrapling is the first browser/scraping option and fetched artifacts must be cited."
            if any(c in {"web_browse", "web_fetch"} for c in capabilities)
            else "No live web research capability was requested by the contract."
        ),
        "execution_routing": "Use workspace exec for source inspection, conversion, OCR, generation, and validation when shell_exec is present.",
        "failure_rule": "A plan that drops a requested count, source path, skill role, or verification gate is not complete.",
        "maintenance_routing": (
            "For Gemma Forge maintenance, plan against exact allowlisted install/runtime targets and require evidence from maintenance-actions.json plus verification commands."
            if "harness_maintenance" in capabilities
            else "No Gemma Forge maintenance capability was requested by the contract."
        ),
    }


def skill_prompt_alias_preview(skill, limit=14):
    aliases = []
    seen = set()
    canonical_names = {
        normalize_skill_phrase(skill.get("key", "")),
        normalize_skill_phrase(skill.get("name", "")),
        normalize_skill_phrase(str(skill.get("name", "")).replace("-", " ")),
    }
    for alias in skill_aliases(skill):
        phrase = normalize_skill_phrase(alias)
        if not phrase or phrase in seen or phrase in canonical_names:
            continue
        seen.add(phrase)
        aliases.append(alias)
        if len(aliases) >= limit:
            break
    return aliases


def build_project_context_prompt(project, mode, staged_skills, model=None, previous_attempt=None, validation_errors=None):
    skill_catalog_block = build_skill_capability_catalog_prompt(discover_installed_skills())
    skills_block = "(none staged)"
    if staged_skills:
        lines = []
        for skill in staged_skills:
            description = truncate_text(skill.get("description", ""), 220) if skill.get("description") else ""
            aliases = skill_prompt_alias_preview(skill)
            alias_text = f"; aliases: {', '.join(aliases)}" if aliases else ""
            use_when = f"; use when: {description}" if description else ""
            lines.append(
                f"  - {skill['name']} (key: {skill['key']}; path: {skill['path']}"
                f"{alias_text}{use_when})"
            )
        skills_block = "\n".join(lines)

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
    source_inputs_block = source_inputs_prompt_block(project)
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

Take a moment. Reason carefully through seven steps in order:

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
5. PICK deliverable.format from the canonical list (svg | html | css | javascript | typescript | python | json | yaml | markdown | pdf | shell | sql | dockerfile | mermaid | txt). The format MUST match the primary deliverable, not a prep step. Logos → svg. Webpages → html. Scripts → python (or shell/javascript). PDF reports → pdf. Never "tbd" or "various".

5b. WRITE path_pattern as a SINGLE relative path or simple glob — never a phrase, range, or comma list.
   Correct examples:
     - output/logo-NN.svg          (NN is a placeholder for the index)
     - output/favicon-*.svg
     - index.html
     - src/cli.py
     - output/report-NN.pdf
   WRONG examples (do NOT do these):
     - "output/file-01.svg to output/file-10.svg"     (phrase with 'to')
     - "output/a.svg, output/b.svg, output/c.svg"     (comma list)
     - "various .svg files in output/"                (vague)
   Use ONE pattern; the count field handles "how many".
5c. SEPARATE file count from content-item count.
   - deliverable.count means number of FILES to write.
   - User phrases like "top 3 articles", "three design options", "6 feature cards",
     or "2 screenshots per category" are CONTENT requirements inside the deliverable.
   - Preserve those phrases in content_requirements, constraints.hard_requirements,
     and acceptance. Do NOT collapse them into vague wording like "structured content".
   - For a web bundle such as "one HTML page and one linked CSS/JS file",
     deliverable.format is html and deliverable.count is the HTML file count
     only. The CSS/JS file is a support file named in acceptance/requirements,
     not a second html deliverable.
6. MAP source material and tools into agent-digestible context.
   - If the user names a local file or directory, treat it as binding source material. The harness imports it to the workspace.
   - Downstream agents must use copied workspace-relative paths, not original absolute paths, in commands.
   - Choose skills for operational fit, not keyword theater.
   - If web research is needed, Scrapling is the first browser/scraping option.
7. EMIT the YAML between the markers. Output a one-paragraph rationale BEFORE the begin marker, then the YAML between markers, then nothing else.

CRITICAL: `deliverable.partial: true` is ONLY for capability gaps. If the user lists multiple steps and the harness CAN do them all, partial is FALSE — the harness will execute the prep steps internally and then produce the primary deliverable in one Execution pass. Multi-step requests are normal; they are NOT partial.

CRITICAL: `image_generation` is ONLY required for RASTER images (jpeg, png, webp, gif, photorealistic renders). Vector formats (svg, mermaid) and document formats (html, css, markdown, code) are PLAIN TEXT — the harness writes them as files. Do NOT put `image_generation` in capabilities_required for an SVG / vector / web / code deliverable. "Logo" / "icon" / "graphic" almost always means SVG; do not flag image_generation for those.

Project request (raw, unedited):
{project}

Harness mode: {mode}
Selected model: {model or DEFAULT_MODEL}

{source_inputs_block}

Available staged skills (you may name ONE in skill.use, or "none"):
{skills_block}

{skill_catalog_block}
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
  format: <svg|html|css|javascript|typescript|python|json|yaml|markdown|pdf|shell|sql|dockerfile|mermaid|txt>
  count: <integer; how many files of this format the harness should write>
  path_pattern: <relative path, e.g. output/logo-NN.svg or index.html>
  encoding: gforge_file_block
  partial: <true|false; true ONLY if the harness lacks a capability the request needs>
  scope: <one-line description of what the harness will actually deliver (matches partial)>
  anti_deflection: |
    <The harness will overwrite this with a canonical anti-deflection paragraph per
    deliverable.format. Write a one-line stub here; the registry value wins.>
content_requirements:
  - count: <integer content-item count from the user, e.g. 3>
    item: <thing repeated inside the deliverable, e.g. articles, options, feature cards>
    scope: <where it applies, e.g. each category or whole deliverable>
    source: <verbatim user phrase that created this requirement>
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
  use: <installed skill key from the catalog, or "none">
  staged_path: <staged path or "n/a">
source_inputs:
  - original_path: <absolute path the user named, or omit this list if none>
    kind: <file|directory>
    import_policy: <copy into workspace before execution>
tool_plan:
  - step: <concrete tool step>
    tool: <staged skill/capability/workspace tool>
    evidence: <workspace path or artifact that proves it happened>
    instruction: <one direct instruction to the execution agent>
agent_digest:
  selected_model: <selected local model>
  model_profile: <how to prompt this model>
  perspectives:
    - <intent/tool/verifier/source perspective>
gsd_directives:
  planner_standard: <how GSD should plan this request>
  counts_are_hard_gates: <true|false>
  source_inputs_are_hard_gates: <true|false>
  execution_routing: <when to use workspace exec / skills>
acceptance:
  - <verifiable check, e.g. "6 files exist under output/">
  - <verifiable check>
open_questions: <empty list, OR one blocking question per missing capability>
---
{CONTEXT_END_MARKER}

Rules:
- Quote the user verbatim in intent.surface_ask, in double-quotes.
- deliverable.format must be one concrete canonical value from the list above.
- deliverable.count is FILE count only. Put repeated content counts in content_requirements.
- For HTML support-file bundles, deliverable.count counts HTML files only; keep
  linked CSS/JS files as support files / acceptance requirements, not extra HTML
  files.
- For runnable script requests, file/directory counts the script should create are
  script behavior requirements. Preserve them in content_requirements/acceptance,
  but keep deliverable.count as the number of script files to write.
- If the user points to a local file or directory, source_inputs must list it and capabilities_required must include `import_source_inputs` plus `shell_exec` when content inspection/conversion/OCR/validation is needed.
- Preserve every user-stated quantity above 1 in content_requirements and acceptance.
- capabilities_required must list every capability the user's request implies.
  If any of those are in the harness CANNOT list, you MUST set partial: true,
  populate open_questions, and shrink scope to the partial deliverable.
- skill.use should name the strongest single matching installed skill from the catalog. The harness may add more matching skills deterministically during staging.
- SocratiCode and Axon are higher-level codebase tools. Use them for existing-codebase discovery/structure/impact/dead-code work, not simple fresh content/file tasks.
- UI/UX Pro Max is the design-system/interface suite. Use it for UI, dashboards, layout, states, charts, accessibility, and responsive presentation.
- Scrapling is the first browser/scraping option. Use it for web fetch, crawling, JS-rendered pages, anti-bot/stealth, adaptive selectors, and structured website extraction.
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


def parse_project_context(text, project_text="", model=None):
    raw_yaml, marker_error = extract_context_yaml_block(text)
    if marker_error:
        return None, raw_yaml, [marker_error]
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as error:
        return None, raw_yaml, [f"YAML parse error: {error}"]
    if not isinstance(parsed, dict):
        return None, raw_yaml, ["YAML did not parse to a mapping at top level"]

    enrich_project_context(parsed, project_text, model=model)
    return parsed, dump_project_context_yaml(parsed), validate_project_context(parsed)


def dump_project_context_yaml(parsed):
    """Round-trip the dict through PyYAML so the artifact reflects enrichment."""
    try:
        return yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True).strip()
    except yaml.YAMLError:
        return yaml.safe_dump(parsed, sort_keys=False).strip()


def reconcile_project_context_skill(parsed, project_text):
    """
    Canonicalize Project Context's single skill.use field against the real
    installed skill keys. This repairs capability aliases like `web_browse`
    and deterministic keyword matches when the model writes `none`.
    """
    if not isinstance(parsed, dict):
        return
    skill_info = parsed.get("skill")
    if not isinstance(skill_info, dict):
        skill_info = {}
        parsed["skill"] = skill_info

    skills = discover_installed_skills()
    if not skills:
        skill_info["use"] = "none"
        skill_info["staged_path"] = "n/a"
        return

    selected = resolve_skill_selection({
        "project": project_text or "",
        "messages": [],
        "projectContext": parsed,
    }, skills)

    if selected:
        primary = selected[0]
        skill_info["use"] = primary
        skill_info["staged_path"] = f"{WORKSPACE_SKILLS_ROOT}/{primary}"
    else:
        skill_info["use"] = "none"
        skill_info["staged_path"] = "n/a"
    parsed["skill_plan"] = build_project_context_skill_plan(selected, skills)


def build_project_context_skill_plan(selected_keys, skills):
    plan = []
    for key in selected_keys or []:
        skill = skills.get(key, {"name": key, "key": key})
        role = skill_role_guidance(key)
        plan.append({
            "skill": key,
            "name": skill.get("name", key),
            "staged_path": f"{WORKSPACE_SKILLS_ROOT}/{key}",
            "role": role.get("role", "supporting instructions"),
            "guidance": role.get("guidance", []),
        })
    return plan


def normalize_html_css_support_bundle_context(parsed, project_text):
    if not isinstance(parsed, dict):
        return
    deliverable = parsed.get("deliverable") if isinstance(parsed.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    if fmt != "html":
        return
    if not html_support_bundle_requested(parsed, extra_text=project_text):
        return

    reference_text = project_context_reference_text(parsed, extra_text=project_text)
    expected = parse_positive_int(deliverable.get("count"))
    primary_count = requested_html_file_count(reference_text)
    if expected and primary_count and primary_count < expected:
        deliverable["count"] = primary_count

    support_files = parsed.get("support_files") if isinstance(parsed.get("support_files"), list) else []
    requested_support = []
    for support_format, config in HTML_SUPPORT_FILE_FORMATS.items():
        for support_file in html_support_file_names(reference_text, support_format):
            requested_support.append((support_format, support_file, config["label"]))
    if not requested_support:
        return

    existing_support = {
        (
            str(item.get("format", "")).strip().lower(),
            str(item.get("path_pattern", "")).strip(),
        )
        for item in support_files
        if isinstance(item, dict)
    }
    for support_format, support_file, _label in requested_support:
        support_key = (support_format, support_file)
        if support_key in existing_support:
            continue
        support_files.append({
            "format": support_format,
            "count": 1,
            "path_pattern": support_file,
            "required": True,
        })
    parsed["support_files"] = support_files

    constraints = parsed.get("constraints") if isinstance(parsed.get("constraints"), dict) else {}
    hard_requirements = constraints.get("hard_requirements") if isinstance(constraints.get("hard_requirements"), list) else []
    hard_requirements = [str(item).strip() for item in hard_requirements if str(item).strip()]
    acceptance = parsed.get("acceptance") if isinstance(parsed.get("acceptance"), list) else []
    acceptance = [str(item).strip() for item in acceptance if str(item).strip()]
    for _support_format, support_file, label in requested_support:
        requirement = f"Linked {label} file `{support_file}` must be present and referenced by the HTML."
        if not any(support_file in item for item in hard_requirements):
            hard_requirements.append(requirement)
        if not any(support_file in item for item in acceptance):
            acceptance.append(requirement)
    constraints["hard_requirements"] = hard_requirements
    parsed["constraints"] = constraints
    parsed["acceptance"] = acceptance


def enrich_project_context(parsed, project_text, model=None):
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

    normalize_html_css_support_bundle_context(parsed, project_text or "")

    declared = parsed.get("capabilities_required")
    if not isinstance(declared, list):
        declared = []
    declared_keys = {str(k).strip() for k in declared if str(k).strip()}

    source_inputs = build_source_inputs_contract(project_text or "")
    existing_source_inputs = parsed.get("source_inputs") if isinstance(parsed.get("source_inputs"), list) else []
    if existing_source_inputs:
        for item in existing_source_inputs:
            if not isinstance(item, dict):
                continue
            original = str(item.get("original_path", "")).strip()
            if not original:
                continue
            normalized = normalize_local_source_path_candidate(original)
            if not normalized or not os.path.exists(normalized):
                continue
            if not any(entry.get("original_path") == normalized for entry in source_inputs):
                source_inputs.append({
                    "original_path": normalized,
                    "kind": "directory" if os.path.isdir(normalized) else "file",
                    "exists": True,
                    "workspace_root": f"{SOURCE_INPUTS_ROOT}/<imported-source>",
                    "import_policy": (
                        "Harness copies this source into the workspace before Execution; "
                        "downstream agents must use the workspace-relative copy."
                    ),
                })
    parsed["source_inputs"] = source_inputs

    auto_detected = detect_required_capabilities(project_text or "")
    union = declared_keys.union(auto_detected) | {"emit_files"}
    if source_inputs:
        union.update({"import_source_inputs", "shell_exec"})
    if "harness_maintenance" in union:
        union.add("shell_exec")
    if fmt == "pdf" and "shell_exec" in union:
        # PDF work routinely needs workspace-local Python libraries
        # (pypdf/pdfplumber/reportlab). Expose package installation so the
        # execution model can install dependencies inside the sandbox instead
        # of assuming the host Python already has them.
        union.add("install_package")

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
    reconcile_project_context_skill(parsed, project_text)

    detected_content_requirements = detect_content_quantity_requirements(project_text or "")
    if fmt in SCRIPT_RUNTIME_FORMATS:
        detected_content_requirements = merge_content_quantity_requirements(
            detected_content_requirements,
            detect_script_runtime_quantity_requirements(project_text or ""),
        )
    content_requirements = merge_content_quantity_requirements(
        parsed.get("content_requirements"),
        detected_content_requirements,
    )
    parsed["content_requirements"] = content_requirements
    if content_requirements:
        constraints = parsed.get("constraints") if isinstance(parsed.get("constraints"), dict) else {}
        hard_requirements = constraints.get("hard_requirements") if isinstance(constraints.get("hard_requirements"), list) else []
        hard_requirements = [str(item).strip() for item in hard_requirements if str(item).strip()]
        acceptance = parsed.get("acceptance") if isinstance(parsed.get("acceptance"), list) else []
        acceptance = [str(item).strip() for item in acceptance if str(item).strip()]
        for requirement in content_requirements:
            line = content_requirement_line(requirement)
            if not any(str(requirement.get("source", "")).strip() and str(requirement.get("source", "")).strip() in item for item in hard_requirements):
                hard_requirements.append(line)
            acceptance_line = "Deterministic validation confirms " + line[0].lower() + line[1:]
            if not any(normalize_quantity_item(requirement.get("item", "")) in normalize_quantity_item(item) and str(requirement.get("count")) in item for item in acceptance):
                acceptance.append(acceptance_line)
        constraints["hard_requirements"] = hard_requirements
        parsed["constraints"] = constraints
        parsed["acceptance"] = acceptance

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
    parsed["tool_plan"] = build_tool_plan(parsed)
    parsed["agent_digest"] = build_agent_digest(parsed, project_text, model=model)
    parsed["gsd_directives"] = build_gsd_directives(parsed)
    return parsed


def format_default_task_type(fmt):
    if fmt == "svg":
        return "design_deliverable"
    if fmt in {"html", "css", "javascript", "typescript", "python", "shell", "sql", "dockerfile", "json", "yaml"}:
        return "code"
    if fmt in {"markdown", "pdf", "txt"}:
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
        errors.append("deliverable.format must be one concrete value (svg/html/markdown/pdf/python/etc)")
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
    content_requirements = parsed.get("content_requirements") if isinstance(parsed, dict) and isinstance(parsed.get("content_requirements"), list) else []
    skill_plan = parsed.get("skill_plan") if isinstance(parsed, dict) and isinstance(parsed.get("skill_plan"), list) else []
    source_inputs = parsed.get("source_inputs") if isinstance(parsed, dict) and isinstance(parsed.get("source_inputs"), list) else []
    tool_plan = parsed.get("tool_plan") if isinstance(parsed, dict) and isinstance(parsed.get("tool_plan"), list) else []
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
        f"- File count: `{deliverable.get('count', 'unknown')}`",
        f"- Encoding: `{deliverable.get('encoding', 'unknown')}`",
        f"- Content counts: `{len(content_requirements)}`",
        f"- Source inputs: `{len(source_inputs)}`",
        "",
        "## Content quantity requirements",
        "",
        "\n".join(f"- {content_requirement_line(item)}" for item in content_requirements) if content_requirements else "- None.",
        "",
        "## Skill usage plan",
        "",
        "\n".join(
            f"- `{item.get('skill')}`: {item.get('role')}. " + " ".join(listify(item.get("guidance"))[:2])
            for item in skill_plan
            if isinstance(item, dict)
        ) if skill_plan else "- None.",
        "",
        "## Source inputs",
        "",
        "\n".join(
            f"- `{item.get('original_path')}` ({item.get('kind')}) -> `{item.get('workspace_root', SOURCE_INPUTS_ROOT)}`"
            for item in source_inputs
            if isinstance(item, dict)
        ) if source_inputs else "- None.",
        "",
        "## Tool plan",
        "",
        "\n".join(
            f"- {item.get('step')}: `{item.get('tool')}`; evidence `{item.get('evidence')}`"
            for item in tool_plan
            if isinstance(item, dict)
        ) if tool_plan else "- None.",
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

    prompt = build_project_context_prompt(project, mode, staged_skills, model=model)
    raw, transport = call_ollama_with_transport(model, prompt, options_override=CONTEXT_DELIBERATION_OPTIONS)
    parsed, raw_yaml, errors = parse_project_context(raw, project_text=project, model=model)

    repaired = False
    repair_raw = ""
    repair_transport = None
    if errors:
        repair_prompt = build_project_context_prompt(
            project, mode, staged_skills,
            model=model,
            previous_attempt=raw,
            validation_errors=errors,
        )
        repair_raw, repair_transport = call_ollama_with_transport(
            model, repair_prompt, options_override=CONTEXT_DELIBERATION_OPTIONS,
        )
        repair_parsed, repair_yaml, repair_errors = parse_project_context(repair_raw, project_text=project, model=model)
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
    content_requirements = (context or {}).get("content_requirements") if isinstance((context or {}).get("content_requirements"), list) else []
    source_inputs = (context or {}).get("source_inputs") if isinstance((context or {}).get("source_inputs"), list) else []
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
        f"- Content count requirements: `{len(content_requirements)}`",
        f"- Source inputs: `{len(source_inputs)}`",
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
    if content_requirements:
        lines.extend(["", "## Content quantity requirements", ""])
        lines.extend(f"- {content_requirement_line(item)}" for item in content_requirements)
    if source_inputs:
        lines.extend(["", "## Source inputs", ""])
        lines.extend(
            f"- `{item.get('original_path')}` ({item.get('kind')})"
            for item in source_inputs
            if isinstance(item, dict)
        )
    return "\n".join(lines)


def build_workspace_orientation(target_directory, session, workspace, mode):
    """Post-Execution (or existing-directory) workspace orientation."""
    context = session.get("projectContext") if isinstance(session.get("projectContext"), dict) else None
    deliverable = (context or {}).get("deliverable") if isinstance((context or {}).get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    path_pattern = str(deliverable.get("path_pattern", "")).strip()
    expected_count = deliverable.get("count")
    content_requirements = (context or {}).get("content_requirements") if isinstance((context or {}).get("content_requirements"), list) else []
    source_inputs = (context or {}).get("source_inputs") if isinstance((context or {}).get("source_inputs"), list) else []
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
        f"- Content count requirements: `{len(content_requirements)}`",
        f"- Source inputs: `{len(source_inputs)}`",
    ])
    if actual_deliverable_files:
        lines.append("- Listing:")
        for filename in actual_deliverable_files[:25]:
            lines.append(f"  - `{filename}`")
        if len(actual_deliverable_files) > 25:
            lines.append(f"  - ...and {len(actual_deliverable_files) - 25} more")
    if content_requirements:
        lines.extend(["", "## Content quantity requirements", ""])
        lines.extend(f"- {content_requirement_line(item)}" for item in content_requirements)
    if source_inputs:
        lines.extend(["", "## Source inputs", ""])
        lines.extend(
            f"- `{item.get('original_path')}` ({item.get('kind')})"
            for item in source_inputs
            if isinstance(item, dict)
        )

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
    # renders into continuation repair guidance.
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
    context = session.get("projectContext") if isinstance(session, dict) else {}
    project_info = context.get("project") if isinstance(context, dict) and isinstance(context.get("project"), dict) else {}
    context_name = str(project_info.get("name", "")).strip()
    return os.path.join(
        session_dir(session_id),
        "workspace",
        compact_slug(context_name or project, max_length=52, fallback="deliverable"),
    )


def run_gsd_card(session_id, session, model, mode):
    resource_state = scan_workspace()
    workspace_dir = resolve_execution_workspace(session_id, session, session.get("project", ""))
    os.makedirs(workspace_dir, exist_ok=True)
    skill_context = prepare_workspace_skill_context(workspace_dir, session, extra_keys=["gsd"])
    details = call_ollama(
        model,
        build_planning_prompt(
            session,
            mode,
            resource_state,
            gsd_skill_context=(skill_context or {}).get("prompt"),
        ),
    )
    artifact = write_artifact(session_id, "gsd-plan.md", details)
    return card_result(
        "GSD Planning",
        "Phase plan generated from the project record.",
        details,
        "Review the phases and verify each phase has a testable done condition.",
        artifact,
    )


def run_socraticode_card(session_id, session, model, mode, correction=None):
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

    # User override path (same shape as Axon). Re-running SocratiCode against
    # the same workspace produces the same scan result, so when the user
    # hits Resolve with a non-empty note we treat it as "user reviewed,
    # advance the chain" and record the note in the artifact.
    override_note = ""
    if isinstance(correction, dict):
        override_note = str(correction.get("userNote", "")).strip()
    if override_note and tool_execution.get("requiresAttention"):
        tool_execution["requiresAttention"] = False
        tool_execution["userOverride"] = override_note
        tool_execution["reason"] = (
            f"User reviewed the SocratiCode findings and chose to advance the chain. "
            f"Note: {override_note}"
        )

    details = build_socraticode_details(target_directory, profile, tool_execution, brief)
    artifact = write_artifact(session_id, "socraticode-brief.md", details)
    summary = "SocratiCode indexed and searched the project."
    checkpoint = "Review the SocratiCode search results and confirm the mapped files are relevant."
    if tool_execution.get("userOverride"):
        summary = "SocratiCode scan complete (user override)."
        checkpoint = "SocratiCode findings were acknowledged via the Resolve note above."
    elif tool_execution["status"] != "complete":
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
    ]
    user_override = tool_execution.get("userOverride") if isinstance(tool_execution, dict) else None
    if user_override:
        lines.extend([
            "## User Override",
            "",
            "The user clicked Resolve on this card and provided the following note. "
            "The harness treated the note as authoritative and advanced the chain.",
            "",
            f"> {user_override}",
            "",
        ])
    lines.extend([
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
    ])
    return "\n".join(lines)


def run_axon_card(session_id, session, model, mode, correction=None):
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

    # User override path. Re-running Axon doesn't change its findings (it's a
    # deterministic scan), so when the user hits Resolve with a non-empty
    # note the only sensible read is "user has reviewed these findings and
    # wants to advance." We mark requiresAttention=False so the chain
    # continues, and record the override note in the artifact for audit.
    override_note = ""
    if isinstance(correction, dict):
        override_note = str(correction.get("userNote", "")).strip()
    if override_note and tool_execution.get("requiresAttention"):
        tool_execution["requiresAttention"] = False
        tool_execution["userOverride"] = override_note
        tool_execution["reason"] = (
            f"User reviewed the Axon findings and chose to advance the chain. "
            f"Note: {override_note}"
        )
        summary = "Structural status and dead-code scan complete (user override)."
        checkpoint = "Axon findings were acknowledged via the Resolve note above."

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
    ]
    user_override = tool_execution.get("userOverride") if isinstance(tool_execution, dict) else None
    if user_override:
        lines.extend([
            "## User Override",
            "",
            "The user clicked Resolve on this card and provided the following note. "
            "The harness treated the note as authoritative and advanced the chain.",
            "",
            f"> {user_override}",
            "",
        ])
    lines.extend([
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
    ])
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
    skill_context = None
    workspace_dir = str(session.get("projectDirectory", "") or "").strip() if isinstance(session, dict) else ""
    if workspace_dir and os.path.isdir(workspace_dir):
        skill_context = prepare_workspace_skill_context(workspace_dir, session)
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
        skill_block = (skill_context or {}).get("prompt") or (
            "No Gemma Forge skills are staged for this verification pass."
        )
        checklist = call_ollama(model, f"""Gemma Forge Verification card.
Project: {session.get('project', '')}
Mode: {mode}
Workspace: {context.get('workspace')}
Deterministic validation:
{json.dumps(context.get('validation', {}), indent=2)}
Files found:
{json.dumps(context.get('filesFound', {}), indent=2)}

Gemma Forge skill context for this read-only verification pass:
{skill_block}
{correction_block}
Produce a short verification checklist from these actual artifacts. If auto-run is enabled, list the checks already run and any remaining manual inspection. If a correction block is present above, the checklist MUST explicitly say whether each user/reviewer item has now been satisfied.

Evaluate the workspace against staged skill output and quality rules where applicable. UI/UX work must be checked for layout, responsive behavior, accessibility, states, hierarchy, charts/data presentation, and visual polish. GSD work must be checked for phases, acceptance criteria, dependencies, verification gates, and hard count/source requirements.

Verification may rerun deterministic checks and inspect the current workspace, but it must not edit deliverables. If issues remain, route the work back to the responsible Forge Section (usually Project Execution) with the exact blocker instead of proposing direct edits inside Verification.

FORMATTING RULES — do not violate:
- Refer to deliverables by their relative path in backticks only, e.g. `output/index.html` or `artifacts/validation.json`.
- DO NOT write '[Link to local file]', '<link>', '(see attached)', '(click here)', or any placeholder text for links. The harness appends a real clickable file list at the bottom of this verification report with absolute `file://` URLs. Inventing placeholder link text just confuses the reader.
- DO NOT write `file://` URLs yourself. You do not know the absolute workspace path. The harness owns the canonical 'Local Files' section at the bottom of this report — it has the correct absolute paths. Anything you write will be wrong.
- DO NOT add your own '### Local File Links' / '## File Links' / similar section. The harness emits one automatically; duplicating it just produces two lists, one of them wrong.
- DO NOT invent file paths the harness did not list above. If a path is not in the 'Files found' map, do not reference it as if it exists.""")

    details = build_verification_report(session_id, session, mode, context, checklist, skill_context)
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

    # Axon/SocratiCode are advisory support tools for simple fresh-script
    # deliverables. Do not convert their findings into deterministic validation
    # failures here; doing so lets a support-tool interpretation trigger a
    # Verification repair, which can destroy an already-good deliverable.
    axon_findings = extract_axon_dead_code_findings(session)
    if axon_findings:
        context["validation"]["axonDeadCodeAdvisory"] = axon_findings
    return context


def extract_axon_dead_code_findings(session):
    """Pull the dead-code report from the most recent Axon card run and turn
    each entry into a validation failure string.

    Filters out entries under `.gforge/skills/` because those are bundled
    harness skills, not the model's deliverable. Returns [] if no Axon
    card was run, or the run found no dead code, or the data is missing.
    """
    if not isinstance(session, dict):
        return []
    cards = session.get("cards", []) if isinstance(session.get("cards"), list) else []
    axon_card = next((c for c in cards if isinstance(c, dict) and c.get("id") == "axon"), None)
    if not axon_card:
        return []
    last_run = axon_card.get("lastRun") if isinstance(axon_card.get("lastRun"), dict) else {}
    tool_exec = last_run.get("toolExecution") if isinstance(last_run.get("toolExecution"), dict) else {}
    commands = tool_exec.get("commands") if isinstance(tool_exec.get("commands"), dict) else {}
    dead_code = commands.get("deadCode") if isinstance(commands.get("deadCode"), dict) else {}
    stdout = dead_code.get("stdout") or ""
    if not stdout:
        return []

    # Format from `axon dead-code`:
    #   Dead Code Report (N symbols)
    #   ----------------------------------------
    #
    #     path/to/file.py:
    #       - symbol_name (line 12)
    #       - other_symbol (line 34)
    #
    #     another/file.js:
    #       - foo (line 5)
    findings = []
    current_file = None
    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        # File header: indented, ends with `:`, no leading dash
        if line.endswith(":") and not line.lstrip().startswith("-"):
            current_file = line.strip().rstrip(":").strip()
            continue
        # Symbol entry: leading dash
        stripped = line.lstrip()
        if stripped.startswith("- ") and current_file:
            entry = stripped[2:].strip()
            # Skip dead code in bundled skills / harness support files —
            # those aren't part of the model's deliverable contract.
            if current_file.startswith(".gforge/") or "/.gforge/" in current_file:
                continue
            findings.append(
                f"Axon flagged dead code in `{current_file}`: {entry}. "
                f"Either remove the unused symbol or wire it into the program flow."
            )
    return findings


def build_verification_report(session_id, session, mode, context, checklist, skill_context=None):
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
    ]
    if isinstance(skill_context, dict):
        staged = skill_context.get("staged") if isinstance(skill_context.get("staged"), list) else []
        lines.extend([
            "## Staged Skill Context",
            "",
            f"- Skills root: `{skill_context.get('root', WORKSPACE_SKILLS_ROOT)}`",
        ])
        if staged:
            for skill in staged:
                if not isinstance(skill, dict):
                    continue
                marker = "requested" if skill.get("requested") else "available"
                lines.append(
                    f"- `{skill.get('name', skill.get('key', 'skill'))}` at `{skill.get('path', '')}` ({marker})"
                )
        else:
            lines.append("- No staged skills were available.")
        lines.append("")
    lines.extend([
        "## Files Inspected",
        "",
    ])
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

    # Harness-emitted "Local Files" section: real clickable file:// URLs for
    # every file that actually exists on disk. The model is instructed not
    # to fabricate placeholder link text — this is the source of truth for
    # opening deliverables from the verification report.
    workspace_dir = context.get("workspace", "")
    if workspace_dir and files_found:
        present = [(p, os.path.join(workspace_dir, p))
                   for p, found in files_found.items() if found]
        # Also include any auto-captured screenshot files referenced in the
        # stored validation — those are real artifacts but not part of the
        # contract path_pattern check, so files_found wouldn't list them.
        stored = stored_validation if isinstance(stored_validation, dict) else {}
        for shot in (stored.get("screenshots") or []):
            if not isinstance(shot, dict):
                continue
            shot_rel = (shot.get("path") or "").strip()
            if not shot_rel:
                continue
            shot_abs = os.path.join(workspace_dir, shot_rel)
            if os.path.exists(shot_abs) and (shot_rel, shot_abs) not in present:
                present.append((shot_rel, shot_abs))
        if present:
            lines.extend([
                "",
                "## Local Files",
                "",
                "Click any link below to open the file in your default app.",
                "",
            ])
            for rel, absolute in present:
                # file:// URLs need URL-encoding for spaces / special chars but
                # leave the visible path readable.
                from urllib.parse import quote
                href = "file://" + quote(absolute, safe="/:")
                lines.append(f"- [`{rel}`]({href})")
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
    source_inputs = prepare_workspace_source_inputs(workspace_dir, session)
    maintenance_context = prepare_harness_maintenance_context(workspace_dir, session)
    research = prepare_workspace_research(workspace_dir, session)
    git_references = prepare_workspace_git_references(workspace_dir, session)
    payload, raw, transport = call_ollama_execution_payload(
        model,
        build_model_execution_prompt(session, workspace_dir, review, skill_context, research, git_references, source_inputs, maintenance_context),
        fallback,
    )
    if not isinstance(payload, dict):
        payload = fallback

    files, rejected = normalize_model_files(payload.get("files", []))
    commands = augment_workspace_commands_for_dependencies(workspace_dir, session, files, listify(payload.get("commands")))
    stale_deliverables = quarantine_existing_deliverables(workspace_dir, session)
    written = []
    for item in files:
        path = write_project_file(workspace_dir, item["path"], item["content"])
        written.append({
            "path": item["path"],
            "sha256": file_sha256(path),
            "bytes": os.path.getsize(path),
        })

    command_runs = []
    run_capabilities = set(session_capabilities_required(session))
    if run_capabilities.intersection({"shell_exec", "install_package"}) and commands:
        emit_event("tool", f"workspace exec requested: {len(commands)} command(s)")
        command_runs = tool_workspace.run_workspace_commands(
            workspace_dir,
            commands,
            maintenance_targets=maintenance_context,
        )
        for item in command_runs:
            status = "ok" if item.get("ok") else ("skipped" if item.get("skipped") else "failed")
            emit_event("tool", f"workspace exec {status}: {item.get('command')}")

    maintenance_actions = apply_harness_maintenance_actions(workspace_dir, maintenance_context)

    generated_deliverables = discover_deliverable_files(workspace_dir, session, known_paths={item["path"] for item in written})
    if generated_deliverables:
        written.extend(generated_deliverables)

    metadata = {
        "model": model,
        "modelAuthored": True,
        "requestedProject": session.get("project", ""),
        "summary": payload.get("summary", ""),
        "files": written,
        "rejectedFiles": rejected,
        "staleDeliverables": stale_deliverables,
        "commands": commands,
        "commandRuns": command_runs,
        "notes": listify(payload.get("notes")),
        "verification": listify(payload.get("verification")),
        "gitReferences": git_references,
        "sourceInputs": source_inputs,
        "harnessMaintenance": {
            "requested": maintenance_context.get("requested"),
            "manifest": maintenance_context.get("manifest"),
            "actionsFile": maintenance_context.get("actionsFile"),
            "targets": [
                {
                    "path": item.get("path"),
                    "kind": item.get("kind"),
                    "exists": item.get("exists"),
                    "snapshot_root": item.get("snapshot_root"),
                    "reason": item.get("reason"),
                }
                for item in maintenance_context.get("targets", [])
            ],
            "actions": maintenance_actions,
        },
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
        "commandRuns": command_runs,
        "maintenanceActions": maintenance_actions,
        "notes": metadata["notes"],
        "verification": metadata["verification"],
        "validation": validation,
        "screenshots": screenshots,
        "gitReferences": git_references,
        "metadata": metadata,
    }


PYTHON_IMPORT_PACKAGE_OVERRIDES = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "fitz": "PyMuPDF",
    "PIL": "pillow",
    "pptx": "python-pptx",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}
PDF_WORKSPACE_DEPENDENCY_PACKAGES = ["pypdf", "pdfplumber", "reportlab"]
WORKSPACE_DEPENDENCY_INSTALL_LIMIT = 12


def session_deliverable(session):
    context = session.get("projectContext") if isinstance(session, dict) else None
    if isinstance(context, dict) and isinstance(context.get("deliverable"), dict):
        return context.get("deliverable")
    return {}


def session_deliverable_format(session):
    return str(session_deliverable(session).get("format", "")).strip().lower()


def command_runs_python_script(command):
    try:
        args = command if isinstance(command, list) else shlex.split(str(command or ""))
    except ValueError:
        return False
    if not args:
        return False
    executable = os.path.basename(str(args[0])).lower()
    if executable not in {"python", "python3"}:
        return False
    return any(str(arg).lower().endswith(".py") for arg in args[1:])


def python_script_paths_from_command(command):
    try:
        args = command if isinstance(command, list) else shlex.split(str(command or ""))
    except ValueError:
        return []
    if not args:
        return []
    executable = os.path.basename(str(args[0])).lower()
    if executable not in {"python", "python3"}:
        return []
    paths = []
    for arg in args[1:]:
        value = str(arg)
        if value.lower().endswith(".py"):
            safe = safe_workspace_relative_path(value)
            if safe:
                paths.append(safe)
    return paths


def command_installs_packages(command):
    try:
        args = command if isinstance(command, list) else shlex.split(str(command or ""))
    except ValueError:
        return False
    return tool_workspace.is_package_install_command([str(arg) for arg in args])


def collect_python_imports(source):
    imports = set()
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        for match in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", source or "", re.MULTILINE):
            imports.add(match.group(1))
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add((alias.name or "").split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
    return {name for name in imports if name}


def local_python_module_exists(workspace_dir, script_path, module_name):
    candidates = []
    module_parts = module_name.split(".")
    module_rel = os.path.join(*module_parts)
    candidates.extend([
        os.path.join(workspace_dir, module_rel + ".py"),
        os.path.join(workspace_dir, module_rel, "__init__.py"),
    ])
    script_dir = os.path.dirname(os.path.join(workspace_dir, script_path))
    candidates.extend([
        os.path.join(script_dir, module_rel + ".py"),
        os.path.join(script_dir, module_rel, "__init__.py"),
    ])
    return any(os.path.exists(path) for path in candidates)


def package_for_python_import(module_name):
    if not module_name:
        return None
    if module_name in sys.builtin_module_names:
        return None
    stdlib = getattr(sys, "stdlib_module_names", set())
    if module_name in stdlib:
        return None
    return PYTHON_IMPORT_PACKAGE_OVERRIDES.get(module_name, module_name)


def infer_workspace_python_packages(workspace_dir, files, commands):
    script_paths = []
    for command in commands:
        script_paths.extend(python_script_paths_from_command(command))
    if not script_paths:
        return []

    file_sources = {
        item["path"]: item.get("content", "")
        for item in files
        if isinstance(item, dict) and str(item.get("path", "")).endswith(".py")
    }
    packages = []
    seen = set()
    for script_path in script_paths:
        source = file_sources.get(script_path)
        if source is None:
            full_path = os.path.join(workspace_dir, script_path)
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError:
                source = ""
        for module_name in sorted(collect_python_imports(source)):
            if local_python_module_exists(workspace_dir, script_path, module_name):
                continue
            package = package_for_python_import(module_name)
            if not package or package in seen:
                continue
            seen.add(package)
            packages.append(package)

    return packages[:WORKSPACE_DEPENDENCY_INSTALL_LIMIT]


def augment_workspace_commands_for_dependencies(workspace_dir, session, files, commands):
    commands = listify(commands)
    caps = set(session_capabilities_required(session))
    can_auto_install = "install_package" in caps or ("shell_exec" in caps and tool_workspace.can_install_packages())
    if not can_auto_install:
        return commands
    if not any(command_runs_python_script(command) for command in commands):
        return commands
    if any(command_installs_packages(command) for command in commands):
        return commands
    packages = infer_workspace_python_packages(workspace_dir, files, commands)
    if session_deliverable_format(session) == "pdf":
        for package in PDF_WORKSPACE_DEPENDENCY_PACKAGES:
            if package not in packages:
                packages.append(package)
    if not packages:
        return commands
    packages = packages[:WORKSPACE_DEPENDENCY_INSTALL_LIMIT]
    install_command = "python -m pip install " + " ".join(packages)
    emit_event("tool", "workspace exec auto-provision: Python packages", packages=", ".join(packages))
    return [install_command, *commands]


def deliverable_walk_skip_dirs():
    return {
        ".gforge",
        ".gforge-installs",
        "artifacts",
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "references",
        "research",
        "screenshots",
        "venv",
    }


def quarantine_existing_deliverables(workspace_dir, session):
    deliverable = session_deliverable(session)
    if not deliverable:
        return []
    quarantined = []
    root_path = os.path.abspath(workspace_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = os.path.join(root_path, ".gforge", "attempt-backups", stamp, "deliverables")
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [name for name in dirs if name not in deliverable_walk_skip_dirs()]
        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, root_path).replace(os.sep, "/")
            if not file_matches_deliverable(relative_path, deliverable):
                continue
            destination = os.path.join(backup_root, relative_path)
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.move(full_path, destination)
                quarantined.append({
                    "path": relative_path,
                    "backup": os.path.relpath(destination, root_path).replace(os.sep, "/"),
                })
            except OSError as error:
                quarantined.append({
                    "path": relative_path,
                    "error": str(error),
                })
    if quarantined:
        emit_event("tool", f"workspace deliverable cleanup: {len(quarantined)} stale file(s)")
    return quarantined


def discover_deliverable_files(workspace_dir, session, known_paths=None):
    """
    Find deliverable files created by model-authored commands.

    This matters for binary outputs such as PDFs: the model writes a generator
    script in a GFORGE_FILE block, the harness runs `python ...`, and the real
    `.pdf` appears on disk after command execution.
    """
    context = session.get("projectContext") if isinstance(session, dict) else None
    if not isinstance(context, dict):
        return []
    deliverable = context.get("deliverable") if isinstance(context.get("deliverable"), dict) else {}
    if not deliverable:
        return []
    known = {str(path).replace(os.sep, "/") for path in (known_paths or set())}
    discovered = []
    root_path = os.path.abspath(workspace_dir)
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [name for name in dirs if name not in deliverable_walk_skip_dirs()]
        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            relative_path = os.path.relpath(full_path, root_path).replace(os.sep, "/")
            if relative_path in known:
                continue
            if not file_matches_deliverable(relative_path, deliverable):
                continue
            try:
                discovered.append({
                    "path": relative_path,
                    "sha256": file_sha256(full_path),
                    "bytes": os.path.getsize(full_path),
                    "generatedByCommand": True,
                })
                known.add(relative_path)
            except OSError:
                continue
    return discovered


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


def session_capabilities_required(session):
    context = session.get("projectContext") if isinstance(session, dict) else None
    if isinstance(context, dict) and isinstance(context.get("capabilities_required"), list):
        caps = [str(item).strip() for item in context.get("capabilities_required") if str(item).strip()]
        deliverable = context.get("deliverable") if isinstance(context.get("deliverable"), dict) else {}
        fmt = str(deliverable.get("format", "")).strip().lower()
        if fmt == "pdf" and "shell_exec" in caps and "install_package" not in caps:
            caps.append("install_package")
        return caps
    return []


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


def build_git_reference_context_block(git_references):
    if not isinstance(git_references, dict):
        return ""
    cloned = git_references.get("cloned") or []
    if not git_references.get("requested") and not cloned:
        return ""
    if not cloned:
        reason = git_references.get("error") or "no repository URLs were cloned"
        return f"\nGit reference step skipped: {reason}\n"
    lines = [
        "",
        "Harness-cloned repository references (already on disk; cite by path, do NOT claim you cloned these yourself).",
        f"- GitHub CLI authenticated: `{git_references.get('ghAuthenticated')}`",
        f"- Manifest: `{git_references.get('artifact') or 'n/a'}`",
        "",
    ]
    for item in cloned:
        marker = "ok" if item.get("ok") else "FAIL"
        path = item.get("path") or "(no path)"
        url = item.get("url") or "(no url)"
        auth = item.get("auth") or "git"
        lines.append(f"- [{marker} via {auth}] {path} ({url})")
    lines.append("")
    return "\n".join(lines)


def source_input_slug(path, index):
    base = os.path.basename(os.path.normpath(path)) or f"source-{index}"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower() or f"source-{index}"
    digest = hashlib.sha1(path.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"{index:02d}-{base}-{digest}"


def path_is_inside(child, parent):
    try:
        return os.path.commonpath([os.path.abspath(child), os.path.abspath(parent)]) == os.path.abspath(parent)
    except ValueError:
        return False


MAINTENANCE_SKIP_DIRS = SOURCE_INPUT_SKIP_DIRS | {
    ".axon",
    ".gforge",
    ".gforge-installs",
    ".pytest_cache",
    ".ruff_cache",
    "chat/session-data",
    "session-data",
}
MAINTENANCE_SKIP_FILES = SOURCE_INPUT_SKIP_FILES | {
    "crash_log.txt",
}


def detect_harness_maintenance_intent(text):
    return "harness_maintenance" in detect_required_capabilities(text or "")


def maintenance_request_flags(text):
    lowered = (text or "").lower()
    model_requested = bool(re.search(
        r"\b(default\s+model|forge\s+brain|ollama|model\s+(route|registry|alias|pull|create|remove|rm)|gemma[-\s]?\d|gemma4|e4b)\b",
        lowered,
    ))
    destructive_requested = bool(re.search(r"\b(delete|remove|rm|uninstall|wipe|clear)\b", lowered))
    return {
        "allowOllama": model_requested,
        "allowDestructive": destructive_requested,
    }


def maintenance_slug(path, index):
    base = os.path.basename(os.path.normpath(path)) or f"target-{index}"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower() or f"target-{index}"
    digest = hashlib.sha1(path.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"{index:02d}-{base}-{digest}"


def build_harness_maintenance_targets(session):
    text = session_user_source_text(session) if isinstance(session, dict) else str(session or "")
    if not detect_harness_maintenance_intent(text):
        return {
            "requested": False,
            "targets": [],
            "allowOllama": False,
            "allowDestructive": False,
            "actionsFile": MAINTENANCE_ACTIONS_FILE,
            "manifest": MAINTENANCE_TARGETS_MANIFEST,
        }

    lowered = text.lower()
    flags = maintenance_request_flags(text)
    targets = []
    seen = set()

    def add_target(path, reason, kind=None):
        if not path:
            return
        expanded = os.path.abspath(os.path.expanduser(path))
        if expanded in seen:
            return
        seen.add(expanded)
        resolved_kind = kind or ("directory" if os.path.isdir(expanded) else "file")
        targets.append({
            "path": expanded,
            "kind": resolved_kind,
            "reason": reason,
            "exists": os.path.exists(expanded),
        })

    model_terms = bool(re.search(r"\b(default\s+model|forge\s+brain|ollama|model\s+(route|registry|alias|pull|create|remove|rm)|gemma[-\s]?\d|gemma4|e4b)\b", lowered))
    skill_terms = bool(re.search(r"\b(skill|skills|socraticode|axon|gsd|scrapling|ui/ux|logo|pdf|mcp|code-writer|code\s+writer)\b", lowered))
    installer_terms = bool(re.search(r"\b(clean[-\s]?install|installer|install\s+script|provision|provisioning|launcher|launch_forge|requirements|pyproject)\b", lowered))
    routing_terms = bool(re.search(r"\b(context\s+writer|project\s+context|skill\s+routing|agent\s+guide|forge\.md|operating\s+guide|planning|gsd)\b", lowered))
    ui_terms = bool(re.search(r"\b(ui|ux|interface|sidebar|settings|button|card|css|javascript|frontend|page)\b", lowered))
    test_terms = bool(re.search(r"\b(test|tests|validate|validation|check|verify|verification)\b", lowered))

    if model_terms:
        add_target(os.path.join(PROJECT_ROOT, "chat", "server.py"), "default model, model route, and model registry logic")
        add_target(os.path.join(PROJECT_ROOT, "launch_forge.command"), "launcher default model pull and alias setup")
        add_target(MODEL_ROUTE_FILE, "live model-route status")
        add_target(MODELS_FILE, "live harness model registry")
    if skill_terms:
        add_target(os.path.join(PROJECT_ROOT, "skills"), "installable bundled Forge skills", kind="directory")
        add_target(os.path.join(GFORGE_DATA_ROOT, "skills"), "live staged harness skills", kind="directory")
        add_target(os.path.join(PROJECT_ROOT, "tools", "provision_clean_install.py"), "clean-install skill provisioning checks")
    if installer_terms:
        add_target(os.path.join(PROJECT_ROOT, "launch_forge.command"), "macOS launcher and install flow")
        add_target(os.path.join(PROJECT_ROOT, "tools", "provision_clean_install.py"), "first-use provisioning flow")
        add_target(os.path.join(PROJECT_ROOT, "tools", "verify_clean_install.sh"), "clean-install verification script")
        add_target(os.path.join(PROJECT_ROOT, "tools", "run_clean_install_test.sh"), "clean VM test runner")
        add_target(os.path.join(PROJECT_ROOT, "requirements.txt"), "Python runtime dependency list")
        add_target(os.path.join(PROJECT_ROOT, "pyproject.toml"), "Python package metadata")
    if routing_terms:
        add_target(os.path.join(PROJECT_ROOT, "chat", "server.py"), "Project Context, GSD, routing, and execution prompts")
        add_target(os.path.join(PROJECT_ROOT, "tests", "skill_routing_test.py"), "deterministic skill-routing coverage")
        add_target(os.path.join(PROJECT_ROOT, "tests", "model_route_test.py"), "route and harness behavior coverage")
        add_target(os.path.join(PROJECT_ROOT, "SKILL.md"), "repo-level Gemma Forge skill guide")
        add_target(os.path.join(PROJECT_ROOT, "forge.md"), "installable hidden Forge operating guide source")
        add_target(os.path.join(PROJECT_ROOT, "docs", "harness-agent-operating-guide.md"), "agent-facing harness operating guide")
        add_target(FORGE_CONTEXT_FILE, "live hidden Forge operating guide")
    if ui_terms:
        add_target(os.path.join(PROJECT_ROOT, "chat", "static"), "Forge Harness frontend assets", kind="directory")
        add_target(os.path.join(PROJECT_ROOT, "chat", "templates"), "Forge Harness HTML templates", kind="directory")
    if test_terms:
        add_target(os.path.join(PROJECT_ROOT, "tests"), "harness test suite", kind="directory")
        add_target(os.path.join(PROJECT_ROOT, "package.json"), "npm check command")

    if not targets:
        add_target(os.path.join(PROJECT_ROOT, "chat", "server.py"), "primary harness backend")
        add_target(os.path.join(PROJECT_ROOT, "launch_forge.command"), "launcher/install entrypoint")
        add_target(os.path.join(PROJECT_ROOT, "forge.md"), "installable hidden Forge operating guide source")
        add_target(os.path.join(PROJECT_ROOT, "docs", "harness-agent-operating-guide.md"), "agent-facing harness operating guide")

    return {
        "requested": True,
        "targets": targets,
        "allowOllama": flags["allowOllama"],
        "allowDestructive": flags["allowDestructive"],
        "actionsFile": MAINTENANCE_ACTIONS_FILE,
        "manifest": MAINTENANCE_TARGETS_MANIFEST,
        "snapshotRoot": MAINTENANCE_TARGETS_ROOT,
    }


def iter_maintenance_target_files(target_path):
    if os.path.isfile(target_path):
        yield target_path, os.path.basename(target_path)
        return
    if not os.path.isdir(target_path):
        return
    for root, dirs, files in os.walk(target_path):
        dirs[:] = [
            name for name in dirs
            if name not in MAINTENANCE_SKIP_DIRS and os.path.join(os.path.relpath(root, target_path), name).strip("./") not in MAINTENANCE_SKIP_DIRS
        ]
        for filename in sorted(files):
            if filename in MAINTENANCE_SKIP_FILES:
                continue
            full_path = os.path.join(root, filename)
            try:
                relative_path = os.path.relpath(full_path, target_path)
            except ValueError:
                continue
            yield full_path, relative_path


def prepare_harness_maintenance_context(workspace_dir, session):
    context = build_harness_maintenance_targets(session)
    if not context.get("requested"):
        return context

    dest_root = safe_workspace_child(workspace_dir, MAINTENANCE_TARGETS_ROOT)
    if os.path.isdir(dest_root):
        shutil.rmtree(dest_root)
    os.makedirs(dest_root, exist_ok=True)

    copied = []
    skipped = []
    total_files = 0
    total_bytes = 0
    for index, target in enumerate(context.get("targets", []), start=1):
        target_path = target.get("path")
        snapshot_root = safe_workspace_child(dest_root, maintenance_slug(target_path, index))
        target["snapshot_root"] = os.path.relpath(snapshot_root, workspace_dir).replace(os.sep, "/")
        if not target.get("exists"):
            skipped.append({"target": target_path, "reason": "target does not exist yet"})
            continue
        os.makedirs(snapshot_root, exist_ok=True)
        for full_path, rel_path in iter_maintenance_target_files(target_path):
            if total_files >= MAINTENANCE_MAX_FILES:
                skipped.append({"target": target_path, "path": rel_path, "reason": f"file limit reached ({MAINTENANCE_MAX_FILES})"})
                continue
            try:
                size = os.path.getsize(full_path)
            except OSError as error:
                skipped.append({"target": target_path, "path": rel_path, "reason": str(error)})
                continue
            if total_bytes + size > MAINTENANCE_MAX_BYTES:
                skipped.append({"target": target_path, "path": rel_path, "bytes": size, "reason": f"byte limit reached ({MAINTENANCE_MAX_BYTES})"})
                continue
            safe_rel = safe_workspace_relative_path(rel_path)
            if not safe_rel:
                skipped.append({"target": target_path, "path": rel_path, "reason": "unsafe relative path"})
                continue
            dest_path = safe_workspace_child(snapshot_root, safe_rel)
            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(full_path, dest_path)
            except OSError as error:
                skipped.append({"target": target_path, "path": rel_path, "reason": str(error)})
                continue
            total_files += 1
            total_bytes += size
            copied.append({
                "target": target_path,
                "snapshot": os.path.relpath(dest_path, workspace_dir).replace(os.sep, "/"),
                "bytes": size,
            })

    context["copied"] = copied
    context["skipped"] = skipped
    write_workspace_support_file(workspace_dir, MAINTENANCE_TARGETS_MANIFEST, render_maintenance_targets_manifest(context))
    emit_event("tool", f"harness maintenance target snapshot: {len(context.get('targets', []))} target(s)")
    return context


def render_maintenance_targets_manifest(context):
    lines = [
        "# Gemma Forge Maintenance Targets",
        "",
        "The user requested Gemma Forge maintenance. The harness copied exact allowlisted targets into this workspace for inspection.",
        "",
        f"- Snapshot root: `{MAINTENANCE_TARGETS_ROOT}`",
        f"- Actions file: `{MAINTENANCE_ACTIONS_FILE}`",
        f"- Ollama commands allowed: `{context.get('allowOllama')}`",
        f"- Destructive actions allowed: `{context.get('allowDestructive')}`",
        "",
    ]
    for target in context.get("targets", []):
        lines.extend([
            f"## {target.get('path')}",
            "",
            f"- Kind: `{target.get('kind')}`",
            f"- Exists: `{target.get('exists')}`",
            f"- Snapshot: `{target.get('snapshot_root') or 'n/a'}`",
            f"- Reason: {target.get('reason')}",
            "",
        ])
    skipped = context.get("skipped") or []
    if skipped:
        lines.extend(["## Skipped", ""])
        for item in skipped[:100]:
            lines.append(f"- `{item.get('target')}` / `{item.get('path', '')}`: {item.get('reason')}")
    return "\n".join(lines).rstrip() + "\n"


def build_harness_maintenance_context_block(context):
    if not isinstance(context, dict) or not context.get("requested"):
        return ""
    lines = [
        "",
        "Gemma Forge maintenance access is active (controlled allowlist).",
        f"- Manifest: `{context.get('manifest')}`",
        f"- Snapshot root: `{context.get('snapshotRoot', MAINTENANCE_TARGETS_ROOT)}`",
        f"- Maintenance actions file: `{context.get('actionsFile', MAINTENANCE_ACTIONS_FILE)}`",
        "- You may inspect only the workspace snapshots listed below.",
        "- To change Gemma Forge outside this workspace, write `artifacts/maintenance-actions.json`; the harness applies only validated actions to the exact allowlisted target paths.",
        "- Supported action types: `copy_file`, `write_file`, `copy_tree`.",
        "- Do not put absolute host paths in normal COMMANDS except `ollama` model names; file changes must go through the maintenance actions file.",
        "- If the target you need is not listed, stop and explain the missing target in NOTES instead of guessing.",
        "",
        "Allowed targets:",
    ]
    for target in context.get("targets", []):
        lines.append(
            f"- `{target.get('path')}` ({target.get('kind')}, exists={target.get('exists')}) "
            f"snapshot `{target.get('snapshot_root') or 'n/a'}` - {target.get('reason')}"
        )
    if context.get("allowOllama"):
        lines.extend([
            "",
            "Ollama maintenance commands may be listed in COMMANDS for model state checks or pulls:",
            "- Allowed: `ollama list`, `ollama show`, `ollama pull`, `ollama cp`, `ollama create`, `ollama ps`, `ollama stop`.",
            "- `ollama rm` is allowed only when the user explicitly requested removal.",
        ])
    lines.extend([
        "",
        "Example `artifacts/maintenance-actions.json`:",
        '{"actions":[{"type":"copy_file","source":"output/server.py","target":"/absolute/allowed/target.py"}]}',
        "",
    ])
    return "\n".join(lines)


def maintenance_target_allows(target, desired_path):
    target_path = os.path.abspath(os.path.expanduser(str(target.get("path", ""))))
    desired = os.path.abspath(os.path.expanduser(str(desired_path or "")))
    if not target_path or not desired:
        return False
    if target.get("kind") == "directory":
        return desired == target_path or path_is_inside(desired, target_path)
    return desired == target_path


def maintenance_path_allowed(context, desired_path):
    return any(maintenance_target_allows(target, desired_path) for target in context.get("targets", []))


def maintenance_backup_slug(path, index):
    base = os.path.basename(os.path.normpath(path)) or f"target-{index}"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower() or f"target-{index}"
    return f"{index:02d}-{base}"


def backup_maintenance_target(path, backup_root, index):
    if not os.path.exists(path):
        return None
    os.makedirs(backup_root, exist_ok=True)
    backup_path = os.path.join(backup_root, maintenance_backup_slug(path, index))
    if os.path.isdir(path):
        shutil.copytree(path, backup_path, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        shutil.copy2(path, backup_path)
    return backup_path


def apply_harness_maintenance_actions(workspace_dir, context):
    result = {
        "requested": bool(isinstance(context, dict) and context.get("requested")),
        "actionsFile": MAINTENANCE_ACTIONS_FILE,
        "applied": [],
        "skipped": [],
    }
    if not result["requested"]:
        return result

    actions_path = safe_workspace_child(workspace_dir, MAINTENANCE_ACTIONS_FILE)
    if not os.path.exists(actions_path):
        result["skipped"].append({"reason": f"`{MAINTENANCE_ACTIONS_FILE}` was not written"})
        return result
    try:
        with open(actions_path, "r") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        result["skipped"].append({"reason": f"could not read maintenance actions: {error}"})
        return result

    actions = payload.get("actions") if isinstance(payload, dict) else payload
    if not isinstance(actions, list):
        result["skipped"].append({"reason": "maintenance actions payload must be a list or an object with an actions list"})
        return result

    backup_root = os.path.join(MAINTENANCE_BACKUP_ROOT, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            result["skipped"].append({"index": index, "reason": "action was not an object"})
            continue
        action_type = str(action.get("type", "")).strip().lower()
        target = os.path.abspath(os.path.expanduser(str(action.get("target", "")).strip()))
        if action_type in {"delete", "remove", "rm", "delete_file", "delete_tree"} and not context.get("allowDestructive"):
            result["skipped"].append({"index": index, "target": target, "reason": "destructive action requires explicit remove/delete request"})
            continue
        if action_type not in {"copy_file", "write_file", "copy_tree"}:
            result["skipped"].append({"index": index, "target": target, "reason": f"unsupported action type `{action_type}`"})
            continue
        if not maintenance_path_allowed(context, target):
            result["skipped"].append({"index": index, "target": target, "reason": "target is not in the maintenance allowlist"})
            continue

        try:
            backup_path = backup_maintenance_target(target, backup_root, index)
            if action_type == "write_file":
                content = action.get("content")
                if not isinstance(content, str):
                    result["skipped"].append({"index": index, "target": target, "reason": "write_file content must be a string"})
                    continue
                if len(content.encode("utf-8", errors="replace")) > MAINTENANCE_MAX_BYTES:
                    result["skipped"].append({"index": index, "target": target, "reason": "write_file content exceeds maintenance byte limit"})
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w") as f:
                    f.write(content)
            else:
                source_rel = safe_workspace_relative_path(str(action.get("source", "")).strip())
                if not source_rel:
                    result["skipped"].append({"index": index, "target": target, "reason": "source must be a safe workspace-relative path"})
                    continue
                source = safe_workspace_child(workspace_dir, source_rel)
                if action_type == "copy_file":
                    if not os.path.isfile(source):
                        result["skipped"].append({"index": index, "target": target, "reason": "copy_file source is not a file"})
                        continue
                    if os.path.getsize(source) > MAINTENANCE_MAX_BYTES:
                        result["skipped"].append({"index": index, "target": target, "reason": "copy_file source exceeds maintenance byte limit"})
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.copy2(source, target)
                elif action_type == "copy_tree":
                    if not os.path.isdir(source):
                        result["skipped"].append({"index": index, "target": target, "reason": "copy_tree source is not a directory"})
                        continue
                    copied_files = 0
                    copied_bytes = 0
                    for full_path, _rel in iter_maintenance_target_files(source):
                        copied_files += 1
                        copied_bytes += os.path.getsize(full_path)
                        if copied_files > MAINTENANCE_MAX_FILES or copied_bytes > MAINTENANCE_MAX_BYTES:
                            raise ValueError("copy_tree source exceeds maintenance limits")
                    os.makedirs(target, exist_ok=True)
                    shutil.copytree(source, target, dirs_exist_ok=True)
            result["applied"].append({
                "index": index,
                "type": action_type,
                "target": target,
                "backup": backup_path,
            })
            emit_event("tool", f"harness maintenance applied: {action_type} -> {target}")
        except (OSError, ValueError) as error:
            result["skipped"].append({"index": index, "target": target, "reason": str(error)})
    return result


def iter_source_input_files(source_path):
    if os.path.isfile(source_path):
        yield source_path, os.path.basename(source_path)
        return
    if not os.path.isdir(source_path):
        return
    for root, dirs, files in os.walk(source_path):
        dirs[:] = [name for name in dirs if name not in SOURCE_INPUT_SKIP_DIRS]
        for filename in sorted(files):
            if filename in SOURCE_INPUT_SKIP_FILES:
                continue
            full_path = os.path.join(root, filename)
            try:
                relative_path = os.path.relpath(full_path, source_path)
            except ValueError:
                continue
            yield full_path, relative_path


def prepare_workspace_source_inputs(workspace_dir, session):
    """
    Copy explicit user-referenced local files/directories into the workspace.

    This is generic by design: PDF, images, CSVs, docs, code folders, and any
    other file type follow the same import path. Skills then decide how to
    inspect/process those workspace-relative copies.
    """
    project_text = session_user_source_text(session) if isinstance(session, dict) else ""
    detected = detect_local_source_paths(project_text)
    result = {
        "requested": bool(detected),
        "root": SOURCE_INPUTS_ROOT,
        "manifest": SOURCE_INPUTS_MANIFEST,
        "detected": detected,
        "sources": [],
        "copied": [],
        "skipped": [],
        "limits": {
            "maxFiles": SOURCE_INPUTS_MAX_FILES,
            "maxBytes": SOURCE_INPUTS_MAX_BYTES,
        },
    }
    if not detected:
        return result

    dest_root = safe_workspace_child(workspace_dir, SOURCE_INPUTS_ROOT)
    if os.path.isdir(dest_root):
        shutil.rmtree(dest_root)
    os.makedirs(dest_root, exist_ok=True)

    workspace_abs = os.path.abspath(workspace_dir)
    total_files = 0
    total_bytes = 0

    emit_event("tool", f"source input import requested: {len(detected)} path(s)")
    for index, item in enumerate(detected, start=1):
        original = item["original_path"]
        source_record = {
            "original_path": original,
            "kind": item.get("kind"),
            "workspace_root": None,
            "files": [],
        }
        if path_is_inside(original, workspace_abs):
            rel = os.path.relpath(original, workspace_abs).replace(os.sep, "/")
            source_record["workspace_root"] = rel
            for full_path, rel_path in iter_source_input_files(original):
                try:
                    size = os.path.getsize(full_path) if os.path.isfile(full_path) else 0
                except OSError:
                    size = 0
                source_record["files"].append({
                    "path": os.path.join(rel, rel_path).replace(os.sep, "/") if os.path.isdir(original) else rel,
                    "bytes": size,
                    "imported": False,
                    "reason": "already inside workspace",
                })
            result["sources"].append(source_record)
            continue

        slug = source_input_slug(original, index)
        source_dest_root = safe_workspace_child(dest_root, slug)
        source_record["workspace_root"] = os.path.relpath(source_dest_root, workspace_dir).replace(os.sep, "/")

        for full_path, rel_path in iter_source_input_files(original):
            if total_files >= SOURCE_INPUTS_MAX_FILES:
                result["skipped"].append({
                    "source": original,
                    "path": rel_path,
                    "reason": f"file limit reached ({SOURCE_INPUTS_MAX_FILES})",
                })
                continue
            if os.path.islink(full_path):
                result["skipped"].append({"source": original, "path": rel_path, "reason": "symlink skipped"})
                continue
            try:
                size = os.path.getsize(full_path)
            except OSError as error:
                result["skipped"].append({"source": original, "path": rel_path, "reason": str(error)})
                continue
            if total_bytes + size > SOURCE_INPUTS_MAX_BYTES:
                result["skipped"].append({
                    "source": original,
                    "path": rel_path,
                    "bytes": size,
                    "reason": f"byte limit reached ({SOURCE_INPUTS_MAX_BYTES})",
                })
                continue
            safe_rel = safe_workspace_relative_path(rel_path)
            if not safe_rel:
                result["skipped"].append({"source": original, "path": rel_path, "reason": "unsafe relative path"})
                continue
            dest_path = safe_workspace_child(source_dest_root, safe_rel)
            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(full_path, dest_path)
            except OSError as error:
                result["skipped"].append({"source": original, "path": rel_path, "reason": str(error)})
                continue
            total_files += 1
            total_bytes += size
            workspace_rel = os.path.relpath(dest_path, workspace_dir).replace(os.sep, "/")
            file_record = {"path": workspace_rel, "bytes": size}
            source_record["files"].append(file_record)
            result["copied"].append(file_record)

        result["sources"].append(source_record)
        emit_event(
            "tool",
            f"source import {source_record['workspace_root']}: {len(source_record['files'])} file(s)",
            source=original,
            files=len(source_record["files"]),
        )

    write_workspace_support_file(workspace_dir, SOURCE_INPUTS_MANIFEST, render_source_inputs_manifest(result))
    return result


def render_source_inputs_manifest(source_inputs):
    lines = [
        "# Source Inputs Imported By Gemma Forge",
        "",
        "The user named local file/directory paths. The harness copied source material into this workspace so downstream agents can operate on relative paths.",
        "",
        f"- Import root: `{SOURCE_INPUTS_ROOT}`",
        f"- File limit: `{source_inputs.get('limits', {}).get('maxFiles')}`",
        f"- Byte limit: `{source_inputs.get('limits', {}).get('maxBytes')}`",
        "",
    ]
    sources = source_inputs.get("sources") or []
    if not sources:
        lines.append("- No sources imported.")
    for source in sources:
        lines.extend([
            f"## {source.get('workspace_root')}",
            "",
            f"- Original: `{source.get('original_path')}`",
            f"- Kind: `{source.get('kind')}`",
            "",
        ])
        files = source.get("files") or []
        if not files:
            lines.append("- No files copied from this source.")
        else:
            for item in files[:200]:
                suffix = " (already in workspace)" if not item.get("imported", True) else ""
                lines.append(f"- `{item.get('path')}` ({item.get('bytes', 0)} bytes){suffix}")
            if len(files) > 200:
                lines.append(f"- ...and {len(files) - 200} more file(s)")
        lines.append("")
    skipped = source_inputs.get("skipped") or []
    if skipped:
        lines.extend(["## Skipped", ""])
        for item in skipped[:100]:
            lines.append(f"- `{item.get('source')}` / `{item.get('path')}`: {item.get('reason')}")
        if len(skipped) > 100:
            lines.append(f"- ...and {len(skipped) - 100} more skipped file(s)")
    return "\n".join(lines).rstrip() + "\n"


def build_source_inputs_context_block(source_inputs):
    if not isinstance(source_inputs, dict) or not source_inputs.get("requested"):
        return ""
    sources = source_inputs.get("sources") or []
    lines = [
        "",
        "Harness-imported source inputs (binding).",
        f"- Manifest: `{source_inputs.get('manifest')}`",
        "- Use these copied workspace-relative paths. Do NOT invent input filenames.",
        "- Do NOT put original absolute `/Users/...` paths in COMMANDS; sandboxed commands must use the copied paths below.",
        "- If the source files are binary, scanned, tabular, or numerous, write a small inspection/extraction/generation script and list a simple `python ...` command in COMMANDS.",
        "",
    ]
    for source in sources:
        files = source.get("files") or []
        lines.append(f"- `{source.get('original_path')}` -> `{source.get('workspace_root')}` ({len(files)} file(s))")
        for item in files[:40]:
            lines.append(f"  * `{item.get('path')}` ({item.get('bytes', 0)} bytes)")
        if len(files) > 40:
            lines.append(f"  * ...and {len(files) - 40} more file(s); see `{source_inputs.get('manifest')}`")
    skipped = source_inputs.get("skipped") or []
    if skipped:
        lines.append(f"- Skipped inputs: {len(skipped)}; see `{source_inputs.get('manifest')}` before claiming complete coverage.")
    lines.append("")
    return "\n".join(lines)


def build_workspace_exec_policy_block(session, maintenance_context=None):
    caps = set(session_capabilities_required(session))
    wants_exec = "shell_exec" in caps
    wants_install = "install_package" in caps
    wants_maintenance = isinstance(maintenance_context, dict) and maintenance_context.get("requested")
    if not wants_exec and not wants_install:
        return ""
    can_exec = tool_workspace.can_run_workspace_commands()
    if not can_exec:
        return "\nWorkspace command execution was requested, but the sandbox runner is unavailable. List commands in NOTES instead of claiming they ran.\n"
    install_lines = ""
    if wants_install:
        install_lines = """
- Package installs are allowed only for project/workspace dependencies: `npm install`, `npm add`, `pnpm install`, `pnpm add`, `yarn install`, `yarn add`, `pip install`, `pip3 install`, or `python -m pip install`.
- Pip installs are automatically targeted into `.gforge-installs/python` unless you provide a safe relative `--target`.
- Do not request `brew`, `apt`, `sudo`, `cargo install`, global installs, deploy, publish, push, credentials, absolute paths, parent directory traversal, pipes, redirection, or multiline shell.
"""
    maintenance_lines = ""
    if wants_maintenance:
        maintenance_lines = """
- For Gemma Forge maintenance, normal COMMANDS still run in the workspace sandbox. Do not use commands to edit host files.
- File changes outside the workspace must be requested through `artifacts/maintenance-actions.json`.
"""
        if maintenance_context.get("allowOllama"):
            maintenance_lines += "- Ollama model maintenance commands are allowed for this run: `ollama list`, `ollama show`, `ollama pull`, `ollama cp`, `ollama create`, `ollama ps`, `ollama stop`; `ollama rm` only when removal was explicit.\n"
    return """
Workspace command execution is available for this run.
- If the contract requires a local command, include a COMMANDS section after your file blocks.
- Commands run after files are written, from the workspace root, through a sandbox that can write only inside the workspace.
- Use simple validation/build commands such as `python -m unittest`, `python script.py`, `node script.js`, `npm test`, `npm run build`, `pytest`, `make test`, or `git status`.
- When source inputs are listed, use commands to inspect/process the copied workspace-relative paths and then validate the generated deliverable.
""" + install_lines + maintenance_lines + """
- Do not claim a command ran unless the final execution report shows a completed command run.
"""


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
    caps_required = session_capabilities_required(session)
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


def prepare_workspace_git_references(workspace_dir, session):
    """
    If the contract needs git_clone or the request names repo URLs, clone
    repositories into <workspace>/references/repos using host git/gh auth.
    """
    project_text = session.get("project", "") if isinstance(session, dict) else ""
    caps_required = session_capabilities_required(session)
    wants_git = "git_clone" in caps_required
    repos = tool_workspace.extract_repo_urls(project_text or "", limit=4)
    if not wants_git and not repos:
        return {"requested": False, "available": tool_workspace.can_clone_repositories(), "cloned": []}
    if not repos:
        return {
            "requested": True,
            "available": tool_workspace.can_clone_repositories(),
            "cloned": [],
            "error": "git_clone required but no repository URL was found in the request",
        }

    emit_event("tool", "git clone references: " + ", ".join(item["display_url"] for item in repos))
    try:
        result = tool_workspace.clone_repositories_into_workspace(workspace_dir, project_text, limit=4)
        for item in result.get("cloned", []):
            status = "ok" if item.get("ok") else "failed"
            emit_event("tool", f"git clone {status}: {item.get('url')} -> {item.get('path')}")
        return result
    except Exception as error:
        log_error("tool-git", "workspace git clone failed", error)
        emit_event("error", f"git clone failed: {error}")
        return {
            "requested": True,
            "available": tool_workspace.can_clone_repositories(),
            "cloned": [],
            "error": str(error),
        }


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
    content_requirements = context.get("content_requirements") if isinstance(context.get("content_requirements"), list) else []

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
        f"- deliverable.path_pattern = `{path_pattern}` — every final deliverable file you write or generate must match this pattern.",
    ]
    if count:
        parts.append(f"- deliverable.count = `{count}` — write exactly this many files of the format.")
    if content_requirements:
        parts.extend([
            "",
            "CONTENT QUANTITY REQUIREMENTS (binding counts inside the deliverable):",
            "- These are NOT file counts. They are repeated content units the user asked for.",
            "- If a requirement says each/per category, repeat that count for every category you include.",
        ])
        if fmt in SCRIPT_RUNTIME_FORMATS:
            parts.append(
                "- For a runnable script deliverable, file/directory counts are behavior the script must "
                "produce when run in a temp test space; do NOT emit those generated outputs as extra deliverables."
            )
        for requirement in content_requirements:
            parts.append(f"- {content_requirement_line(requirement)}")

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


REPAIR_SNAPSHOT_TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".htm",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".svg",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
REPAIR_SNAPSHOT_PRIORITY_PATHS = (
    "artifacts/validation.json",
    "artifacts/model-execution.json",
)


def repair_snapshot_readable_path(relative_path):
    safe_path = safe_workspace_relative_path(relative_path)
    if not safe_path:
        return None
    filename = os.path.basename(safe_path)
    extension = os.path.splitext(filename)[1].lower()
    if extension in REPAIR_SNAPSHOT_TEXT_EXTENSIONS:
        return safe_path
    if filename in {"Dockerfile", "Makefile"}:
        return safe_path
    return None


def add_repair_snapshot_file(items, seen, workspace_dir, relative_path, per_file_limit):
    safe_path = repair_snapshot_readable_path(relative_path)
    if not safe_path or safe_path in seen:
        return False
    full_path = os.path.join(workspace_dir, safe_path)
    if not os.path.isfile(full_path):
        return False
    try:
        size = os.path.getsize(full_path)
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(per_file_limit + 1)
    except OSError:
        return False
    if "\x00" in content[:200]:
        return False
    seen.add(safe_path)
    items.append({
        "path": safe_path,
        "bytes": size,
        "content": truncate_text(content, per_file_limit),
    })
    return True


def build_workspace_repair_snapshot(session, workspace_dir, max_files=12, per_file_limit=1600, total_limit=12000):
    if not workspace_dir or not os.path.isdir(workspace_dir):
        return "Harness file-inspection output: no existing workspace directory was found."

    items = []
    seen = set()

    for relative_path in list(REPAIR_SNAPSHOT_PRIORITY_PATHS) + derive_verification_paths(session, workspace_dir):
        if len(items) >= max_files:
            break
        add_repair_snapshot_file(items, seen, workspace_dir, relative_path, per_file_limit)

    omitted = 0
    root_path = os.path.abspath(workspace_dir)
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [name for name in dirs if name not in IGNORED_CODE_DIRS]
        for filename in sorted(files):
            relative_path = os.path.relpath(os.path.join(root, filename), root_path).replace(os.sep, "/")
            if relative_path in seen:
                continue
            if len(items) >= max_files:
                if repair_snapshot_readable_path(relative_path):
                    omitted += 1
                continue
            add_repair_snapshot_file(items, seen, workspace_dir, relative_path, per_file_limit)

    if not items:
        return "Harness file-inspection output: workspace exists, but no readable text deliverables were found yet."

    lines = ["Harness file-inspection output (read this before deciding what to write):"]
    for item in items:
        lines.extend([
            "",
            f"--- {item['path']} ({item['bytes']} bytes) ---",
            item["content"],
        ])
    if omitted:
        lines.append(f"\n... {omitted} additional readable file(s) omitted from this bounded snapshot.")
    return truncate_text("\n".join(lines), total_limit)


def build_repair_continuation_block(session, workspace_dir, review):
    if not review:
        return ""

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

USER CORRECTION (authoritative human steer):
> {user_note}
"""

    snapshot = build_workspace_repair_snapshot(session, workspace_dir)
    return f"""
CONTINUATION REPAIR MODE (binding on this retry):

The prior attempt failed review or deterministic validation. Do not start over,
discard useful work, or pivot to a fresh plan. Starting over is allowed only if
the human explicitly asks for a restart.

Your job:
- Treat the harness file-inspection output below as the current-file check for this workspace.
- Fix the exact blockers in findings, fixesNeeded, validationFailures, and any human correction.
- Preserve working structure and content that already satisfies the request.
- Re-emit complete file blocks only for files that must be repaired or added; when updating a file, include the entire corrected file content.
- Proceed from the existing workspace and complete the rest of the original request for delivery.

Reviewer findings (structured):
{json.dumps(review_payload, indent=2)}
{user_note_section}
{snapshot}
"""


def build_model_execution_prompt(session, workspace_dir, review=None, skill_context=None, research=None, git_references=None, source_inputs=None, maintenance_context=None):
    review_block = build_repair_continuation_block(session, workspace_dir, review)
    skill_block = (skill_context or {}).get("prompt", "No Gemma Forge skills are staged for this workspace.")

    context_block = build_execution_context_block(session)
    research_block = build_research_context_block(research)
    git_reference_block = build_git_reference_context_block(git_references)
    source_inputs_block = build_source_inputs_context_block(source_inputs)
    maintenance_block = build_harness_maintenance_context_block(maintenance_context)
    workspace_exec_block = build_workspace_exec_policy_block(session, maintenance_context)

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
{source_inputs_block}
{maintenance_block}
{research_block}
{git_reference_block}
{workspace_exec_block}
After your file blocks you may optionally add these sections (each prefix in ALL CAPS at the start of a line):

SUMMARY:
one or two sentences about what you produced.

COMMANDS:
- optional simple workspace command(s) only when the contract requires shell_exec.

NOTES:
- short implementation notes (optional)

VERIFICATION:
- specific checks that prove the contract was satisfied (optional)

Rules:
- Every file path must be relative to the workspace root.
- Final deliverable files must match deliverable.path_pattern from the contract. Support scripts/manifests may live under `scripts/`, `tools/`, or `artifacts/` only when needed to inspect imported sources, generate binary deliverables, or validate the result.
- Do not use absolute paths or parent directory traversal.
- Do not write into `.gforge/`; it is reserved for harness-provided support context.
- Include complete file contents, not patches.
- Do NOT wrap files in markdown code fences. Use only the `<<<GFORGE_FILE:...>>>` / `<<<END_GFORGE_FILE>>>` delimiters shown in the contract above.
- LINKS RULE: If any HTML / CSS / Markdown file you emit contains a local-relative `href`, `src`, or `url()` pointing to another file in the workspace (e.g. `href="results/option_A.html"`), you MUST also emit that target file as its own `<<<GFORGE_FILE:...>>>` block. The harness's deterministic validator scans every HTML/CSS/MD deliverable for local-relative refs and FAILS the run if any of them point at files you did not actually write. Either deliver the file or remove the link. Do not promise files you don't produce.
- PATH RESOLUTION RULE: HTML / CSS path references resolve RELATIVE to the file that contains them, just like a browser does it. This is a common small-model bug — read this twice:
    * If you emit `output/index.html` with `<a href="results/option_1.html">`, the browser looks for `output/results/option_1.html` — NOT `results/option_1.html` at the workspace root. If you put `option_1.html` at the workspace root instead, the link is broken.
    * Going the other way: if `results/option_1.html` has `<a href="../index.html">`, the browser looks for `index.html` at the workspace root. If your index lives at `output/index.html`, that link is also broken.
  Easiest correct approach: put ALL cross-linked deliverable files in the SAME directory. If `index.html` and `option_1.html` are siblings at the workspace root, then `<a href="option_1.html">` from index works, and `<a href="index.html">` from option_1 works. No `output/` or `results/` subdirectories unless the contract specifically requires them.
  If you must split across directories, use the real relative path: from `output/index.html` to a file at workspace-root `results/option_1.html` is `<a href="../results/option_1.html">`.
  The deterministic validator resolves every href / src / url() exactly the way a browser would. If the resolved path is not on disk, the run fails — and the failure message tells you the resolved path so you can fix it on the next attempt.
"""


def normalize_model_files(files):
    normalized = []
    rejected = []
    if not isinstance(files, list):
        return normalized, [{"path": "", "reason": "files was not a list"}]

    # First pass — basic per-item safety + content checks.
    accepted_items = []
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
        accepted_items.append({"path": safe_path, "content": content})

    # Second pass — within-batch dir/file collision check. Catches the
    # small-model hallucination where the same name is used both as a file
    # and as a parent directory in the same emission, e.g. emitting both
    # `output` (as a file) and `output/index.html` (which needs `output` to
    # be a directory). Without this guard, the second write would fail
    # with NotADirectoryError or the first write would clobber the dir.
    file_paths = {x["path"] for x in accepted_items}
    parent_dirs = set()
    for x in accepted_items:
        parts = x["path"].split("/")
        for i in range(1, len(parts)):
            parent_dirs.add("/".join(parts[:i]))

    final = []
    for x in accepted_items:
        if x["path"] in parent_dirs:
            rejected.append({
                "path": x["path"],
                "reason": (
                    f"path collision: `{x['path']}` is also the parent directory of "
                    f"another file in this same batch. A name cannot be both a file "
                    f"and a directory at once."
                ),
            })
            continue
        final.append(x)

    return final, rejected


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
    evidence_required_even_when_available = {"git_clone", "shell_exec", "install_package", "web_browse", "skill_author"}
    for capability, pattern, evidence_kind in CLAIM_PATTERNS:
        for match in pattern.finditer(claim_text):
            if capability in can_now_set and capability not in evidence_required_even_when_available:
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
            evidence_ok, detail = check_claim_evidence(evidence_kind, match, claim_text, workspace_dir=workspace_dir)
            if evidence_ok:
                continue
            # Dedupe identical fabrication quotes — the same URL is often repeated
            # across summary + notes + verification, but a single flag is enough.
            dedupe_key = (capability, quote.strip().lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            if capability in can_now_set:
                reason = f"requires on-disk evidence for `{capability}` and none was found ({detail})"
            else:
                reason = f"cannot `{capability}` and there is no on-disk evidence ({detail})"
            failures.append(
                f"Fabricated-claim guard: model said \"{quote[:160]}\" but the harness "
                f"{reason}. Remove the claim or shrink scope honestly."
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


def check_claim_evidence(kind, match, claim_text, workspace_dir=None):
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
        if workspace_dir:
            repo_root = os.path.join(workspace_dir, "references", "repos")
            if os.path.isdir(repo_root):
                try:
                    for entry in os.listdir(repo_root):
                        full = os.path.join(repo_root, entry)
                        if os.path.isdir(full) and os.path.isdir(os.path.join(full, ".git")) and token.lower() in entry.lower():
                            return True, f"workspace repo checkout at {full}"
                except OSError:
                    pass
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
        if workspace_dir:
            research_dir = os.path.join(workspace_dir, "research")
            try:
                artifacts = [
                    name for name in os.listdir(research_dir)
                    if name.lower().endswith(".md") and os.path.isfile(os.path.join(research_dir, name))
                ]
            except OSError:
                artifacts = []
            if len(artifacts) >= n:
                return True, f"{len(artifacts)} research artifact(s) exist in {research_dir}"
            if artifacts:
                return False, f"only {len(artifacts)} research artifact(s) exist; claim needs {n}"
        return False, f"no research artifacts found for claim of researching {n} source(s)"

    if kind == "command_log":
        if workspace_dir:
            metadata_path = os.path.join(workspace_dir, "artifacts", "model-execution.json")
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
            except (OSError, json.JSONDecodeError):
                metadata = {}
            command_runs = metadata.get("commandRuns") if isinstance(metadata, dict) else None
            if isinstance(command_runs, list):
                ran = [item for item in command_runs if isinstance(item, dict) and not item.get("skipped")]
                ok = [item for item in ran if item.get("ok")]
                if ok:
                    return True, f"{len(ok)} workspace command(s) completed successfully"
                if ran:
                    return False, f"{len(ran)} workspace command(s) ran but none completed successfully"
        return False, "no completed workspace command run was recorded"

    if kind == "package_evidence":
        if workspace_dir:
            metadata_path = os.path.join(workspace_dir, "artifacts", "model-execution.json")
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
            except (OSError, json.JSONDecodeError):
                metadata = {}
            command_runs = metadata.get("commandRuns") if isinstance(metadata, dict) else None
            if isinstance(command_runs, list):
                install_runs = [
                    item for item in command_runs
                    if isinstance(item, dict)
                    and item.get("ok")
                    and re.search(r"\b(npm|pnpm|yarn|pip|pip3|python3?)\b.*\b(install|add)\b", str(item.get("command", "")), re.IGNORECASE)
                ]
                if install_runs:
                    return True, f"{len(install_runs)} package install command(s) completed successfully"
        return False, "no completed workspace package install run was recorded"

    if kind in ("external_call_evidence", "message_evidence", "deploy_evidence"):
        return False, f"harness cannot {kind.replace('_', ' ')}; no tool runtime is present"

    return False, f"unhandled claim evidence kind: {kind}"


def validate_local_link_targets(workspace_dir, files):
    """
    Scan model-authored HTML / CSS / Markdown files for local-relative
    references (href / src / url() / [text](path)) and flag any that
    point at files the model promised but never actually wrote.

    Catches a class of small-model hallucination where the page LOOKS
    complete (links to `results/option_A.html`, `assets/script.js`, etc.)
    but the harness only received one GFORGE_FILE block for the index
    itself. Project-agnostic — works for any HTML/CSS/MD output.

    Returns a list of failure strings. Each one names the source file
    that contained the dead link and the path it pointed at.
    """
    failures = []
    if not workspace_dir or not os.path.isdir(workspace_dir):
        return failures

    # Regex patterns for the common local-link forms. We deliberately
    # keep these narrow — better to miss an exotic href than to
    # false-positive on a JS template string.
    html_attr_re = re.compile(
        r"""\s(?:href|src|poster|action|data-src)\s*=\s*["']([^"'#?]+)["']""",
        re.IGNORECASE,
    )
    css_url_re = re.compile(r"""url\(\s*['"]?([^'")\s#?]+)""", re.IGNORECASE)
    md_link_re = re.compile(r"""\]\(([^)\s#?]+)\)""")

    def is_external(ref):
        ref = (ref or "").strip()
        if not ref:
            return True
        lower = ref.lower()
        if lower.startswith(("http://", "https://", "mailto:", "tel:", "javascript:", "data:", "//", "ftp://")):
            return True
        # Skip pure fragments (#anchor) — handled by the regex `[^"'#?]+`
        # but keep this as a defensive check.
        if ref.startswith("#"):
            return True
        # Skip absolute web-root paths — we can't tell where the doc
        # root is, so don't flag them. (Most static deliveries use
        # relative paths anyway.)
        if ref.startswith("/"):
            return True
        return False

    for item in files:
        relative_path = item.get("path", "") if isinstance(item, dict) else ""
        if not relative_path:
            continue
        ext = os.path.splitext(relative_path)[1].lower()
        if ext not in {".html", ".htm", ".css", ".md"}:
            continue
        safe_path = safe_workspace_relative_path(relative_path)
        if not safe_path:
            continue
        src_path = os.path.join(workspace_dir, safe_path)
        if not os.path.isfile(src_path):
            continue
        try:
            with open(src_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        refs = set()
        if ext in {".html", ".htm"}:
            refs.update(html_attr_re.findall(content))
            refs.update(css_url_re.findall(content))
        elif ext == ".css":
            refs.update(css_url_re.findall(content))
        elif ext == ".md":
            refs.update(md_link_re.findall(content))

        src_dir = os.path.dirname(src_path)
        for ref in refs:
            if is_external(ref):
                continue
            ref_clean = ref.split("?", 1)[0].split("#", 1)[0].strip()
            if not ref_clean:
                continue
            target_abs = os.path.normpath(os.path.join(src_dir, ref_clean))
            # Guard against escapes out of the workspace.
            try:
                rel_inside = os.path.relpath(target_abs, workspace_dir)
            except ValueError:
                continue
            if rel_inside.startswith(".."):
                continue
            if not os.path.exists(target_abs):
                # Try to find a file with the same basename anywhere else in
                # the workspace and suggest the correct relative path. This
                # turns a "missing file" finding into a fixable one — the
                # model can re-emit with the right path on the next pass.
                basename = os.path.basename(ref_clean)
                suggestions = []
                if basename:
                    for root, _, names in os.walk(workspace_dir):
                        if basename in names:
                            actual_abs = os.path.join(root, basename)
                            try:
                                suggested_rel = os.path.relpath(actual_abs, src_dir)
                            except ValueError:
                                continue
                            suggestions.append(suggested_rel.replace(os.sep, "/"))
                # Show the resolved (broken) target relative to workspace so the
                # model sees what its href ACTUALLY resolves to vs. what it
                # probably meant.
                resolved_rel = rel_inside.replace(os.sep, "/")
                hint = ""
                if suggestions:
                    # Pick the shortest suggestion (usually correct).
                    suggestions.sort(key=len)
                    hint = f" — the file exists at the workspace, did you mean `href=\"{suggestions[0]}\"`?"
                failures.append(
                    f"`{safe_path}` links to `{ref_clean}` "
                    f"which resolves to `{resolved_rel}` — not found{hint}"
                )

    return failures


def validate_negated_support_file_constraints(workspace_dir, files, project_context):
    failures = []
    reference_text = project_context_reference_text(project_context) if isinstance(project_context, dict) else ""
    if not reference_text:
        return failures

    if html_support_format_negated(reference_text, "css"):
        css_paths = []
        css_links = []
        for item in files:
            relative_path = item.get("path", "") if isinstance(item, dict) else ""
            safe_path = safe_workspace_relative_path(relative_path)
            if not safe_path:
                continue
            ext = os.path.splitext(safe_path)[1].lower()
            if ext == ".css":
                css_paths.append(safe_path)
                continue
            if ext not in {".html", ".htm"}:
                continue
            html_path = os.path.join(workspace_dir, safe_path)
            if not os.path.isfile(html_path):
                continue
            try:
                with open(html_path, "r", encoding="utf-8", errors="replace") as f:
                    html = f.read()
            except OSError:
                continue
            css_links.extend(
                re.findall(
                    r"""<link\b[^>]*\bhref\s*=\s*["']([^"']+\.css(?:[?#][^"']*)?)["'][^>]*>""",
                    html,
                    re.IGNORECASE,
                )
            )
        if css_paths:
            failures.append(
                "CSS file was forbidden by the project contract, but the model wrote "
                + ", ".join(f"`{path}`" for path in sorted(set(css_paths)))
            )
        if css_links:
            failures.append(
                "CSS file was forbidden by the project contract, but HTML links "
                + ", ".join(f"`{link}`" for link in sorted(set(css_links)))
            )
    return failures


DELIVERABLE_FORMAT_EXTENSIONS = {
    "html": {".html", ".htm"},
    "css": {".css"},
    "javascript": {".js", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "python": {".py"},
    "svg": {".svg"},
    "json": {".json"},
    "yaml": {".yaml", ".yml"},
    "markdown": {".md", ".markdown"},
    "pdf": {".pdf"},
    "shell": {".sh", ".bash", ".zsh"},
    "sql": {".sql"},
    "dockerfile": {"", ".dockerfile"},
    "mermaid": {".mmd", ".mermaid"},
    "txt": {".txt"},
}

TEXT_CONTENT_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".py", ".svg", ".json", ".yaml", ".yml", ".md", ".markdown",
    ".sh", ".bash", ".zsh", ".sql", ".txt",
}

SCRIPT_RUNTIME_FORMATS = {"python"}
SCRIPT_RUNTIME_SIDE_EFFECT_TERMS = (
    ".txt", ".md", ".json", ".csv", ".pdf", ".html",
    "directory", "directories", "folder", "folders", "file", "files",
)
SCRIPT_RUNTIME_SIDE_EFFECT_VERBS = (
    "create", "creates", "created", "make", "makes", "made", "generate",
    "generates", "generated", "write", "writes", "written", "populate",
    "populates", "save", "saves", "emit", "emits",
)


def path_pattern_parts(deliverable):
    path_pattern = str((deliverable or {}).get("path_pattern", "")).strip()
    fmt = str((deliverable or {}).get("format", "")).strip().lower()
    first_path_token = path_pattern
    if path_pattern:
        for token in re.split(r"\s+|,", path_pattern):
            if "/" in token or (fmt and token.lower().endswith("." + fmt)):
                first_path_token = token
                break
    pattern_dir = os.path.dirname(first_path_token) if first_path_token else ""
    pattern_ext = os.path.splitext(os.path.basename(first_path_token))[1].lower()
    if not pattern_ext and fmt in DELIVERABLE_FORMAT_EXTENSIONS:
        exts = [ext for ext in DELIVERABLE_FORMAT_EXTENSIONS[fmt] if ext]
        pattern_ext = exts[0] if exts else ""
    return path_pattern, pattern_dir, pattern_ext


def project_context_reference_text(project_context, extra_text=""):
    chunks = []
    if isinstance(project_context, dict):
        project = project_context.get("project") if isinstance(project_context.get("project"), dict) else {}
        chunks.extend(str(project.get(key, "")) for key in ("name", "type", "domain"))

        intent = project_context.get("intent") if isinstance(project_context.get("intent"), dict) else {}
        chunks.extend(str(intent.get(key, "")) for key in ("surface_ask", "underlying_need", "success_means"))

        deliverable = project_context.get("deliverable") if isinstance(project_context.get("deliverable"), dict) else {}
        chunks.extend(str(deliverable.get(key, "")) for key in ("format", "count", "path_pattern", "scope"))

        constraints = project_context.get("constraints") if isinstance(project_context.get("constraints"), dict) else {}
        hard = constraints.get("hard_requirements") if isinstance(constraints.get("hard_requirements"), list) else []
        chunks.extend(str(item) for item in hard)

        acceptance = project_context.get("acceptance") if isinstance(project_context.get("acceptance"), list) else []
        chunks.extend(str(item) for item in acceptance)

        support_files = project_context.get("support_files") if isinstance(project_context.get("support_files"), list) else []
        for item in support_files:
            if isinstance(item, dict):
                chunks.extend(str(item.get(key, "")) for key in ("format", "count", "path_pattern"))
    if extra_text:
        chunks.append(str(extra_text))
    return "\n".join(chunk for chunk in chunks if str(chunk).strip())


def named_files_in_text(text, extensions):
    extensions = tuple(ext.lower().lstrip(".") for ext in extensions)
    if not extensions:
        return []
    ext_pattern = "|".join(re.escape(ext) for ext in extensions)
    pattern = re.compile(
        rf"(?<![\w./-])([A-Za-z0-9_.\/-]+\.({ext_pattern}))(?![\w.-])",
        re.IGNORECASE,
    )
    seen = set()
    matches = []
    for match in pattern.finditer(str(text or "")):
        path = match.group(1).strip("`'\"“”‘’.,;:()[]{}<>")
        path = path.replace("\\", "/").lstrip("./")
        if not path or path in seen:
            continue
        seen.add(path)
        matches.append(path)
    return matches


def dedupe_named_files_by_basename(paths):
    deduped = []
    seen = set()
    for path in paths or []:
        cleaned = str(path or "").replace("\\", "/").strip()
        if not cleaned:
            continue
        key = os.path.basename(cleaned).lower() or cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def requested_html_file_count(text):
    text = str(text or "")
    html_files = dedupe_named_files_by_basename(named_files_in_text(text, (".html", ".htm")))
    if html_files:
        return len(html_files)

    patterns = [
        re.compile(
            rf"\b(?P<count>{COUNT_TOKEN_PATTERN})\s+html\s+(?:pages?|files?|documents?)\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?P<count>{COUNT_TOKEN_PATTERN})\s+(?:single\s+)?html\s+page\b",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return parse_positive_int(match.group("count"))

    if re.search(r"\b(?:one|1|single|a)\s+(?:linked\s+)?html\s+(?:page|file|document)\b", text, re.IGNORECASE):
        return 1
    if re.search(r"\b(?:single-page|single page|one-page|one page)\b", text, re.IGNORECASE):
        return 1
    return None


HTML_SUPPORT_FILE_FORMATS = {
    "css": {
        "extensions": (".css",),
        "fallback": "styles.css",
        "terms": ("stylesheet", "css file", "linked css"),
        "label": "CSS support",
        "negation_patterns": (
            r"\bno\s+(?:separate\s+|external\s+|linked\s+)?css\s+files?\b",
            r"\bno\s+\.css\s+files?\b",
            r"\bwithout\s+(?:a\s+|any\s+)?(?:separate\s+|external\s+|linked\s+)?css\s+files?\b",
            r"\bdo\s+not\s+(?:create|emit|include|link|write|add)\s+(?:a\s+|any\s+)?(?:separate\s+|external\s+|linked\s+)?css\s+files?\b",
            r"\bmust\s+not\s+(?:create|emit|include|link|write|add)\s+(?:a\s+|any\s+)?(?:separate\s+|external\s+|linked\s+)?css\s+files?\b",
        ),
    },
    "javascript": {
        "extensions": (".js", ".mjs", ".cjs"),
        "fallback": "app.js",
        "terms": (
            "javascript file",
            "js file",
            "linked javascript",
            "linked js",
            "script file",
            "script src",
        ),
        "label": "JavaScript support",
        "negation_patterns": (
            r"\bno\s+(?:separate\s+|external\s+|linked\s+)?(?:javascript|js)\s+files?\b",
            r"\bno\s+\.(?:js|mjs|cjs)\s+files?\b",
            r"\bwithout\s+(?:a\s+|any\s+)?(?:separate\s+|external\s+|linked\s+)?(?:javascript|js)\s+files?\b",
            r"\bdo\s+not\s+(?:create|emit|include|link|write|add)\s+(?:a\s+|any\s+)?(?:separate\s+|external\s+|linked\s+)?(?:javascript|js)\s+files?\b",
            r"\bmust\s+not\s+(?:create|emit|include|link|write|add)\s+(?:a\s+|any\s+)?(?:separate\s+|external\s+|linked\s+)?(?:javascript|js)\s+files?\b",
        ),
    },
}


def html_support_format_negated(reference_text, support_format):
    config = HTML_SUPPORT_FILE_FORMATS.get(support_format) or {}
    text = str(reference_text or "").lower()
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in config.get("negation_patterns", ()))


def html_support_file_names(reference_text, support_format):
    config = HTML_SUPPORT_FILE_FORMATS.get(support_format)
    if not config:
        return []
    files = dedupe_named_files_by_basename(named_files_in_text(reference_text, config["extensions"]))
    lowered = str(reference_text or "").lower()
    if not files and html_support_format_negated(reference_text, support_format):
        return []
    if not files and any(term in lowered for term in config["terms"]):
        files = [config["fallback"]]
    return files


def html_support_bundle_requested(project_context, extra_text="", support_formats=None):
    text = project_context_reference_text(project_context, extra_text=extra_text)
    lowered = text.lower()
    if not text:
        return False
    has_html = (
        bool(named_files_in_text(lowered, (".html", ".htm")))
        or "html" in lowered
        or "webpage" in lowered
        or "web page" in lowered
        or "single-page" in lowered
        or "single page" in lowered
    )
    formats = support_formats or tuple(HTML_SUPPORT_FILE_FORMATS)
    has_support = any(html_support_file_names(text, support_format) for support_format in formats)
    return has_html and has_support


def html_css_support_bundle_requested(project_context, extra_text=""):
    return html_support_bundle_requested(project_context, extra_text=extra_text, support_formats=("css",))


def html_javascript_support_bundle_requested(project_context, extra_text=""):
    return html_support_bundle_requested(
        project_context,
        extra_text=extra_text,
        support_formats=("javascript",),
    )


def effective_deliverable_file_count(project_context):
    if not isinstance(project_context, dict):
        return None
    deliverable = project_context.get("deliverable") if isinstance(project_context.get("deliverable"), dict) else {}
    expected = parse_positive_int(deliverable.get("count"))
    fmt = str(deliverable.get("format", "")).strip().lower()
    if fmt == "html" and expected and expected > 1 and html_support_bundle_requested(project_context):
        primary_count = requested_html_file_count(project_context_reference_text(project_context))
        if primary_count and primary_count < expected:
            return primary_count
    return expected


def file_matches_deliverable(relative_path, deliverable):
    fmt = str((deliverable or {}).get("format", "")).strip().lower()
    path_pattern, pattern_dir, pattern_ext = path_pattern_parts(deliverable)
    relative_path = str(relative_path or "").replace(os.sep, "/")
    ext = os.path.splitext(relative_path)[1].lower()
    allowed_exts = DELIVERABLE_FORMAT_EXTENSIONS.get(fmt, set())
    if allowed_exts and ext not in allowed_exts:
        return False
    if pattern_ext and ext != pattern_ext:
        return False
    if pattern_dir:
        normalized_dir = pattern_dir.replace(os.sep, "/").strip("/")
        if normalized_dir and not relative_path.startswith(normalized_dir + "/"):
            return False
    return bool(relative_path and not relative_path.startswith(".gforge/"))


def validate_deliverable_file_count(files, project_context):
    if not isinstance(project_context, dict):
        return []
    deliverable = project_context.get("deliverable") if isinstance(project_context.get("deliverable"), dict) else {}
    expected = effective_deliverable_file_count(project_context)
    if not expected or expected <= 1:
        return []
    matching = [
        item for item in files
        if isinstance(item, dict) and file_matches_deliverable(item.get("path", ""), deliverable)
    ]
    if len(matching) >= expected:
        return []
    path_pattern = str(deliverable.get("path_pattern", "")).strip() or "(no path_pattern)"
    fmt = str(deliverable.get("format", "")).strip() or "file"
    return [
        f"deliverable.count expected at least {expected} `{fmt}` file(s) matching `{path_pattern}`, "
        f"but the model wrote {len(matching)}."
    ]


def code_deliverable_files_for_extensions(files, project_context, extensions):
    deliverable = project_context.get("deliverable") if isinstance(project_context, dict) and isinstance(project_context.get("deliverable"), dict) else {}
    extensions = tuple(ext.lower() for ext in extensions)
    matching = [
        item for item in files
        if isinstance(item, dict)
        and str(item.get("path", "")).lower().endswith(extensions)
        and file_matches_deliverable(item.get("path", ""), deliverable)
    ]
    if matching:
        return matching
    return [
        item for item in files
        if isinstance(item, dict) and str(item.get("path", "")).lower().endswith(extensions)
    ]


def code_deliverable_files(files, project_context, extension):
    return code_deliverable_files_for_extensions(files, project_context, (extension,))


HTML_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
HTML_OPTIONAL_CLOSE_TAGS = {
    "body", "colgroup", "dd", "dt", "head", "html", "li", "option",
    "optgroup", "p", "tbody", "td", "tfoot", "th", "thead", "tr",
}
HTML_IMPLICIT_CLOSE_BEFORE_START = {
    "dd": {"dd", "dt"},
    "dt": {"dd", "dt"},
    "li": {"li"},
    "option": {"option"},
    "optgroup": {"option", "optgroup"},
    "p": {"p"},
    "tbody": {"tbody", "thead", "tfoot"},
    "td": {"td", "th"},
    "tfoot": {"tbody", "thead", "tfoot"},
    "th": {"td", "th"},
    "thead": {"tbody", "thead", "tfoot"},
    "tr": {"td", "th", "tr"},
}


class HTMLIntegrityParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        normalized = str(tag or "").lower()
        if normalized and normalized not in HTML_VOID_TAGS:
            closable = HTML_IMPLICIT_CLOSE_BEFORE_START.get(normalized, set())
            while self.stack and self.stack[-1][0] in closable:
                self.stack.pop()
            self.stack.append((normalized, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        return None

    def handle_endtag(self, tag):
        normalized = str(tag or "").lower()
        if not normalized or normalized in HTML_VOID_TAGS:
            return
        if not self.stack:
            line, col = self.getpos()
            self.errors.append(f"closing tag </{normalized}> has no matching start tag at line {line}, column {col}")
            return
        open_tag, _pos = self.stack[-1]
        if open_tag == normalized:
            self.stack.pop()
            return
        open_tags = [item[0] for item in self.stack]
        line, col = self.getpos()
        while self.stack and self.stack[-1][0] in HTML_OPTIONAL_CLOSE_TAGS:
            self.stack.pop()
            if self.stack and self.stack[-1][0] == normalized:
                self.stack.pop()
                return
        if normalized in open_tags:
            self.errors.append(
                f"closing tag </{normalized}> is mismatched at line {line}, column {col}; "
                f"expected </{open_tag}> first"
            )
        else:
            self.errors.append(f"closing tag </{normalized}> has no matching start tag at line {line}, column {col}")


def validate_html_source(source, relative_path):
    if not str(source or "").strip():
        return "HTML file is empty"
    parser = HTMLIntegrityParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as error:
        return f"HTML parser rejected the file ({error})"
    if parser.errors:
        return parser.errors[0]
    return ""


CSS_BRACKET_PAIRS = {"}": "{", ")": "(", "]": "["}


def css_line_col(source, index):
    prefix = source[:index]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    col = index + 1 if last_newline < 0 else index - last_newline
    return line, col


def validate_css_source(source, relative_path):
    source = str(source or "")
    if not source.strip():
        return "CSS file is empty"
    stack = []
    quote = ""
    escaped = False
    in_comment = False
    index = 0
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if in_comment:
            if char == "*" and nxt == "/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char == "/" and nxt == "*":
            in_comment = True
            index += 2
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in "{([":
            stack.append((char, index))
        elif char in CSS_BRACKET_PAIRS:
            expected = CSS_BRACKET_PAIRS[char]
            if not stack or stack[-1][0] != expected:
                line, col = css_line_col(source, index)
                return f"unexpected `{char}` at line {line}, column {col}"
            stack.pop()
        index += 1
    if in_comment:
        return "unterminated CSS comment"
    if quote:
        return f"unterminated CSS string starting with `{quote}`"
    if stack:
        opener, opener_index = stack[-1]
        line, col = css_line_col(source, opener_index)
        return f"unclosed `{opener}` opened at line {line}, column {col}"
    return ""


JAVASCRIPT_SYNTAX_EXTENSIONS = (".js", ".mjs", ".cjs")


def javascript_syntax_error_detail(output):
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    for line in lines:
        if "SyntaxError" in line:
            return line[:240]
    return (lines[0] if lines else "node --check failed without diagnostic output")[:240]


def validate_javascript_file_syntax(path, relative_path):
    node = shutil.which("node")
    if not node:
        return "Node.js `node` is not available, so JavaScript syntax could not be checked"
    try:
        # `node --check` parses the file without executing model-authored code.
        proc = subprocess.run(
            [node, "--check", path],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "node --check timed out after 10s"
    except (OSError, subprocess.SubprocessError) as error:
        return f"node --check could not inspect the file ({error})"
    if proc.returncode != 0:
        detail = javascript_syntax_error_detail((proc.stderr or "") + "\n" + (proc.stdout or ""))
        return f"syntax check failed: {detail}"
    return ""


SQL_SYNTAX_EXTENSIONS = (".sql",)


def sql_dollar_quote_delimiter_at(source, index):
    match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", source[index:])
    return match.group(0) if match else ""


def sql_tokens_contain_statement(tokens):
    text = " ".join(tokens)
    if not text:
        return False
    statement_patterns = (
        r"\bselect\b.+\bfrom\b",
        r"\binsert\b.+\binto\b",
        r"\bupdate\b.+\bset\b",
        r"\bdelete\b.+\bfrom\b",
        r"\bcreate\b.+\b(?:table|view|index|schema|database|trigger|procedure|function)\b",
        r"\balter\b.+\b(?:table|view|index|schema|database)\b",
        r"\bdrop\b.+\b(?:table|view|index|schema|database|trigger|procedure|function)\b",
        r"\bmerge\b.+\binto\b",
        r"\btruncate\b.+\b(?:table\b)?",
        r"\bgrant\b.+\b(?:on|to)\b",
        r"\brevoke\b.+\b(?:on|from)\b",
        r"\bcopy\b.+\b(?:from|to)\b",
        r"\bpragma\b",
        r"\b(?:begin|commit|rollback)\b.+\b(?:transaction|work)\b",
        r"\b(?:explain|analyze|vacuum|attach|detach|call|declare|replace)\b",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in statement_patterns)


def validate_sql_source(source, relative_path):
    source = str(source or "")
    if not source.strip():
        return "SQL file is empty"

    stack = []
    quote = ""
    quote_start = 0
    in_block_comment = False
    block_comment_start = 0
    tokens = []
    current_token = []
    index = 0

    def flush_token():
        if current_token:
            tokens.append("".join(current_token).lower())
            current_token.clear()

    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                if next_char == quote:
                    index += 2
                    continue
                quote = ""
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        delimiter = sql_dollar_quote_delimiter_at(source, index) if char == "$" else ""
        if delimiter:
            end_index = source.find(delimiter, index + len(delimiter))
            if end_index < 0:
                line, col = css_line_col(source, index)
                return f"unterminated SQL dollar-quoted string starting at line {line}, column {col}"
            flush_token()
            index = end_index + len(delimiter)
            continue

        if char == "-" and next_char == "-":
            flush_token()
            newline_index = source.find("\n", index + 2)
            if newline_index < 0:
                break
            index = newline_index + 1
            continue
        if char == "#":
            flush_token()
            newline_index = source.find("\n", index + 1)
            if newline_index < 0:
                break
            index = newline_index + 1
            continue
        if char == "/" and next_char == "*":
            flush_token()
            in_block_comment = True
            block_comment_start = index
            index += 2
            continue

        if char in {"'", '"', "`"}:
            flush_token()
            quote = char
            quote_start = index
            index += 1
            continue

        if char == "(":
            flush_token()
            stack.append(index)
            index += 1
            continue
        if char == ")":
            flush_token()
            if not stack:
                line, col = css_line_col(source, index)
                return f"unexpected `)` at line {line}, column {col}"
            stack.pop()
            index += 1
            continue

        if char.isalnum() or char == "_":
            current_token.append(char)
        else:
            flush_token()
        index += 1

    flush_token()
    if in_block_comment:
        line, col = css_line_col(source, block_comment_start)
        return f"unterminated SQL block comment starting at line {line}, column {col}"
    if quote:
        line, col = css_line_col(source, quote_start)
        return f"unterminated SQL string or quoted identifier starting with `{quote}` at line {line}, column {col}"
    if stack:
        line, col = css_line_col(source, stack[-1])
        return f"unclosed `(` opened at line {line}, column {col}"
    if not sql_tokens_contain_statement(tokens):
        return "SQL file does not contain a recognizable SQL statement"
    return ""


def validate_code_file_integrity(workspace_dir, files, project_context):
    failures = []
    deliverable = project_context.get("deliverable") if isinstance(project_context, dict) and isinstance(project_context.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()

    if fmt == "python":
        for item in code_deliverable_files(files, project_context, ".py"):
            relative_path = item.get("path", "")
            safe_path = safe_workspace_relative_path(relative_path)
            if not safe_path:
                continue
            path = os.path.join(workspace_dir, safe_path)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
                ast.parse(source, filename=safe_path)
            except SyntaxError as error:
                failures.append(
                    f"invalid Python deliverable `{safe_path}`: syntax error on line {error.lineno} "
                    f"({error.msg})"
                )
            except OSError as error:
                failures.append(f"invalid Python deliverable `{safe_path}`: could not read file ({error})")

    if fmt in {"html", "css"}:
        for item in code_deliverable_files_for_extensions(files, project_context, (".html", ".htm")):
            relative_path = item.get("path", "")
            safe_path = safe_workspace_relative_path(relative_path)
            if not safe_path:
                continue
            path = os.path.join(workspace_dir, safe_path)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    failure = validate_html_source(f.read(), safe_path)
                if failure:
                    failures.append(f"invalid HTML deliverable `{safe_path}`: {failure}")
            except OSError as error:
                failures.append(f"invalid HTML deliverable `{safe_path}`: could not read file ({error})")

        for item in code_deliverable_files_for_extensions(files, project_context, (".css",)):
            relative_path = item.get("path", "")
            safe_path = safe_workspace_relative_path(relative_path)
            if not safe_path:
                continue
            path = os.path.join(workspace_dir, safe_path)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    failure = validate_css_source(f.read(), safe_path)
                if failure:
                    failures.append(f"invalid CSS deliverable `{safe_path}`: {failure}")
            except OSError as error:
                failures.append(f"invalid CSS deliverable `{safe_path}`: could not read file ({error})")

    if fmt == "javascript" or (fmt == "html" and html_javascript_support_bundle_requested(project_context)):
        for item in code_deliverable_files_for_extensions(files, project_context, JAVASCRIPT_SYNTAX_EXTENSIONS):
            relative_path = item.get("path", "")
            safe_path = safe_workspace_relative_path(relative_path)
            if not safe_path:
                continue
            path = os.path.join(workspace_dir, safe_path)
            if not os.path.isfile(path):
                continue
            failure = validate_javascript_file_syntax(path, safe_path)
            if failure:
                failures.append(f"invalid JavaScript deliverable `{safe_path}`: {failure}")

    if fmt == "sql":
        for item in code_deliverable_files_for_extensions(files, project_context, SQL_SYNTAX_EXTENSIONS):
            relative_path = item.get("path", "")
            safe_path = safe_workspace_relative_path(relative_path)
            if not safe_path:
                continue
            path = os.path.join(workspace_dir, safe_path)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    failure = validate_sql_source(f.read(), safe_path)
                if failure:
                    failures.append(f"invalid SQL deliverable `{safe_path}`: {failure}")
            except OSError as error:
                failures.append(f"invalid SQL deliverable `{safe_path}`: could not read file ({error})")
    return failures


def first_nonempty_line(text, limit=220):
    for line in str(text or "").splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:limit]
    return ""


def validate_workspace_command_runs(metadata, capabilities_required):
    failures = []
    commands = listify(metadata.get("commands")) if isinstance(metadata, dict) else []
    command_runs = metadata.get("commandRuns") if isinstance(metadata, dict) else None
    needs_shell = "shell_exec" in set(capabilities_required or [])

    if needs_shell and not commands:
        failures.append("shell_exec was required, but execution metadata listed no workspace commands")
        return failures
    if commands and not isinstance(command_runs, list):
        failures.append("workspace command(s) were requested, but no commandRuns evidence was recorded")
        return failures
    if not isinstance(command_runs, list):
        return failures

    for item in command_runs:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "(unknown command)")
        if item.get("skipped"):
            reason = first_nonempty_line(item.get("reason") or item.get("stderr"))
            suffix = f": {reason}" if reason else ""
            failures.append(f"workspace command skipped: `{command}`{suffix}")
            continue
        if not item.get("ok"):
            detail = first_nonempty_line(item.get("stderr")) or first_nonempty_line(item.get("stdout"))
            rc = item.get("returncode")
            rc_text = f" rc={rc}" if rc is not None else ""
            suffix = f": {detail}" if detail else ""
            failures.append(f"workspace command failed{rc_text}: `{command}`{suffix}")
    return failures


def validate_pdf_file(path, relative_path):
    try:
        with open(path, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return f"invalid PDF deliverable `{relative_path}`: missing %PDF header"
            try:
                f.seek(max(os.path.getsize(path) - 2048, 0))
            except OSError:
                f.seek(0)
            tail = f.read()
            if b"%%EOF" not in tail:
                return f"invalid PDF deliverable `{relative_path}`: missing %%EOF marker"
    except OSError as error:
        return f"invalid PDF deliverable `{relative_path}`: could not read file ({error})"

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        pdfinfo = shutil.which("pdfinfo")
        if pdfinfo:
            try:
                proc = subprocess.run(
                    [pdfinfo, path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as error:
                return f"invalid PDF deliverable `{relative_path}`: pdfinfo could not inspect file ({error})"
            if proc.returncode != 0:
                detail = first_nonempty_line(proc.stderr) or first_nonempty_line(proc.stdout)
                suffix = f": {detail}" if detail else ""
                return f"invalid PDF deliverable `{relative_path}`: pdfinfo rejected file{suffix}"
            return ""

        try:
            with open(path, "rb") as f:
                data = f.read(2_000_000)
                f.seek(max(os.path.getsize(path) - 4096, 0))
                tail = f.read()
        except OSError as error:
            return f"invalid PDF deliverable `{relative_path}`: could not inspect structure ({error})"
        has_classic_xref = b"xref" in data and b"trailer" in data and b"startxref" in tail
        has_xref_stream = b"/Type /XRef" in data and b"startxref" in tail
        if not (has_classic_xref or has_xref_stream):
            return f"invalid PDF deliverable `{relative_path}`: missing xref/trailer structure"
        return ""

    try:
        reader = PdfReader(path, strict=True)
        if len(reader.pages) < 1:
            return f"invalid PDF deliverable `{relative_path}`: no pages found"
    except Exception as error:
        return f"invalid PDF deliverable `{relative_path}`: pypdf rejected file ({type(error).__name__}: {error})"
    return ""


def extract_pdf_validation_text(path, relative_path):
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        pass
    else:
        try:
            reader = PdfReader(path, strict=False)
            chunks = []
            for page in reader.pages[:20]:
                chunks.append(page.extract_text() or "")
            text = "\n".join(chunk for chunk in chunks if chunk)
            if text.strip():
                return text
        except Exception:
            pass

    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return ""
    try:
        proc = subprocess.run(
            [pdftotext, path, "-"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def validate_deliverable_file_integrity(workspace_dir, files, project_context):
    failures = []
    deliverable = project_context.get("deliverable") if isinstance(project_context, dict) and isinstance(project_context.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    for item in files:
        relative_path = item.get("path", "") if isinstance(item, dict) else ""
        safe_path = safe_workspace_relative_path(relative_path)
        if not safe_path:
            continue
        ext = os.path.splitext(safe_path)[1].lower()
        if ext != ".pdf" and fmt != "pdf":
            continue
        if fmt and not file_matches_deliverable(safe_path, deliverable):
            continue
        path = os.path.join(workspace_dir, safe_path)
        if not os.path.isfile(path):
            continue
        if ext == ".pdf":
            failure = validate_pdf_file(path, safe_path)
            if failure:
                failures.append(failure)
    return failures


def validation_text_extensions(project_context):
    if not isinstance(project_context, dict):
        return None
    deliverable = project_context.get("deliverable") if isinstance(project_context.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    if fmt == "html":
        # UI/component counts should measure rendered document structure.
        # CSS selector names and comments are support code, not extra cards.
        return {".html", ".htm", ".md", ".markdown", ".txt", ".pdf"}
    return None


def read_validation_text_files(workspace_dir, files, project_context=None):
    allowed_extensions = validation_text_extensions(project_context)
    chunks = []
    for item in files:
        relative_path = item.get("path", "") if isinstance(item, dict) else ""
        safe_path = safe_workspace_relative_path(relative_path)
        if not safe_path:
            continue
        ext = os.path.splitext(safe_path)[1].lower()
        if allowed_extensions is not None and ext not in allowed_extensions:
            continue
        if ext not in TEXT_CONTENT_EXTENSIONS and ext != ".pdf":
            continue
        path = os.path.join(workspace_dir, safe_path)
        if not os.path.isfile(path):
            continue
        if ext == ".pdf":
            text = extract_pdf_validation_text(path, safe_path)
            if text.strip():
                chunks.append(f"\n<!-- {safe_path} -->\n" + text)
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                chunks.append(f"\n<!-- {safe_path} -->\n" + f.read())
        except OSError:
            continue
    return "\n".join(chunks)


def regex_count(pattern, text):
    return len(re.findall(pattern, text or "", re.IGNORECASE | re.MULTILINE | re.DOTALL))


def content_requirement_text(requirement):
    if not isinstance(requirement, dict):
        return ""
    return " ".join(
        str(requirement.get(key, "") or "")
        for key in ("item", "scope", "source")
    ).lower()


SQL_CONTENT_STATEMENT_PATTERNS = {
    "insert": r"\binsert\s+into\b",
    "select": r"\bselect\b(?:(?!;).)*\bfrom\b",
    "update": r"\bupdate\b(?:(?!;).)*\bset\b",
    "delete": r"\bdelete\b(?:(?!;).)*\bfrom\b",
    "create": r"\bcreate\s+(?:table|view|index|schema|database|trigger|procedure|function)\b",
    "alter": r"\balter\s+(?:table|view|index|schema|database)\b",
    "drop": r"\bdrop\s+(?:table|view|index|schema|database|trigger|procedure|function)\b",
}


def sql_content_statement_kind(requirement, raw_item=""):
    text = f"{raw_item} {content_requirement_text(requirement)}".lower()
    if not re.search(r"\b(?:statements?|queries?|query)\b", text):
        return ""
    for keyword in SQL_CONTENT_STATEMENT_PATTERNS:
        if re.search(rf"\b{keyword}\b", text):
            return keyword
    return ""


def sql_source_without_comments_and_literals(source):
    source = str(source or "")
    output = []
    quote = ""
    in_block_comment = False
    index = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                if next_char == quote:
                    index += 2
                    continue
                quote = ""
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        delimiter = sql_dollar_quote_delimiter_at(source, index) if char == "$" else ""
        if delimiter:
            end_index = source.find(delimiter, index + len(delimiter))
            if end_index < 0:
                break
            output.append(" ")
            index = end_index + len(delimiter)
            continue

        if char == "-" and next_char == "-":
            newline_index = source.find("\n", index + 2)
            if newline_index < 0:
                break
            output.append("\n")
            index = newline_index + 1
            continue
        if char == "#":
            newline_index = source.find("\n", index + 1)
            if newline_index < 0:
                break
            output.append("\n")
            index = newline_index + 1
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            output.append(" ")
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            output.append(" ")
            index += 1
            continue

        output.append(char)
        index += 1
    return "".join(output)


def count_sql_statement_occurrences(source, statement_kind):
    pattern = SQL_CONTENT_STATEMENT_PATTERNS.get(statement_kind)
    if not pattern:
        return 0
    return regex_count(pattern, sql_source_without_comments_and_literals(source))


def content_requirement_uses_exact_count(requirement):
    text = content_requirement_text(requirement)
    if re.search(r"\b(?:at\s+least|minimum|min\.?|no\s+fewer\s+than|or\s+more)\b", text):
        return False
    return bool(sql_content_statement_kind(requirement))


def content_requirement_is_script_runtime_side_effect(requirement, project_context):
    if not isinstance(project_context, dict):
        return False
    deliverable = project_context.get("deliverable") if isinstance(project_context.get("deliverable"), dict) else {}
    fmt = str(deliverable.get("format", "")).strip().lower()
    if fmt not in SCRIPT_RUNTIME_FORMATS:
        return False
    if requirement.get("validation_mode") == "script_runtime":
        return True

    text = content_requirement_text(requirement)
    if not text:
        return False
    has_side_effect_term = any(term in text for term in SCRIPT_RUNTIME_SIDE_EFFECT_TERMS)
    has_creation_verb = any(re.search(rf"\b{re.escape(verb)}\b", text) for verb in SCRIPT_RUNTIME_SIDE_EFFECT_VERBS)
    return has_side_effect_term and has_creation_verb


def script_runtime_requirement_key(requirement):
    text = content_requirement_text(requirement)
    item_text = str(requirement.get("item", "") or "").lower()
    expected = parse_positive_int(requirement.get("minimum_total")) or parse_positive_int(requirement.get("count"))
    if "director" in item_text or "folder" in item_text or re.search(r"\bdirs?\b", item_text):
        return ("directory", expected)
    extension_match = re.search(r"\.([a-z0-9]{1,12})\b", item_text) or re.search(r"\.([a-z0-9]{1,12})\b", text)
    if extension_match:
        return ("extension", extension_match.group(1).lower(), expected)
    if "director" in text or "folder" in text or re.search(r"\bdirs?\b", text):
        return ("directory", expected)
    if "file" in text:
        return ("file", expected)
    return ("other", normalize_quantity_item(requirement.get("item", "items")), expected)


def count_runtime_filesystem_units(root_dir, requirement, ignored_files=None):
    text = content_requirement_text(requirement)
    if not text:
        return 0
    ignored_files = set(ignored_files or [])

    directory_names = set(re.findall(r"\bdir\d+\b", text))
    for start, end in re.findall(r"\bdir(\d+)\s*(?:through|thru|to|-)\s*dir(\d+)\b", text):
        start_num = int(start)
        end_num = int(end)
        if 0 < start_num <= end_num <= 100:
            directory_names.update(f"dir{index}" for index in range(start_num, end_num + 1))
    directory_names = sorted(directory_names)
    if directory_names:
        found = set()
        for current_root, dirs, _files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".gforge-installs"}]
            for dirname in dirs:
                if dirname.lower() in directory_names:
                    found.add(dirname.lower())
        return len(found)

    extension_match = re.search(r"\.([a-z0-9]{1,12})\b", text)
    if extension_match:
        wanted_ext = "." + extension_match.group(1).lower()
        total = 0
        for current_root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".gforge-installs"}]
            for name in files:
                rel = os.path.relpath(os.path.join(current_root, name), root_dir).replace(os.sep, "/")
                if rel in ignored_files or name in ignored_files:
                    continue
                if name.lower().endswith(wanted_ext):
                    total += 1
        return total

    if "director" in text or "folder" in text:
        total = 0
        for current_root, dirs, _files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".gforge-installs"}]
            total += len(dirs)
        return total

    if "file" in text:
        total = 0
        for current_root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".gforge-installs"}]
            for name in files:
                rel = os.path.relpath(os.path.join(current_root, name), root_dir).replace(os.sep, "/")
                if rel in ignored_files or name in ignored_files:
                    continue
                total += 1
        return total

    return 0


def count_html_list_items(text, unordered_only=False):
    tag = "ul" if unordered_only else r"(?:ul|ol)"
    blocks = re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", text or "", re.IGNORECASE | re.DOTALL)
    if blocks:
        return sum(regex_count(r"<li\b", block) for block in blocks)
    return regex_count(r"<li\b", text)


def content_requirement_requests_list_count(requirement, normalized_item):
    text = content_requirement_text(requirement)
    if not text:
        return False
    if normalized_item not in {"check", "item", "entry", "example", "row"}:
        return False
    return bool(re.search(r"\b(?:unordered|ordered|bullet|numbered)?\s*list\b|\b<ul\b|\b<li\b", text))


def validate_python_script_runtime_side_effects(workspace_dir, files, project_context, requirements):
    candidates = code_deliverable_files(files, project_context, ".py")
    if not candidates:
        return {
            "ok": False,
            "mode": "script_runtime",
            "failure": "script runtime validation could not find a Python deliverable to run",
        }

    safe_path = safe_workspace_relative_path(candidates[0].get("path", ""))
    if not safe_path:
        return {
            "ok": False,
            "mode": "script_runtime",
            "failure": f"script runtime validation found an unsafe Python path: {candidates[0].get('path', '')}",
        }

    source_path = os.path.join(workspace_dir, safe_path)
    if not os.path.isfile(source_path):
        return {
            "ok": False,
            "mode": "script_runtime",
            "failure": f"script runtime validation could not find Python file `{safe_path}`",
        }

    if not tool_workspace.can_run_workspace_commands():
        return {
            "ok": False,
            "mode": "script_runtime",
            "failure": "script runtime validation could not run because workspace exec is unavailable",
        }

    with tempfile.TemporaryDirectory(prefix="gforge-script-validate-") as tmpdir:
        validation_script = os.path.basename(safe_path)
        shutil.copy2(source_path, os.path.join(tmpdir, validation_script))
        command = f"python {validation_script}"
        runs = tool_workspace.run_workspace_commands(tmpdir, [command], limit=1, timeout=30)
        run = runs[0] if runs else {}
        if not run or run.get("skipped") or not run.get("ok"):
            detail = first_nonempty_line(run.get("reason") or run.get("stderr") or run.get("stdout"))
            suffix = f": {detail}" if detail else ""
            return {
                "ok": False,
                "mode": "script_runtime",
                "root": tmpdir,
                "failure": f"script runtime validation failed for `{safe_path}`{suffix}",
                "commandRun": run,
            }

        results = []
        failures = []
        for requirement in requirements:
            expected = parse_positive_int(requirement.get("minimum_total")) or parse_positive_int(requirement.get("count"))
            if not expected or expected <= 1:
                continue
            actual = count_runtime_filesystem_units(tmpdir, requirement, ignored_files={validation_script})
            result = {
                "item": requirement.get("item", "items"),
                "expected": expected,
                "actual": actual,
                "scope": requirement.get("scope", "whole deliverable"),
                "source": requirement.get("source", ""),
                "mode": "script_runtime",
            }
            results.append(result)
            if actual < expected:
                failures.append(
                    f"script runtime validation expected at least {expected} `{requirement.get('item', 'items')}` "
                    f"after running `{safe_path}` ({requirement.get('scope', 'whole deliverable')}), "
                    f"but the isolated test run produced {actual}. Source: {requirement.get('source', '')}"
                )
        return {
            "ok": True,
            "mode": "script_runtime",
            "results": results,
            "failures": failures,
            "commandRun": run,
        }


def count_content_units(text, item, requirement=None):
    raw_item = str(item or "").lower()
    normalized_item = normalize_quantity_item(item)
    if not text:
        return 0

    statement_kind = sql_content_statement_kind(requirement, raw_item=raw_item)
    if statement_kind:
        return count_sql_statement_occurrences(text, statement_kind)

    if requirement and content_requirement_requests_list_count(requirement, normalized_item):
        unordered_only = "unordered" in content_requirement_text(requirement) or "<ul" in content_requirement_text(requirement)
        return count_html_list_items(text, unordered_only=unordered_only)

    if "status" in raw_item and normalized_item == "card":
        return regex_count(
            r"<(?:div|section|li|article)\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*\bstatus-card\b)[^>]*>",
            text,
        )

    if normalized_item in {"article", "headline", "story", "topic"}:
        candidates = [
            regex_count(r"<article\b", text),
            regex_count(r"<(?:div|section|li)\b[^>]*(?:article|story|headline|news-card|news-item|article-card|story-card|topic-card)[^>]*>", text),
            regex_count(r"\b(?:article|headline|story)\s*(?:#|no\.?|number)?\s*\d+\b", text),
            regex_count(r"\b(?:title|headline)\s*[:=]\s*['\"]", text),
        ]
        return max(candidates)

    if normalized_item in {"option", "variant", "concept"}:
        labels = set(re.findall(r"\b(?:option|variant|concept)\s*(?:#|no\.?|number)?\s*(\d+)\b", text, re.IGNORECASE))
        candidates = [
            len(labels),
            regex_count(r"<(?:div|section|li)\b[^>]*(?:option|variant|concept|design-option)[^>]*>", text),
        ]
        return max(candidates)

    if normalized_item in {"card", "feature", "product", "item", "entry", "example"}:
        keyword = re.escape(normalized_item)
        candidates = [
            regex_count(rf"<(?:div|section|li|article)\b[^>]*(?:{keyword}|card|item|entry)[^>]*>", text),
            regex_count(rf"\b{keyword}\s*(?:#|no\.?|number)?\s*\d+\b", text),
        ]
        return max(candidates)

    if normalized_item in {"image", "screenshot"}:
        return max(
            regex_count(r"<img\b", text),
            regex_count(r"\b(?:image|screenshot)\s*(?:#|no\.?|number)?\s*\d+\b", text),
            regex_count(r"background(?:-image)?\s*:\s*url\(", text),
        )

    if normalized_item in {"logo", "icon"}:
        return max(
            regex_count(r"<svg\b", text),
            regex_count(r"<img\b", text),
            regex_count(rf"\b{re.escape(normalized_item)}\s*(?:#|no\.?|number)?\s*\d+\b", text),
        )

    if normalized_item == "category":
        return max(
            regex_count(r"<section\b", text),
            regex_count(r"\bcategory\s+report\s*[:\-]", text),
            regex_count(r"\breport\s+category\s*[:\-]", text),
            regex_count(rf"\b{re.escape(normalized_item)}\s*(?:#|no\.?|number)?\s*\d+\b", text),
        )

    if normalized_item == "section":
        return max(
            regex_count(r"<section\b", text),
            regex_count(rf"\b{re.escape(normalized_item)}\s*(?:#|no\.?|number)?\s*\d+\b", text),
        )

    return max(
        regex_count(rf"\b{re.escape(normalized_item)}s?\s*(?:#|no\.?|number)?\s*\d+\b", text),
        regex_count(rf"\b{re.escape(normalized_item)}s?\b", text),
    )


def validate_content_quantity_requirements(workspace_dir, files, project_context):
    context_requirements = project_context.get("content_requirements") if isinstance(project_context, dict) else []
    if isinstance(project_context, dict):
        context_requirements = merge_content_quantity_requirements(
            context_requirements,
            script_runtime_quantity_requirements_from_context(project_context),
        )
    requirements = merge_content_quantity_requirements(
        context_requirements,
        [],
    )
    if not requirements:
        return [], []

    combined_text = read_validation_text_files(workspace_dir, files, project_context)
    results = []
    failures = []
    script_runtime_requirements = []
    seen_script_runtime = set()
    for requirement in requirements:
        if not content_requirement_is_script_runtime_side_effect(requirement, project_context):
            continue
        key = script_runtime_requirement_key(requirement)
        if key in seen_script_runtime:
            continue
        seen_script_runtime.add(key)
        script_runtime_requirements.append(requirement)
    if script_runtime_requirements:
        runtime_result = validate_python_script_runtime_side_effects(
            workspace_dir,
            files,
            project_context,
            script_runtime_requirements,
        )
        if not runtime_result.get("ok"):
            failures.append(runtime_result.get("failure") or "script runtime validation failed")
            for requirement in script_runtime_requirements:
                expected = parse_positive_int(requirement.get("minimum_total")) or parse_positive_int(requirement.get("count"))
                if not expected or expected <= 1:
                    continue
                results.append({
                    "item": requirement.get("item", "items"),
                    "expected": expected,
                    "actual": 0,
                    "scope": requirement.get("scope", "whole deliverable"),
                    "source": requirement.get("source", ""),
                    "mode": runtime_result.get("mode", "script_runtime"),
                })
        else:
            results.extend(runtime_result.get("results") or [])
            failures.extend(runtime_result.get("failures") or [])

    script_runtime_ids = {
        id(requirement) for requirement in requirements
        if content_requirement_is_script_runtime_side_effect(requirement, project_context)
    }
    for requirement in requirements:
        if id(requirement) in script_runtime_ids:
            continue
        expected = parse_positive_int(requirement.get("minimum_total")) or parse_positive_int(requirement.get("count"))
        if not expected or expected <= 1:
            continue
        actual = count_content_units(combined_text, requirement.get("item", "items"), requirement=requirement)
        result = {
            "item": requirement.get("item", "items"),
            "expected": expected,
            "actual": actual,
            "scope": requirement.get("scope", "whole deliverable"),
            "source": requirement.get("source", ""),
        }
        exact_count = content_requirement_uses_exact_count(requirement)
        if exact_count:
            result["operator"] = "exact"
        results.append(result)
        if exact_count and actual != expected:
            failures.append(
                f"content requirement expected exactly {expected} `{requirement.get('item', 'items')}` "
                f"inside the deliverable ({requirement.get('scope', 'whole deliverable')}), "
                f"but deterministic validation found {actual}. Source: {requirement.get('source', '')}"
            )
        elif actual < expected:
            failures.append(
                f"content requirement expected at least {expected} `{requirement.get('item', 'items')}` "
                f"inside the deliverable ({requirement.get('scope', 'whole deliverable')}), "
                f"but deterministic validation found {actual}. Source: {requirement.get('source', '')}"
            )
    return failures, results


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
    capabilities_required = session_capabilities_required(session)
    claim_text = collect_claim_text(metadata)
    claim_failures = validate_claims_against_disk(claim_text, capabilities_required, workspace_dir=workspace_dir)
    failures.extend(claim_failures)

    command_failures = validate_workspace_command_runs(metadata, capabilities_required)
    failures.extend(command_failures)

    file_count_failures = validate_deliverable_file_count(files, project_context)
    failures.extend(file_count_failures)

    file_integrity_failures = validate_deliverable_file_integrity(workspace_dir, files, project_context)
    failures.extend(file_integrity_failures)

    code_integrity_failures = validate_code_file_integrity(workspace_dir, files, project_context)
    failures.extend(code_integrity_failures)

    # Catch hallucinated local-relative href/src/url() targets in any
    # HTML / CSS / Markdown deliverable. Small models often fabricate
    # links to "results/option_A.html", "assets/main.css", etc., even
    # when only the index file was actually emitted.
    link_failures = validate_local_link_targets(workspace_dir, files)
    failures.extend(link_failures)

    negated_support_failures = validate_negated_support_file_constraints(workspace_dir, files, project_context)
    failures.extend(negated_support_failures)

    content_failures, content_results = validate_content_quantity_requirements(workspace_dir, files, project_context)
    failures.extend(content_failures)

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
        "contentRequirements": content_results,
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

    git_references = execution.get("gitReferences") or metadata.get("gitReferences") or {}
    git_lines = []
    if isinstance(git_references, dict) and (git_references.get("requested") or git_references.get("cloned")):
        git_lines = ["", "## Git Repository References", ""]
        artifact = git_references.get("artifact") or "n/a"
        git_lines.append(f"- Manifest: `{artifact}`")
        git_lines.append(f"- GitHub CLI authenticated: `{git_references.get('ghAuthenticated')}`")
        for item in git_references.get("cloned", []):
            if not isinstance(item, dict):
                continue
            marker = "ok" if item.get("ok") else "FAIL"
            git_lines.append(f"- [{marker}] `{item.get('path')}` from {item.get('url')} via {item.get('auth')}")

    command_runs = execution.get("commandRuns") or metadata.get("commandRuns") or []
    command_lines = []
    if command_runs:
        command_lines = ["", "## Workspace Command Runs", ""]
        for item in command_runs:
            if not isinstance(item, dict):
                continue
            marker = "ok" if item.get("ok") else ("skipped" if item.get("skipped") else "FAIL")
            command = item.get("command") or "(no command)"
            rc = item.get("returncode", "n/a")
            ms = item.get("elapsedMs", 0)
            command_lines.append(f"- [{marker}] `{command}` rc=`{rc}` ({ms} ms)")
            if item.get("reason"):
                command_lines.append(f"  Reason: {item.get('reason')}")
            if item.get("stdout"):
                command_lines.append(f"  stdout: `{truncate_text(item.get('stdout'), 240)}`")
            if item.get("stderr"):
                command_lines.append(f"  stderr: `{truncate_text(item.get('stderr'), 240)}`")

    content_requirement_lines = []
    for item in validation.get("contentRequirements", []) if isinstance(validation, dict) else []:
        if not isinstance(item, dict):
            continue
        content_requirement_lines.append(
            f"- `{item.get('item', 'items')}`: expected `{item.get('expected')}`, "
            f"found `{item.get('actual')}` ({item.get('scope', 'whole deliverable')})"
        )

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
        *git_lines,
        *command_lines,
        "",
        "## Content Quantity Checks",
        "",
        "\n".join(content_requirement_lines) or "- None.",
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

    # On-disk collision checks. These catch the case where the model
    # references a name that already exists as the WRONG type (a file when
    # a directory is needed, or a directory when a file is needed), e.g.
    # an earlier card created `output/` as a dir and now a new emission
    # wants to write `output` as a file. Raise a descriptive error so the
    # caller logs it as a rejection instead of leaving a stale traceback
    # in the harness log.
    if os.path.isdir(path):
        raise ValueError(
            f"path collision: `{relative_path}` already exists on disk as a "
            f"directory, cannot overwrite it with a file."
        )
    parent = os.path.dirname(path)
    if parent:
        cur = root
        for segment in os.path.relpath(parent, root).split(os.sep):
            cur = os.path.join(cur, segment)
            if os.path.isfile(cur):
                rel_to_workspace = os.path.relpath(cur, root)
                raise ValueError(
                    f"path collision: parent of `{relative_path}` requires "
                    f"`{rel_to_workspace}` to be a directory, but it already "
                    f"exists on disk as a file."
                )

    os.makedirs(os.path.dirname(path), exist_ok=True) if parent else None
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


def registry_model_record(model_name):
    selected = normalize_model_name(model_name)
    if not selected:
        return None
    registry = load_models()
    for model in registry.get("models", []):
        if model_name_matches(model, selected):
            return model
    return None


def selected_model_readiness(model_name):
    model = normalize_model_name(model_name or DEFAULT_MODEL)
    record = registry_model_record(model)
    if record and record.get("status") != "installed":
        return {
            "ready": False,
            "model": model,
            "source": record.get("source"),
            "status": record.get("status") or "not-installed",
            "reason": "registered-not-installed",
        }
    return {"ready": True, "model": model}


def model_not_ready_response(readiness):
    model = readiness.get("model") or "this model"
    source = readiness.get("source")
    source_text = f" from {source}" if source else ""
    status = readiness.get("status", "not-installed")
    if status == "provisioning":
        detail = "is still provisioning and is not runnable in Ollama yet."
    elif status == "failed":
        detail = "failed provisioning and is not runnable in Ollama yet."
    elif status == "downloaded":
        detail = "was downloaded only and has not been imported into Ollama yet."
    else:
        detail = "is not installed in Ollama yet."
    return jsonify({
        "error": (
            f"{model} is registered{source_text}, but it {detail} "
            "Gemma Forge can only start projects with models that Ollama can run. "
            "Provision/import the model in Settings, then use an installed Forge Brain."
        ),
        "model": model,
        "status": status,
    }), 409


def clamp_int(value, minimum, maximum, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_hf_model_query(value):
    query = re.sub(r"\s+", " ", str(value or "").strip())
    for prefix in ("https://huggingface.co/", "http://huggingface.co/", "https://hf.co/", "http://hf.co/", "hf.co/"):
        if query.startswith(prefix):
            query = query[len(prefix):].strip("/")
            break
    if query.startswith("models/"):
        query = query[len("models/"):]
    return query[:HF_MODEL_SEARCH_MAX_QUERY_CHARS].strip()


def suggested_ollama_model_name(repo_id):
    model_part = str(repo_id or "").strip().split("/")[-1]
    model_part = re.sub(r"(?i)(?:[-_.]?gguf)$", "", model_part)
    model_part = re.sub(r"[^A-Za-z0-9_.:-]+", "-", model_part).strip("-._:")
    return model_part.lower() or DEFAULT_MODEL


def model_info_value(model, key, default=None):
    if isinstance(model, dict):
        return model.get(key, default)
    return getattr(model, key, default)


def model_card_license(model):
    card_data = model_info_value(model, "card_data") or model_info_value(model, "cardData")
    if isinstance(card_data, dict):
        return card_data.get("license") or "Not specified"
    if card_data is not None and getattr(card_data, "license", None):
        return card_data.license
    return "Not specified"


def model_available_formats(model):
    tags = model_info_value(model, "tags", []) or []
    siblings = model_info_value(model, "siblings", []) or []
    haystack = " ".join(str(tag).lower() for tag in tags)
    for sibling in siblings:
        filename = getattr(sibling, "rfilename", None)
        if filename:
            haystack += f" {filename.lower()}"

    formats = []
    for label, tokens in (
        ("gguf", ("gguf",)),
        ("safetensors", ("safetensors",)),
        ("pytorch", ("pytorch_model", ".bin")),
    ):
        if any(token in haystack for token in tokens):
            formats.append(label)
    return formats


def hf_model_choice_payload(model, installed_models=None):
    model_id = model_info_value(model, "modelId") or model_info_value(model, "id") or ""
    provider, _, short_name = model_id.partition("/")
    suggested_name = suggested_ollama_model_name(model_id)
    return {
        "modelId": model_id,
        "repoId": model_id,
        "provider": provider,
        "displayName": short_name or model_id,
        "downloads": model_info_value(model, "downloads", 0) or 0,
        "likes": model_info_value(model, "likes", 0) or 0,
        "pipelineTag": model_info_value(model, "pipeline_tag"),
        "license": model_card_license(model),
        "availableFormats": model_available_formats(model),
        "suggestedOllamaName": suggested_name,
        "installed": is_ollama_model_installed(suggested_name, installed_models or []),
    }


def hf_search_results(query, offset=0, limit=HF_MODEL_SEARCH_PAGE_SIZE, api=None, installed_models=None):
    if HfApi is None and api is None:
        raise RuntimeError("huggingface_hub is not installed")

    clean_query = normalize_hf_model_query(query)
    if not clean_query:
        return {
            "query": "",
            "offset": 0,
            "limit": limit,
            "results": [],
            "hasNext": False,
            "hasPrevious": False,
        }

    client = api or HfApi()
    page_size = clamp_int(limit, 1, HF_MODEL_SEARCH_PAGE_SIZE, HF_MODEL_SEARCH_PAGE_SIZE)
    page_offset = clamp_int(offset, 0, HF_MODEL_SEARCH_MAX_OFFSET, 0)
    requested = page_offset + page_size + 1
    collected = []
    seen = set()

    exact_candidate = clean_query if "/" in clean_query and " " not in clean_query else ""
    if exact_candidate:
        try:
            exact = client.model_info(exact_candidate, timeout=5)
            exact_id = model_info_value(exact, "modelId") or model_info_value(exact, "id")
            if exact_id:
                seen.add(exact_id)
                collected.append(exact)
        except Exception:
            pass

    for model in client.list_models(search=clean_query, sort="downloads", limit=requested, cardData=True):
        model_id = model_info_value(model, "modelId") or model_info_value(model, "id")
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        collected.append(model)
        if len(collected) >= requested:
            break

    page = collected[page_offset:page_offset + page_size]
    return {
        "query": clean_query,
        "offset": page_offset,
        "limit": page_size,
        "results": [hf_model_choice_payload(model, installed_models) for model in page],
        "hasNext": len(collected) > page_offset + page_size,
        "hasPrevious": page_offset > 0,
        "nextOffset": page_offset + page_size if len(collected) > page_offset + page_size else None,
        "previousOffset": max(0, page_offset - page_size) if page_offset > 0 else None,
    }


def validate_ollama_model_name(model_name):
    if not model_name:
        return "Choose an Ollama model name before provisioning."
    if len(model_name) > 128:
        return "Ollama model names must be 128 characters or fewer."
    if model_name.startswith(("-", "/", ".")):
        return "Ollama model names cannot start with '-', '/', or '.'."
    if ".." in model_name or any(char.isspace() for char in model_name):
        return "Ollama model names cannot contain spaces or '..'."
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$", model_name):
        return "Use only letters, numbers, '.', '_', '-', ':', or '/' in the Ollama model name."
    return ""


def validate_hf_repo_id(repo_id):
    if not repo_id:
        return "Choose a Hugging Face repo before provisioning."
    if len(repo_id) > 180 or repo_id.count("/") != 1:
        return "Use a Hugging Face repo id like provider/model before provisioning."
    if repo_id.startswith(("-", ".", "/")) or repo_id.endswith(("-", ".", "/")):
        return "Use a valid Hugging Face repo id like provider/model."
    if ".." in repo_id or "--" in repo_id or any(char.isspace() for char in repo_id):
        return "Hugging Face repo ids cannot contain spaces, '..', or '--'."
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$", repo_id):
        return "Use a Hugging Face repo id like provider/model before provisioning."
    return ""


def normalize_quantization(value):
    quantization = str(value or MODEL_PROVISION_QUANTIZATION).strip().upper()
    if quantization == "FP16":
        return "FP16"
    if not re.match(r"^[A-Z0-9_]{2,24}$", quantization):
        return MODEL_PROVISION_QUANTIZATION
    return quantization


def model_provision_job_snapshot(job_id):
    with MODEL_PROVISION_LOCK:
        job = MODEL_PROVISION_JOBS.get(job_id)
        if not job:
            return None
        return json.loads(json.dumps(job))


def update_model_provision_job(job_id, **updates):
    event_payload = None
    with MODEL_PROVISION_LOCK:
        job = MODEL_PROVISION_JOBS.get(job_id)
        if not job:
            return None
        message = updates.get("message")
        step = updates.get("step")
        status = updates.get("status")
        job.update({key: value for key, value in updates.items() if value is not None})
        job["updatedAt"] = utc_now()
        if status in {"installed", "downloaded", "failed"}:
            job["finishedAt"] = job.get("finishedAt") or job["updatedAt"]
        if step or message:
            job.setdefault("steps", []).append({
                "at": job["updatedAt"],
                "status": status or job.get("status"),
                "step": step or job.get("step"),
                "message": message or job.get("message"),
            })
            job["steps"] = job["steps"][-40:]
        event_payload = json.loads(json.dumps(job))

    emit_event(
        "model-provision",
        event_payload.get("message", "Model provisioning updated."),
        jobId=event_payload.get("id"),
        model=event_payload.get("modelName"),
        repoId=event_payload.get("repoId"),
        status=event_payload.get("status"),
        step=event_payload.get("step"),
        progress=event_payload.get("progress"),
    )
    return event_payload


def update_model_registry_for_provision(job, status, **extra):
    registry = load_models()
    upsert_registry_model(registry, {
        "name": job["modelName"],
        "model": job["modelName"],
        "source": job.get("repoId") or "ollama",
        "status": status,
        "downloadOnly": job.get("downloadOnly", False),
        "createInterface": job.get("createInterface", False),
        "jobId": job.get("id"),
        "updatedAt": utc_now(),
        **extra,
    })
    save_models(registry)
    return registry


def start_model_provision_job(request_data):
    repo_id = request_data["repoId"]
    model_name = request_data["modelName"]
    with MODEL_PROVISION_LOCK:
        for job in MODEL_PROVISION_JOBS.values():
            if (
                job.get("repoId") == repo_id
                and job.get("modelName") == model_name
                and job.get("status") in {"queued", "provisioning"}
            ):
                return json.loads(json.dumps(job))

        job_id = f"model_{uuid.uuid4().hex[:12]}"
        job = {
            "id": job_id,
            "repoId": repo_id,
            "modelName": model_name,
            "status": "provisioning",
            "runnable": False,
            "step": "queued",
            "progress": 0.02,
            "message": f"Provisioning started for {model_name} from {repo_id}.",
            "createInterface": bool(request_data.get("createInterface")),
            "downloadOnly": bool(request_data.get("downloadOnly")),
            "quantization": normalize_quantization(request_data.get("quantization")),
            "startedAt": utc_now(),
            "updatedAt": utc_now(),
            "steps": [],
        }
        MODEL_PROVISION_JOBS[job_id] = job
        snapshot = json.loads(json.dumps(job))

    update_model_registry_for_provision(snapshot, "provisioning")
    update_model_provision_job(
        job_id,
        step="queued",
        progress=0.02,
        message=f"Provisioning queued: {repo_id} -> {model_name}.",
    )
    threading.Thread(target=run_model_provision_job, args=(job_id,), daemon=True).start()
    return snapshot


def run_model_provision_job(job_id):
    job = model_provision_job_snapshot(job_id)
    if not job:
        return

    try:
        repo_id = job["repoId"]
        model_name = job["modelName"]
        quantization = normalize_quantization(job.get("quantization"))
        model_dir = provision_download_dir(repo_id)
        out_gguf = provision_output_gguf_path(model_name)
        os.makedirs(MODELS_ROOT, exist_ok=True)

        update_model_provision_job(
            job_id,
            status="provisioning",
            step="inspect",
            progress=0.08,
            message=f"Inspecting {repo_id} for direct GGUF files.",
        )
        remote_gguf = preferred_remote_gguf_file(repo_id)

        update_model_provision_job(
            job_id,
            status="provisioning",
            step="download",
            progress=0.18,
            message=f"Downloading {repo_id} into {model_dir}.",
            modelDir=model_dir,
        )
        download_kwargs = {}
        if remote_gguf:
            download_kwargs["allow_patterns"] = [remote_gguf]
        download_model_repo(repo_id, model_dir, **download_kwargs)

        if job.get("downloadOnly"):
            latest = model_provision_job_snapshot(job_id) or job
            update_model_registry_for_provision(
                latest,
                "downloaded",
                localPath=model_dir,
                error=None,
            )
            update_model_provision_job(
                job_id,
                status="downloaded",
                step="downloaded",
                progress=1.0,
                modelDir=model_dir,
                runnable=False,
                message=f"Downloaded {repo_id} to {model_dir}. Download only is checked, so Ollama import was skipped.",
            )
            return

        gguf_path = find_downloaded_gguf_file(model_dir, remote_gguf)
        if gguf_path:
            update_model_provision_job(
                job_id,
                status="provisioning",
                step="gguf",
                progress=0.58,
                ggufPath=gguf_path,
                message=f"Found GGUF file {os.path.basename(gguf_path)}. Conversion and quantization are not needed.",
            )
        else:
            converter = require_llama_cpp_converter()
            update_model_provision_job(
                job_id,
                status="provisioning",
                step="convert",
                progress=0.36,
                ggufPath=out_gguf,
                message=f"Converting {repo_id} to FP16 GGUF with llama.cpp.",
            )
            out_temp = out_gguf.replace(".gguf", "-f16.gguf")
            run_provision_command(
                job_id,
                [sys.executable, converter, model_dir, "--outfile", out_temp],
                "convert",
            )

            if quantization == "FP16":
                os.replace(out_temp, out_gguf)
                update_model_provision_job(
                    job_id,
                    status="provisioning",
                    step="quantize",
                    progress=0.62,
                    message="Keeping FP16 GGUF; quantization was skipped.",
                )
            else:
                quantizer = require_llama_quantize()
                update_model_provision_job(
                    job_id,
                    status="provisioning",
                    step="quantize",
                    progress=0.56,
                    message=f"Quantizing to {quantization}.",
                )
                run_provision_command(
                    job_id,
                    [quantizer, out_temp, out_gguf, quantization],
                    "quantize",
                )
                if os.path.exists(out_temp):
                    os.remove(out_temp)
            gguf_path = out_gguf

        modelfile_path = provision_modelfile_path(model_name)
        update_model_provision_job(
            job_id,
            status="provisioning",
            step="modelfile",
            progress=0.76,
            modelfilePath=modelfile_path,
            message=f"Writing Ollama Modelfile for {model_name}.",
        )
        write_ollama_modelfile(modelfile_path, gguf_path)

        update_model_provision_job(
            job_id,
            status="provisioning",
            step="ollama-create",
            progress=0.86,
            message=f"Importing {model_name} into Ollama.",
        )
        run_provision_command(job_id, ["ollama", "create", model_name, "-f", modelfile_path], "ollama-create")

        detected = scan_workspace()
        if not is_ollama_model_installed(model_name, detected["ollama"]["models"]):
            raise RuntimeError(f"Ollama create finished, but {model_name} did not appear in Ollama's model list.")

        latest = model_provision_job_snapshot(job_id) or job
        update_model_registry_for_provision(
            latest,
            "installed",
            localPath=model_dir,
            ggufPath=gguf_path,
            modelfilePath=modelfile_path,
            quantization=quantization,
            error=None,
        )

        session_id = None
        if job.get("createInterface"):
            sessions = load_sessions()
            session_id = create_session_record(sessions, f"Model interface for {model_name}", model_name)
            save_sessions(sessions, create_keys={session_id})

        update_model_provision_job(
            job_id,
            status="installed",
            step="installed",
            progress=1.0,
            runnable=True,
            session_id=session_id,
            message=f"Ready: {model_name} is installed in Ollama and can be used as a Forge Brain.",
        )
    except Exception as error:
        latest = model_provision_job_snapshot(job_id) or job
        update_model_registry_for_provision(latest, "failed", error=str(error))
        update_model_provision_job(
            job_id,
            status="failed",
            step="failed",
            progress=1.0,
            runnable=False,
            error=str(error),
            message=f"Provisioning failed for {latest.get('modelName')}: {error}",
        )
        log_error(
            "model-provision",
            "Model provisioning failed.",
            error,
            {"jobId": job_id, "repoId": latest.get("repoId"), "model": latest.get("modelName")},
        )


def provision_download_dir(repo_id):
    return os.path.join(MODELS_ROOT, safe_id(repo_id.replace("/", "_")))


def provision_output_gguf_path(model_name):
    return os.path.join(MODELS_ROOT, f"{safe_id(model_name)}.gguf")


def provision_modelfile_path(model_name):
    return os.path.join(MODELS_ROOT, f"Modelfile_{safe_id(model_name)}")


def read_hf_token():
    try:
        if HF_TOKEN_PATH and os.path.exists(HF_TOKEN_PATH):
            with open(HF_TOKEN_PATH, "r") as token_file:
                return token_file.read().strip() or None
    except OSError:
        return None
    return None


def download_model_repo(repo_id, model_dir, **kwargs):
    if snapshot_download is None:
        raise RuntimeError("huggingface_hub is not installed.")
    os.makedirs(model_dir, exist_ok=True)
    token = read_hf_token()
    download_args = {
        "repo_id": repo_id,
        "local_dir": model_dir,
        "max_workers": 8,
    }
    if token:
        download_args["token"] = token
    download_args.update(kwargs)
    return snapshot_download(**download_args)


def preferred_remote_gguf_file(repo_id):
    if HfApi is None:
        return None
    token = read_hf_token()
    try:
        api = HfApi()
        kwargs = {"token": token} if token else {}
        files = api.list_repo_files(repo_id, **kwargs)
    except Exception:
        return None
    return choose_preferred_gguf(files)


def choose_preferred_gguf(paths):
    ggufs = [path for path in paths if str(path).lower().endswith(".gguf")]
    if not ggufs:
        return None

    def score(path):
        name = os.path.basename(str(path)).lower()
        preferences = ("q4_k_m", "q4-k-m", "q4_k_s", "q5_k_m", "q5-k-m", "q8_0", "f16", "fp16")
        for index, token in enumerate(preferences):
            if token in name:
                return (index, len(name), name)
        return (len(preferences), len(name), name)

    return sorted(ggufs, key=score)[0]


def find_downloaded_gguf_file(model_dir, preferred_remote=None):
    if preferred_remote:
        preferred_path = os.path.join(model_dir, preferred_remote)
        if os.path.exists(preferred_path):
            return preferred_path

    candidates = []
    for root, _dirs, files in os.walk(model_dir):
        for filename in files:
            if filename.lower().endswith(".gguf"):
                candidates.append(os.path.join(root, filename))
    return choose_preferred_gguf(candidates)


def require_llama_cpp_converter():
    candidates = [
        os.path.join(LLAMA_CPP_ROOT, "convert_hf_to_gguf.py"),
        os.path.join(GFORGE_HOME, "tools", "llama.cpp", "convert_hf_to_gguf.py"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"llama.cpp converter was not found. Expected convert_hf_to_gguf.py under {LLAMA_CPP_ROOT}.")


def require_llama_quantize():
    candidates = [
        os.path.join(LLAMA_CPP_BIN, "llama-quantize"),
        os.path.join(LLAMA_CPP_ROOT, "build", "bin", "llama-quantize"),
        shutil.which("llama-quantize"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"llama.cpp quantizer was not found. Expected llama-quantize under {LLAMA_CPP_BIN}.")


def run_provision_command(job_id, command, step):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=MODEL_PROVISION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Required command was not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{step} timed out after {MODEL_PROVISION_TIMEOUT_SECONDS} seconds.") from error

    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if output:
        update_model_provision_job(
            job_id,
            step=step,
            commandOutput=output[-4000:],
            message=f"{step} output received.",
        )
    if result.returncode != 0:
        snippet = output[-1200:] if output else "No command output."
        raise RuntimeError(f"{step} failed with exit code {result.returncode}: {snippet}")
    return output


def escape_modelfile_string(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_ollama_modelfile(modelfile_path, gguf_path):
    os.makedirs(os.path.dirname(modelfile_path), exist_ok=True)
    content = "\n".join([
        f"FROM {os.path.abspath(gguf_path)}",
        "PARAMETER temperature 1.0",
        "PARAMETER top_p 0.95",
        "PARAMETER top_k 64",
        f"SYSTEM \"{escape_modelfile_string(MODEL_PROVISION_SYSTEM_PROMPT)}\"",
        f"TEMPLATE \"\"\"{MODEL_PROVISION_TEMPLATE}\"\"\"",
    ])
    with open(modelfile_path, "w") as modelfile:
        modelfile.write(content)
        modelfile.write("\n")


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
