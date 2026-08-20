import os
import ctypes

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QLineEdit, QLabel, QPushButton, QApplication
)

from config import MENU_PREVIEW_LENGTH
from utils import (
    PINYIN_AVAILABLE, extract_preview, entry_matches, make_entry_label
)
from services.window_activation import get_focused_window

try:
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    win32gui = None


class QuickSelectPopup(QWidget):
    ENTRY_GROUP_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent_app=None):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.parent_app = parent_app
        self.target_hwnd = None
        self.target_focus_hwnd = None

        self.setMinimumSize(420, 320)
        self.setMaximumSize(500, 450)

        self._init_ui()
        self._load_data()
        self._apply_style()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(6, 6, 6, 4)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('搜索话术...')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_edit)
        close_btn = QPushButton('X')
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.close)
        close_btn.setToolTip('关闭')
        search_layout.addWidget(close_btn)
        main_layout.addLayout(search_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 0, 0, 4)
        left_layout.setSpacing(2)
        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self._on_group_changed)
        left_layout.addWidget(QLabel('分组'))
        left_layout.addWidget(self.group_list)
        left_panel.setMinimumWidth(100)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 4, 4)
        right_layout.setSpacing(2)
        self.entry_list = QListWidget()
        self.entry_list.itemClicked.connect(self._send_entry)
        right_layout.addWidget(QLabel('话术'))
        right_layout.addWidget(self.entry_list)
        right_panel.setMinimumWidth(220)
        splitter.addWidget(right_panel)

        self.main_splitter = splitter
        self.left_panel = left_panel
        self.right_panel = right_panel
        splitter.setSizes([140, 280])
        main_layout.addWidget(splitter)

    def _apply_style(self):
        self.setStyleSheet("""
            QuickSelectPopup {
                background-color: rgb(232, 242, 252);
                border: 1px solid #B0B0B0;
            }
            QLineEdit {
                padding: 4px 6px;
                font-size: 10pt;
                border: 1px solid #C0C0C0;
                border-radius: 3px;
            }
            QListWidget {
                font-size: 10pt;
                border: 1px solid #D0D0D0;
                border-radius: 3px;
                background-color: #FAFAFA;
            }
            QListWidget::item {
                padding: 4px 6px;
                border-radius: 2px;
            }
            QListWidget::item:selected {
                background-color: #0078D7;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #E8F0FE;
            }
            QLabel {
                font-size: 9pt;
                color: #666666;
                padding: 2px 2px 0 2px;
            }
            QPushButton {
                font-size: 10pt;
                font-weight: bold;
                border: none;
                background: transparent;
                color: #888;
            }
            QPushButton:hover {
                color: #333;
                background: #E0E0E0;
                border-radius: 3px;
            }
        """)

    def _load_data(self):
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for g in self.parent_app.group_order:
            if g in self.parent_app.data and self.parent_app.data[g]:
                count = len(self.parent_app.data[g])
                item = QListWidgetItem(f'{g} ({count})')
                item.setData(Qt.ItemDataRole.UserRole, g)
                self.group_list.addItem(item)
        self.group_list.blockSignals(False)

        if self.group_list.count() > 0:
            self.group_list.setCurrentRow(0)

    def _current_group(self):
        item = self.group_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _on_group_changed(self):
        self._refresh_entries(self.search_edit.text().strip().lower())

    def _refresh_entries(self, filter_text=''):
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        if filter_text:
            groups = self.parent_app.group_order
        else:
            current_group = self._current_group()
            groups = [current_group] if current_group else []

        for group in groups:
            if group not in self.parent_app.data:
                continue
            for i, entry in enumerate(self.parent_app.data[group]):
                plain = extract_preview(
                    entry.get('html_content', ''), MENU_PREVIEW_LENGTH
                )
                if not entry_matches(entry, filter_text, plain=plain):
                    continue
                tags = entry.get('tags', [])
                li = QListWidgetItem(
                    make_entry_label(
                        plain, group, tags, show_group=bool(filter_text)
                    )
                )
                li.setData(Qt.ItemDataRole.UserRole, i)
                li.setData(self.ENTRY_GROUP_ROLE, group)
                li.setToolTip(entry.get('html_content', ''))
                self.entry_list.addItem(li)
        self.entry_list.blockSignals(False)

    def _on_search(self, text):
        self._refresh_entries(text.strip().lower())

    def _send_entry(self, item):
        if not item:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        group = item.data(self.ENTRY_GROUP_ROLE) or self._current_group()
        if not group:
            return
        entries = self.parent_app.data.get(group, [])
        if idx < 0 or idx >= len(entries):
            return
        html = entries[idx].get('html_content', '')
        target_hwnd = self.target_hwnd
        target_focus_hwnd = self.target_focus_hwnd
        self.close()
        # 等 Qt 完成弹窗隐藏和焦点释放后再开始恢复目标窗口。
        QTimer.singleShot(
            0,
            lambda: self.parent_app._do_paste_text(
                html,
                target_hwnd=target_hwnd,
                target_focus_hwnd=target_focus_hwnd,
            ),
        )

    def show_at_cursor(self):
        try:
            import win32gui
            self.target_hwnd = win32gui.GetForegroundWindow()
            self.target_focus_hwnd = get_focused_window(
                self.target_hwnd, win32gui, ctypes.windll.user32
            )
        except Exception:
            self.target_hwnd = None
            self.target_focus_hwnd = None
        cursor = QCursor.pos()
        # 跟随鼠标所在的显示器，而不是固定主屏；
        # 否则在外接副屏上触发时，弹窗会被强行夹回主屏。
        screen = QApplication.screenAt(cursor) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(cursor.x(), geo.right() - self.width()))
            y = max(geo.top(), min(cursor.y(), geo.bottom() - self.height()))
            self.move(x, y)
        else:
            self.move(cursor)
        self._load_data()
        self.search_edit.clear()
        self.search_edit.setFocus()
        self.show()
