import os
import re
import ctypes as _ctypes

from PyQt6.QtCore import QTimer, QMimeData, QUrl
from PyQt6.QtGui import QAction, QTextDocumentFragment
from PyQt6.QtWidgets import QApplication

from config import MEDIA_BASE_DIR, PASTE_FILE_DELAY_MS, MENU_PREVIEW_LENGTH
from utils import extract_preview, logger


VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002
WM_PASTE = 0x0302


class PasteControllerMixin:
    """粘贴 / 发送话术的全部逻辑。

    通过 self 访问主窗口的 _paste_target_hwnd / _pending_html / _pending_plain，
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

    def _do_paste_text(self, html_content, target_hwnd=None):
        self._paste_target_hwnd = target_hwnd
        processed_html = self._convert_html_for_paste(html_content)
        plain = QTextDocumentFragment.fromHtml(html_content).toPlainText()

        attachments = self._collect_attachment_paths(html_content)
        if attachments:
            processed_html = self._strip_file_links(processed_html)
            plain = QTextDocumentFragment.fromHtml(processed_html).toPlainText()
            self._pending_html = processed_html
            self._pending_plain = plain
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(fp) for fp in attachments])
            QApplication.clipboard().setMimeData(mime)
            QTimer.singleShot(50, self._paste_files_then_html)
        else:
            mime = QMimeData()
            mime.setHtml(processed_html)
            mime.setText(plain)
            QApplication.clipboard().setMimeData(mime)
            QTimer.singleShot(50, self._paste_ctrl_v)

    def _paste_files_then_html(self):
        self._paste_ctrl_v()
        QTimer.singleShot(PASTE_FILE_DELAY_MS, self._paste_html_only)

    def _paste_html_only(self):
        html = getattr(self, '_pending_html', '')
        plain = getattr(self, '_pending_plain', '')
        self._pending_html = None
        self._pending_plain = None
        if html:
            mime = QMimeData()
            mime.setHtml(html)
            mime.setText(plain)
            QApplication.clipboard().setMimeData(mime)
            QTimer.singleShot(50, self._paste_ctrl_v)

    def _collect_attachment_paths(self, html_content):
        abs_base = os.path.abspath(MEDIA_BASE_DIR)
        paths = []
        seen = set()
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html_content):
            full = os.path.normpath(os.path.join(abs_base, m.group(1)))
            if os.path.exists(full) and full not in seen:
                seen.add(full)
                paths.append(full)
        return paths

    def _strip_file_links(self, content):
        return re.sub(r'<(a|A)\b[^>]*>.*?</(a|A)>', '', content, flags=re.DOTALL)

    def _convert_html_for_paste(self, html_content):
        abs_base = os.path.abspath(MEDIA_BASE_DIR)

        def repl_img(m):
            prefix = m.group(1)
            quote = m.group(2)
            path = m.group(3)
            full = os.path.normpath(os.path.join(abs_base, path))
            if os.path.exists(full):
                return prefix + quote + full.replace('\\', '/') + quote
            return m.group(0)

        return re.sub(r'(<img[^>]*?\bsrc\s*=\s*)(["\'])([^"\']+)\2',
                      repl_img, html_content)

    def _paste_ctrl_v(self):
        hwnd = self._paste_target_hwnd
        self._paste_target_hwnd = None
        try:
            import time
            import win32gui
            if hwnd:
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.08)
            time.sleep(0.02)
            _ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
            _ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.04)
            _ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            _ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
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