from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit


class HotkeyLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText('点击此处，然后按下热键组合')

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                   Qt.Key.Key_Meta, Qt.Key.Key_unknown):
            return
        pynput_parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            pynput_parts.append('<ctrl>')
        if modifiers & Qt.KeyboardModifier.AltModifier:
            pynput_parts.append('<alt>')
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            pynput_parts.append('<shift>')
        key_str = self._qt_key_to_string(key)
        if key_str:
            pynput_parts.append(key_str)
            self.setText('+'.join(pynput_parts))
        else:
            self.clear()
        event.accept()

    def keyReleaseEvent(self, event):
        self.editingFinished.emit()
        event.accept()

    @staticmethod
    def _qt_key_to_string(key):
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key).lower()
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(key)
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            return f'<f{(key - Qt.Key.Key_F1) + 1}>'
        mapping = {
            Qt.Key.Key_Space: '<space>',
            Qt.Key.Key_Escape: '<esc>',
            Qt.Key.Key_Return: '<enter>',
            Qt.Key.Key_Enter: '<enter>',
            Qt.Key.Key_Tab: '<tab>',
            Qt.Key.Key_Backspace: '<backspace>',
            Qt.Key.Key_Delete: '<delete>',
            Qt.Key.Key_Home: '<home>',
            Qt.Key.Key_End: '<end>',
            Qt.Key.Key_PageUp: '<page_up>',
            Qt.Key.Key_PageDown: '<page_down>',
            Qt.Key.Key_Left: '<left>',
            Qt.Key.Key_Right: '<right>',
            Qt.Key.Key_Up: '<up>',
            Qt.Key.Key_Down: '<down>',
            Qt.Key.Key_Insert: '<insert>',
            Qt.Key.Key_Minus: '-',
            Qt.Key.Key_Equal: '=',
            Qt.Key.Key_BracketLeft: '[',
            Qt.Key.Key_BracketRight: ']',
            Qt.Key.Key_Semicolon: ';',
            Qt.Key.Key_QuoteLeft: '`',
            Qt.Key.Key_Apostrophe: "'",
            Qt.Key.Key_Comma: ',',
            Qt.Key.Key_Period: '.',
            Qt.Key.Key_Slash: '/',
            Qt.Key.Key_Backslash: '\\',
        }
        return mapping.get(key)