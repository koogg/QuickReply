import json
import os
import sys
import winreg

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QLabel, QInputDialog,
    QMessageBox, QSplitter, QSystemTrayIcon, QMenu, QFileDialog,
    QLineEdit, QApplication, QAbstractItemView
)
from PyQt6.QtGui import QAction, QFont, QMouseEvent

from config import (
    DATA_FILE, MENU_PREVIEW_LENGTH, LIST_PREVIEW_LENGTH,
    MEDIA_BASE_DIR,
)
from utils import (
    get_default_icon, PINYIN_AVAILABLE, get_pinyin_variants,
    extract_preview, entry_matches, make_entry_label,
    invalidate_entry_pinyin_cache, logger
)
from listeners.hotkey_listener import HotKeyListenerThread
from widgets.editor import RichHuashuEditDialog
from widgets.quick_select import QuickSelectPopup
from widgets.search_widget import FloatingSearchWidget
from widgets.title_bar import CustomTitleBar
from widgets.settings_dialog import SettingsDialog
from widgets.data_manager import DataManagerMixin
from widgets.paste_controller import PasteControllerMixin


class KefuHelperApp(QMainWindow, DataManagerMixin, PasteControllerMixin):
    GROUP_ROLE = Qt.ItemDataRole.UserRole + 1       # 保存每个分组项对应的真实组名
    ENTRY_GROUP_ROLE = Qt.ItemDataRole.UserRole + 2  # 话术项所属分组（搜索/过滤时使用）

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint)
        self.data = {}
        self.group_order = []
        self.settings = {}
        self.hotkey_listener = None
        self.dock_hotkey_listener = None
        self.quick_popup = None
        self.floating_search = None
        self._paste_target_hwnd = None
        self._paste_target_focus_hwnd = None
        self._paste_sequence_id = 0
        self._paste_operations = []
        self._paste_operation_index = 0
        self._last_geometry_str = ''
        self._backup_timer = None

        self.init_ui()
        self.load_data()
        self._apply_theme()
        self._restore_geometry()
        self._setup_hotkey()
        self._setup_tray()
        self._apply_startup()
        self._apply_float_search()
        self._apply_backup_schedule()

    def init_ui(self):
        self.setWindowTitle('快捷回复')
        self.setMinimumSize(680, 540)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        main_layout.addWidget(self.title_bar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 6, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        content_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self.on_group_selected)
        self.group_list.itemDoubleClicked.connect(self.rename_group)
        self.group_list.setAcceptDrops(True)
        self.group_list.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.group_list.dropEvent = self._group_drop_event
        left_layout.addWidget(self.group_list)

        group_btn_layout = QHBoxLayout()
        group_btn_layout.setSpacing(4)
        self.add_group_btn = QPushButton('＋')
        self.add_group_btn.setFixedSize(36, 28)
        self.add_group_btn.setFont(QFont('Microsoft YaHei UI', 11, QFont.Weight.Bold))
        self.add_group_btn.clicked.connect(self.add_group)
        self.del_group_btn = QPushButton('－')
        self.del_group_btn.setFixedSize(36, 28)
        self.del_group_btn.setFont(QFont('Microsoft YaHei UI', 11, QFont.Weight.Bold))
        self.del_group_btn.clicked.connect(self.delete_group)
        self.group_up_btn = QPushButton('▲')
        self.group_up_btn.setFixedSize(36, 28)
        self.group_up_btn.setFont(QFont('Microsoft YaHei UI', 9))
        self.group_up_btn.clicked.connect(self.move_group_up)
        self.group_down_btn = QPushButton('▼')
        self.group_down_btn.setFixedSize(36, 28)
        self.group_down_btn.setFont(QFont('Microsoft YaHei UI', 9))
        self.group_down_btn.clicked.connect(self.move_group_down)
        group_btn_layout.addWidget(self.add_group_btn)
        group_btn_layout.addWidget(self.del_group_btn)
        group_btn_layout.addWidget(self.group_up_btn)
        group_btn_layout.addWidget(self.group_down_btn)
        group_btn_layout.addStretch()
        left_layout.addLayout(group_btn_layout)
        left_panel.setMinimumWidth(group_btn_layout.minimumSize().width())

        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('搜索话术...')
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        right_layout.addWidget(self.search_edit)

        self.entry_list = QListWidget()
        self.entry_list.currentRowChanged.connect(self.on_entry_selected)
        self.entry_list.itemDoubleClicked.connect(self.edit_entry)
        self.entry_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.entry_list.setDragEnabled(True)
        self.entry_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        right_layout.addWidget(self.entry_list)

        entry_btn_layout = QHBoxLayout()
        entry_btn_layout.setSpacing(4)
        self.add_entry_btn = QPushButton('＋')
        self.add_entry_btn.setFixedSize(36, 28)
        self.add_entry_btn.setFont(QFont('Microsoft YaHei UI', 11, QFont.Weight.Bold))
        self.add_entry_btn.setToolTip('新建话术')
        self.add_entry_btn.clicked.connect(self.add_entry)
        self.del_entry_btn = QPushButton('－')
        self.del_entry_btn.setFixedSize(36, 28)
        self.del_entry_btn.setFont(QFont('Microsoft YaHei UI', 11, QFont.Weight.Bold))
        self.del_entry_btn.setToolTip('删除选中')
        self.del_entry_btn.clicked.connect(self.delete_selected_entries)
        self.move_up_btn = QPushButton('▲')
        self.move_up_btn.setFixedSize(36, 28)
        self.move_up_btn.setFont(QFont('Microsoft YaHei UI', 9))
        self.move_up_btn.setToolTip('话术上移')
        self.move_up_btn.clicked.connect(self.move_entry_up)
        self.move_down_btn = QPushButton('▼')
        self.move_down_btn.setFixedSize(36, 28)
        self.move_down_btn.setFont(QFont('Microsoft YaHei UI', 9))
        self.move_down_btn.setToolTip('话术下移')
        self.move_down_btn.clicked.connect(self.move_entry_down)
        entry_btn_layout.addWidget(self.add_entry_btn)
        entry_btn_layout.addWidget(self.del_entry_btn)
        entry_btn_layout.addWidget(self.move_up_btn)
        entry_btn_layout.addWidget(self.move_down_btn)
        entry_btn_layout.addStretch()
        # 设置入口（含导出/导入/清理）
        self.settings_btn = QPushButton('⚙')
        self.settings_btn.setFixedSize(56, 28)
        self.settings_btn.setFont(QFont('Microsoft YaHei UI', 12))
        self.settings_btn.setToolTip('设置')
        self.settings_btn.clicked.connect(self.open_settings)
        entry_btn_layout.addWidget(self.settings_btn)
        right_layout.addLayout(entry_btn_layout)
        right_panel.setMinimumWidth(entry_btn_layout.minimumSize().width())

        splitter.addWidget(right_panel)
        self.main_splitter = splitter
        self.left_panel = left_panel
        self.right_panel = right_panel
        splitter.setSizes([200, 450])

        main_layout.addWidget(content)

    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget { font-family: 'Microsoft YaHei UI'; }
            CustomTitleBar { background-color: #1A3A5C; }
            CustomTitleBar QLabel { color: #D0E0F0; }
            CustomTitleBar QPushButton {
                background: transparent; color: white; border: none;
                font-size: 13pt; padding: 0;
            }
            CustomTitleBar QPushButton:hover { background-color: #4A90D9; border-radius: 3px; }
            QMainWindow { background-color: #E8F2FC; }
            QLabel { color: #333; font-size: 10pt; }
            QPushButton {
                background-color: #4A90D9;
                color: white;
                border: none;
                padding: 5px 14px;
                border-radius: 4px;
                font-size: 10pt;
            }
            QPushButton:hover { background-color: #357ABD; }
            QPushButton:pressed { background-color: #2A5F9E; }
            QPushButton:checked { background-color: #2A5F9E; }
            QPushButton:disabled { background-color: #B0C4DE; }
            QLineEdit {
                padding: 5px 8px;
                border: 1px solid #B0C4DE;
                border-radius: 4px;
                background: white;
                font-size: 10pt;
            }
            QLineEdit:focus { border-color: #4A90D9; }
            QListWidget {
                border: 1px solid #C8D8E8;
                border-radius: 4px;
                background: white;
                font-size: 10pt;
                alternate-background-color: #F0F6FC;
                outline: none;
            }
            QListWidget::item { padding: 5px 8px; border-radius: 2px; outline: none; border: none; }
            QListWidget::item:selected { background-color: #4A90D9; color: white; outline: none; border: none; }
            QListWidget::item:hover { background-color: #D6E8FA; outline: none; border: none; }
            QListWidget::item:focus { outline: none; border: none; }
            QSplitter::handle { background-color: #C8D8E8; width: 2px; }
            QComboBox {
                padding: 4px 8px;
                border: 1px solid #B0C4DE;
                border-radius: 4px;
                background: white;
                font-size: 10pt;
            }
            QComboBox:focus { border-color: #4A90D9; }
            QComboBox QAbstractItemView {
                selection-background-color: #4A90D9;
                selection-color: white;
            }
            QCheckBox { font-size: 10pt; spacing: 6px; }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border: 1px solid #B0C4DE;
                border-radius: 3px;
                background: white;
            }
            QCheckBox::indicator:checked { background-color: #4A90D9; }
        """)

    def _stop_listener(self, listener):
        if listener is None:
            return None
        try:
            listener.stop_listener()
            listener.wait(1000)
            listener.deleteLater()
        except Exception as e:
            logger.error('停止监听器出错: %s', e)
        return None

    def _setup_hotkey(self):
        self.hotkey_listener = self._stop_listener(self.hotkey_listener)
        self.dock_hotkey_listener = self._stop_listener(self.dock_hotkey_listener)

        self.hotkey_listener = HotKeyListenerThread(self.settings, self)
        self.hotkey_listener.hotkey_triggered.connect(self.on_hotkey_triggered)
        self.hotkey_listener.start()

        dock_hotkey = self.settings.get('dock_hotkey', '')
        if dock_hotkey:
            dock_settings = self.settings.copy()
            dock_settings['trigger_type'] = 'keyboard'
            dock_settings['trigger_key'] = dock_hotkey
            self.dock_hotkey_listener = HotKeyListenerThread(dock_settings, self)
            self.dock_hotkey_listener.hotkey_triggered.connect(self._toggle_dock_hotkey)
            self.dock_hotkey_listener.start()

    def on_hotkey_triggered(self):
        if not self.quick_popup:
            self.quick_popup = QuickSelectPopup(self)
        self.quick_popup.show_at_cursor()

    def _toggle_dock_hotkey(self):
        enabled = not self.settings.get('dock_enabled', False)
        self.settings['dock_enabled'] = enabled
        self.save_data()
        self._apply_float_search()

    def _apply_float_search(self):
        enabled = self.settings.get('dock_enabled', False) and \
            self.settings.get('floating_search_enabled', True)
        if enabled:
            if not self.floating_search:
                self.floating_search = FloatingSearchWidget(self)
            self.floating_search.set_orientation(
                self.settings.get('dock_position', '底部'))
            self.floating_search.show()
            self.floating_search.raise_()
        else:
            if self.floating_search:
                self.floating_search.hide()

    def _setup_tray(self):
        icon = get_default_icon()
        self.tray_icon = QSystemTrayIcon(icon, self)
        tray_menu = QMenu()
        show_action = QAction('显示窗口', self)
        show_action.triggered.connect(self.show_and_raise)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        quit_action = QAction('退出程序', self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def show_and_raise(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_and_raise()

    def quit_app(self):
        self.hotkey_listener = self._stop_listener(self.hotkey_listener)
        self.dock_hotkey_listener = self._stop_listener(self.dock_hotkey_listener)
        QApplication.quit()

    def closeEvent(self, event):
        self.save_data()
        self._save_geometry()
        self.hide()
        event.ignore()

    def _geometry_str(self):
        geo = self.geometry()
        return f'{geo.x()},{geo.y()},{geo.width()},{geo.height()}'

    def _save_geometry(self):
        geo_str = self._geometry_str()
        if geo_str == self.settings.get('window_geometry') or geo_str == self._last_geometry_str:
            self._last_geometry_str = geo_str
            return
        self.settings['window_geometry'] = geo_str
        self._last_geometry_str = geo_str
        self.save_data()

    def _restore_geometry(self):
        geo_str = self.settings.get('window_geometry', '')
        self._last_geometry_str = geo_str
        if geo_str:
            try:
                parts = [int(x) for x in geo_str.split(',')]
                if len(parts) == 4:
                    from PyQt6.QtCore import QRect
                    self.setGeometry(QRect(parts[0], parts[1], parts[2], parts[3]))
                    self._last_geometry_str = self._geometry_str()
            except Exception:
                pass

    def refresh_group_list(self):
        current_group = self.get_current_group()
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for g in self.group_order:
            if g in self.data:
                count = len(self.data[g])
                item = QListWidgetItem(f'{g} ({count})')
                item.setData(self.GROUP_ROLE, g)
                self.group_list.addItem(item)
        self.group_list.blockSignals(False)
        if current_group:
            for i in range(self.group_list.count()):
                if self.group_list.item(i).data(self.GROUP_ROLE) == current_group:
                    self.group_list.setCurrentRow(i)
                    break

    def get_current_group(self):
        item = self.group_list.currentItem()
        if item:
            return item.data(self.GROUP_ROLE)
        return None

    def on_group_selected(self):
        self.refresh_entry_list(self.search_edit.text().strip().lower())

    def refresh_entry_list(self, filter_text=''):
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        if filter_text:
            for group in self.group_order:
                if group not in self.data:
                    continue
                for i, entry in enumerate(self.data[group]):
                    preview = extract_preview(entry.get('html_content', ''),
                                             LIST_PREVIEW_LENGTH)
                    if not entry_matches(entry, filter_text, plain=preview):
                        continue
                    tags = entry.get('tags', [])
                    item = QListWidgetItem(make_entry_label(preview, group, tags,
                                                            show_group=True))
                    item.setData(Qt.ItemDataRole.UserRole, i)
                    item.setData(self.ENTRY_GROUP_ROLE, group)
                    item.setToolTip(entry.get('html_content', ''))
                    self.entry_list.addItem(item)
        else:
            group = self.get_current_group()
            if group and group in self.data:
                for i, entry in enumerate(self.data[group]):
                    html = entry.get('html_content', '')
                    tags = entry.get('tags', [])
                    preview = extract_preview(html, LIST_PREVIEW_LENGTH)
                    item = QListWidgetItem(make_entry_label(preview, '', tags))
                    item.setData(Qt.ItemDataRole.UserRole, i)
                    item.setData(self.ENTRY_GROUP_ROLE, group)
                    item.setToolTip(html)
                    self.entry_list.addItem(item)
        self.entry_list.blockSignals(False)

    def on_entry_selected(self):
        pass

    def _on_search_text_changed(self, text):
        self.refresh_entry_list(text.strip().lower())

    def add_group(self):
        name, ok = QInputDialog.getText(self, '添加分组', '分组名称:')
        if ok and name.strip():
            name = name.strip()
            if name in self.data:
                QMessageBox.warning(self, '提示', '分组已存在')
                return
            self.data[name] = []
            self.group_order.append(name)
            self.save_data()
            self.refresh_group_list()
            for i in range(self.group_list.count()):
                if self.group_list.item(i).data(self.GROUP_ROLE) == name:
                    self.group_list.setCurrentRow(i)
                    break

    def rename_group(self):
        old_name = self.get_current_group()
        if not old_name:
            return
        name, ok = QInputDialog.getText(self, '重命名分组', '新名称:', text=old_name)
        if ok and name.strip():
            name = name.strip()
            if name != old_name and name in self.data:
                QMessageBox.warning(self, '提示', '分组已存在')
                return
            self.data[name] = self.data.pop(old_name)
            self.group_order = [name if g == old_name else g for g in self.group_order]
            self.save_data()
            self.refresh_group_list()

    def delete_group(self):
        group = self.get_current_group()
        if not group:
            return
        confirm = QMessageBox.question(
            self, '确认删除', f'确定要删除分组 "{group}" 及其所有话术吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            del self.data[group]
            self.group_order.remove(group)
            self.save_data()
            self.refresh_group_list()

    def move_group_up(self):
        group = self.get_current_group()
        if not group:
            return
        idx = self.group_order.index(group)
        if idx > 0:
            self.group_order[idx], self.group_order[idx - 1] = self.group_order[idx - 1], self.group_order[idx]
            self.save_data()
            self.refresh_group_list()
            self.group_list.setCurrentRow(idx - 1)

    def move_group_down(self):
        group = self.get_current_group()
        if not group:
            return
        idx = self.group_order.index(group)
        if idx < len(self.group_order) - 1:
            self.group_order[idx], self.group_order[idx + 1] = self.group_order[idx + 1], self.group_order[idx]
            self.save_data()
            self.refresh_group_list()
            self.group_list.setCurrentRow(idx + 1)

    def add_entry(self):
        group = self.get_current_group()
        if not group:
            QMessageBox.warning(self, '提示', '请先选择分组')
            return
        dialog = RichHuashuEditDialog(parent=self)
        if dialog.exec() == RichHuashuEditDialog.DialogCode.Accepted:
            html = dialog.get_html_content()
            tags = dialog.get_tags()
            self.data[group].append({
                'html_content': html,
                'tags': tags
            })
            self.save_data()
            self.refresh_group_list()
            self.refresh_entry_list()
            idx = len(self.data[group]) - 1
            self.entry_list.setCurrentRow(idx)

    def _get_entry_group(self, item):
        if not item:
            return None
        group = item.data(self.ENTRY_GROUP_ROLE)
        if not group:
            group = self.get_current_group()
        return group

    def edit_entry(self):
        item = self.entry_list.currentItem()
        if not item:
            QMessageBox.warning(self, '提示', '请先选择话术')
            return
        group = self._get_entry_group(item)
        if not group or group not in self.data:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        entries = self.data.get(group, [])
        if idx < 0 or idx >= len(entries):
            return
        entry = entries[idx]
        dialog = RichHuashuEditDialog(
            html_content=entry.get('html_content', ''),
            tags=entry.get('tags', []),
            parent=self
        )
        if dialog.exec() == RichHuashuEditDialog.DialogCode.Accepted:
            entries[idx] = {
                'html_content': dialog.get_html_content(),
                'tags': dialog.get_tags()
            }
            invalidate_entry_pinyin_cache(entries[idx])
            self.save_data()
            self.refresh_group_list()
            self.refresh_entry_list(self.search_edit.text().strip().lower())

    def delete_selected_entries(self):
        items = self.entry_list.selectedItems()
        if not items:
            return
        count = len(items)
        msg = f'确定要删除选中的 {count} 个话术吗？'
        if count == 1:
            msg = '确定要删除该话术吗？'
        confirm = QMessageBox.question(
            self, '确认删除', msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        deletions = {}
        for item in items:
            group = self._get_entry_group(item)
            if not group:
                continue
            idx = item.data(Qt.ItemDataRole.UserRole)
            if group not in deletions:
                deletions[group] = []
            deletions[group].append(idx)
        for group, indices in deletions.items():
            entries = self.data.get(group, [])
            for idx in sorted(indices, reverse=True):
                if 0 <= idx < len(entries):
                    entries.pop(idx)
        self.save_data()
        self.refresh_group_list()
        self.refresh_entry_list(self.search_edit.text().strip().lower())

    def _group_drop_event(self, event):
        if event.source() == self.entry_list:
            target_item = self.group_list.itemAt(event.position().toPoint())
            if not target_item:
                event.ignore()
                return
            target_group = target_item.data(self.GROUP_ROLE)
            if not target_group or target_group not in self.data:
                event.ignore()
                return
            # 多选拖拽时按“源组+源索引”分组收集后逆序 pop，避免索引错位
            pending = {}
            for item in self.entry_list.selectedItems():
                source_group = self._get_entry_group(item)
                if not source_group or source_group == target_group:
                    continue
                idx = item.data(Qt.ItemDataRole.UserRole)
                pending.setdefault(source_group, []).append(idx)
            changed = False
            for source_group, indices in pending.items():
                entries = self.data.get(source_group, [])
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(entries):
                        entry_data = entries.pop(idx)
                        invalidate_entry_pinyin_cache(entry_data)
                        self.data[target_group].append(entry_data)
                        changed = True
            if changed:
                self.save_data()
                self.refresh_group_list()
                self.on_group_selected()
            event.accept()
        else:
            event.ignore()

    def move_entry_up(self):
        item = self.entry_list.currentItem()
        if not item:
            return
        group = self._get_entry_group(item)
        if not group or group not in self.data:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        entries = self.data.get(group, [])
        if idx > 0:
            entries[idx], entries[idx - 1] = entries[idx - 1], entries[idx]
            self.save_data()
            filter_text = self.search_edit.text().strip().lower()
            self.refresh_entry_list(filter_text)
            if not filter_text:
                self.entry_list.setCurrentRow(idx - 1)

    def move_entry_down(self):
        item = self.entry_list.currentItem()
        if not item:
            return
        group = self._get_entry_group(item)
        if not group or group not in self.data:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        entries = self.data.get(group, [])
        if idx < len(entries) - 1:
            entries[idx], entries[idx + 1] = entries[idx + 1], entries[idx]
            self.save_data()
            filter_text = self.search_edit.text().strip().lower()
            self.refresh_entry_list(filter_text)
            if not filter_text:
                self.entry_list.setCurrentRow(idx + 1)

    def open_settings(self):
        old_settings = dict(self.settings)
        dialog = SettingsDialog(self.settings, self, parent_app=self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.settings = dialog.get_settings()
            self.save_data()
            hotkey_keys = ('trigger_type', 'trigger_key', 'double_key')
            dock_hotkey_keys = ('dock_hotkey',)
            float_keys = ('dock_enabled', 'dock_position', 'dock_width',
                          'floating_search_enabled')
            if any(old_settings.get(k) != self.settings.get(k) for k in hotkey_keys) or \
               any(old_settings.get(k) != self.settings.get(k) for k in dock_hotkey_keys):
                self._setup_hotkey()
            if any(old_settings.get(k) != self.settings.get(k) for k in float_keys):
                self._apply_float_search()
            if old_settings.get('startup_enabled') != self.settings.get('startup_enabled'):
                self._apply_startup()
            if any(old_settings.get(k) != self.settings.get(k)
                    for k in ('backup_enabled', 'backup_time', 'backup_keep')):
                self._apply_backup_schedule()

    def _apply_startup(self):
        enabled = self.settings.get('startup_enabled', False)
        app_name = 'QuickReply'
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        try:
            if enabled:
                if getattr(sys, 'frozen', False):
                    target = f'"{sys.executable}"'
                else:
                    script = os.path.abspath(sys.argv[0])
                    target = f'"{sys.executable}" "{script}"'
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, target)
                winreg.CloseKey(key)
            else:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
                winreg.CloseKey(key)
        except Exception as e:
            logger.error('开机启动设置失败: %s', e)
