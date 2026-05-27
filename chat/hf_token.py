import base64
import os
import time
from typing import Any

import requests

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:  # pragma: no cover - dependency is declared for installs.
    hashes = None
    serialization = None
    padding = None
    rsa = None


HOME = os.path.expanduser("~")
GFORGE_HOME = os.environ.get("GFORGE_HOME", os.path.join(HOME, ".gforge"))
HF_TOKEN_DEFAULT = os.path.join(GFORGE_HOME, "credentials", "hf-token")
HF_TOKEN_LEGACY_PATH = "/Users/webot/.webot/credentials/hf-token"
HF_TOKEN_PATH_ENV_VARS = ("GFORGE_HF_TOKEN_PATH", "HF_TOKEN_PATH")
HF_TOKEN_VALUE_ENV_VARS = ("GFORGE_HF_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
HF_TOKEN_SERVICE_URL_DEFAULT = "https://ops.webot.agency/api/gforge/hf-token"
HF_TOKEN_SERVICE_URL_ENV = "GFORGE_HF_TOKEN_URL"
HF_TOKEN_SERVICE_DISABLE_ENV = "GFORGE_DISABLE_ORACLE_HF_TOKEN"

_REMOTE_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires": 0.0}
_REMOTE_READY_CACHE: dict[str, Any] = {"ready": None, "expires": 0.0}


def _expand_config_path(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path.strip()))


def hf_token_service_url() -> str:
    return os.environ.get(HF_TOKEN_SERVICE_URL_ENV, HF_TOKEN_SERVICE_URL_DEFAULT).strip()


def remote_hf_token_enabled() -> bool:
    return os.environ.get(HF_TOKEN_SERVICE_DISABLE_ENV, "").strip() != "1" and bool(hf_token_service_url())


def hf_token_from_env() -> str | None:
    for key in HF_TOKEN_VALUE_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def configured_hf_token_path() -> str | None:
    for key in HF_TOKEN_PATH_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            return _expand_config_path(value)
    return None


def fallback_hf_token_path() -> str:
    if os.path.exists(HF_TOKEN_LEGACY_PATH):
        return HF_TOKEN_LEGACY_PATH
    return HF_TOKEN_DEFAULT


def resolve_hf_token_path() -> str:
    return configured_hf_token_path() or fallback_hf_token_path()


def read_hf_token_file(path: str | None = None) -> str | None:
    token_path = _expand_config_path(path) if path else resolve_hf_token_path()
    try:
        if token_path and os.path.exists(token_path):
            with open(token_path, "r") as token_file:
                return token_file.read().strip() or None
    except OSError:
        return None
    return None


def remote_hf_token_ready(timeout: float = 3.0) -> bool:
    if not remote_hf_token_enabled():
        return False
    now = time.time()
    if _REMOTE_READY_CACHE["expires"] > now:
        return bool(_REMOTE_READY_CACHE["ready"])
    try:
        response = requests.get(hf_token_service_url(), timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        ready = bool(payload.get("ready"))
    except Exception:
        ready = False
    _REMOTE_READY_CACHE.update({"ready": ready, "expires": now + 60})
    return ready


def fetch_remote_hf_token(timeout: float = 10.0) -> str | None:
    if not remote_hf_token_enabled() or rsa is None or serialization is None:
        return None
    now = time.time()
    if _REMOTE_TOKEN_CACHE["expires"] > now and _REMOTE_TOKEN_CACHE["token"]:
        return str(_REMOTE_TOKEN_CACHE["token"])

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    try:
        response = requests.post(
            hf_token_service_url(),
            json={
                "purpose": "gemma-forge-hf-token",
                "publicKey": public_key_pem,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        encrypted = base64.b64decode(str(payload.get("ciphertext", "")))
        if not encrypted:
            return None
        token = private_key.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        ).decode("utf-8").strip()
    except Exception:
        return None
    if token:
        _REMOTE_TOKEN_CACHE.update({"token": token, "expires": now + 3600})
    return token or None


def read_hf_token() -> str | None:
    token = hf_token_from_env()
    if token:
        return token
    configured_path = configured_hf_token_path()
    if configured_path:
        return read_hf_token_file(configured_path)
    token = fetch_remote_hf_token()
    if token:
        return token
    return read_hf_token_file(fallback_hf_token_path())


def hf_token_source() -> str:
    if hf_token_from_env():
        return "env"
    configured_path = configured_hf_token_path()
    if configured_path and os.path.exists(configured_path):
        return "configured-file"
    if remote_hf_token_ready():
        return "oracle"
    if os.path.exists(fallback_hf_token_path()):
        return "local-file"
    return "missing"


def hf_token_ready() -> bool:
    return hf_token_source() != "missing"
