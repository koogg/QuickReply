"""Windows 目标窗口激活与键盘输入辅助。"""

import ctypes
from ctypes import wintypes


SW_RESTORE = 9
SW_SHOW = 5
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56
GA_ROOT = 2


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hwndActive', wintypes.HWND),
        ('hwndFocus', wintypes.HWND),
        ('hwndCapture', wintypes.HWND),
        ('hwndMenuOwner', wintypes.HWND),
        ('hwndMoveSize', wintypes.HWND),
        ('hwndCaret', wintypes.HWND),
        ('rcCaret', wintypes.RECT),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ('uMsg', wintypes.DWORD),
        ('wParamL', wintypes.WORD),
        ('wParamH', wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    # INPUT 的 cbSize 必须包含最大成员 MOUSEINPUT；只声明键盘成员会
    # 在 64 位 Windows 上得到 32 而不是系统要求的 40 字节。
    _fields_ = [
        ('mi', _MOUSEINPUT),
        ('ki', _KEYBDINPUT),
        ('hi', _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ('union',)
    _fields_ = [
        ('type', wintypes.DWORD),
        ('union', _INPUT_UNION),
    ]


def _keyboard_input(vk, flags=0):
    return _INPUT(
        type=INPUT_KEYBOARD,
        union=_INPUT_UNION(
            ki=_KEYBDINPUT(
                wVk=vk,
                wScan=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )


def send_ctrl_v(user32):
    """通过 SendInput 发送一次 Ctrl+V，成功时返回 True。"""
    inputs = (_INPUT * 4)(
        _keyboard_input(VK_CONTROL),
        _keyboard_input(VK_V),
        _keyboard_input(VK_V, KEYEVENTF_KEYUP),
        _keyboard_input(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    send_input = user32.SendInput
    if hasattr(send_input, 'argtypes'):
        send_input.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        )
        send_input.restype = wintypes.UINT
    return send_input(4, inputs, ctypes.sizeof(_INPUT)) == 4


def _get_window_thread_id(hwnd, user32):
    if not hwnd:
        return 0
    get_thread_id = user32.GetWindowThreadProcessId
    if hasattr(get_thread_id, 'argtypes'):
        get_thread_id.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        get_thread_id.restype = wintypes.DWORD
    return get_thread_id(hwnd, None)


def _root_window(hwnd, win32gui_api):
    if not hwnd:
        return None
    if hasattr(win32gui_api, 'GetAncestor'):
        return win32gui_api.GetAncestor(hwnd, GA_ROOT) or hwnd
    return hwnd


def _belongs_to_window(target, candidate, win32gui_api):
    if not target or not candidate:
        return False
    target = _root_window(target, win32gui_api)
    if candidate == target or _root_window(candidate, win32gui_api) == target:
        return True
    return bool(
        hasattr(win32gui_api, 'IsChild') and
        win32gui_api.IsChild(target, candidate)
    )


def get_focused_window(hwnd, win32gui_api, user32):
    """返回目标窗口输入线程中当前获得焦点的控件句柄。"""
    try:
        target = _root_window(hwnd, win32gui_api)
        thread_id = _get_window_thread_id(target, user32)
        if not thread_id:
            return None
        info = _GUITHREADINFO(cbSize=ctypes.sizeof(_GUITHREADINFO))
        get_info = user32.GetGUIThreadInfo
        if hasattr(get_info, 'argtypes'):
            get_info.argtypes = (
                wintypes.DWORD,
                ctypes.POINTER(_GUITHREADINFO),
            )
            get_info.restype = wintypes.BOOL
        if not get_info(thread_id, ctypes.byref(info)):
            return None
        focus = int(info.hwndFocus) if info.hwndFocus else None
        return focus if _belongs_to_window(target, focus, win32gui_api) else None
    except Exception:
        return None


def is_target_foreground(hwnd, win32gui_api):
    """判断前台窗口是否属于目标顶层窗口。"""
    try:
        active = win32gui_api.GetForegroundWindow()
        return _belongs_to_window(hwnd, active, win32gui_api)
    except Exception:
        return False


def target_focus_restored(hwnd, focus_hwnd, win32gui_api, user32):
    """判断目标已在前台，且原输入控件焦点已经恢复。"""
    if not is_target_foreground(hwnd, win32gui_api):
        return False
    if not focus_hwnd:
        return True
    current_focus = get_focused_window(hwnd, win32gui_api, user32)
    if current_focus == focus_hwnd:
        return True
    try:
        return bool(
            current_focus and
            (win32gui_api.IsChild(focus_hwnd, current_focus) or
             win32gui_api.IsChild(current_focus, focus_hwnd))
        )
    except Exception:
        return False


def activate_window(hwnd, win32gui_api, user32, kernel32, focus_hwnd=None):
    """尽力激活目标顶层窗口，并确认它已成为前台窗口。

    Windows 会限制后台进程直接抢占前台。临时附加当前线程、原前台
    线程和目标线程的输入队列，可让钉钉等多进程桌面应用可靠恢复焦点。
    """
    if not hwnd:
        return False
    try:
        if hasattr(win32gui_api, 'IsWindow') and not win32gui_api.IsWindow(hwnd):
            return False
        target = _root_window(hwnd, win32gui_api)
        if win32gui_api.IsIconic(target):
            win32gui_api.ShowWindow(target, SW_RESTORE)

        if not _belongs_to_window(target, focus_hwnd, win32gui_api):
            focus_hwnd = None

        current_thread = kernel32.GetCurrentThreadId()
        foreground = win32gui_api.GetForegroundWindow()
        foreground_thread = _get_window_thread_id(foreground, user32)
        target_thread = _get_window_thread_id(target, user32)
        focus_thread = _get_window_thread_id(focus_hwnd, user32)
        attached = []
        for thread_id in (foreground_thread, target_thread, focus_thread):
            if thread_id and thread_id != current_thread and thread_id not in attached:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached.append(thread_id)
        try:
            win32gui_api.ShowWindow(target, SW_SHOW)
            win32gui_api.BringWindowToTop(target)
            win32gui_api.SetForegroundWindow(target)
            if focus_hwnd:
                set_focus = user32.SetFocus
                if hasattr(set_focus, 'argtypes'):
                    set_focus.argtypes = (wintypes.HWND,)
                    set_focus.restype = wintypes.HWND
                set_focus(focus_hwnd)
        finally:
            for thread_id in reversed(attached):
                user32.AttachThreadInput(current_thread, thread_id, False)

        return is_target_foreground(target, win32gui_api)
    except Exception:
        return False
