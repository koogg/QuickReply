import os

from services.media_paths import resolve_media_path, to_media_relative_path
from widgets import paste_controller


def create_media_tree(tmp_path):
    base = tmp_path / 'media_files'
    images = base / 'images'
    files = base / 'files'
    images.mkdir(parents=True)
    files.mkdir()
    image = images / 'hello.png'
    attachment = files / 'manual.pdf'
    image.write_bytes(b'image')
    attachment.write_bytes(b'file')
    return base, image, attachment


def test_resolve_media_path_accepts_standard_relative_paths(tmp_path):
    base, image, attachment = create_media_tree(tmp_path)

    assert resolve_media_path(base, 'images/hello.png', must_exist=True) == str(image)
    assert resolve_media_path(base, r'files\manual.pdf', must_exist=True) == str(attachment)


def test_resolve_media_path_rejects_escape_absolute_and_unknown_subdir(tmp_path):
    base, _, _ = create_media_tree(tmp_path)
    outside = tmp_path / 'secret.txt'
    outside.write_text('secret', encoding='utf-8')
    wrong_subdir = base / 'other'
    wrong_subdir.mkdir()
    (wrong_subdir / 'file.txt').write_text('x', encoding='utf-8')

    assert resolve_media_path(base, '../secret.txt', must_exist=True) is None
    assert resolve_media_path(base, str(outside), must_exist=True) is None
    assert resolve_media_path(base, 'other/file.txt', must_exist=True) is None
    assert resolve_media_path(base, 'files/missing.txt', must_exist=True) is None


def test_to_media_relative_path_requires_candidate_inside_standard_subdir(tmp_path):
    base, image, _ = create_media_tree(tmp_path)
    outside = tmp_path / 'media_files_backup' / 'images' / 'hello.png'
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b'image')

    assert to_media_relative_path(base, image) == 'images/hello.png'
    assert to_media_relative_path(base, outside) is None
    assert to_media_relative_path(base, base) is None


def test_paste_controller_ignores_escaped_attachment_and_image(
        tmp_path, monkeypatch):
    base, image, attachment = create_media_tree(tmp_path)
    outside = tmp_path / 'secret.txt'
    outside.write_text('secret', encoding='utf-8')
    monkeypatch.setattr(paste_controller, 'MEDIA_BASE_DIR', str(base))
    controller = paste_controller.PasteControllerMixin()

    html = (
        '<a href="files/manual.pdf">manual</a>'
        '<a href="../secret.txt">secret</a>'
    )
    assert controller._collect_attachment_paths(html) == [str(attachment)]

    converted = controller._convert_html_for_paste(
        '<img src="images/hello.png"><img src="../secret.txt">'
    )
    normalized_image = str(image).replace('\\', '/')
    assert f'src="{normalized_image}"' in converted
    assert 'src="../secret.txt"' in converted


def test_mixed_text_and_files_keep_editor_order(tmp_path, monkeypatch):
    base, _, first_attachment = create_media_tree(tmp_path)
    second_attachment = base / 'files' / 'quote.docx'
    second_attachment.write_bytes(b'quote')
    monkeypatch.setattr(paste_controller, 'MEDIA_BASE_DIR', str(base))
    controller = paste_controller.PasteControllerMixin()
    html = (
        '<p>第一段</p>'
        '<a href="files/manual.pdf">manual.pdf</a>'
        '<p>第二段</p>'
        '<a href="files/quote.docx">quote.docx</a>'
        '<p>第三段</p>'
    )

    operations = controller._build_paste_operations(html)

    assert [operation[0] for operation in operations] == [
        'html', 'file', 'html', 'file', 'html'
    ]
    assert '第一段' in operations[0][2]
    assert operations[1][1] == str(first_attachment)
    assert '第二段' in operations[2][2]
    assert operations[3][1] == str(second_attachment)
    assert '第三段' in operations[4][2]


def test_plain_text_stays_a_single_paste_operation(tmp_path, monkeypatch):
    base, _, _ = create_media_tree(tmp_path)
    monkeypatch.setattr(paste_controller, 'MEDIA_BASE_DIR', str(base))
    controller = paste_controller.PasteControllerMixin()

    operations = controller._build_paste_operations('<p>只有文本</p>')

    assert len(operations) == 1
    assert operations[0][0] == 'html'
    assert operations[0][2] == '只有文本'


def test_paste_queue_executes_operations_in_order(tmp_path, monkeypatch):
    base, _, first_attachment = create_media_tree(tmp_path)
    second_attachment = base / 'files' / 'quote.docx'
    second_attachment.write_bytes(b'quote')
    monkeypatch.setattr(paste_controller, 'MEDIA_BASE_DIR', str(base))

    class FakeClipboard:
        mime = None

        def setMimeData(self, mime):
            self.mime = mime

    class FakeApplication:
        clipboard_instance = FakeClipboard()

        @classmethod
        def clipboard(cls):
            return cls.clipboard_instance

    class ImmediateTimer:
        @staticmethod
        def singleShot(_delay, callback):
            callback()

    monkeypatch.setattr(paste_controller, 'QApplication', FakeApplication)
    monkeypatch.setattr(paste_controller, 'QTimer', ImmediateTimer)
    controller = paste_controller.PasteControllerMixin()
    pasted = []

    def record_paste():
        mime = FakeApplication.clipboard_instance.mime
        if mime.hasUrls():
            pasted.append(('file', os.path.basename(mime.urls()[0].toLocalFile())))
        else:
            pasted.append(('html', mime.text()))

    controller._paste_ctrl_v = record_paste
    controller._do_paste_text(
        '<p>甲</p>'
        '<a href="files/manual.pdf">manual.pdf</a>'
        '<p>乙</p>'
        '<a href="files/quote.docx">quote.docx</a>'
        '<p>丙</p>',
        target_hwnd=123,
    )

    assert pasted == [
        ('html', '甲'),
        ('file', first_attachment.name),
        ('html', '乙'),
        ('file', second_attachment.name),
        ('html', '丙'),
    ]
    assert controller._paste_target_hwnd is None
