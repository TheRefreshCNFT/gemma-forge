import json
import os
import re
import select
import shlex
import shutil
import subprocess
import time
import hashlib
import fcntl
from contextlib import contextmanager


HOME = os.path.expanduser("~")
GFORGE_HOME = os.environ.get("GFORGE_HOME", os.path.join(HOME, ".gforge"))
GFORGE_TOOLS_ROOT = os.environ.get("GFORGE_TOOLS_ROOT", os.path.join(GFORGE_HOME, "tools"))
GFORGE_NODE_BIN = os.path.join(GFORGE_TOOLS_ROOT, "node_modules", ".bin")
SOCRATICODE_LOCAL_BIN = os.path.join(GFORGE_NODE_BIN, "socraticode")
AXON_FALLBACK_BIN = os.path.join(HOME, ".local", "bin", "axon")
TOOL_LOCK_ROOT = os.path.join(GFORGE_HOME, "harness", "tool-locks")
SOCRATICODE_PACKAGE = os.environ.get("GFORGE_SOCRATICODE_PACKAGE", "socraticode@latest")
SOCRATICODE_QDRANT_CONTAINER = os.environ.get("GFORGE_SOCRATICODE_QDRANT", "socraticode-qdrant")
DOCKER_APP_BIN = "/Applications/Docker.app/Contents/Resources/bin/docker"
MCP_PROTOCOL_VERSION = "2024-11-05"


class ToolRuntimeError(RuntimeError):
    pass


def run_command(command, timeout=1200, cwd=None, env=None):
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        return {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": str(error),
        }


