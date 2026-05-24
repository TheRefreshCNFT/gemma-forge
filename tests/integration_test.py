import os
import subprocess
import sys
from src.config import AppConfig
from src.hf_engine import HuggingFaceEngine
from huggingface_hub import snapshot_download

def log(msg):
    print(f"[TEST] {msg}")

def run_cmd(cmd):
    log(f"Executing: {cmd}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(f"  {line.strip()}")
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {process.returncode}")

def test_full_pipeline():
    config = AppConfig()
    hf_engine = HuggingFaceEngine()
    
    # 1. Use the default small Gemma 4 lane unless a test override is provided.
    model_id = os.environ.get("GFORGE_INTEGRATION_MODEL", "google/gemma-4-E4B-it")
    log(f"Checking Hugging Face metadata for {model_id}...")
    hf_engine.search_models(query=model_id)
    log(f"Selected model: {model_id}")
    
    # 2. Download
    base_path = config.get("paths.models_root")
    os.makedirs(base_path, exist_ok=True)
    model_dir = os.path.join(base_path, model_id.replace("/", "_"))
    
    log(f"Downloading model to {model_dir}...")
    snapshot_download(repo_id=model_id, local_dir=model_dir)
    
    # 3. Forge
    out_gguf = os.path.join(base_path, "gemma-forge-test.gguf")
    model_name = "gemma-forge-test"
    
    # Convert
    log("Converting to GGUF (FP16)...")
    out_temp = out_gguf.replace(".gguf", "-f16.gguf")
    llama_cpp_root = config.get("paths.llama_cpp_root")
    run_cmd([sys.executable, os.path.join(llama_cpp_root, "convert_hf_to_gguf.py"), model_dir, "--outfile", out_temp])
    
    # Quantize
    log("Quantizing to Q4_K_M...")
    llama_cpp_bin = config.get("paths.llama_cpp_bin")
    run_cmd([os.path.join(llama_cpp_bin, "llama-quantize"), out_temp, out_gguf, "Q4_K_M"])
    if os.path.exists(out_temp):
        os.remove(out_temp)
        
    # Modelfile
    log("Generating Modelfile...")
    modelfile_content = f"FROM {os.path.abspath(out_gguf)}\nSYSTEM \"You are a test bot.\"\n"
    modelfile_path = os.path.join(base_path, "Modelfile_test")
    with open(modelfile_path, "w") as f:
        f.write(modelfile_content)
        
    # Import to Ollama
    log(f"Importing to Ollama as {model_name}...")
    run_cmd(["ollama", "create", model_name, "-f", modelfile_path])
    
    # 4. Verify
    log("Verifying with 'ollama list'...")
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False)
    if model_name in result.stdout:
        log(f"SUCCESS: {model_name} is in the Ollama list!")
    else:
        log(f"FAILURE: {model_name} not found in Ollama list.")
        print(result.stdout)
        raise RuntimeError("Model failed to appear in Ollama list")

if __name__ == "__main__":
    try:
        test_full_pipeline()
    except Exception as e:
        print(f"Integration Test Failed: {e}")
        exit(1)
