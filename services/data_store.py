import json
import os
import tempfile
from copy import deepcopy


CURRENT_SCHEMA_VERSION = 1
LEGACY_SCHEMA_VERSION = 0
IMPORT_CONFLICT_REPLACE = 'replace'
IMPORT_CONFLICT_APPEND = 'append'


class DataValidationError(ValueError):
    """数据文件结构或版本不受当前程序支持。"""


def merge_imported_groups(existing_data, existing_order, imported_data,
                          imported_order, conflict_strategy=None):
    """合并导入分组，返回新的 data、group_order 和同名分组列表。"""
    conflicts = [name for name in imported_data if name in existing_data]
    if conflicts and conflict_strategy not in {
        IMPORT_CONFLICT_REPLACE, IMPORT_CONFLICT_APPEND,
    }:
        raise ValueError('存在同名分组时必须指定替换或追加策略')

    merged_data = deepcopy(existing_data)
    merged_order = list(existing_order)
    ordered_imports = []
    seen = set()
    for name in list(imported_order) + list(imported_data):
        if name in imported_data and name not in seen:
            ordered_imports.append(name)
            seen.add(name)

    for name in ordered_imports:
        entries = deepcopy(imported_data[name])
        if name in merged_data:
            if conflict_strategy == IMPORT_CONFLICT_REPLACE:
                merged_data[name] = entries
            else:
                merged_data[name] = list(merged_data[name]) + entries
        else:
            merged_data[name] = entries
            if name not in merged_order:
                merged_order.append(name)

    return merged_data, merged_order, conflicts


def _validate_string_list(value, field_name):
    if not isinstance(value, list):
        raise DataValidationError(f'{field_name} 必须是数组')
    if not all(isinstance(item, str) for item in value):
        raise DataValidationError(f'{field_name} 中的每一项都必须是字符串')


def validate_document(document):
    """校验当前版本的数据文档，不静默修复异常业务数据。"""
    if not isinstance(document, dict):
        raise DataValidationError('数据文件顶层必须是对象')

    version = document.get('schema_version')
    if isinstance(version, bool) or not isinstance(version, int):
        raise DataValidationError('schema_version 必须是整数')
    if version != CURRENT_SCHEMA_VERSION:
        raise DataValidationError(
            f'不支持的数据版本 {version}，当前仅支持 {CURRENT_SCHEMA_VERSION}'
        )

    data = document.get('data')
    if not isinstance(data, dict):
        raise DataValidationError('data 必须是对象')
    for group_name, entries in data.items():
        if not isinstance(group_name, str):
            raise DataValidationError('分组名称必须是字符串')
        if not isinstance(entries, list):
            raise DataValidationError(f'分组“{group_name}”的话术必须是数组')
        for index, entry in enumerate(entries):
            prefix = f'分组“{group_name}”的第 {index + 1} 条话术'
            if not isinstance(entry, dict):
                raise DataValidationError(f'{prefix}必须是对象')
            if not isinstance(entry.get('html_content', ''), str):
                raise DataValidationError(f'{prefix}的 html_content 必须是字符串')
            _validate_string_list(entry.get('tags', []), f'{prefix}的 tags')

    _validate_string_list(document.get('group_order'), 'group_order')
    if not isinstance(document.get('settings'), dict):
        raise DataValidationError('settings 必须是对象')


def migrate_document(document):
    """把旧格式迁移到当前内存格式；当前 v0 -> v1 只增加版本字段。"""
    if not isinstance(document, dict):
        raise DataValidationError('数据文件顶层必须是对象')

    version = document.get('schema_version', LEGACY_SCHEMA_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise DataValidationError('schema_version 必须是非负整数')
    if version > CURRENT_SCHEMA_VERSION:
        raise DataValidationError(
            f'数据版本 {version} 高于当前程序支持的 {CURRENT_SCHEMA_VERSION}，'
            '请升级 QuickReply 后再打开'
        )

    migrated = dict(document)
    if version == LEGACY_SCHEMA_VERSION:
        migrated.setdefault('data', {})
        migrated.setdefault('group_order', [])
        migrated.setdefault('settings', {})
        migrated['schema_version'] = 1
        version = 1

    if version != CURRENT_SCHEMA_VERSION:
        raise DataValidationError(f'缺少从数据版本 {version} 开始的迁移步骤')
    validate_document(migrated)
    return migrated


def load_json_document(path):
    with open(path, 'r', encoding='utf-8') as file:
        return migrate_document(json.load(file))


def build_document(data, group_order, settings):
    """构造可持久化文档，并剔除仅用于搜索的运行时缓存。"""
    clean_data = {
        group: [
            {key: value for key, value in entry.items() if key != '_pinyin'}
            if isinstance(entry, dict) else entry
            for entry in entries
        ]
        for group, entries in data.items()
    }
    document = {
        'schema_version': CURRENT_SCHEMA_VERSION,
        'data': clean_data,
        'group_order': (
            list(group_order) if isinstance(group_order, list) else group_order
        ),
        'settings': dict(settings) if isinstance(settings, dict) else settings,
    }
    validate_document(document)
    return document


def atomic_write_json(path, document):
    """在目标同目录写临时文件，落盘完成后原子替换目标文件。"""
    validate_document(document)
    absolute_path = os.path.abspath(path)
    directory = os.path.dirname(absolute_path)
    os.makedirs(directory, exist_ok=True)
    prefix = f'.{os.path.basename(absolute_path)}.'
    fd, temp_path = tempfile.mkstemp(
        dir=directory, prefix=prefix, suffix='.tmp', text=True
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            json.dump(document, file, ensure_ascii=False, indent=2)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, absolute_path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def rotate_backups(backup_dir, keep):
    """保留最新的指定份数，返回成功删除的旧备份路径。"""
    keep = max(1, int(keep))
    if not os.path.isdir(backup_dir):
        return []
    backups = sorted(
        (
            os.path.join(backup_dir, name)
            for name in os.listdir(backup_dir)
            if name.startswith('Date_backup_') and name.endswith('.json')
        ),
        key=os.path.getmtime,
    )
    removed = []
    while len(backups) > keep:
        path = backups.pop(0)
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            continue
    return removed
