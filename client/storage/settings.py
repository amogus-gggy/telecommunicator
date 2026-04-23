"""File-based settings storage."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


class LocalStorage:
    """Persists key-value settings to a JSON file."""

    def __init__(self, directory: str) -> None:
        self._path = os.path.join(directory, "messenger_settings.json")
        os.makedirs(directory, exist_ok=True)
        logger.info("[LocalStorage] Initialized. Settings file: %s", self._path)

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
                logger.debug("[LocalStorage] Loaded: %s", data)
                return data
        except FileNotFoundError:
            logger.info("[LocalStorage] File not found, returning empty dict")
            return {}
        except json.JSONDecodeError as e:
            logger.warning("[LocalStorage] JSON decode error: %s", e)
            return {}

    def get(self, key: str) -> str | None:
        value = self._load().get(key)
        logger.info("[LocalStorage] get(%r) -> %r", key, value)
        return value

    def set(self, key: str, value: str) -> None:
        logger.info("[LocalStorage] set(%r, %r)", key, value)
        data = self._load()
        data[key] = value
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.info("[LocalStorage] Saved to %s: %s", self._path, data)
        except Exception as e:
            logger.error("[LocalStorage] Failed to save: %s", e)
