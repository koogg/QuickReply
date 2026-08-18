import shutil
import os
import re
from datetime import datetime, timedelta

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QFileDialog

from config import (
    DATA_FILE, BACKUP_DIR, MEDIA_BASE_DIR, TRASH_DIR,
)
from services.data_store import (
    IMPORT_CONFLICT_APPEND, IMPORT_CONFLICT_REPLACE,
    atomic_write_json, build_document, load_json_document,
    merge_imported_groups, rotate_backups,
)
from services.media_paths import resolve_media_path
from utils import logger


def _ensure_dir(filepath):
    """确保传入文件路径所在目录存在。"""
    d = os.path.dirname(filepath)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def ensure_directory(path):
    """确保目录存在。"""
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


class DataManagerMixin:
    """数据持久化、备份调度、导入导出、文件清理。

    所有方法通过 self 访问主窗口的 data / group_order / settings，
    由 KefuHelperApp 继承混入。
    """

    # ---- 数据加载 / 保存 -----------------------------------------------

    def load_data(self):
        self._data_write_blocked = False
        path = DATA_FILE if os.path.exists(DATA_FILE) else self._legacy_data_file()
        if path and os.path.exists(path):
            try:
                obj = load_json_document(path)
                self.data = obj.get('data', {})
                self.group_order = obj.get('group_order', [])
                self.settings = obj.get('settings', {})
            except Exception as e:
                self._data_write_blocked = True
                QMessageBox.warning(self, '数据加载失败', str(e))
                self.data = {}
                self.group_order = []
                self.settings = {}
        else:
            self.data = {}
            self.group_order = []
            self.settings = {}
        for entries in self.data.values():
            for entry in entries:
                if isinstance(entry, dict) and '_pinyin' in entry:
                    del entry['_pinyin']
        self.refresh_group_list()

    @staticmethod
    def _legacy_data_file():
        for name in ('Data.json', 'date.json'):
            if os.path.exists(name):
                return name
        return None

    def save_data(self):
        if getattr(self, '_data_write_blocked', False):
            QMessageBox.warning(
                self, '数据保存已阻止',
                '原数据文件加载失败。为避免覆盖原文件，请先导入一份有效数据。'
            )
            return False

        _ensure_dir(DATA_FILE)
        try:
            document = build_document(self.data, self.group_order, self.settings)
            atomic_write_json(DATA_FILE, document)
            return True
        except Exception as e:
            QMessageBox.warning(self, '数据保存失败', str(e))
            return False

    # ---- 备份 ---------------------------------------------------------

    def _apply_backup_schedule(self):
        """根据 settings 启停每日定时备份。"""
        if self._backup_timer is not None:
            try:
                self._backup_timer.stop()
                self._backup_timer.deleteLater()
            except Exception:
                pass
            self._backup_timer = None

        if not self.settings.get('backup_enabled', False):
            return

        self._backup_next_time = self._compute_next_backup_time()
        timer = QTimer(self)
        timer.timeout.connect(self._check_scheduled_backup)
        timer.start(60_000)
        self._backup_timer = timer

    def _compute_next_backup_time(self):
        target = self.settings.get('backup_time', '12:00')
        try:
            hh, mm = target.split(':')
            hh, mm = int(hh), int(mm)
        except Exception:
            hh, mm = 12, 0
        now = datetime.now()
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    def _check_scheduled_backup(self):
        nxt = getattr(self, '_backup_next_time', None)
        if nxt is None:
            return
        if datetime.now() < nxt:
            return
        self._do_scheduled_backup()
        self._backup_next_time = self._compute_next_backup_time()

    def _do_scheduled_backup(self):
        if not os.path.exists(DATA_FILE):
            return
        ensure_directory(BACKUP_DIR)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(BACKUP_DIR, f'Date_backup_{timestamp}.json')
        try:
            shutil.copy2(DATA_FILE, backup_path)
            logger.info('定时备份完成: %s', backup_path)
        except Exception as e:
            logger.error('定时备份失败: %s', e)
            return
        keep = int(self.settings.get('backup_keep', 10))
        rotate_backups(BACKUP_DIR, keep)

    # ---- 导入 / 导出 --------------------------------------------------

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '导出数据', '', 'JSON文件 (*.json)')
        if path:
            try:
                shutil.copy2(DATA_FILE, path)
                QMessageBox.information(self, '导出成功', f'数据已导出到 {path}')
            except Exception as e:
                QMessageBox.warning(self, '导出失败', str(e))

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '导入数据', '', 'JSON文件 (*.json)')
        if path:
            try:
                obj = load_json_document(path)
                imported_data = obj.get('data', {})
                imported_order = obj.get('group_order', [])
                conflicts = [
                    name for name in imported_data if name in self.data
                ]
                conflict_strategy = None
                if conflicts:
                    conflict_strategy = self._ask_import_conflict_strategy(
                        conflicts
                    )
                    if conflict_strategy is None:
                        return

                previous_data = self.data
                previous_group_order = self.group_order
                previous_settings = self.settings
                previous_write_blocked = getattr(
                    self, '_data_write_blocked', False
                )
                new_settings = dict(self.settings)
                self.data, self.group_order, _ = merge_imported_groups(
                    self.data,
                    self.group_order,
                    imported_data,
                    imported_order,
                    conflict_strategy,
                )
                imported_settings = obj.get('settings', {})
                runtime_keys = {
                    'trigger_type', 'trigger_key', 'double_key',
                    'dock_enabled', 'dock_position', 'dock_width', 'dock_hotkey',
                    'floating_search_enabled', 'startup_enabled',
                    'backup_enabled', 'backup_time', 'backup_keep',
                    'window_geometry',
                }
                for k, v in imported_settings.items():
                    if k not in runtime_keys:
                        new_settings[k] = v
                self.settings = new_settings
                self._data_write_blocked = False
                if not self.save_data():
                    self.data = previous_data
                    self.group_order = previous_group_order
                    self.settings = previous_settings
                    self._data_write_blocked = previous_write_blocked
                    return
                self.refresh_group_list()
                self.refresh_entry_list()
                new_group_count = len(imported_data) - len(conflicts)
                if conflicts:
                    action = (
                        '替换' if conflict_strategy == IMPORT_CONFLICT_REPLACE
                        else '追加'
                    )
                    detail = (
                        f'新增 {new_group_count} 个分组，'
                        f'{action} {len(conflicts)} 个同名分组。'
                    )
                else:
                    detail = f'已新增 {new_group_count} 个分组。'
                QMessageBox.information(
                    self, '导入成功', f'数据已导入。{detail}'
                )
            except Exception as e:
                QMessageBox.warning(self, '导入失败', str(e))

    def _ask_import_conflict_strategy(self, conflicts):
        names = '\n'.join(f'• {name}' for name in conflicts[:10])
        if len(conflicts) > 10:
            names += f'\n• ……等共 {len(conflicts)} 个分组'

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle('发现同名分组')
        dialog.setText(
            f'导入文件中有 {len(conflicts)} 个同名分组：\n\n{names}\n\n'
            '请选择这些分组的处理方式。'
        )
        replace_button = dialog.addButton(
            '替换同名分组', QMessageBox.ButtonRole.AcceptRole
        )
        append_button = dialog.addButton(
            '追加到同名分组', QMessageBox.ButtonRole.ActionRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() is replace_button:
            return IMPORT_CONFLICT_REPLACE
        if dialog.clickedButton() is append_button:
            return IMPORT_CONFLICT_APPEND
        return None

    # ---- 文件清理 -----------------------------------------------------

    def _clean_unused_files(self):
        base = os.path.abspath(MEDIA_BASE_DIR)
        images_dir = os.path.join(base, 'images')
        files_dir = os.path.join(base, 'files')

        referenced = set()
        for group in self.data.values():
            for entry in group:
                html = entry.get('html_content', '')
                for m in re.finditer(r'(?:src|href)=["\']([^"\']+)["\']', html):
                    path = resolve_media_path(base, m.group(1), must_exist=True)
                    if path:
                        referenced.add(path)

        unused = []
        total_size = 0
        for subdir in (images_dir, files_dir):
            if not os.path.isdir(subdir):
                continue
            for fname in os.listdir(subdir):
                fpath = os.path.join(subdir, fname)
                if not os.path.isfile(fpath):
                    continue
                if fpath not in referenced:
                    size = os.path.getsize(fpath)
                    total_size += size
                    unused.append(fpath)

        if not unused:
            QMessageBox.information(self, '清理完成', '没有发现未使用的文件。')
            return

        msg = f'发现 {len(unused)} 个未使用的文件，共 {self._format_size(total_size)}，是否清理？\n\n'
        msg += f'(清理后文件将移到 "{TRASH_DIR}/" 便于撤销，可自行删除该目录彻底回收)\n\n'
        for p in unused[:20]:
            msg += f'  {os.path.relpath(p, base)}\n'
        if len(unused) > 20:
            msg += f'  ... 等共 {len(unused)} 个文件\n'

        confirm = QMessageBox.question(
            self, '清理文件', msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            trash_base = os.path.abspath(TRASH_DIR)
            ensure_directory(trash_base)
            cleaned = 0
            for p in unused:
                try:
                    rel = os.path.relpath(p, base)
                    dest_dir = os.path.dirname(os.path.join(trash_base, rel))
                    os.makedirs(dest_dir, exist_ok=True)
                    dest = os.path.join(trash_base, rel)
                    if os.path.exists(dest):
                        os.remove(dest)
                    shutil.move(p, dest)
                    cleaned += 1
                except Exception as e:
                    logger.error('移动到回收区失败: %s -> %r (%s)', p, TRASH_DIR, e)
            QMessageBox.information(self, '清理完成',
                                    f'已清理 {cleaned} 个文件到 "{TRASH_DIR}/"，'
                                    f'释放 {self._format_size(total_size)} 空间。')

    @staticmethod
    def _format_size(size):
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'
