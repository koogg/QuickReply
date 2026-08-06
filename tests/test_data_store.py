import json
import os

import pytest

from services.data_store import (
    CURRENT_SCHEMA_VERSION,
    DataValidationError,
    atomic_write_json,
    build_document,
    load_json_document,
    migrate_document,
    rotate_backups,
)
from widgets import data_manager


def legacy_document():
    return {
        'data': {
            '常用话术': [
                {
                    'html_content': '<p>您好</p>',
                    'tags': ['问候'],
                }
            ]
        },
        'group_order': ['常用话术'],
        'settings': {'dock_enabled': False},
    }


def test_legacy_document_migrates_without_changing_existing_fields():
    legacy = legacy_document()

    migrated = migrate_document(legacy)

    assert migrated['schema_version'] == CURRENT_SCHEMA_VERSION
    assert migrated['data'] == legacy['data']
    assert migrated['group_order'] == legacy['group_order']
    assert migrated['settings'] == legacy['settings']
    assert 'schema_version' not in legacy


def test_legacy_document_keeps_previous_missing_field_defaults():
    migrated = migrate_document({'data': {}})

    assert migrated == {
        'schema_version': CURRENT_SCHEMA_VERSION,
        'data': {},
        'group_order': [],
        'settings': {},
    }


def test_future_schema_is_rejected():
    document = legacy_document()
    document['schema_version'] = CURRENT_SCHEMA_VERSION + 1

    with pytest.raises(DataValidationError, match='高于当前程序支持'):
        migrate_document(document)


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('data', []),
        ('group_order', {}),
        ('settings', []),
    ],
)
def test_invalid_top_level_shapes_are_rejected(field, value):
    document = {
        'schema_version': CURRENT_SCHEMA_VERSION,
        'data': {},
        'group_order': [],
        'settings': {},
    }
    document[field] = value

    with pytest.raises(DataValidationError):
        migrate_document(document)


def test_build_document_strips_runtime_pinyin_cache():
    document = build_document(
        {
            '常用话术': [
                {
                    'html_content': '<p>您好</p>',
                    'tags': [],
                    '_pinyin': {'sp': 'nh'},
                }
            ]
        },
        ['常用话术'],
        {},
    )

    assert document['schema_version'] == CURRENT_SCHEMA_VERSION
    assert '_pinyin' not in document['data']['常用话术'][0]


def test_atomic_write_round_trip_and_no_temp_file(tmp_path):
    target = tmp_path / 'Date.json'
    document = build_document(legacy_document()['data'], ['常用话术'], {})

    atomic_write_json(target, document)

    assert load_json_document(target) == document
    assert list(tmp_path.glob('.Date.json.*.tmp')) == []


def test_atomic_write_failure_preserves_original_file(tmp_path):
    target = tmp_path / 'Date.json'
    target.write_text('original', encoding='utf-8')
    document = {
        'schema_version': CURRENT_SCHEMA_VERSION,
        'data': {},
        'group_order': [],
        'settings': {'not_json_serializable': {1, 2}},
    }

    with pytest.raises(TypeError):
        atomic_write_json(target, document)

    assert target.read_text(encoding='utf-8') == 'original'
    assert list(tmp_path.glob('.Date.json.*.tmp')) == []


def test_data_manager_load_and_save_integrates_schema_and_atomic_writer(
        tmp_path, monkeypatch):
    target = tmp_path / 'Date.json'
    target.write_text(
        json.dumps(legacy_document(), ensure_ascii=False),
        encoding='utf-8',
    )
    monkeypatch.setattr(data_manager, 'DATA_FILE', str(target))

    class DummyManager(data_manager.DataManagerMixin):
        def refresh_group_list(self):
            self.refreshed = True

    manager = DummyManager()
    manager.load_data()
    manager.data['常用话术'][0]['_pinyin'] = {'sp': 'nh'}

    assert manager.refreshed is True
    assert manager.save_data() is True

    saved = json.loads(target.read_text(encoding='utf-8'))
    assert saved['schema_version'] == CURRENT_SCHEMA_VERSION
    assert saved['data'] == legacy_document()['data']


def test_rotate_backups_keeps_newest_files_and_ignores_other_names(tmp_path):
    created = []
    for index in range(4):
        path = tmp_path / f'Date_backup_2026080{index}_120000.json'
        path.write_text(str(index), encoding='utf-8')
        os.utime(path, (100 + index, 100 + index))
        created.append(path)
    unrelated = tmp_path / 'manual.json'
    unrelated.write_text('keep', encoding='utf-8')

    removed = rotate_backups(tmp_path, keep=2)

    assert set(map(os.path.abspath, removed)) == {
        os.path.abspath(created[0]),
        os.path.abspath(created[1]),
    }
    assert not created[0].exists()
    assert not created[1].exists()
    assert created[2].exists()
    assert created[3].exists()
    assert unrelated.exists()


def test_rotate_backups_never_removes_all_backups(tmp_path):
    backup = tmp_path / 'Date_backup_20260806_120000.json'
    backup.write_text('data', encoding='utf-8')

    rotate_backups(tmp_path, keep=0)

    assert backup.exists()


def test_build_document_rejects_invalid_group_order_type():
    with pytest.raises(DataValidationError, match='group_order'):
        build_document({}, 'not-a-list', {})


def test_failed_load_blocks_later_save_from_overwriting_source(
        tmp_path, monkeypatch):
    target = tmp_path / 'Date.json'
    target.write_text('{broken json', encoding='utf-8')
    original = target.read_text(encoding='utf-8')
    warnings = []
    monkeypatch.setattr(data_manager, 'DATA_FILE', str(target))
    monkeypatch.setattr(
        data_manager.QMessageBox,
        'warning',
        lambda *args: warnings.append(args),
    )

    class DummyManager(data_manager.DataManagerMixin):
        def refresh_group_list(self):
            pass

    manager = DummyManager()
    manager.load_data()
    manager.data = {'新分组': []}
    manager.group_order = ['新分组']

    assert manager._data_write_blocked is True
    assert manager.save_data() is False
    assert target.read_text(encoding='utf-8') == original
    assert len(warnings) == 2
