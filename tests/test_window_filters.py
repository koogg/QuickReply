from services.window_filters import is_shell_surface_window


class FakeWin32:
    def __init__(self, classes=None, parents=None, shell_window=999):
        self.classes = classes or {}
        self.parents = parents or {}
        self.shell_window = shell_window

    def GetShellWindow(self):
        return self.shell_window

    def GetClassName(self, hwnd):
        return self.classes.get(hwnd, '')

    def GetParent(self, hwnd):
        return self.parents.get(hwnd, 0)


def test_taskbar_and_overflow_windows_are_ignored():
    api = FakeWin32(classes={
        1: 'Shell_TrayWnd',
        2: 'TopLevelWindowForOverflowXamlIsland',
        3: 'NotifyIconOverflowWindow',
    })

    assert is_shell_surface_window(1, api)
    assert is_shell_surface_window(2, api)
    assert is_shell_surface_window(3, api)


def test_child_of_taskbar_is_ignored():
    api = FakeWin32(
        classes={10: 'ToolbarWindow32', 11: 'TrayNotifyWnd'},
        parents={10: 11},
    )

    assert is_shell_surface_window(10, api)


def test_shell_desktop_handle_is_ignored():
    api = FakeWin32(shell_window=42)

    assert is_shell_surface_window(42, api)


def test_normal_application_window_is_kept():
    api = FakeWin32(classes={7: 'Chrome_WidgetWin_1'})

    assert not is_shell_surface_window(7, api)


def test_invalid_or_cyclic_window_chain_is_safe():
    api = FakeWin32(classes={5: 'Unknown'}, parents={5: 5})

    assert not is_shell_surface_window(None, api)
    assert not is_shell_surface_window(5, api)
