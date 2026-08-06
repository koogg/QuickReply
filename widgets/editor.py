import os
import re
import shutil
import uuid

from PyQt6.QtGui import QFont, QImageReader
from PyQt6.QtWidgets import (
    QTextEdit, QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QDialogButtonBox, QMessageBox, QFileDialog
)

from config import (
    MEDIA_BASE_DIR, MEDIA_IMAGES_SUBDIR, MEDIA_FILES_SUBDIR,
    EDITOR_IMAGE_MAX_WIDTH
)
from services.media_paths import resolve_media_path, to_media_relative_path
from utils import logger


IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif'}

class CustomTextEdit(QTextEdit):
    def __init__(self, parent_dialog=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_dialog = parent_dialog
        self.setAcceptDrops(True)

    def canInsertFromMimeData(self, source):
        if source.hasUrls():
            for url in source.urls():
                if url.isLocalFile():
                    return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            handled = False
            for url in source.urls():
                if url.isLocalFile():
                    self.parent_dialog.insert_file_action(url.toLocalFile())
                    handled = True
            if handled:
                return
        super().insertFromMimeData(source)


class RichHuashuEditDialog(QDialog):
    def __init__(self, html_content=None, tags=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('编辑话术内容')
        self.setMinimumSize(550, 500)

        layout = QVBoxLayout(self)

        toolbar_layout = QHBoxLayout()
        self.insert_file_btn = QPushButton('插入文件')
        self.insert_file_btn.clicked.connect(lambda: self.insert_file_action())
        toolbar_layout.addWidget(self.insert_file_btn)

        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        self.content_edit = CustomTextEdit(self)
        self.content_edit.setAcceptRichText(True)
        if html_content:
            self.content_edit.setHtml(self._prepare_html_for_editing(html_content))
        self.content_edit.setFont(QFont('Arial', 10))
        layout.addWidget(self.content_edit)

        self.tags_label = QLabel("标签 (多个标签请用英文逗号 ',' 分隔):")
        layout.addWidget(self.tags_label)

        self.tags_edit = QLineEdit(self)
        if tags and isinstance(tags, list):
            self.tags_edit.setText(', '.join(tags))
        layout.addWidget(self.tags_edit)

        button_box = QDialogButtonBox()
        save_btn = button_box.addButton('保存', QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        button_box.accepted.connect(self.accept_dialog)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self.setSizeGripEnabled(True)
        self._ensure_media_dirs_exist()

    def _ensure_media_dirs_exist(self):
        try:
            base = os.path.abspath(MEDIA_BASE_DIR)
            os.makedirs(os.path.join(base, MEDIA_IMAGES_SUBDIR), exist_ok=True)
            os.makedirs(os.path.join(base, MEDIA_FILES_SUBDIR), exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, '目录错误', f'无法创建媒体存储目录: {e}')

    def _copy_to_media_and_get_relative_path(self, source_path, subfolder):
        if not source_path or not os.path.exists(source_path):
            logger.warning('源文件路径无效或不存在: %s', source_path)
            return None

        try:
            dest_folder_abs = os.path.abspath(os.path.join(MEDIA_BASE_DIR, subfolder))
            original_filename = os.path.basename(source_path)
            base, ext = os.path.splitext(original_filename)
            safe_base = re.sub(r'[^\w\u4e00-\u9fff-]', '_', base).strip()
            if not safe_base:
                safe_base = 'media_' + uuid.uuid4().hex[:6]
            unique_filename = f'{safe_base}{ext}'
            target_path_abs = os.path.join(dest_folder_abs, unique_filename)

            counter = 1
            while os.path.exists(target_path_abs):
                unique_filename = f'{safe_base}_{counter}{ext}'
                target_path_abs = os.path.join(dest_folder_abs, unique_filename)
                counter += 1

            shutil.copy2(source_path, target_path_abs)
            return os.path.join(subfolder, unique_filename).replace('\\', '/')
        except Exception as e:
            QMessageBox.warning(self, '复制错误', f'复制文件失败: {e}')
            logger.warning('复制错误详情: %s', e)
            return None

    def _prepare_html_for_editing(self, html_str):
        if not html_str:
            return ''
        pattern = re.compile(
            '(src|href)\\s*=\\s*([\"\\\']?)((?:images/|files/)[^\"\\\'\\s>]+)\\2',
            flags=re.IGNORECASE
        )
        abs_base = os.path.abspath(MEDIA_BASE_DIR)
        def repl(m):
            attr, quote, rel_path = m.group(1), m.group(2), m.group(3)
            full_path = resolve_media_path(abs_base, rel_path, must_exist=True)
            if full_path:
                abs_path = full_path.replace('\\', '/')
                return f'{attr}={quote}{abs_path}{quote}'
            return m.group(0)
        html = pattern.sub(repl, html_str)

        # 给 img 标签补上显示宽度：保存时已剔除 width，编辑器加载时重新加上，
        # 既能在编辑器里保持紧凑视图，也不会被保存到话术内容里。
        def add_display_width(m):
            tag, end = m.group(1), m.group(2)
            if re.search(r'\bwidth\s*=', tag, re.IGNORECASE):
                return tag + end
            return tag + f' width="{EDITOR_IMAGE_MAX_WIDTH}"' + end
        html = re.sub(
            r'(<img\b[^>]*?\bsrc\s*=\s*["\'][^"\']+["\'][^>]*?)(/?>)',
            add_display_width, html, flags=re.IGNORECASE
        )
        return html

    def insert_image_action(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self, '选择图片', '', '图片文件 (*.png *.jpg *.jpeg *.gif *.bmp)')
            if not file_path:
                return
        rel_path = self._copy_to_media_and_get_relative_path(file_path, MEDIA_IMAGES_SUBDIR)
        if rel_path:
            abs_path = os.path.abspath(os.path.join(MEDIA_BASE_DIR, rel_path)).replace('\\', '/')
            cursor = self.content_edit.textCursor()
            cursor.insertHtml(f'<img src="{abs_path}" width="{EDITOR_IMAGE_MAX_WIDTH}" />')

    def insert_file_link_action(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self, '选择文件', '', '所有文件 (*.*)')
            if not file_path:
                return
        rel_path = self._copy_to_media_and_get_relative_path(file_path, MEDIA_FILES_SUBDIR)
        if rel_path:
            filename = os.path.basename(file_path)
            cursor = self.content_edit.textCursor()
            cursor.insertHtml(f'<a href="{rel_path}">{filename}</a>')

    def insert_file_action(self, file_path=None):
        if file_path is None:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self, '选择文件', '', '所有文件 (*.*)')
            if not file_paths:
                return
        else:
            file_paths = [file_path]
        for fp in file_paths:
            ext = os.path.splitext(fp)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                img_reader = QImageReader(fp)
                if img_reader.canRead():
                    self.insert_image_action(fp)
                    continue
            self.insert_file_link_action(fp)

    def get_html_content(self):
        html = self.content_edit.toHtml()
        def convert_to_relative(match):
            attr_full = match.group(0)
            attr_name = match.group(1)
            quote = match.group(2)
            path = match.group(3)
            rel_path = to_media_relative_path(MEDIA_BASE_DIR, path)
            if rel_path:
                return f'{attr_name}{quote}{rel_path}{quote}'
            return attr_full
        pattern = re.compile(r'((?:src|href)\s*=\s*)(["\']?)([^"\'\s>]+)\2', re.IGNORECASE)
        html = pattern.sub(convert_to_relative, html)

        # 剥离 img 标签上的 width / height，避免贴入聊天框时被压缩
        def strip_img_size(m):
            tag = m.group(0)
            tag = re.sub(r'\s+(?:width|height)\s*=\s*(["\'])[^"\']*\1',
                         '', tag, flags=re.IGNORECASE)
            return tag
        html = re.sub(r'<img\b[^>]*/?>', strip_img_size, html, flags=re.IGNORECASE)
        return html

    def get_tags(self):
        return [t.strip() for t in self.tags_edit.text().split(',') if t.strip()]

    def accept_dialog(self):
        if not self.content_edit.toPlainText().strip():
            QMessageBox.warning(self, '提示', '话术内容不能为空')
            return
        super().accept()
