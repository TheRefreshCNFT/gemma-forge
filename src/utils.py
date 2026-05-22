import subprocess
import shutil
import platform

def check_ollama_installed() -> bool:
    """Checks if ollama is available in the system path."""
    return shutil.which("ollama") is not None

def get_ollama_version() -> str:
    """Tries to get the current ollama version."""
    try:
        result = subprocess.run(
            ["ollama", "--version"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Unknown"

def is_ollama_running() -> bool:
    """Checks if the ollama serve process is active."""
    try:
        # Attempt to call the ollama API local port
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False
