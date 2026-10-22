#!/usr/bin/env python3
"""Prepare an offline transcript copy with bounded generated branch identifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

MAX_ENTRY_ID_BYTES = 128
LEGACY_BRANCH_ID = re.compile(r'.+~openbot-branch-[0-9a-f]{64}\Z')
TEXT_FIELDS = frozenset(('content', 'text', 'prompt', 'message', 'description'))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def plan(rows: list[tuple[int, str, str]]) -> dict[str, str]:
    """Only normalize identifiers created by the old history branch merger."""
    occupied = {entry_id for _, entry_id, _ in rows}
    if len(occupied) != len(rows):
        raise ValueError('Duplicate transcript identities')
    aliases = {}
    for _, entry_id, raw in rows:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('id') != entry_id:
            raise ValueError('Transcript body and row identities differ')
        if len(entry_id.encode('utf-8')) <= MAX_ENTRY_ID_BYTES:
            continue
        if not LEGACY_BRANCH_ID.fullmatch(entry_id):
            raise ValueError('Unrecognized oversized identity; manual review required')
        for counter in range(100000):
            seed = entry_id if counter == 0 else entry_id + '\0' + str(counter)
            candidate = 'openbot-branch-' + hashlib.sha256(seed.encode()).hexdigest()
            if candidate not in occupied:
                occupied.add(candidate)
                aliases[entry_id] = candidate
                break
        else:
            raise ValueError('Cannot allocate a unique bounded identity')

    def check_references(value: object, path: tuple[object, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                check_references(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check_references(child, (*path, index))
        elif isinstance(value, str) and value in aliases:
            if path != ('id',) and path[-1] not in TEXT_FIELDS:
                raise ValueError('Structured reference requires explicit alias review')

    for _, _, raw in rows:
        check_references(json.loads(raw), ())
    return aliases


def prepare(source: Path, output: Path, proof: Path, *, detached: bool) -> dict:
    """Never modify a live store; preserve the source and every non-ID field."""
    if not detached:
        raise ValueError('A completed detached snapshot is required')
    if source.is_symlink() or not source.is_file():
        raise ValueError('Source must be a regular detached file')
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(source) + suffix).exists():
            raise ValueError('SQLite sidecar present; take a completed snapshot first')
    paths = [source.absolute(), output.absolute(), proof.absolute()]
    if len(set(paths)) != 3 or output.exists() or output.is_symlink() or proof.exists() or proof.is_symlink():
        raise ValueError('Output and proof must be new, distinct paths')
    before_sha = sha256(source)
    temporary = []
    installed = []
    try:
        with sqlite3.connect(source.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as original:
            if original.execute('pragma integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Source integrity check failed')
            rows = original.execute('select seq,id,entry from transcript_entries order by seq').fetchall()
            aliases = plan(rows)
            fd, name = tempfile.mkstemp(prefix='.history-copy-', dir=output.parent)
            os.close(fd)
            candidate = Path(name)
            temporary.append(candidate)
            with sqlite3.connect(candidate) as copied:
                original.backup(copied)
                for seq, entry_id, raw in rows:
                    if entry_id in aliases:
                        value = json.loads(raw)
                        value['id'] = aliases[entry_id]
                        copied.execute('update transcript_entries set id=?,entry=? where seq=?',
                                       (aliases[entry_id], encode(value), seq))
                copied.commit()
                if copied.execute('pragma integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Prepared copy integrity check failed')
                actual = copied.execute('select seq,id,entry from transcript_entries order by seq').fetchall()
                if len(actual) != len(rows):
                    raise ValueError('Transcript count changed')
                for (seq, entry_id, raw), (new_seq, new_id, new_raw) in zip(rows, actual):
                    expected = json.loads(raw)
                    expected['id'] = aliases.get(entry_id, entry_id)
                    if seq != new_seq or new_id != expected['id'] or json.loads(new_raw) != expected:
                        raise ValueError('A field other than the entry identity changed')
        if sha256(source) != before_sha or any(
            Path(str(source) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')
        ):
            raise ValueError('Source changed during preparation')
        report = {
            'schema': 'openbot-bounded-history-identities/v1',
            'sourceSHA256': before_sha,
            'outputSHA256': sha256(candidate),
            'entries': len(rows),
            'normalizedIdentifiers': len(aliases),
            'aliases': aliases,
            'sourceUnchanged': True,
            'allOtherPayloadFieldsPreserved': True,
            'sourceOrderPreserved': True,
            'networkCalls': 0,
        }
        fd, name = tempfile.mkstemp(prefix='.history-proof-', dir=proof.parent)
        temp_proof = Path(name)
        temporary.append(temp_proof)
        with os.fdopen(fd, 'w', encoding='utf-8') as destination:
            destination.write(encode(report) + '\n')
            destination.flush()
            os.fsync(destination.fileno())
        with candidate.open('rb') as snapshot:
            os.fsync(snapshot.fileno())
        # Hard links install only into absent names, including against a race.
        for staged, target in ((temp_proof, proof), (candidate, output)):
            os.link(staged, target)
            installed.append(target)
        for parent in {output.parent, proof.parent}:
            directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return report
    except BaseException:
        for target in installed:
            target.unlink()
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--detached-snapshot', action='store_true')
    args = parser.parse_args()
    report = prepare(args.source, args.output, args.proof, detached=args.detached_snapshot)
    print(encode({key: report[key] for key in ('entries', 'normalizedIdentifiers',
                                              'sourceUnchanged', 'allOtherPayloadFieldsPreserved')}))


if __name__ == '__main__':
    main()
