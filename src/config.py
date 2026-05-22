import os
import json
from typing import Any, Dict


HOME = os.path.expanduser("~")
GFORGE_HOME = os.environ.get("GFORGE_HOME", os.path.join(HOME, ".gforge"))

class AppConfig:
    # Environment Paths
    DEFAULT_CONFIG = {
        "paths": {
            "llama_cpp_root": os.environ.get(
                "LLAMA_CPP_ROOT",
                os.path.join(GFORGE_HOME, "tools", "llama.cpp"),
            ),
            "llama_cpp_bin": os.environ.get(
                "LLAMA_CPP_BIN",
                os.path.join(GFORGE_HOME, "tools", "llama.cpp", "build", "bin"),
            ),
            "models_root": os.environ.get("GFORGE_MODELS_ROOT", os.path.join(GFORGE_HOME, "models")),
        },
        "ui": {
            "theme": "dark",
            "color": "blue",
            "window_size": "1000x800",
            "title": "GEMMA FORGE",
            "accent_color": "#3b8ed0",
            "bg_color": "#1a1a1a",
        },
        "modelfile_defaults": {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
            "system_prompt": "You are a helpful assistant.",
            "template": "gemma_thinking",
        }
    }

    TEMPLATES = {
        "gemma_thinking": """{{ if .System }}<start_of_turn>system
{{ .System }}<end_of_turn>
{{ end }}{{ if .Prompt }}<start_of_turn>user
{{ .Prompt }}<end_of_turn>
{{ end }}<start_of_turn>model
<thought>
{{ .Response }}<end_of_turn>""",
        "llama3": """<start_of_turn>user
{{ .Prompt }}<end_of_turn>
<start_of_turn>model
{{ .Response }}<end_of_turn>""",
        "default": """{{ .Prompt }}
Assistant: {{ .Response }}"""
    }

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.settings = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    return {**self.DEFAULT_CONFIG, **json.load(f)}
            except Exception:
                return self.DEFAULT_CONFIG
        return self.DEFAULT_CONFIG

    def save_config(self):
        with open(self.config_path, "w") as f:
            json.dump(self.settings, f, indent=4)

    def get(self, key_path: str, default=None):
        """Get nested keys using dot notation (e.g., 'paths.llama_cpp_root')"""
        keys = key_path.split(".")
        val = self.settings
        try:
            for k in keys:
                val = val[k]
            return val
        except (KeyError, TypeError):
            return default

    def set(self, key_path: str, value: Any):
        """Set nested keys using dot notation"""
        keys = key_path.split(".")
        val = self.settings
        for k in keys[:-1]:
            val = val.setdefault(k, {})
        val[keys[-1]] = value
        self.save_config()
