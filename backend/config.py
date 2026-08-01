"""Config file I/O - copied verbatim from craftmap/overlay.py's Config
section (persists window position/size, hotkey, view mode, collapsed
tree node keys). Shares config.json with the existing tkinter app; see
paths.py.

pywebview dispatches every single JS->Python js_api call on its own
freshly-spawned thread (see the installed webview package's
webview/util.py: js_bridge_call's own docstring plus its `Thread(target=
_call).start()`), with zero coordination between them - and CraftMap's
several screens each fire off a handful of config-reading/writing calls
independently during their own startup, all racing at once. A plain
load-whole-file/mutate-one-key/save-whole-file sequence run from
multiple concurrent threads is a textbook lost-update race: whichever
thread's save() call lands last wins outright, silently discarding any
key some other thread had just written, using only the stale snapshot
it happened to load(). Confirmed live: this is what was wiping out
window position, the rebound hotkey, wreck tracker settings, and more,
down to just whatever the last writer's own narrow snapshot still had.
_LOCK plus update_config() below is the fix - every call site that
mutates config.json MUST go through update_config() (never its own
load_config()+save_config() pair) so the whole read-modify-write is one
atomic unit against every other thread doing the same.
"""

import json
import os
import threading

from .paths import CONFIG_PATH

# Reentrant: update_config() below calls load_config()/save_config() while
# already holding it, and a plain Lock would deadlock a thread against
# itself in that case.
_LOCK = threading.RLock()


def load_config():
    defaults = {"toggle_key": "F1"}
    with _LOCK:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    return {**defaults, **json.load(f)}
            except (OSError, ValueError):
                pass
        return defaults


def save_config(cfg):
    # Written to a temp file and swapped in via os.replace (atomic on both
    # POSIX and Windows) rather than truncating CONFIG_PATH in place - a
    # concurrent load_config() (still guarded by the same _LOCK, but from
    # a process crash/kill mid-write rather than another thread) should
    # never be able to observe a half-written, truncated JSON file.
    with _LOCK:
        tmp_path = f"{CONFIG_PATH}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp_path, CONFIG_PATH)
        except OSError:
            pass


def update_config(mutate):
    """The only safe way to change config.json: atomically load the
    current config, apply `mutate(cfg)` (which mutates the dict in
    place - no return value needed), and save the result, all under one
    lock acquisition so no other thread's own update_config() call can
    interleave and clobber it. See this module's own docstring for why
    a bare load_config()+save_config() pair is NOT safe for a
    read-modify-write."""
    with _LOCK:
        cfg = load_config()
        mutate(cfg)
        save_config(cfg)
        return cfg
