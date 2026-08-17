import os
import re
import ctypes as _ctypes
import time

from PyQt6.QtCore import QTimer, QMimeData, QUrl
from PyQt6.QtGui import QAction, QTextDocumentFragment
from PyQt6.QtWidgets import QApplication

from config import (
    MEDIA_BASE_DIR, PASTE_FILE_DELAY_MS, PASTE_TEXT_DELAY_MS,
    MENU_PREVIEW_LENGTH,
)
from services.media_paths import resolve_media_path
from services.window_activation import (
    activate_window, is_target_foreground, send_ctrl_v,
    target_focus_restored,
)
from utils import extract_preview, logger


WM_PASTE = 0x0302
ATTACHMENT_LINK_RE = re.compile(
    r'<a\b[^>]*\bhref\s*=\s*(?P<quote>["\'])'
    r'(?P<path>[^"\']+)(?P=quote)[^>]*>.*?</a\s*>',
    re.IGNORECASE | re.DOTALL,
)



class PasteControllerMixin:
    """粘贴 / 发送话术的全部逻辑。

    通过 self 访问主窗口的目标句柄和有序粘贴队列，
    由 KefuHelperApp 继承混入。
    """

    def _create_huashu_action(self, entry, index, parent_menu, show_group=False, group_name=''):
        preview = extract_preview(entry.get('html_content', ''), MENU_PREVIEW_LENGTH)
        tags = entry.get('tags', [])
        label = preview
        if show_group and group_name:
            label = f'[{group_name}] {preview}'
        if tags:
            label += f'  #{", ".join(tags)}'
        action = QAction(label, parent_menu)
        action.setToolTip(entry.get('html_content', ''))
        return action

    def _do_paste_text(self, html_content, target_hwnd=None,
                       target_focus_hwnd=None):
        sequence_id = getattr(self, '_paste_sequence_id', 0) + 1
        self._paste_sequence_id = sequence_id
        self._paste_target_hwnd = target_hwnd
        self._paste_target_focus_hwnd = target_focus_hwnd
        self._paste_operations = self._build_paste_operations(html_content)
        self._paste_operation_index = 0
        self._run_next_paste_operation(sequence_id)

    def _build_paste_operations(self, html_content):
        """按编辑时的先后顺序拆分文本片段和文件附件。"""
        abs_base = os.path.abspath(MEDIA_BASE_DIR)
        operations = []
        cursor = 0
        for match in ATTACHMENT_LINK_RE.finditer(html_content):
            full_path = resolve_media_path(
                abs_base, match.group('path'), must_exist=True
            )
            if not full_path:
                continue
            self._append_html_operation(
                operations, html_content[cursor:match.start()]
            )
            operations.append(('file', full_path))
            cursor = match.end()
        self._append_html_operation(operations, html_content[cursor:])
        return operations

    def _append_html_operation(self, operations, html_fragment):
        if not html_fragment:
            return
        processed_html = self._convert_html_for_paste(html_fragment)
        fragment = QTextDocumentFragment.fromHtml(processed_html)
        plain = fragment.toPlainText()
        if not plain and not re.search(r'<img\b', processed_html, re.IGNORECASE):
            return
        # 分割点可能位于完整 Qt HTML 文档中间，重新序列化为独立有效片段。
        operations.append(('html', fragment.toHtml(), plain))

    def _run_next_paste_operation(self, sequence_id):
        if sequence_id != getattr(self, '_paste_sequence_id', None):
            return
        operations = getattr(self, '_paste_operations', [])
        index = getattr(self, '_paste_operation_index', 0)
        if index >= len(operations):
            self._paste_target_hwnd = None
            self._paste_target_focus_hwnd = None
            self._paste_operations = []
            return

        operation = operations[index]
        self._paste_operation_index = index + 1
        mime = QMimeData()
        if operation[0] == 'file':
            mime.setUrls([QUrl.fromLocalFile(operation[1])])
            next_delay = PASTE_FILE_DELAY_MS
        else:
            mime.setHtml(operation[1])
            mime.setText(operation[2])
            next_delay = PASTE_TEXT_DELAY_MS
        QApplication.clipboard().setMimeData(mime)
        QTimer.singleShot(
            50,
            lambda: self._paste_current_operation(sequence_id, next_delay),
        )

    def _paste_current_operation(self, sequence_id, next_delay):
        if sequence_id != getattr(self, '_paste_sequence_id', None):
            return
        self._paste_ctrl_v()
        QTimer.singleShot(
            next_delay,
            lambda: self._run_next_paste_operation(sequence_id),
        )

    def _collect_attachment_paths(self, html_content):
        abs_base = os.path.abspath(MEDIA_BASE_DIR)
        paths = []
        seen = set()
        for match in ATTACHMENT_LINK_RE.finditer(html_content):
            full = resolve_media_path(
                abs_base, match.group('path'), must_exist=True
            )
            if full and full not in seen:
                seen.add(full)
                paths.append(full)
        return paths

    def _convert_html_for_paste(self, html_content):
        abs_base = os.path.abspath(MEDIA_BASE_DIR)

        def repl_img(m):
            prefix = m.group(1)
            quote = m.group(2)
            path = m.group(3)
            full = resolve_media_path(abs_base, path, must_exist=True)
            if full:
                return prefix + quote + full.replace('\\', '/') + quote
            return m.group(0)

        return re.sub(r'(<img[^>]*?\bsrc\s*=\s*)(["\'])([^"\']+)\2',
                      repl_img, html_content)

    def _paste_ctrl_v(self):
        hwnd = self._paste_target_hwnd
        focus_hwnd = getattr(self, '_paste_target_focus_hwnd', None)
        try:
            import win32gui
            if hwnd:
                activate_window(
                    hwnd,
                    win32gui,
                    _ctypes.windll.user32,
                    _ctypes.windll.kernel32,
                    focus_hwnd=focus_hwnd,
                )
                started_at = time.monotonic()
                not_before = started_at + 0.08
                deadline = started_at + 0.35
                retried = False
                while time.monotonic() < deadline:
                    focus_ready = target_focus_restored(
                        hwnd, focus_hwnd, win32gui, _ctypes.windll.user32
                    )
                    # Chromium 类窗口即使已报告焦点成功，也需要短暂时间
                    # 处理激活消息；过早 SendInput 会被第一次点击吞掉。
                    if focus_ready and time.monotonic() >= not_before:
                        break
                    if not retried and time.monotonic() >= deadline - 0.2:
                        activate_window(
                            hwnd,
                            win32gui,
                            _ctypes.windll.user32,
                            _ctypes.windll.kernel32,
                            focus_hwnd=focus_hwnd,
                        )
                        retried = True
                    time.sleep(0.025)
                if not is_target_foreground(hwnd, win32gui):
                    logger.warning('目标窗口激活失败，已取消本次粘贴: hwnd=%s', hwnd)
                    self._try_wm_paste(hwnd)
                    return
            time.sleep(0.02)
            if not send_ctrl_v(_ctypes.windll.user32):
                raise RuntimeError('SendInput 未能发送完整 Ctrl+V 键序列')
        except Exception as e:
            logger.error('Ctrl+V失败(键盘): %s', e)
            self._try_wm_paste(hwnd)

    def _try_wm_paste(self, hwnd):
        try:
            if hwnd:
                _ctypes.windll.user32.PostMessageW(hwnd, WM_PASTE, 0, 0)
        except Exception as e:
            logger.error('WM_PASTE也失败: %s', e)

    def handle_huashu_menu_selection_from_action(self, action):
        html = action.toolTip()
        if not html:
            return
        self._do_paste_text(html)
