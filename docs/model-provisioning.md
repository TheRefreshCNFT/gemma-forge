# Model Provisioning

Gemma Forge has one fixed first-run path: `./launch_forge.command` pulls
`gemma4:e4b`, creates the local alias `gemma-4-e4b-it`, and opens the harness
with that model ready. New users are not asked to choose a model during
quickstart.

After the app is running, users can add more models from Settings.

## Optional Model Lanes

### Import An Ollama Model

Use this when the model is already available through Ollama.

```bash
ollama pull <model>
```

Then open Settings and import installed Ollama models.

### Provision A GGUF Repo

Use this for Hugging Face repos that already include `.gguf` files. Gemma Forge
downloads the selected GGUF file, writes an Ollama Modelfile, runs
`ollama create`, and marks the model runnable only after Ollama lists it.

The curated optional download catalog lives at
[`docs/model-downloads.json`](model-downloads.json). It is metadata only; model
weights are not committed to this repository or downloaded during quickstart.

### Advanced: Convert Raw Hugging Face Weights

Raw Hugging Face repos with `.safetensors` or PyTorch weights but no GGUF files
require a llama.cpp conversion toolchain. Gemma Forge checks this before
conversion and reports a clear setup message if it is missing.

Install or point Gemma Forge at a prepared llama.cpp checkout:

```bash
git clone https://github.com/ggerganov/llama.cpp ~/.gforge/tools/llama.cpp
cd ~/.gforge/tools/llama.cpp
cmake -B build
cmake --build build --config Release -j
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements/requirements-convert_hf_to_gguf.txt
```

If your converter environment is somewhere else, set:

```bash
export LLAMA_CPP_ROOT=/path/to/llama.cpp
export LLAMA_CPP_BIN=/path/to/llama.cpp/build/bin
export GFORGE_LLAMA_CPP_PYTHON=/path/to/llama.cpp/.venv/bin/python
npm run harness:restart
```

For most users, a direct GGUF repo or Ollama model is the better path. Raw
conversion is for large models, new architectures, or users who specifically
want to manage quantization locally.

## Catalog Maintenance

The catalog should be checked monthly. Keep entries lightweight:

- Source repo or Ollama tag.
- Recommended GGUF filename when applicable.
- Suggested Ollama model name.
- Approximate download size.
- Whether llama.cpp conversion is required.
- Last verified date and status.

Do not commit `.gguf`, `.safetensors`, Ollama blobs, or local model caches to
the repository.
