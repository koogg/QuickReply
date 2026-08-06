from PyQt6.QtCore import Qt, QTimer, QPoint, QEvent
from PyQt6.QtGui import QCursor, QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QMenu,
    QListWidget, QListWidgetItem, QApplication
)

from utils import extract_preview, entry_matches, make_entry_label
from services.window_filters import is_shell_surface_window

try:
    import win32gui
    import ctypes
    from ctypes import wintypes, windll, byref, sizeof
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    win32gui = None
    ctypes = None
    wintypes = None
    windll = None
    byref = None
    sizeof = None


def _get_dpi_scale(hwnd):
    try:
        MONITOR_DEFAULTTONEAREST = 2
        hmon = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return dpi_x.value / 96.0, dpi_y.value / 96.0
    except Exception:
        return 1.0, 1.0


class FloatingSearchWidget(QWidget):
    def __init__(self, parent_app=None):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.parent_app = parent_app
        self.last_tracked_hwnd = None
        self.self_hwnd = None
        self.main_window_hwnd = None
        self._orientation = '底部'
        self._last_x = -1
        self._last_y = -1
        self.init_ui()

        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.update_position)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)
        self.pending_search_text = ''

        self._dock_save_timer = QTimer(self)
        self._dock_save_timer.setSingleShot(True)
        self._dock_save_timer.setInterval(300)
        self._dock_save_timer.timeout.connect(self._flush_dock_width)
        self._dirty_dock_width = None

    def init_ui(self):
        self.setStyleSheet("""
            FloatingSearchWidget {
                background-color: #FFFFFF;
                border: 1px solid #A0A0A0;
                border-radius: 4px;
            }
            QLineEdit {
                padding: 4px 8px;
                font-size: 10pt;
                border: 1px solid #C0C0C0;
                border-radius: 3px;
            }
            QLineEdit:focus { border-color: #4A90D9; }
            QListWidget {
                font-size: 10pt;
                border: none;
                background-color: #FAFAFA;
            }
            QListWidget::item { padding: 5px 8px; border-radius: 2px; outline: none; border: none; }
            QListWidget::item:selected { background-color: #0078D7; color: white; outline: none; border: none; }
            QListWidget::item:hover { background-color: #E8F0FE; outline: none; border: none; }
        """)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText('搜索话术...')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.on_enter_pressed)
        self.search_edit.textChanged.connect(self.on_search_text_changed)
        self.main_layout.addWidget(self.search_edit)

        self.result_list = QListWidget()
        self.result_list.itemClicked.connect(self._on_item_clicked)
        self.result_list.installEventFilter(self)
        self.result_list.hide()

        self.results_menu = None
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_w = 0

    def set_orientation(self, orientation):
        self._orientation = orientation
        self._last_x = -1
        self._last_y = -1
        self._rebuild_layout()

    def _rebuild_layout(self):
        is_right = self._orientation == '右侧'
        if is_right:
            dock_width = self.parent_app.settings.get('dock_width', 220) if self.parent_app else 220
            self.setMinimumWidth(dock_width)
            self.setMaximumWidth(dock_width)
            self.resize(dock_width, max(200, self.height()))
            self.setMinimumHeight(200)
            self.setMaximumHeight(800)
            self.search_edit.setFixedHeight(30)
            if self.main_layout.indexOf(self.result_list) == -1:
                self.main_layout.addWidget(self.result_list)
            self.result_list.show()
            if self.results_menu:
                self.results_menu.close()
                self.results_menu = None
        else:
            self.setMinimumSize(200, 30)
            self.setMaximumSize(5000, 30)
            self.resize(self.width(), 30)
            self.setFixedHeight(30)
            self.search_edit.setFixedHeight(30)
            if self.main_layout.indexOf(self.result_list) != -1:
                self.main_layout.removeWidget(self.result_list)
            self.result_list.hide()

    def _ensure_size(self):
        if self._orientation == '右侧':
            self._enforce_right_width()

    def _enforce_right_width(self):
        target = self.parent_app.settings.get('dock_width', 220) if self.parent_app else 220
        if self.width() != target:
            self.setMinimumWidth(target)
            self.setMaximumWidth(target)
            self.resize(target, self.height())

    def showEvent(self, event):
        super().showEvent(event)
        self.self_hwnd = int(self.winId()) if self.winId() else None
        if self.parent_app and self.parent_app.winId():
            self.main_window_hwnd = int(self.parent_app.winId())
        pos = self.parent_app.settings.get('dock_position', '底部') if self.parent_app else '底部'
        self.set_orientation(pos)
        self.position_timer.start(100)
        # 立刻按当前前台窗口在正确的显示器上定位一次，避免在主屏闪一下
        QTimer.singleShot(0, self.update_position)
        QTimer.singleShot(50, self._ensure_size)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.position_timer.stop()
        if self.results_menu:
            self.results_menu.close()

    def update_position(self):
        if not HAS_WIN32 or not win32gui:
            return
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return
            if is_shell_surface_window(hwnd, win32gui):
                return
            if self.self_hwnd and hwnd == self.self_hwnd:
                return
            if self.main_window_hwnd and hwnd == self.main_window_hwnd:
                return
            if self.results_menu and self.results_menu.isVisible():
                menu_hwnd = int(self.results_menu.winId()) if self.results_menu.winId() else None
                if menu_hwnd and hwnd == menu_hwnd:
                    return

            rect = wintypes.RECT()
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            result = windll.dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                byref(rect), sizeof(rect)
            )
            if result != 0:
                wr = win32gui.GetWindowRect(hwnd)
                rect.left, rect.top, rect.right, rect.bottom = \
                    wr[0], wr[1], wr[2], wr[3]

            scale_x, scale_y = _get_dpi_scale(hwnd)
            win_left = int(rect.left / scale_x)
            win_top = int(rect.top / scale_y)
            win_right = int(rect.right / scale_x)
            win_bottom = int(rect.bottom / scale_y)
            win_width = win_right - win_left
            win_height = win_bottom - win_top

            # 找到目标窗口所在的 Qt 屏幕 —— 多显示器情况下必须据此把 widget
            # 放到同一块屏，否则会被系统推回主屏或落到副屏外。
            center = QPoint(int(win_left + win_width / 2),
                            int(win_top + win_height / 2))
            screen = QApplication.screenAt(center) or QApplication.primaryScreen()
            if screen is None:
                return
            sg = screen.availableGeometry()

            if self._orientation == '右侧' and win_height > 200:
                self._enforce_right_width()
                w_size = self.width() or self.sizeHint().width()
                max_h = max(200, int(win_height - 20))
                max_h = min(max_h, sg.height() - 8)
                self.setMaximumHeight(max_h)
                h_size = self.height() or self.sizeHint().height()
                x = int(win_right) + 2
                y = int(win_top) + 5
            elif win_width > 100:
                self.setFixedWidth(win_width)
                w_size = win_width
                h_size = self.height() or self.sizeHint().height()
                x = int(win_left)
                y = int(win_bottom)
            else:
                return

            # 把 widget 约束在该屏的可用工作区（避开任务栏等）。
            if x + w_size > sg.right():
                x = sg.right() - w_size
            if x < sg.left():
                x = sg.left()
            if y + h_size > sg.bottom():
                y = sg.bottom() - h_size
            if y < sg.top():
                y = sg.top()

            if x != self._last_x or y != self._last_y:
                self._last_x = x
                self._last_y = y
                self.move(x, y)

            self.last_tracked_hwnd = hwnd
        except Exception as e:
            # 多显示器坐标系敏感，吞异常会导致问题难定位，至少打个日志
            try:
                from utils import logger
                logger.error('update_position 失败: %s', e)
            except Exception:
                pass

    def on_search_text_changed(self, text):
        self.pending_search_text = text.strip().lower()
        self.search_timer.stop()
        if not self.pending_search_text:
            if self._orientation == '右侧':
                self._refresh_result_list()
            elif self.results_menu:
                self.results_menu.close()
            return
        self.search_timer.start(150)

    def _do_search(self):
        search_term = self.pending_search_text
        if not search_term:
            return
        if self._orientation == '右侧':
            self._refresh_result_list()
        else:
            self._show_menu_results()

    def _collect_results(self):
        results = []
        for group_name in self.parent_app.group_order:
            if group_name not in self.parent_app.data:
                continue
            for i, entry in enumerate(self.parent_app.data[group_name]):
                plain_text_raw = extract_preview(entry.get('html_content', ''), 100000)
                if not entry_matches(self.parent_app.data[group_name][i],
                                     self.pending_search_text, plain=plain_text_raw):
                    continue
                tags_list = entry.get('tags', [])
                results.append({'group': group_name, 'index': i, 'data': entry,
                                'plain': plain_text_raw, 'tags': tags_list})
        return results

    def _refresh_result_list(self):
        results = self._collect_results()
        self.result_list.blockSignals(True)
        self.result_list.clear()
        for r in results[:30]:
            plain = r['plain'].replace('\n', ' ').replace('\r', '')
            if len(plain) > 45:
                plain = plain[:45] + '...'
            item = QListWidgetItem(
                make_entry_label(plain, r['group'], r['tags'], show_group=True))
            item.setData(Qt.ItemDataRole.UserRole, r['index'])
            item.setData(Qt.ItemDataRole.UserRole + 1, r['group'])
            item.setToolTip(r['data'].get('html_content', ''))
            self.result_list.addItem(item)
        self.result_list.blockSignals(False)

    def _show_menu_results(self):
        results = self._collect_results()
        if not results:
            if self.results_menu:
                self.results_menu.close()
            return
        if self.results_menu:
            self.results_menu.close()
            self.results_menu.deleteLater()
        self.results_menu = QMenu(self)
        self.results_menu.setStyleSheet("""
            QMenu { font-family: 'Microsoft YaHei UI'; background: white; border: 1px solid #C0C0C0;
                   border-radius: 3px; font-size: 11pt; padding: 2px; }
            QMenu::item { padding: 6px 20px; border-radius: 3px; }
            QMenu::item:selected { background-color: #0078D7; color: white; }
        """)
        for r in results[:15]:
            plain = r['plain'].replace('\n', ' ').replace('\r', '')
            if len(plain) > 45:
                plain = plain[:45] + '...'
            action = self.results_menu.addAction(
                make_entry_label(plain, r['group'], r['tags'], show_group=True))
            action.setToolTip(r['data'].get('html_content', ''))
            action.setData({'group': r['group'], 'index': r['index']})
            action.triggered.connect(self._on_menu_selected)
        global_pos = self.mapToGlobal(QPoint(0, 0))
        menu_height = self.results_menu.sizeHint().height()
        self.results_menu.popup(QPoint(global_pos.x(), global_pos.y() - menu_height))
        self.results_menu.installEventFilter(self)
        QTimer.singleShot(0, self.search_edit.setFocus)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if obj == self.result_list:
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    item = self.result_list.currentItem()
                    if item:
                        self._send_item(item)
                    return True
            elif obj == self.results_menu:
                if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Return,
                               Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_Tab):
                    self.search_edit.setFocus()
                    QApplication.sendEvent(self.search_edit, event)
                    return True
        return super().eventFilter(obj, event)

    def _on_item_clicked(self, item):
        if item:
            self._send_item(item)

    def _on_menu_selected(self):
        action = self.sender()
        if action:
            data = action.data()
            if data:
                html = action.toolTip()
                if html and self.last_tracked_hwnd:
                    self.parent_app._do_paste_text(html, target_hwnd=self.last_tracked_hwnd)
                self.search_edit.clear()
                if self.results_menu:
                    self.results_menu.close()
                self.search_edit.setFocus()

    def _send_item(self, item):
        idx = item.data(Qt.ItemDataRole.UserRole)
        group = item.data(Qt.ItemDataRole.UserRole + 1)
        entries = self.parent_app.data.get(group, [])
        if 0 <= idx < len(entries):
            html = entries[idx].get('html_content', '')
            if html and self.last_tracked_hwnd:
                self.parent_app._do_paste_text(html, target_hwnd=self.last_tracked_hwnd)
        self.search_edit.clear()
        self.search_edit.setFocus()

    def on_enter_pressed(self):
        if self._orientation == '右侧':
            item = self.result_list.currentItem()
            if item:
                self._send_item(item)
        elif self.results_menu and self.results_menu.isVisible():
            actions = self.results_menu.actions()
            if actions:
                actions[0].trigger()

    def mousePressEvent(self, event: QMouseEvent):
        if self._orientation == '右侧' and event.position().x() < 6:
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_w = self.width()
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._resizing:
            dx = event.globalPosition().toPoint().x() - self._resize_start_x
            new_w = self._resize_start_w - dx
            if 120 <= new_w <= 600:
                self.setMinimumWidth(new_w)
                self.setMaximumWidth(new_w)
                self.resize(new_w, self.height())
                self.updateGeometry()
                if self.parent_app:
                    self.parent_app.settings['dock_width'] = new_w
                    self._dirty_dock_width = new_w
                    self._dock_save_timer.start()
            event.accept()
        elif self._orientation == '右侧' and event.position().x() < 6:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._resizing = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._flush_dock_width()
        super().mouseReleaseEvent(event)

    def _flush_dock_width(self):
        self._dock_save_timer.stop()
        if self._dirty_dock_width is None or not self.parent_app:
            return
        self.parent_app.save_data()
        self._dirty_dock_width = None
