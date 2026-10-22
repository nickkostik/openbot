#!/usr/bin/env python3
"""Restore missing required sidebar fields in native version-1 settings.

Account runtime sections omit native persistence fields. This narrow repair
does not validate the rest of the native configuration or remap identities.
Prefer getHostSettings/setHostSettings for ordinary preference changes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

MAX_BYTES = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalize(settings):
    require(isinstance(settings, dict) and type(settings.get('version')) is int
            and settings['version'] == 1, 'Expected native settings version 1')
    result = copy.deepcopy(settings)
    if 'sidebarSections' not in result:
        return result, 0
    sections = result['sidebarSections']
    require(isinstance(sections, list) and len(sections) <= 500,
            'Expected a bounded native sidebarSections array')
    changed = 0; identities = set()
    for section in sections:
        require(isinstance(section, dict)
                and isinstance(section.get('id'), str) and section['id']
                and isinstance(section.get('name'), str), 'Invalid native section')
        require(section['id'] not in identities, 'Duplicate native section identity')
        identities.add(section['id'])
        if 'agentIds' not in section:
            section['agentIds'] = []; changed += 1
        if 'isCollapsed' not in section:
            section['isCollapsed'] = False; changed += 1
        require(isinstance(section['agentIds'], list) and len(section['agentIds']) <= 5000
                and all(isinstance(value, str) and value for value in section['agentIds']),
                'Invalid native section agentIds')
        require(type(section['isCollapsed']) is bool, 'Invalid native section isCollapsed')
    return result, changed


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key')
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError('Non-finite JSON value')


def read_regular(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as handle:
        metadata = os.fstat(handle.fileno())
        require(stat.S_ISREG(metadata.st_mode), 'Settings must be a regular file')
        require(os.geteuid() in (0, metadata.st_uid), 'Settings must belong to the current owner')
        require(metadata.st_size <= MAX_BYTES, 'Settings exceed the recovery size bound')
        raw = handle.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, 'Settings exceed the recovery size bound')
    return raw, metadata


def signature(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns,
            metadata.st_ctime_ns, metadata.st_uid, metadata.st_gid, metadata.st_mode)


def assert_unchanged(path, raw, metadata):
    current, current_metadata = read_regular(path)
    require(current == raw and signature(current_metadata) == signature(metadata),
            'Settings changed during recovery; inspect the backup and retry')


def write_private(descriptor, raw, metadata):
    with os.fdopen(descriptor, 'wb') as handle:
        os.fchmod(handle.fileno(), 0o600)
        if os.geteuid() == 0:
            os.fchown(handle.fileno(), metadata.st_uid, metadata.st_gid)
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def repair(path, *, apply=False, backup_dir=None):
    path = Path(path)
    raw, metadata = read_regular(path)
    settings = json.loads(raw.decode('utf-8'), object_pairs_hook=object_pairs,
                          parse_constant=reject_constant)
    normalized, count = normalize(settings)
    result = {'changedFields': count, 'applied': False,
              'beforeSHA256': hashlib.sha256(raw).hexdigest()}
    if not count:
        return result
    replacement = (json.dumps(normalized, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    require(len(replacement) <= MAX_BYTES, 'Normalized settings exceed the recovery size bound')
    if not apply:
        return result
    require(backup_dir is not None, 'An explicit private backup directory is required')
    backups = Path(backup_dir)
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_stat = backups.lstat()
    require(stat.S_ISDIR(backup_stat.st_mode) and backup_stat.st_uid == os.geteuid()
            and not backup_stat.st_mode & 0o077, 'Backup directory must be private and owned')
    descriptor, backup_name = tempfile.mkstemp(prefix='native-settings-before-', suffix='.json', dir=backups)
    write_private(descriptor, raw, metadata)
    sync_directory(backups)
    result['backup'] = backup_name
    descriptor, temporary = tempfile.mkstemp(prefix='.native-settings-repair-', dir=path.parent)
    try:
        write_private(descriptor, replacement, metadata)
        # This detects observed concurrent writes; callers must quiesce settings
        # writers because a filesystem rename is not a native settings lock.
        assert_unchanged(path, raw, metadata)
        os.replace(temporary, path)
        sync_directory(path.parent)
        after, _ = read_regular(path)
        require(after == replacement, 'Settings readback changed; inspect the private backup')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    result.update(applied=True, afterSHA256=hashlib.sha256(replacement).hexdigest())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write the reviewed repair; default is dry run')
    args = parser.parse_args()
    print(json.dumps(repair(args.settings, apply=args.apply, backup_dir=args.backup_dir)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, UnicodeError, RecursionError):
        # Native settings can contain credentials. Keep parse errors and input
        # values out of the console; the exact original remains in the backup.
        print('Native sidebar repair refused; inspect settings and private backups locally.', file=sys.stderr)
        raise SystemExit(2)
