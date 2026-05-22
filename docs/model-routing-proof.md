# Gemma 4 Model Routing Proof

Gemma Forge starts by recommending `gemma-4`, then routes the selected Forge Brain through every model-backed harness call.

## Route

1. The frontend initializes the Forge Brain from the model registry and the recommended model.
2. New projects save the selected Forge Brain as the project model.
3. Planning, protocol-card runs, and project messages send the selected model in the API payload.
4. The Flask harness passes that value into the Ollama `/api/chat` request.
5. The harness records the last attempted model call in `~/.gforge/harness/model-route.json`.

## Verification

Open Settings in the harness and check the model route status line. It reports the selected model and the last harness model call.

The API endpoint is:

```text
GET http://127.0.0.1:5005/api/model/route
```

Expected recommended model field:

```json
{
  "defaultModel": "gemma-4"
}
```
