from PyQt6.QtWidgets import QMainWindow

from main_window import KefuHelperApp


class LayoutOnlyWindow(KefuHelperApp):
    def __init__(self):
        QMainWindow.__init__(self)
        self.init_ui()


def test_main_splitter_respects_button_row_minimum_widths(qapp):
    window = LayoutOnlyWindow()
    window.show()
    qapp.processEvents()

    splitter = window.main_splitter
    assert splitter.childrenCollapsible() is False
    assert window.left_panel.minimumWidth() > 0
    assert window.right_panel.minimumWidth() > 0

    splitter.setSizes([0, 10_000])
    qapp.processEvents()
    assert splitter.sizes()[0] >= window.left_panel.minimumWidth()

    splitter.setSizes([10_000, 0])
    qapp.processEvents()
    assert splitter.sizes()[1] >= window.right_panel.minimumWidth()

    window.hide()
    window.deleteLater()
    qapp.processEvents()
