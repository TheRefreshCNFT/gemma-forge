import os
import logging
from typing import List, Dict, Any, Optional
from huggingface_hub import HfApi, login

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HuggingFaceEngine")

class HuggingFaceEngine:
    def __init__(self, token_path: str = "/Users/webot/.webot/credentials/hf-token"):
        self.api = HfApi()
        self.token = self._load_token(token_path)
        if self.token:
            try:
                login(token=self.token)
                logger.info("Authenticated with Hugging Face Hub.")
            except Exception as e:
                logger.warning(f"Failed to authenticate with HF token: {e}")
        else:
            logger.warning("No HF token found. Some gated models may not be accessible.")

    def _load_token(self, token_path: str) -> Optional[str]:
        """Loads the HF token from the specified file path."""
        try:
            if os.path.exists(token_path):
                with open(token_path, "r") as f:
                    return f.read().strip()
        except Exception as e:
            logger.error(f"Error reading token file at {token_path}: {e}")
        return None

    def search_models(
        self, 
        query: Optional[str] = None, 
        sort: str = "downloads", 
        library: Optional[str] = None,
        tags: Optional[List[str]] = None,
        license: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Searches for models on the HF Hub with various filters and sorting.
        """
        try:
            # Prepare filters
            filters = []
            if tags:
                filters.extend(tags)
            if library:
                filters.append(f"library:{library}")

            # Try listing models WITHOUT 'direction' to avoid the TypeError
            # Most HfApi.list_models implementations sort by downloads desc by default
            # if sort='downloads' is passed.
            models = self.api.list_models(
                search=query,
                sort=sort,
                filter=filters,
            )
            
            results = []
            count = 0
            for model in models:
                if count >= limit:
                    break
                
                # Manual license filtering if provided
                if license and model.card_data and model.card_data.get("license") != license:
                    continue

                available_formats = self._get_available_formats(model.modelId)

                results.append({
                    "model_id": model.modelId,
                    "display_name": model.modelId.split("/")[-1],
                    "downloads": getattr(model, "downloads", 0),
                    "license": model.card_data.get("license") if model.card_data and model.card_data.get("license") else "Not specified",
                    "available_formats": available_formats
                })
                count += 1
            
            return results

        except Exception as e:
            logger.error(f"Error searching models: {e}")
            return []

    def _get_available_formats(self, model_id: str) -> List[str]:
        """Checks the model repository for specific weight formats."""
        formats = []
        try:
            files = self.api.list_repo_files(model_id)
            if any(".safetensors" in f for f in files):
                formats.append("safetensors")
            if any(".bin" in f or "pytorch_model" in f for f in files):
                formats.append("pytorch")
            if any(".gguf" in f for f in files):
                formats.append("gguf")
        except Exception as e:
            logger.debug(f"Could not fetch files for {model_id}: {e}")
        return formats

    def get_top_gguf_compatible(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Returns the Top 10 most popular models compatible with GGUF conversion.
        """
        return self.search_models(
            sort="downloads",
            tags=["safetensors"], 
            limit=limit
        )
