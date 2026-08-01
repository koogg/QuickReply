from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QDialogButtonBox, QWidget, QSpinBox, QGroupBox, QFormLayout,
    QPushButton, QTimeEdit
)
from PyQt6.QtGui import QFont

from widgets.hotkey_edit import HotkeyLineEdit


# ---- 设置项小工具 ----------------------------------------------------------

def _section(title):
    """构造一个带标题 + 阴影样式的分组容器。"""
    box = QGroupBox(title)
    box.setStyleSheet("""
        QGroupBox {
            border: 1px solid #C8D8E8;
            border-radius: 6px;
            margin-top: 10px;
            padding: 8px 8px 6px 8px;
            background-color: #F4F9FE;
            font-weight: bold;
            color: #2A5F9E;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
            background: transparent;
        }
    """)
    inner = QVBoxLayout(box)
    inner.setSpacing(6)
    return box, inner


class BackupSection(QGroupBox):
    """备份设置区，独立成块方便复用。"""
    def __init__(self, settings):
        super().__init__('定时备份')
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #C8D8E8; border-radius: 6px;
                margin-top: 10px; padding: 8px 8px 6px 8px;
                background-color: #F4F9FE;
                font-weight: bold; color: #2A5F9E;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 8px; padding: 0 4px; background: transparent;
            }
        """)
        form = QFormLayout(self)
        form.setSpacing(6)

        self.enabled_check = QCheckBox('启用每日定时备份')
        self.enabled_check.setChecked(settings.get('backup_enabled', False))
        form.addRow(self.enabled_check)

        row_time = QHBoxLayout()
        row_time.addWidget(QLabel('备份时间:'))
        from PyQt6.QtCore import QTime
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat('HH:mm')
        t = settings.get('backup_time', '12:00')
        try:
            hh, mm = t.split(':')
            self.time_edit.setTime(QTime(int(hh), int(mm)))
        except Exception:
            self.time_edit.setTime(QTime(12, 0))
        row_time.addWidget(self.time_edit)
        row_time.addStretch()
        form.addRow(row_time)

        row_keep = QHBoxLayout()
        row_keep.addWidget(QLabel('保留份数:'))
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(1, 100)
        self.keep_spin.setValue(settings.get('backup_keep', 10))
        self.keep_spin.setSuffix(' 份')
        row_keep.addWidget(self.keep_spin)
        row_keep.addStretch()
        form.addRow(row_keep)

    def values(self):
        return {
            'backup_enabled': self.enabled_check.isChecked(),
            'backup_time': self.time_edit.time().toString('HH:mm'),
            'backup_keep': self.keep_spin.value(),
        }


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None, *, parent_app=None):
        super().__init__(parent)
        self.setWindowTitle('设置')
        self.setMinimumWidth(400)
        self.settings = settings.copy() if settings else {}
        self.parent_app = parent_app

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ---- 触发方式 -----------------------------------------------------
        box, inner = _section('触发方式')
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(['鼠标中键', '自定义热键', '双击按键'])
        trigger_map = {'mouse': '鼠标中键', 'keyboard': '自定义热键', 'double_press': '双击按键'}
        raw = self.settings.get('trigger_type', 'double_press')
        self.trigger_combo.setCurrentText(trigger_map.get(raw, '双击按键'))
        self.trigger_combo.currentTextChanged.connect(self._on_trigger_type_changed)
        inner.addWidget(self.trigger_combo)

        self.mouse_info = QLabel('  呼出方式：鼠标中键点击')
        self.mouse_info.setStyleSheet('color: #666; font-size: 9pt;')
        inner.addWidget(self.mouse_info)

        self.key_widget = QWidget()
        key_layout = QHBoxLayout(self.key_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(QLabel('热键组合:'))
        self.key_edit = HotkeyLineEdit()
        self.key_edit.setText(self.settings.get('trigger_key', ''))
        key_layout.addWidget(self.key_edit)
        inner.addWidget(self.key_widget)

        self.double_key_widget = QWidget()
        dk_layout = QHBoxLayout(self.double_key_widget)
        dk_layout.setContentsMargins(0, 0, 0, 0)
        dk_layout.addWidget(QLabel('双击按键:'))
        self.double_key_combo = QComboBox()
        self.double_key_combo.addItems(['左Ctrl', '右Ctrl', '左Alt', '右Alt', '左Shift', '右Shift'])
        dk_map = {'<ctrl>': '左Ctrl', '<ctrl_r>': '右Ctrl', '<alt>': '左Alt',
                  '<alt_r>': '右Alt', '<shift>': '左Shift', '<shift_r>': '右Shift'}
        self.double_key_combo.setCurrentText(dk_map.get(self.settings.get('double_key', '<ctrl_r>'), '右Ctrl'))
        dk_layout.addWidget(self.double_key_combo)
        inner.addWidget(self.double_key_widget)
        layout.addWidget(box)

        # ---- 吸附设置 -----------------------------------------------------
        box, inner = _section('吸附设置')
        self.dock_enabled_check = QCheckBox('启用吸附模式')
        self.dock_enabled_check.setChecked(self.settings.get('dock_enabled', False))
        inner.addWidget(self.dock_enabled_check)

        # 吸附位置 + 侧边宽度 同一行（仅"右侧"才显示宽度）
        pos_width_row = QHBoxLayout()
        pos_width_row.addWidget(QLabel('吸附位置:'))
        self.dock_pos_combo = QComboBox()
        self.dock_pos_combo.addItems(['底部', '右侧'])
        self.dock_pos_combo.setCurrentText(self.settings.get('dock_position', '底部'))
        self.dock_pos_combo.currentTextChanged.connect(self._on_dock_pos_changed)
        pos_width_row.addWidget(self.dock_pos_combo)
        pos_width_row.addSpacing(12)
        self.dock_width_label = QLabel('侧边宽度:')
        pos_width_row.addWidget(self.dock_width_label)
        self.dock_width_spin = QSpinBox()
        self.dock_width_spin.setRange(120, 600)
        self.dock_width_spin.setValue(self.settings.get('dock_width', 260))
        self.dock_width_spin.setSuffix(' px')
        pos_width_row.addWidget(self.dock_width_spin)
        pos_width_row.addStretch()
        inner.addLayout(pos_width_row)

        dock_key_layout = QHBoxLayout()
        dock_key_layout.addWidget(QLabel('吸附快捷键:'))
        self.dock_key_edit = HotkeyLineEdit()
        self.dock_key_edit.setText(self.settings.get('dock_hotkey', ''))
        self.dock_key_edit.setPlaceholderText('可选')
        dock_key_layout.addWidget(self.dock_key_edit)
        inner.addLayout(dock_key_layout)
        layout.addWidget(box)

        # ---- 通用 -----------------------------------------------------
        box, inner = _section('通用')
        self.search_check = QCheckBox('全局搜索窗口跟随焦点')
        self.search_check.setChecked(self.settings.get('floating_search_enabled', True))
        inner.addWidget(self.search_check)

        self.startup_check = QCheckBox('开机自动启动')
        self.startup_check.setChecked(self.settings.get('startup_enabled', False))
        inner.addWidget(self.startup_check)
        layout.addWidget(box)

        # ---- 定时备份 -----------------------------------------------------
        self.backup_section = BackupSection(self.settings)
        layout.addWidget(self.backup_section)

        # ---- 数据管理（原导出/导入/清理） --------------------------------
        box, inner = _section('数据管理')
        row = QHBoxLayout()
        row.setSpacing(6)
        self.export_btn = QPushButton('导出数据')
        self.export_btn.clicked.connect(self._do_export)
        row.addWidget(self.export_btn)
        self.import_btn = QPushButton('导入数据')
        self.import_btn.clicked.connect(self._do_import)
        row.addWidget(self.import_btn)
        self.clean_btn = QPushButton('清理未用文件')
        self.clean_btn.clicked.connect(self._do_clean)
        row.addWidget(self.clean_btn)
        row.addStretch()
        inner.addLayout(row)
        layout.addWidget(box)

        layout.addStretch()

        button_box = QDialogButtonBox()
        button_box.addButton('确定', QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._on_trigger_type_changed(self.trigger_combo.currentText())
        self._on_dock_pos_changed(self.dock_pos_combo.currentText())

    # ---- 数据管理按钮回调（转调主窗口） -----------------------------

    def _do_export(self):
        if self.parent_app:
            self.parent_app.export_data()

    def _do_import(self):
        if self.parent_app:
            self.parent_app.import_data()

    def _do_clean(self):
        if self.parent_app:
            self.parent_app._clean_unused_files()

    # ---- 视图联动 -----------------------------------------------------

    def _on_dock_pos_changed(self, pos):
        show_width = (pos == '右侧')
        self.dock_width_label.setVisible(show_width)
        self.dock_width_spin.setVisible(show_width)

    def _on_trigger_type_changed(self, trigger_type):
        self.key_widget.setVisible(trigger_type == '自定义热键')
        self.double_key_widget.setVisible(trigger_type == '双击按键')
        self.mouse_info.setVisible(trigger_type == '鼠标中键')

    def _validate_and_accept(self):
        # 热键留空时靠 placeholder 提示，不强制拦截
        self.accept()

    def get_settings(self):
        dk_map = {'左Ctrl': '<ctrl>', '右Ctrl': '<ctrl_r>', '左Alt': '<alt>',
                  '右Alt': '<alt_r>', '左Shift': '<shift>', '右Shift': '<shift_r>'}
        trigger_map = {'鼠标中键': 'mouse', '自定义热键': 'keyboard', '双击按键': 'double_press'}
        result = {
            'trigger_type': trigger_map[self.trigger_combo.currentText()],
            'trigger_key': self.key_edit.text().strip(),
            'double_key': dk_map[self.double_key_combo.currentText()],
            'floating_search_enabled': self.search_check.isChecked(),
            'startup_enabled': self.startup_check.isChecked(),
            'dock_hotkey': self.dock_key_edit.text().strip(),
            'dock_position': self.dock_pos_combo.currentText(),
            'dock_width': self.dock_width_spin.value(),
            'dock_enabled': self.dock_enabled_check.isChecked(),
        }
        result.update(self.backup_section.values())
        return result