def auto_install_tools_enabled():
    value = os.environ.get("GFORGE_AUTO_INSTALL_TOOLS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def npm_available():
    return shutil.which("npm")


def npx_available():
    return shutil.which("npx")


def docker_command():
    return shutil.which("docker") or (DOCKER_APP_BIN if os.access(DOCKER_APP_BIN, os.X_OK) else None)


def node_version_status():
    node_path = shutil.which("node")
    if not node_path:
        return {
            "ready": False,
            "path": None,
            "version": None,
            "reason": "Node.js was not found. SocratiCode requires Node.js 18 through 25.",
        }

    result = run_command([node_path, "--version"], timeout=5)
    version = result.get("stdout", "").strip()
    match = re.search(r"v?(\d+)", version)
    major = int(match.group(1)) if match else None
    if major is None:
        return {
            "ready": False,
            "path": node_path,
            "version": version,
            "reason": "Could not parse Node.js version.",
        }
    if major < 18 or major >= 26:
        return {
            "ready": False,
            "path": node_path,
            "version": version,
            "reason": "SocratiCode supports Node.js 18 through 25.",
        }
    return {
        "ready": True,
        "path": node_path,
        "version": version,
        "reason": "Node.js version is supported.",
    }


def install_socraticode_runtime():
    npm_path = npm_available()
    if not npm_path:
        return {
            "installed": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "npm was not found. Install Node.js/npm to install SocratiCode.",
        }

    os.makedirs(GFORGE_TOOLS_ROOT, exist_ok=True)
    return run_command(
        [npm_path, "install", "--prefix", GFORGE_TOOLS_ROOT, SOCRATICODE_PACKAGE],
        timeout=1200,
    )


def resolve_socraticode_command(auto_install=None):
    if auto_install is None:
        auto_install = auto_install_tools_enabled()

    env_command = os.environ.get("GFORGE_SOCRATICODE_COMMAND", "").strip()
    if env_command:
        return {
            "command": shlex.split(env_command),
            "mode": "env",
            "installed": True,
            "path": shlex.split(env_command)[0],
            "install": None,
        }

    if os.path.exists(SOCRATICODE_LOCAL_BIN):
        return {
            "command": [SOCRATICODE_LOCAL_BIN],
            "mode": "gforge-local",
            "installed": True,
            "path": SOCRATICODE_LOCAL_BIN,
            "install": None,
        }

    path_command = shutil.which("socraticode")
    if path_command:
        return {
            "command": [path_command],
            "mode": "path",
            "installed": True,
            "path": path_command,
            "install": None,
        }

    install = None
    if auto_install:
        install = install_socraticode_runtime()
        if os.path.exists(SOCRATICODE_LOCAL_BIN):
            return {
                "command": [SOCRATICODE_LOCAL_BIN],
                "mode": "gforge-local",
                "installed": True,
                "path": SOCRATICODE_LOCAL_BIN,
                "install": install,
            }

    npx_path = npx_available()
    if npx_path:
        return {
            "command": [npx_path, "-y", "socraticode"],
            "mode": "npx",
            "installed": False,
            "path": npx_path,
            "install": install,
        }

    return {
        "command": None,
        "mode": "unavailable",
        "installed": False,
        "path": None,
        "install": install,
    }


def docker_status():
    docker_path = docker_command()
    if not docker_path:
        return {
            "ready": False,
            "path": None,
            "serverVersion": None,
            "qdrantRunning": False,
            "qdrantStatus": "Docker was not found.",
        }

    info = run_command([docker_path, "info", "--format", "{{json .ServerVersion}}"], timeout=10)
    ready = info.get("returncode") == 0
    container = qdrant_container_status(docker_path) if ready else {
        "running": False,
        "status": "Docker is not running.",
    }
    return {
        "ready": ready,
        "path": docker_path,
        "serverVersion": info.get("stdout", "").strip('"') if ready else None,
        "qdrantRunning": bool(container.get("running")),
        "qdrantStatus": container.get("status", ""),
        "qdrantImage": container.get("image", ""),
        "error": info.get("stderr", "") if not ready else "",
    }


def qdrant_container_status(docker_path=None):
    command = docker_path or docker_command()
    if not command:
        return {"running": False, "status": "Docker was not found.", "image": ""}
    result = run_command(
        [
            command,
            "ps",
            "-a",
            "--filter",
            f"name={SOCRATICODE_QDRANT_CONTAINER}",
            "--format",
            "{{.Names}}\t{{.Image}}\t{{.Status}}",
        ],
        timeout=10,
    )
    if result.get("returncode") != 0:
        return {"running": False, "status": result.get("stderr", "Docker query failed."), "image": ""}
    lines = [line for line in result.get("stdout", "").splitlines() if line.strip()]
    for line in lines:
        parts = line.split("\t")
        if parts and parts[0] == SOCRATICODE_QDRANT_CONTAINER:
            status = parts[2] if len(parts) > 2 else ""
            image = parts[1] if len(parts) > 1 else ""
            return {
                "running": status.lower().startswith("up"),
                "status": status,
                "image": image,
            }
    return {"running": False, "status": "Qdrant container has not been created yet.", "image": ""}


def socraticode_runtime_status(auto_install=None):
    node = node_version_status()
    docker = docker_status()
    resolved = resolve_socraticode_command(auto_install=auto_install)
    install = resolved.get("install")
    install_ok = install is None or install.get("returncode") == 0
    ready = bool(resolved.get("command")) and bool(node.get("ready")) and bool(docker.get("ready")) and install_ok
    reason = "SocratiCode runtime is ready."
    if not resolved.get("command"):
        reason = "SocratiCode command could not be resolved."
    elif not node.get("ready"):
        reason = node.get("reason", "Node.js is not ready.")
    elif not docker.get("ready"):
        reason = docker.get("error") or "Docker is not ready."
    elif not install_ok:
        reason = install.get("stderr") or "SocratiCode install failed."
    return {
        "ready": ready,
        "installed": bool(resolved.get("installed")),
        "executable": bool(resolved.get("command")),
        "mode": resolved.get("mode"),
        "path": resolved.get("path"),
        "command": resolved.get("command"),
        "node": node,
        "docker": docker,
        "install": install,
        "reason": reason,
    }


class SocratiCodeMcpClient:
    def __init__(self, command, timeout=1200):
        self.command = command
        self.timeout = timeout
        self.process = None
        self.next_id = 1
        self.stderr_lines = []

    def __enter__(self):
        env = os.environ.copy()
        env.setdefault(
            "SOCRATICODE_LOG_FILE",
            os.path.join(GFORGE_HOME, "harness", "logs", "socraticode.log"),
        )
        os.makedirs(os.path.dirname(env["SOCRATICODE_LOG_FILE"]), exist_ok=True)
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._initialize()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if not self.process:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream and not stream.closed:
                stream.close()
        self.process = None

    def _send(self, message):
        if not self.process or not self.process.stdin:
            raise ToolRuntimeError("SocratiCode MCP process is not running.")
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _read_response(self, message_id, timeout=None):
        if not self.process or not self.process.stdout or not self.process.stderr:
            raise ToolRuntimeError("SocratiCode MCP process is not running.")

        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise ToolRuntimeError(
                    "SocratiCode MCP process exited before responding. "
                    f"stderr: {stderr or 'no stderr'}"
                )

            readable, _, _ = select.select([self.process.stdout, self.process.stderr], [], [], 0.2)
            for stream in readable:
                line = stream.readline()
                if not line:
                    continue
                if stream is self.process.stderr:
                    self.stderr_lines.append(line.strip())
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("id") == message_id:
                    if payload.get("error"):
                        raise ToolRuntimeError(json.dumps(payload["error"]))
                    return payload

        raise ToolRuntimeError(f"SocratiCode MCP call timed out waiting for id {message_id}.")

    def _request(self, method, params=None, timeout=None):
        message_id = self.next_id
        self.next_id += 1
        self._send({
            "jsonrpc": "2.0",
            "id": message_id,
            "method": method,
            "params": params or {},
        })
        return self._read_response(message_id, timeout=timeout)

    def _notify(self, method, params=None):
        self._send({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        })

    def _initialize(self):
        self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "gemma-forge", "version": "0.1.0"},
            },
            timeout=1200,
        )
        self._notify("notifications/initialized", {})

    def call_tool(self, name, arguments=None, timeout=None):
        response = self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        )
        result = response.get("result", {})
        text = "\n".join(
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )
        return {
            "tool": name,
            "arguments": arguments or {},
            "text": text.strip(),
            "raw": result,
            "stderr": "\n".join(self.stderr_lines[-20:]),
        }


