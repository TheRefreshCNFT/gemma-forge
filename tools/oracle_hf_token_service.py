#!/usr/bin/env python3
import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


HOST = os.environ.get("GFORGE_HF_TOKEN_HOST", "127.0.0.1")
PORT = int(os.environ.get("GFORGE_HF_TOKEN_PORT", "5017"))
TOKEN_PATH = os.environ.get("GFORGE_HF_TOKEN_FILE", "/home/opc/webot_configs/hf-token.txt")
PURPOSE = "gemma-forge-hf-token"


def _json(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_token():
    with open(TOKEN_PATH, "r") as token_file:
        return token_file.read().strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "GemmaForgeHFToken/1.0"

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        if self.path not in ("/", "/healthz"):
            _json(self, 404, {"error": "not found"})
            return
        _json(self, 200, {"ready": bool(os.path.exists(TOKEN_PATH))})

    def do_POST(self):
        if self.path != "/":
            _json(self, 404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if payload.get("purpose") != PURPOSE:
                _json(self, 400, {"error": "invalid purpose"})
                return
            public_key_pem = str(payload.get("publicKey", "")).encode("utf-8")
            public_key = serialization.load_pem_public_key(public_key_pem)
            token = _read_token().encode("utf-8")
            encrypted = public_key.encrypt(
                token,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except Exception:
            _json(self, 400, {"error": "token request failed"})
            return
        _json(self, 200, {
            "alg": "RSA-OAEP-SHA256",
            "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        })


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
