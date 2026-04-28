"""File-based settings storage with in-memory cache."""

from __future__ import annotations

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class LocalStorage:
    """Persists key-value settings to a JSON file with in-memory cache."""

    def __init__(self, directory: str) -> None:
        self._path = os.path.join(directory, "messenger_settings.json")
        os.makedirs(directory, exist_ok=True)
        self._cache: dict | None = None  # in-memory cache, None = not loaded yet
        logger.info("[LocalStorage] Initialized. Settings file: %s", self._path)

    def _load(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
                logger.debug("[LocalStorage] Loaded from disk: %s", data)
                self._cache = data
                return data
        except FileNotFoundError:
            logger.info("[LocalStorage] File not found, returning empty dict")
            self._cache = {}
            return self._cache
        except json.JSONDecodeError as e:
            logger.warning("[LocalStorage] JSON decode error: %s", e)
            self._cache = {}
            return self._cache

    def get(self, key: str) -> str | None:
        value = self._load().get(key)
        logger.debug("[LocalStorage] get(%r) -> %r", key, value)
        return value

    def set(self, key: str, value: str) -> None:
        logger.debug("[LocalStorage] set(%r, %r)", key, value)
        data = self._load()
        data[key] = value
        self._cache = data
        self._flush()

    def _flush(self) -> None:
        """Write cache to disk atomically."""
        try:
            dir_name = os.path.dirname(self._path)
            with tempfile.NamedTemporaryFile(
                "w", dir=dir_name, delete=False, suffix=".tmp", encoding="utf-8"
            ) as tmp:
                json.dump(self._cache, tmp)
                tmp_path = tmp.name
            os.replace(tmp_path, self._path)
            logger.debug("[LocalStorage] Saved to %s", self._path)
        except Exception as e:
            logger.error("[LocalStorage] Failed to save: %s", e)
