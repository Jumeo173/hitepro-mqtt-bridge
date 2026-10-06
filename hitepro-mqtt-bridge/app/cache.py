"""Работа с кэшем состояний, имён и реестром опубликованных discovery."""
import json
import os
import logging

_LOGGER = logging.getLogger(__name__)

DATA_DIR = "/data"
STATE_FILE = os.path.join(DATA_DIR, "state.json")
NAMES_FILE = os.path.join(DATA_DIR, "names.json")
PUBLISHED_FILE = os.path.join(DATA_DIR, "published.json")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        _LOGGER.warning("Не удалось прочитать %s: %s", path, e)
        return default


def _save_json(path, data):
    _ensure_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_state() -> dict:
    return _load_json(STATE_FILE, {})


def save_state(state: dict):
    _save_json(STATE_FILE, state)


def load_names() -> dict:
    return _load_json(NAMES_FILE, {})


def save_names(names: dict):
    _save_json(NAMES_FILE, names)


def load_published() -> dict:
    return _load_json(PUBLISHED_FILE, {})


def save_published(published: dict):
    _save_json(PUBLISHED_FILE, published)
