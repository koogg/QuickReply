import sys
import os
import logging

from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QIcon, QPainter, QColor, QBrush, QPen, QPolygon, QPixmap, QTextDocumentFragment

from config import TRAY_ICON_PATH

try:
    from pypinyin import lazy_pinyin, Style
    PINYIN_AVAILABLE = True
except ImportError:
    PINYIN_AVAILABLE = False


def get_resource_path(relative_path):
    # 打包后：exe 同级 > _internal/ 子目录 > _MEIPASS 解压目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        for base in (exe_dir, os.path.join(exe_dir, '_internal')):
            candidate = os.path.join(base, relative_path)
            if os.path.exists(candidate):
                return candidate
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    # 开发态
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def configure_logging():
    logger = logging.getLogger('QuickReply')
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    try:
        log_path = get_resource_path('error.log')
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        pass
    if sys.stderr is not None:
        try:
            ch = logging.StreamHandler()
            ch.setFormatter(formatter)
            logger.addHandler(ch)
        except Exception:
            pass
    logger.propagate = False
    return logger


logger = configure_logging()


def create_default_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor(51, 153, 255)))
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    painter.drawEllipse(2, 2, 60, 60)
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawRoundedRect(QRect(14, 16, 36, 24), 4, 4)
    tail = QPolygon([QPoint(20, 40), QPoint(28, 40), QPoint(16, 50)])
    painter.drawPolygon(tail)
    painter.setBrush(QBrush(QColor(51, 153, 255)))
    painter.drawEllipse(20, 25, 6, 6)
    painter.drawEllipse(29, 25, 6, 6)
    painter.drawEllipse(38, 25, 6, 6)
    painter.end()
    return QIcon(pixmap)


def get_default_icon():
    icon_path = get_resource_path(TRAY_ICON_PATH)
    if os.path.exists(icon_path):
        return QIcon(icon_path)
    return create_default_icon()


def extract_preview(html_content, max_len):
    if not html_content:
        return ''
    text = QTextDocumentFragment.fromHtml(html_content).toPlainText()
    text = text.replace('\n', ' ').replace('\r', '')
    if len(text) > max_len:
        return text[:max_len] + '...'
    return text


def get_pinyin_variants(text):
    if not PINYIN_AVAILABLE or not text:
        return '', ''
    try:
        first_letters = lazy_pinyin(text, style=Style.FIRST_LETTER)
        shoupin = ''.join(first_letters).lower()
        full_pinyin = lazy_pinyin(text)
        quanpin = ''.join(full_pinyin).lower()
        return shoupin, quanpin
    except Exception:
        return '', ''


def get_entry_pinyin_cache(entry):
    """缓存话术 entry 的全文 / 标签拼音，避免每次搜索都重算。
    缓存写入到 entry['_pinyin']，须由 save_data 在落盘前剔除。"""
    cache = entry.get('_pinyin')
    if cache is not None:
        return cache
    cache = {'sp': '', 'qp': '', 'tags': []}
    if PINYIN_AVAILABLE:
        text = extract_preview(entry.get('html_content', ''), 100000)
        sp, qp = get_pinyin_variants(text)
        cache['sp'] = sp
        cache['qp'] = qp
        for tag in entry.get('tags', []):
            ts, tq = get_pinyin_variants(tag)
            cache['tags'].append((ts, tq))
    entry['_pinyin'] = cache
    return cache


def invalidate_entry_pinyin_cache(entry):
    """在 entry 内容 / 标签发生变更后调用，使拼音缓存失效。"""
    if isinstance(entry, dict) and '_pinyin' in entry:
        del entry['_pinyin']


def entry_matches(entry, term, *, plain=None):
    """判断 entry 是否匹配搜索 term（含拼音）。"""
    if not term:
        return True
    if plain is None:
        plain = extract_preview(entry.get('html_content', ''), 100000)
    lower = plain.lower()
    tags = entry.get('tags', [])
    tag_str = ' '.join(tags).lower()
    if term in lower or term in tag_str:
        return True
    if not PINYIN_AVAILABLE:
        return False
    cache = get_entry_pinyin_cache(entry)
    if term in cache['sp'] or term in cache['qp']:
        return True
    for ts, tq in cache['tags']:
        if term in ts or term in tq:
            return True
    return False


def make_entry_label(preview, group_name, tags, *, show_group=False):
    """统一构造话术列表/菜单项的展示文本。"""
    label = f'[{group_name}] {preview}' if show_group and group_name else preview
    if tags:
        label += f'  #{", ".join(tags)}'
    return label