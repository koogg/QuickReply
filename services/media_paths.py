import os


MEDIA_SUBDIRECTORIES = frozenset({'images', 'files'})
def _as_path_string(value):
    try:
        path = os.fspath(value)
    except TypeError:
        return None
    if not isinstance(path, str) or not path or '\x00' in path:
        return None
    return path




def _is_within(base_path, candidate_path):
    try:
        return os.path.commonpath((base_path, candidate_path)) == base_path
    except (OSError, ValueError):
        return False


def resolve_media_path(base_dir, stored_path, *, must_exist=False):
    """安全解析媒体相对路径；非法、越界或不在标准子目录时返回 None。"""
    stored_path = _as_path_string(stored_path)
    if stored_path is None:
        return None
    drive, _ = os.path.splitdrive(stored_path)
    if drive or os.path.isabs(stored_path):
        return None

    normalized_stored = stored_path.replace('/', os.sep).replace('\\', os.sep)
    first_part = normalized_stored.split(os.sep, 1)[0].lower()
    if first_part not in MEDIA_SUBDIRECTORIES:
        return None

    base_path = os.path.realpath(os.path.abspath(base_dir))
    candidate_path = os.path.realpath(
        os.path.abspath(os.path.join(base_path, normalized_stored))
    )
    if not _is_within(base_path, candidate_path):
        return None
    if must_exist and not os.path.isfile(candidate_path):
        return None
    return candidate_path


def to_media_relative_path(base_dir, candidate_path):
    """把媒体根目录内的绝对路径转换为正斜杠相对路径。"""
    candidate_path = _as_path_string(candidate_path)
    if candidate_path is None:
        return None
    base_path = os.path.realpath(os.path.abspath(base_dir))
    absolute_candidate = os.path.realpath(os.path.abspath(candidate_path))
    if not _is_within(base_path, absolute_candidate):
        return None
    relative = os.path.relpath(absolute_candidate, base_path)
    first_part = relative.split(os.sep, 1)[0].lower()
    if first_part not in MEDIA_SUBDIRECTORIES:
        return None
    return relative.replace('\\', '/')
