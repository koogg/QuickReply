import utils


def test_extract_preview_converts_html_and_truncates():
    assert utils.extract_preview('<p>你好<br>世界</p>', 4) == '你好 世...'


def test_entry_matches_content_and_tags_case_insensitively():
    entry = {
        'html_content': '<p>Hello Customer</p>',
        'tags': ['售后', 'VIP'],
    }

    assert utils.entry_matches(entry, 'customer')
    assert utils.entry_matches(entry, 'vip')
    assert not utils.entry_matches(entry, 'missing')


def test_entry_matches_pinyin_and_invalidates_cache(monkeypatch):
    entry = {
        'html_content': '<p>你好客户</p>',
        'tags': ['售后'],
    }
    variants = {
        '你好客户': ('nhkh', 'nihaokehu'),
        '售后': ('sh', 'shouhou'),
    }
    monkeypatch.setattr(utils, 'PINYIN_AVAILABLE', True)
    monkeypatch.setattr(
        utils, 'get_pinyin_variants',
        lambda text: variants.get(text, ('', '')),
    )

    assert utils.entry_matches(entry, 'nhkh')
    assert utils.entry_matches(entry, 'shouhou')
    assert '_pinyin' in entry

    utils.invalidate_entry_pinyin_cache(entry)
    assert '_pinyin' not in entry


def test_empty_search_matches_every_entry():
    assert utils.entry_matches({'html_content': '', 'tags': []}, '')
