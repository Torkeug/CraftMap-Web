# pylint: disable=missing-function-docstring
"""Win32 interop helpers for the overlay window: hwnd resolution, OS focus
detection, click-through, composited-window flicker reduction, and the
single-instance mutex check.

Ported from the retired tkinter app's own win32util.py for this
pywebview-based rewrite - see pywebview_hwnd() below, which replaces the
original's Tk-specific root_hwnd(widget). Every other function here is
unchanged: they're plain ctypes calls against a raw HWND, agnostic to
which GUI toolkit produced that window.
"""

import ctypes

GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2
# SWP_NOSIZE|SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE|SWP_FRAMECHANGED
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
# RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_UPDATENOW
_RDW_FLAGS = 0x0185
ERROR_ALREADY_EXISTS = 183

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.GetAncestor.restype = ctypes.c_void_p
_user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
_user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.AttachThreadInput.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
_user32.IsWindowVisible.restype = ctypes.c_int
_user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_user32.FindWindowW.restype = ctypes.c_void_p
_user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]


def pywebview_hwnd(window):
    """Resolve a pywebview Window (edgechromium/WinForms backend) to its
    real top-level HWND. window.native.Handle is a .NET IntPtr; .ToInt32()
    gives the raw integer handle - confirmed empirically against pywebview
    6.2.1, since this attribute path isn't guaranteed stable across
    versions. Falls back through GetAncestor(GA_ROOT) in case a future
    backend's native handle isn't already the top-level window, matching
    the same defensive pattern the tkinter app's root_hwnd used."""
    hwnd = window.native.Handle.ToInt32()
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    return root or hwnd


def set_window_alpha(hwnd, alpha: int):
    """Uniformly blend the WHOLE window (chrome included) against whatever
    is behind it, at a constant alpha (0-255) - this is what the tkinter
    app's self.attributes('-alpha', 0.94) actually does under the hood.
    Distinct from pywebview's own transparent=True, which is CSS
    "punch-through" transparency for areas with no opaque content - a
    different mechanism that does nothing for a window whose HTML fills
    the whole body with an opaque background (confirmed empirically)."""
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new_style = style | WS_EX_LAYERED
    if new_style != style:
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
    _user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)


def hwnd_is_foreground(hwnd) -> bool:
    """True if hwnd currently owns the OS foreground/keyboard focus.

    Deliberately a raw Win32 check rather than Tk's own focus_get(): Tk's
    focus tracking is Tcl-internal bookkeeping that gets updated the moment
    something calls focus()/focus_force(), regardless of whether the OS
    actually granted that window the focus. For an overrideredirect popup
    whose focus is grabbed programmatically (see force_foreground_window)
    instead of by a normal user click, that bookkeeping can drift from
    reality and never correct itself, silently leaving click-through stuck.
    Comparing against GetForegroundWindow() has no such gap - it always
    reflects what Windows itself considers focused."""
    if not hwnd:
        return False
    try:
        return _user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def is_window_visible(hwnd) -> bool:
    """True if hwnd is currently shown on screen (WinForms Visible/OS
    WS_VISIBLE state) - a raw Win32 check, not pywebview's own Window
    object, so it reflects the real native state regardless of whether
    pywebview's own show()/hide() bookkeeping has drifted from it."""
    if not hwnd:
        return False
    try:
        return bool(_user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def force_foreground_window(hwnd) -> bool:
    """Robustly make hwnd the OS foreground window, and report whether it
    actually worked.

    A plain SetForegroundWindow() call is routinely ignored by Windows'
    foreground-lock heuristic unless it originates from the thread that
    currently owns the input focus - which is exactly what happens when this
    is called from a global hotkey callback: the hotkey fires on a
    background hook thread and is marshalled onto the Tk loop via `after`,
    several steps removed from the original keypress. Temporarily attaching
    our input queue to the current foreground thread's is the standard
    workaround."""
    fg_hwnd = _user32.GetForegroundWindow()
    fg_thread = _user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
    cur_thread = _kernel32.GetCurrentThreadId()

    attached = False
    try:
        if fg_thread and fg_thread != cur_thread:
            attached = bool(_user32.AttachThreadInput(fg_thread, cur_thread, True))
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        if attached:
            _user32.AttachThreadInput(fg_thread, cur_thread, False)

    return hwnd_is_foreground(hwnd)


def set_click_through(hwnd, enabled: bool):
    """Toggle WS_EX_TRANSPARENT on a window so mouse input (including which
    cursor the OS displays) passes through to whatever is beneath it instead
    of being intercepted by this window."""
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        new_style = style | WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        new_style = style & ~WS_EX_TRANSPARENT
    if new_style != style:
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        # Nudge Windows to re-evaluate hit-testing for the new extended
        # style immediately, instead of waiting on some unrelated message.
        # NOACTIVATE is essential here: without it this call itself steals
        # focus back, immediately undoing the very unfocus transition that
        # triggered it.
        _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_FLAGS)


def redraw_window(hwnd):
    _user32.RedrawWindow(hwnd, None, None, _RDW_FLAGS)


def find_window_by_title(title: str):
    """Resolve a top-level window's HWND by its exact title text. Used to
    focus the already-running instance's main window from a second, blocked
    launch (see main.py's _AlreadyRunningApi) - that's a separate process
    with no in-process Window object to call force_foreground_window on
    directly, so FindWindowW is the only way to get an hwnd for it at all."""
    return _user32.FindWindowW(None, title)


def check_single_instance(mutex_name="CraftMap_SingleInstance") -> bool:
    """True if this is the only running instance. Holds a named mutex for
    the lifetime of the process as the actual enforcement mechanism; the
    return value just reports whether we won the race."""
    _kernel32.CreateMutexW(None, True, mutex_name)
    return _kernel32.GetLastError() != ERROR_ALREADY_EXISTS
