SHELL_SURFACE_CLASSES = frozenset({
    'notifyiconoverflowwindow',
    'progman',
    'shell_secondarytraywnd',
    'shell_traywnd',
    'toplevelwindowforoverflowxamlisland',
    'traynotifywnd',
    'workerw',
})


def is_shell_surface_window(hwnd, win32_api):
    """判断句柄是否属于任务栏、托盘、隐藏图标弹层或桌面。"""
    if not hwnd or win32_api is None:
        return False

    try:
        if hwnd == win32_api.GetShellWindow():
            return True
    except Exception:
        pass

    current = hwnd
    visited = set()
    for _ in range(8):
        if not current or current in visited:
            break
        visited.add(current)
        try:
            class_name = win32_api.GetClassName(current)
            if class_name and class_name.lower() in SHELL_SURFACE_CLASSES:
                return True
            current = win32_api.GetParent(current)
        except Exception:
            break
    return False