def call_socraticode_tool(name, arguments=None, timeout=1200, auto_install=None):
    status = socraticode_runtime_status(auto_install=auto_install)
    if not status.get("ready"):
        raise ToolRuntimeError(status.get("reason", "SocratiCode runtime is not ready."))
    with SocratiCodeMcpClient(status["command"], timeout=timeout) as client:
        return client.call_tool(name, arguments or {}, timeout=timeout)


def socraticode_mcp_probe(project_path, timeout=1200):
    try:
        result = call_socraticode_tool(
            "codebase_status",
            {"projectPath": project_path},
            timeout=timeout,
            auto_install=True,
        )
        return {
            "ready": True,
            "returncode": 0,
            "stdout": result.get("text", ""),
            "stderr": result.get("stderr", ""),
        }
    except ToolRuntimeError as error:
        return {
            "ready": False,
            "returncode": 1,
            "stdout": "",
            "stderr": str(error),
        }


def status_text_is_complete(text):
    lower = (text or "").lower()
    return "status: green" in lower and "indexed chunks:" in lower


def parse_indexed_chunks(text):
    match = re.search(r"Indexed chunks:\s*(\d+)", text or "", re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def run_socraticode_project_scan(project_path, query, extra_extensions=".html,.css", timeout=1200):
    status = socraticode_runtime_status(auto_install=True)
    if not status.get("ready"):
        return {
            "status": "unavailable",
            "requiresAttention": True,
            "reason": status.get("reason", "SocratiCode runtime is not ready."),
            "runtime": status,
            "commands": {},
        }

    commands = {}
    try:
        with SocratiCodeMcpClient(status["command"], timeout=timeout) as client:
            commands["index"] = client.call_tool(
                "codebase_index",
                {"projectPath": project_path, "extraExtensions": extra_extensions},
                timeout=timeout,
            )
            started = time.time()
            current_status = None
            while time.time() - started < timeout:
                current_status = client.call_tool(
                    "codebase_status",
                    {"projectPath": project_path},
                    timeout=1200,
                )
                commands["status"] = current_status
                if status_text_is_complete(current_status.get("text", "")):
                    break
                time.sleep(1)

            if not current_status or not status_text_is_complete(current_status.get("text", "")):
                return {
                    "status": "degraded",
                    "requiresAttention": True,
                    "reason": "SocratiCode indexing did not report a complete green index before timeout.",
                    "runtime": status,
                    "commands": commands,
                }

            commands["search"] = client.call_tool(
                "codebase_search",
                {"projectPath": project_path, "query": query, "limit": 8, "minScore": 0},
                timeout=1200,
            )
            commands["graphStatus"] = client.call_tool(
                "codebase_graph_status",
                {"projectPath": project_path},
                timeout=1200,
            )
    except ToolRuntimeError as error:
        return {
            "status": "degraded",
            "requiresAttention": True,
            "reason": str(error),
            "runtime": status,
            "commands": commands,
        }

    search_text = commands.get("search", {}).get("text", "")
    chunks = parse_indexed_chunks(commands.get("status", {}).get("text", ""))
    return {
        "status": "complete" if search_text else "degraded",
        "requiresAttention": not bool(search_text),
        "reason": "SocratiCode indexed and searched the project." if search_text else "SocratiCode search returned no text results.",
        "runtime": status,
        "indexedChunks": chunks,
        "commands": commands,
    }


def axon_command():
    return shutil.which("axon") or (AXON_FALLBACK_BIN if os.path.exists(AXON_FALLBACK_BIN) else None)


def axon_runtime_status():
    command = axon_command()
    if not command:
        return {
            "ready": False,
            "executable": False,
            "path": None,
            "version": None,
            "reason": "Axon CLI was not found.",
        }
    version = run_command([command, "--version"], timeout=10)
    ready = version.get("returncode") == 0
    return {
        "ready": ready,
        "executable": True,
        "path": command,
        "version": version.get("stdout", "") or version.get("stderr", ""),
        "reason": "Axon CLI is ready." if ready else version.get("stderr", "Axon version check failed."),
    }


def axon_project_probe(project_path):
    status = axon_runtime_status()
    if not status.get("ready"):
        return {
            "ready": False,
            "returncode": 1,
            "stdout": "",
            "stderr": status.get("reason", "Axon CLI is not ready."),
        }
    result = run_command([status["path"], "status"], timeout=1200, cwd=project_path)
    return {
        "ready": result.get("returncode") == 0,
        "returncode": result.get("returncode"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


@contextmanager
def tool_file_lock(name, key, timeout=120):
    os.makedirs(TOOL_LOCK_ROOT, exist_ok=True)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(TOOL_LOCK_ROOT, f"{name}-{digest}.lock")
    start = time.time()
    with open(path, "w") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.write(f"{os.getpid()} {time.time()} {key}\n")
                lock_file.flush()
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise ToolRuntimeError(f"Timed out waiting for {name} lock for {key}.")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_axon_project_scan(project_path, timeout=1200):
    status = axon_runtime_status()
    if not status.get("ready"):
        return {
            "status": "unavailable",
            "requiresAttention": True,
            "reason": status.get("reason", "Axon runtime is not ready."),
            "runtime": status,
            "commands": {},
        }

    commands = {}
    command = status["path"]
    try:
        with tool_file_lock("axon", os.path.abspath(project_path), timeout=timeout):
            commands["analyze"] = run_command([command, "analyze", project_path], timeout=timeout)
            commands["status"] = run_command([command, "status"], timeout=1200, cwd=project_path)
            if (
                commands["analyze"].get("returncode") == 0
                and commands["status"].get("returncode") == 0
            ):
                commands["deadCode"] = run_command([command, "dead-code"], timeout=1200, cwd=project_path)
            else:
                commands["deadCode"] = {
                    "command": [command, "dead-code"],
                    "returncode": None,
                    "stdout": "",
                    "stderr": "",
                    "skipped": True,
                    "reason": "Skipped because analyze or status failed.",
                }
    except ToolRuntimeError as error:
        return {
            "status": "degraded",
            "requiresAttention": True,
            "reason": str(error),
            "runtime": status,
            "commands": commands,
        }

    failures = [
        name for name, result in commands.items()
        if result.get("returncode") not in (0, None)
    ]
    lock_failure = any(
        "could not set lock" in (result.get("stderr", "") + result.get("stdout", "")).lower()
        for result in commands.values()
    )
    if failures:
        reason = f"Axon command(s) failed: {', '.join(failures)}."
        if lock_failure:
            reason = f"{reason} The project index appears to be locked by another Axon process."
        return {
            "status": "degraded",
            "requiresAttention": True,
            "reason": reason,
            "runtime": status,
            "commands": commands,
        }

    return {
        "status": "complete",
        "requiresAttention": False,
        "reason": "Axon analyze, status, and dead-code completed.",
        "runtime": status,
        "commands": commands,
    }
