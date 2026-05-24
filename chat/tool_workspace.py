"""
Gemma Forge workspace tool helpers.

The harness, not the local model, performs these actions. GitHub clones are
materialized inside the project workspace so later prompts can reference real
files. Shell commands and package installs are run only through a workspace
sandbox; deploy, publish, push, sudo, and system package managers stay blocked.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlparse


REPO_URL_PATTERN = re.compile(
    r"(?:https?://(?:github|gitlab|bitbucket)\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:\.git)?(?:/[^\s,)>'\"]*)?|git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)",
    re.IGNORECASE,
)

COMMAND_META_PATTERN = re.compile(r"[\n\r;&|<>`$]")
ALLOWED_COMMANDS = {
    "bash",
    "git",
    "make",
    "node",
    "npm",
    "pip",
    "pip3",
    "pnpm",
    "pytest",
    "python",
    "python3",
    "sh",
    "yarn",
}
OLLAMA_COMMANDS = {
    "cp",
    "create",
    "list",
    "pull",
    "ps",
    "rm",
    "show",
    "stop",
}
OLLAMA_NETWORK_COMMANDS = {"cp", "create", "list", "pull", "ps", "rm", "show", "stop"}
BLOCKED_SUBCOMMANDS = {
    ("git", "push"),
    ("git", "credential"),
    ("git", "config", "--global"),
    ("npm", "publish"),
    ("pnpm", "publish"),
    ("yarn", "publish"),
}
DEFAULT_WORKSPACE_COMMAND_TIMEOUT = 60
LONG_WORKSPACE_COMMAND_TIMEOUT = 300
SCRIPT_COMMANDS = {"bash", "node", "python", "python3", "sh"}
SCRIPT_EXTENSIONS = (".bash", ".cjs", ".js", ".mjs", ".py", ".sh", ".ts")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str, length: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:length]


def _redact(text: str, limit: int = 4000) -> str:
    if not text:
        return ""
    text = re.sub(r"https://[^/@\s:]+:[^/@\s]+@", "https://***:***@", text)
    text = re.sub(r"(gh[opsu]_[A-Za-z0-9_]+)", "gh_************************************", text)
    return text.strip()[:limit]


def _safe_child(root: str, *parts: str) -> str:
    root_path = os.path.abspath(root)
    child = os.path.abspath(os.path.join(root_path, *parts))
    if os.path.commonpath([root_path, child]) != root_path:
        raise ValueError("workspace path escaped the workspace root")
    return child


def is_git_available() -> bool:
    return shutil.which("git") is not None


def is_gh_available() -> bool:
    return shutil.which("gh") is not None


def is_gh_authenticated() -> bool:
    gh = shutil.which("gh")
    if not gh:
        return False
    try:
        result = subprocess.run(
            [gh, "auth", "status", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def is_sandbox_available() -> bool:
    return shutil.which("sandbox-exec") is not None


def can_clone_repositories() -> bool:
    return is_git_available()


def can_run_workspace_commands() -> bool:
    return is_sandbox_available()


def can_install_packages() -> bool:
    if not is_sandbox_available():
        return False
    return any(shutil.which(command) for command in ("npm", "pnpm", "yarn", "pip", "pip3", "python3", "python"))


def normalize_repo_url(raw_url: str) -> dict | None:
    raw = str(raw_url or "").strip().rstrip(".,;:)>]'\"")
    if not raw:
        return None
    if raw.lower().startswith("git@github.com:"):
        repo = raw.split(":", 1)[1]
        repo = repo[:-4] if repo.endswith(".git") else repo
        parts = repo.split("/")
        if len(parts) >= 2:
            owner_repo = "/".join(parts[:2])
            return {
                "host": "github.com",
                "owner_repo": owner_repo,
                "clone_url": f"https://github.com/{owner_repo}.git",
                "display_url": f"https://github.com/{owner_repo}",
            }
        return None
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if host not in {"github.com", "gitlab.com", "bitbucket.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    owner_repo = f"{owner}/{repo}"
    return {
        "host": host,
        "owner_repo": owner_repo,
        "clone_url": f"https://{host}/{owner_repo}.git",
        "display_url": f"https://{host}/{owner_repo}",
    }


def extract_repo_urls(text: str, limit: int = 4) -> list[dict]:
    seen = set()
    repos = []
    for match in REPO_URL_PATTERN.findall(str(text or "")):
        repo = normalize_repo_url(match)
        if not repo:
            continue
        key = (repo["host"], repo["owner_repo"].lower())
        if key in seen:
            continue
        seen.add(key)
        repos.append(repo)
        if len(repos) >= limit:
            break
    return repos


def repo_slug(repo: dict) -> str:
    owner_repo = str(repo.get("owner_repo", "repo")).replace("/", "-")
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", owner_repo).strip("-").lower()
    return f"{base}-{_sha(repo.get('display_url') or repo.get('clone_url') or base)}"


def clone_repositories_into_workspace(workspace_dir: str, text: str, limit: int = 4) -> dict:
    repos = extract_repo_urls(text, limit=limit)
    result = {
        "requested": bool(repos),
        "available": can_clone_repositories(),
        "ghAuthenticated": is_gh_authenticated(),
        "cloned": [],
        "artifact": None,
    }
    if not repos:
        return result
    if not can_clone_repositories():
        result["error"] = "git is not installed"
        return result

    repos_root = _safe_child(workspace_dir, "references", "repos")
    os.makedirs(repos_root, exist_ok=True)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    gh = shutil.which("gh")
    git = shutil.which("git") or "git"
    gh_ok = bool(gh and result["ghAuthenticated"])

    for repo in repos:
        destination = _safe_child(repos_root, repo_slug(repo))
        if os.path.isdir(destination):
            result["cloned"].append({
                "ok": True,
                "skipped": True,
                "url": repo["display_url"],
                "path": os.path.relpath(destination, workspace_dir).replace(os.sep, "/"),
                "auth": "existing checkout",
                "stdout": "",
                "stderr": "",
            })
            continue

        if gh_ok and repo["host"] == "github.com":
            command = [gh, "repo", "clone", repo["owner_repo"], destination, "--", "--depth=1"]
            auth = "gh authenticated"
        else:
            command = [git, "clone", "--depth=1", repo["clone_url"], destination]
            auth = "git https"

        started = time.time()
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=1200,
                check=False,
                env=env,
            )
            ok = proc.returncode == 0
            if not ok and os.path.isdir(destination):
                shutil.rmtree(destination, ignore_errors=True)
            result["cloned"].append({
                "ok": ok,
                "skipped": False,
                "url": repo["display_url"],
                "path": os.path.relpath(destination, workspace_dir).replace(os.sep, "/"),
                "auth": auth,
                "returncode": proc.returncode,
                "elapsedMs": int((time.time() - started) * 1000),
                "stdout": _redact(proc.stdout),
                "stderr": _redact(proc.stderr),
            })
        except (FileNotFoundError, subprocess.SubprocessError) as error:
            if os.path.isdir(destination):
                shutil.rmtree(destination, ignore_errors=True)
            result["cloned"].append({
                "ok": False,
                "skipped": False,
                "url": repo["display_url"],
                "path": os.path.relpath(destination, workspace_dir).replace(os.sep, "/"),
                "auth": auth,
                "returncode": 1,
                "elapsedMs": int((time.time() - started) * 1000),
                "stdout": "",
                "stderr": _redact(f"{type(error).__name__}: {error}"),
            })

    result["artifact"] = write_git_artifact(workspace_dir, result)
    return result


def write_git_artifact(workspace_dir: str, result: dict) -> str:
    lines = [
        "# GitHub / Git Repository References",
        "",
        f"- Created at: `{_utc_now()}`",
        f"- Git available: `{result.get('available')}`",
        f"- GitHub CLI authenticated: `{result.get('ghAuthenticated')}`",
        "",
    ]
    for item in result.get("cloned", []):
        status = "ok" if item.get("ok") else "failed"
        if item.get("skipped"):
            status = "existing"
        lines.extend([
            f"## {item.get('url')}",
            "",
            f"- Status: `{status}`",
            f"- Auth mode: `{item.get('auth')}`",
            f"- Workspace path: `{item.get('path')}`",
            f"- Return code: `{item.get('returncode', 'n/a')}`",
            "",
        ])
        if item.get("stdout"):
            lines.extend(["### stdout", "", "```", item["stdout"], "```", ""])
        if item.get("stderr"):
            lines.extend(["### stderr", "", "```", item["stderr"], "```", ""])
    path = _safe_child(workspace_dir, "references", "github-repos.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return os.path.relpath(path, workspace_dir).replace(os.sep, "/")


def _profile_string(workspace_dir: str, tmp_dir: str, allow_network: bool = False) -> str:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    network_rule = "\n(allow network-outbound)" if allow_network else ""
    home = os.path.expanduser("~")
    denied_read_roots = [
        "/Volumes",
        os.path.join(home, ".aws"),
        os.path.join(home, ".azure"),
        os.path.join(home, ".config", "gh"),
        os.path.join(home, ".docker"),
        os.path.join(home, ".gnupg"),
        os.path.join(home, ".gforge"),
        os.path.join(home, ".kube"),
        os.path.join(home, ".ollama"),
        os.path.join(home, ".ssh"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Library"),
    ]
    deny_rules = "\n".join(
        f'  (subpath "{esc(path)}")'
        for path in denied_read_roots
        if os.path.exists(path) and not os.path.commonpath([os.path.abspath(path), os.path.abspath(sys.prefix)]) == os.path.abspath(path)
    )
    system_read_roots = [
        "/System",
        "/Library",
        "/usr",
        "/bin",
        "/sbin",
        "/etc",
        "/dev",
        "/opt/homebrew",
        "/opt/local",
        "/private/var",
        "/var",
    ]
    python_read_roots = [
        os.path.realpath(getattr(sys, "base_prefix", sys.prefix)),
        os.path.realpath(getattr(sys, "exec_prefix", sys.prefix)),
        os.path.realpath(sys.prefix),
        os.path.realpath(os.path.dirname(sys.executable)),
        os.path.realpath(sys.executable),
    ]
    read_roots = system_read_roots + python_read_roots + [
        workspace_dir,
        tmp_dir,
        os.path.realpath(workspace_dir),
        os.path.realpath(tmp_dir),
    ]
    python_read_rules = "\n".join(
        f'  (subpath "{esc(path)}")'
        for path in sorted(set(read_roots))
        if path and os.path.exists(path)
    )
    return f"""(version 1)
