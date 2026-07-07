"""Config file I/O - copied verbatim from craftmap/overlay.py's Config
section (persists window position/size, hotkey, view mode, collapsed
tree node keys). Shares config.json with the existing tkinter app; see
paths.py."""

import json
import os

from .paths import CONFIG_PATH


def load_config():
    defaults = {"toggle_key": "F1"}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return {**defaults, **json.load(f)}
        except (OSError, ValueError):
            pass
    return defaults


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass
