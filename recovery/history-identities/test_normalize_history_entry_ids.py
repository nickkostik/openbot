import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from normalize_history_entry_ids import plan, prepare


LONG_ID = 'agent-outbound-' + 'a' * 64 + '~openbot-branch-' + 'b' * 64


def record(identifier, **fields):
    return json.dumps({'id': identifier, 'kind': 'message', 'content': 'Saved text', **fields})


class HistoryIdentityTests(unittest.TestCase):
    def test_preserves_content_order_source_and_other_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, proof = (root / name for name in ('source.db', 'copy.db', 'proof.json'))
            with sqlite3.connect(source) as db:
                db.executescript('create table transcript_entries(seq integer primary key,id text unique,entry text);'
                                 'create table kv(key text,value text);create table blobs(id text,data blob);')
                db.executemany('insert into transcript_entries values(?,?,?)', [
                    (3, LONG_ID, record(LONG_ID, content=LONG_ID, timestampMs=123)),
                    (8, 'next', record('next', content='Quoted ' + LONG_ID)),
                ])
                db.execute('insert into kv values(?,?)', ('metadata', 'unchanged'))
                db.execute('insert into blobs values(?,?)', ('root', b'untouched SDK bytes'))
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            result = prepare(source, output, proof, detached=True)
            self.assertEqual(result['normalizedIdentifiers'], 1)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(proof.stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(output) as db:
                rows = db.execute('select seq,id,entry from transcript_entries order by seq').fetchall()
                self.assertEqual([r[0] for r in rows], [3, 8])
                self.assertLessEqual(len(rows[0][1].encode()), 128)
                self.assertEqual(json.loads(rows[0][2])['content'], LONG_ID)
                self.assertEqual(db.execute('select value from kv').fetchone()[0], 'unchanged')
                self.assertEqual(db.execute('select data from blobs').fetchone()[0], b'untouched SDK bytes')

    def test_unknown_oversized_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            plan([(1, 'x' * 129, record('x' * 129))])

    def test_limit_is_utf8_bytes(self):
        identifier = 'é' * 65
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            plan([(1, identifier, record(identifier))])
        self.assertEqual(plan([(1, 'x' * 128, record('x' * 128))]), {})

    def test_structured_links_require_review(self):
        with self.assertRaisesRegex(ValueError, 'Structured reference'):
            plan([(1, LONG_ID, record(LONG_ID)),
                  (2, 'reply', record('reply', replyToMessageId=LONG_ID))])

    def test_mismatching_or_duplicate_ids_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'identities differ'):
            plan([(1, 'one', record('two'))])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            plan([(1, 'one', record('one')), (2, 'one', record('one'))])

    def test_digest_collision_is_deterministic(self):
        occupied = 'openbot-branch-' + hashlib.sha256(LONG_ID.encode()).hexdigest()
        rows = [(1, LONG_ID, record(LONG_ID)), (2, occupied, record(occupied))]
        first = plan(rows)
        self.assertNotEqual(first[LONG_ID], occupied)
        self.assertEqual(first, plan(rows))

    def test_live_sidecar_and_existing_outputs_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, proof = (root / name for name in ('source.db', 'copy.db', 'proof.json'))
            source.touch()
            with self.assertRaisesRegex(ValueError, 'detached'):
                prepare(source, output, proof, detached=False)
            Path(str(source) + '-wal').touch()
            with self.assertRaisesRegex(ValueError, 'sidecar'):
                prepare(source, output, proof, detached=True)
            Path(str(source) + '-wal').unlink()
            output.touch()
            with self.assertRaisesRegex(ValueError, 'new, distinct'):
                prepare(source, output, proof, detached=True)
            self.assertTrue(output.exists())

    def test_symlink_source_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.db'
            source.touch()
            link = root / 'link.db'
            link.symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'regular detached'):
                prepare(link, root / 'copy.db', root / 'proof.json', detached=True)


if __name__ == '__main__':
    unittest.main()