(deny default)
(allow process*)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup)
{network_rule}
(allow file-read*)
(allow file-map-executable)
(deny file-read*
{deny_rules})
(allow file-read*
{python_read_rules})
(allow file-write*
  (subpath "{esc(workspace_dir)}")
  (subpath "{esc(tmp_dir)}"))
(deny file-write*
  (subpath "{esc(os.path.join(workspace_dir, '.gforge'))}"))
"""


def _blocked_subcommand(args: list[str]) -> str:
    lowered = [os.path.basename(arg).lower() for arg in args[:3]]
    for blocked in BLOCKED_SUBCOMMANDS:
        if tuple(lowered[:len(blocked)]) == blocked:
            return " ".join(blocked)
    return ""


def is_package_install_command(args: list[str]) -> bool:
    if not args:
        return False
    executable = os.path.basename(args[0]).lower()
    if executable in {"npm", "pnpm"}:
        return len(args) > 1 and args[1].lower() in {"install", "i", "add"}
    if executable == "yarn":
        return len(args) == 1 or (len(args) > 1 and args[1].lower() in {"install", "add"})
    if executable in {"pip", "pip3"}:
        return len(args) > 1 and args[1].lower() == "install"
    if executable in {"python", "python3"}:
        lowered = [arg.lower() for arg in args]
        return len(args) > 3 and lowered[1:4] == ["-m", "pip", "install"]
    return False


def package_install_targeted_args(args: list[str]) -> list[str]:
    if not is_package_install_command(args):
        return args
    executable = os.path.basename(args[0]).lower()
    if executable in {"pip", "pip3"}:
        tail = args[2:]
        if any(arg in {"--target", "-t", "--user", "--prefix"} or arg.startswith("--target=") or arg.startswith("--prefix=") for arg in tail):
            return args
        return [args[0], args[1], "--target", ".gforge-installs/python", *tail]
    if executable in {"python", "python3"}:
        tail = args[4:]
        if any(arg in {"--target", "-t", "--user", "--prefix"} or arg.startswith("--target=") or arg.startswith("--prefix=") for arg in tail):
            return args
        return [*args[:4], "--target", ".gforge-installs/python", *tail]
    return args


def command_runs_script_file(args: list[str]) -> bool:
    if not args:
        return False
    executable = os.path.basename(args[0]).lower()
    if executable not in SCRIPT_COMMANDS:
        return False
    return any(str(arg).lower().endswith(SCRIPT_EXTENSIONS) for arg in args[1:])


def workspace_command_timeout(args: list[str], default: int = DEFAULT_WORKSPACE_COMMAND_TIMEOUT) -> int:
    if is_package_install_command(args) or command_runs_script_file(args):
        return max(default, LONG_WORKSPACE_COMMAND_TIMEOUT)
    return default


def _maintenance_flag(maintenance_targets, key: str) -> bool:
    if not isinstance(maintenance_targets, dict):
        return False
    return bool(maintenance_targets.get(key))


def validate_ollama_command(args: list[str], maintenance_targets=None) -> str:
    if not _maintenance_flag(maintenance_targets, "allowOllama"):
        return "`ollama` commands are only allowed for explicit Gemma Forge model maintenance"
    if len(args) < 2:
        return "`ollama` requires a subcommand"
    subcommand = args[1].lower()
    if subcommand not in OLLAMA_COMMANDS:
        return f"`ollama {subcommand}` is not allowed in workspace exec"
    if subcommand == "rm" and not _maintenance_flag(maintenance_targets, "allowDestructive"):
        return "`ollama rm` is destructive and requires an explicit remove/delete request"
    if subcommand in {"pull", "cp", "create", "rm", "stop"} and len(args) < 3:
        return f"`ollama {subcommand}` requires a model argument"
    return ""


def is_ollama_command(args: list[str]) -> bool:
    return bool(args) and os.path.basename(args[0]).lower() == "ollama"


def is_ollama_network_command(args: list[str]) -> bool:
    return is_ollama_command(args) and len(args) > 1 and args[1].lower() in OLLAMA_NETWORK_COMMANDS


def normalize_workspace_command(command, maintenance_targets=None) -> tuple[list[str] | None, str]:
    if isinstance(command, list):
        args = [str(item).strip() for item in command if str(item).strip()]
    else:
        raw = str(command or "").strip()
        if not raw:
            return None, "command was empty"
        if COMMAND_META_PATTERN.search(raw):
            return None, "shell metacharacters, pipes, redirection, or multiline commands are not allowed"
        try:
            args = shlex.split(raw)
        except ValueError as error:
            return None, f"could not parse command: {error}"
    if not args:
        return None, "command was empty"

    executable = os.path.basename(args[0]).lower()
    if executable == "pip" and not shutil.which(args[0]) and shutil.which("pip3"):
        args[0] = "pip3"
        executable = "pip3"
    allowed_commands = set(ALLOWED_COMMANDS)
    if _maintenance_flag(maintenance_targets, "allowOllama"):
        allowed_commands.add("ollama")
    if executable not in allowed_commands:
        return None, f"`{executable}` is not in the workspace command allowlist"

    if executable == "ollama":
        reason = validate_ollama_command(args, maintenance_targets)
        if reason:
            return None, reason

    if executable in {"bash", "sh"} and any(arg in {"-c", "-lc"} for arg in args[1:]):
        return None, "inline shell execution is blocked; run a relative script file instead"
    if executable in {"python", "python3"} and any(arg == "-c" for arg in args[1:]):
        return None, "inline Python execution is blocked; run a relative script file instead"
    if executable == "node" and any(arg in {"-e", "--eval", "-p", "--print"} for arg in args[1:]):
        return None, "inline Node execution is blocked; run a relative script file instead"

    blocked = _blocked_subcommand(args)
    if blocked:
        return None, f"`{blocked}` is intentionally blocked in workspace exec"

    args = package_install_targeted_args(args)

    for arg in args[1:]:
        if arg == ".." or arg.startswith("../") or "/../" in arg:
            return None, "parent directory traversal is not allowed"
        if os.path.isabs(arg):
            return None, "absolute path arguments are not allowed"
    return args, ""


def run_workspace_commands(workspace_dir: str, commands, limit: int = 6, timeout: int = DEFAULT_WORKSPACE_COMMAND_TIMEOUT, maintenance_targets=None) -> list[dict]:
    if not commands:
        return []
    items = commands if isinstance(commands, list) else [commands]
    results = []
    sandbox = shutil.which("sandbox-exec")
    if not sandbox:
        return [{
            "ok": False,
            "command": str(command),
            "skipped": True,
            "reason": "sandbox-exec is not available; workspace exec is disabled",
        } for command in items[:limit]]

    workspace_abs = os.path.realpath(os.path.abspath(workspace_dir))
    for command in items[:limit]:
        args, reason = normalize_workspace_command(command, maintenance_targets=maintenance_targets)
        display = command if isinstance(command, str) else " ".join(str(item) for item in command)
        if not args:
            results.append({
                "ok": False,
                "command": str(display),
                "skipped": True,
                "reason": reason,
            })
            continue

        command_timeout = workspace_command_timeout(args, timeout)
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="gforge-workspace-exec-") as tmp:
            install_root = os.path.join(workspace_abs, ".gforge-installs")
            workspace_tmp = os.path.join(install_root, "tmp")
            os.makedirs(workspace_tmp, exist_ok=True)
            profile_path = os.path.join(tmp, "sandbox.sb")
            with open(profile_path, "w") as f:
                f.write(_profile_string(
                    workspace_abs,
                    workspace_tmp,
                    allow_network=is_package_install_command(args) or is_ollama_network_command(args),
                ))
            python_bin_dir = os.path.dirname(sys.executable)
            install_python = os.path.join(install_root, "python")
            env = {
                "HOME": workspace_abs,
                "TMPDIR": workspace_tmp,
                "PATH": f"{python_bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
                "PIP_CACHE_DIR": os.path.join(install_root, "pip-cache"),
                "PYTHONUSERBASE": os.path.join(install_root, "python-user"),
                "PYTHONPATH": install_python,
                "NPM_CONFIG_CACHE": os.path.join(install_root, "npm-cache"),
                "PNPM_HOME": os.path.join(install_root, "pnpm-home"),
                "YARN_CACHE_FOLDER": os.path.join(install_root, "yarn-cache"),
                "NO_COLOR": "1",
                "CI": "1",
            }
            try:
                proc = subprocess.run(
                    [sandbox, "-f", profile_path, *args],
                    cwd=workspace_abs,
                    capture_output=True,
                    text=True,
                    timeout=command_timeout,
                    check=False,
                    env=env,
                )
                results.append({
                    "ok": proc.returncode == 0,
                    "command": " ".join(shlex.quote(arg) for arg in args),
                    "skipped": False,
                    "returncode": proc.returncode,
                    "elapsedMs": int((time.time() - started) * 1000),
                    "stdout": _redact(proc.stdout),
                    "stderr": _redact(proc.stderr),
                })
            except subprocess.TimeoutExpired as error:
                results.append({
                    "ok": False,
                    "command": " ".join(shlex.quote(arg) for arg in args),
                    "skipped": False,
                    "returncode": 124,
                    "elapsedMs": int((time.time() - started) * 1000),
                    "stdout": _redact(error.stdout or ""),
                    "stderr": _redact(error.stderr or f"command timed out after {command_timeout}s"),
                })
            except (FileNotFoundError, subprocess.SubprocessError) as error:
                results.append({
                    "ok": False,
                    "command": " ".join(shlex.quote(arg) for arg in args),
                    "skipped": False,
                    "returncode": 1,
                    "elapsedMs": int((time.time() - started) * 1000),
                    "stdout": "",
                    "stderr": _redact(f"{type(error).__name__}: {error}"),
                })
    return results
