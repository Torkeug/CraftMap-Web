"""Helpers for launching/reading the sibling spacecraft-memory-research
repo's wreck_tracker.py as a subprocess ("Activate live tracking" button,
frontend/js/wrecks.js). Subprocess lifecycle (the Popen handle itself)
lives on Api as an underscore-prefixed attribute (see api.py's own
docstring on why) - this module only holds the pure path/IO helpers
around it.

Kept as a subprocess handoff rather than importing that repo's code
directly - see CRAFTMAP_INTEGRATION.md and this app's CLAUDE.md: live-
process-memory reading is a materially different risk category
(ToS/EULA exposure) than everything else this static-file-only app does,
and the two are deliberately kept separate at the code level even though
this button makes CraftMap the thing that triggers it.
"""
import json
import sys
from pathlib import Path


def resolve_paths(script_path):
    """(live_out, events_out, state_file) paths matching wreck_tracker.py's
    own argparse defaults (all alongside the script itself, see its
    module docstring) - CraftMap and the poller agree on where to look
    with zero extra config beyond the one script_path setting."""
    script_dir = Path(script_path).resolve().parent
    return (
        script_dir / "current_planet_wrecks.json",
        script_dir / "wreck_events.jsonl",
        script_dir / "wreck_tracker_state.json",
    )


def resolve_poi_counts_path(script_path):
    """poi_resource_counts.json path matching wreck_tracker.py's own
    --poi-out default (alongside the script) - same zero-config-agreement
    convention resolve_paths already established for the other three
    output files. Kept as its own function rather than folded into
    resolve_paths' return tuple so existing callers of that function don't
    need to change shape."""
    return Path(script_path).resolve().parent / "poi_resource_counts.json"


def python_executable(configured_python_path):
    """The interpreter to launch wreck_tracker.py with. It's pure-stdlib
    (see its own imports), so any Python 3 install works - doesn't need
    to be the sibling repo's own venv. Falls back to sys.executable only
    when NOT frozen (running from source, where sys.executable really is
    a python.exe); a frozen CraftMap.exe can't run a .py script itself,
    so a frozen build requires an explicit configured_python_path -
    caller is responsible for surfacing that as a setup error, not this
    function (returns None rather than guessing)."""
    if configured_python_path:
        return configured_python_path
    if getattr(sys, "frozen", False):
        return None
    return sys.executable


def read_live_snapshot(live_out_path):
    """The poller's overwritten-every-cycle JSON snapshot - see
    wreck_tracker.py's own module docstring, step 5. None if the poller
    has never run (file doesn't exist yet) or the file is mid-write
    (wreck_tracker.py writes atomically via a temp-file rename, so a
    torn read shouldn't normally happen, but a missing/corrupt file is
    handled the same as "not tracking yet" rather than raised)."""
    path = Path(live_out_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
