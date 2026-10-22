import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native_sidebar', Path(__file__).with_name('repair-native-sidebar-settings.py'))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def fixture():
    return {'version': 1, 'theme': 'system', 'accountScopes': {'example': {'unknown': [1, True]}},
            'sidebarSections': [{'id': str(i), 'name': 'Section', **({'agentIds': ['bot']} if i < 4 else {})}
                                for i in range(5)]}


class NativeSidebarTests(unittest.TestCase):
    def test_actual_six_missing_fields_preserve_every_other_value(self):
        original = fixture(); before = copy.deepcopy(original)
        actual, count = repair.normalize(original)
        expected = copy.deepcopy(original)
        for section in expected['sidebarSections']:
            section.setdefault('agentIds', [])
            section['isCollapsed'] = False
        self.assertEqual(count, 6)
        self.assertEqual(actual, expected)
        self.assertEqual(original, before)
        self.assertEqual(repair.normalize(actual), (actual, 0))

    def test_collapsed_and_unknown_section_metadata_retained(self):
        original = fixture()
        original['sidebarSections'][0].update(isCollapsed=True, future={'x': 'literal'})
        actual, count = repair.normalize(original)
        self.assertEqual(count, 5)
        self.assertTrue(actual['sidebarSections'][0]['isCollapsed'])
        self.assertEqual(actual['sidebarSections'][0]['future'], {'x': 'literal'})

    def test_absent_and_explicit_empty_preferences_stay_distinct(self):
        for original in ({'version': 1}, {'version': 1, 'sidebarSections': []}):
            self.assertEqual(repair.normalize(original), (original, 0))

    def test_malformed_existing_values_and_unknown_layouts_refuse(self):
        invalid = [None, [], {'version': True}, {'version': 2}, {'version': '1'},
                   {'version': 1, 'sidebarSections': None},
                   {'version': 1, 'sidebarSections': {'sections': []}}]
        for field, value in [('agentIds', None), ('agentIds', 'bot'), ('agentIds', [None]),
                             ('isCollapsed', None), ('isCollapsed', 0), ('isCollapsed', 'false'),
                             ('id', ''), ('name', 123)]:
            original = fixture(); original['sidebarSections'][0][field] = value; invalid.append(original)
        duplicate = fixture(); duplicate['sidebarSections'].append(duplicate['sidebarSections'][0]); invalid.append(duplicate)
        for original in invalid:
            with self.subTest(original=original), self.assertRaises(ValueError):
                repair.normalize(original)

    def test_private_backup_atomic_readback_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; backups = Path(directory) / 'backups'
            raw = json.dumps(fixture(), separators=(',', ':')).encode(); path.write_bytes(raw)
            before = path.stat()
            self.assertEqual(repair.repair(path)['changedFields'], 6)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse(backups.exists())
            result = repair.repair(path, apply=True, backup_dir=backups)
            self.assertTrue(result['applied'])
            self.assertEqual(Path(result['backup']).read_bytes(), raw)
            self.assertEqual(stat.S_IMODE(Path(result['backup']).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (before.st_uid, before.st_gid))
            self.assertEqual(json.loads(path.read_bytes()), repair.normalize(fixture())[0])
            self.assertNotEqual(before.st_ino, path.stat().st_ino)
            after = path.read_bytes()
            self.assertEqual(repair.repair(path, apply=True, backup_dir=backups)['changedFields'], 0)
            self.assertEqual(path.read_bytes(), after)
            self.assertEqual(len(list(backups.iterdir())), 1)

    def test_invalid_json_is_never_rewritten(self):
        for raw in (b'{"version":1,"version":1}', b'{"version":1,"x":NaN}',
                    b'{"version":1,"x":Infinity}', b'not json', b'\xff'):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'settings.json'; path.write_bytes(raw)
                with self.assertRaises((ValueError, UnicodeError)):
                    repair.repair(path, apply=True, backup_dir=Path(directory) / 'backups')
                self.assertEqual(path.read_bytes(), raw)
                self.assertFalse((Path(directory) / 'backups').exists())

    def test_symlink_and_non_regular_settings_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; target = Path(directory) / 'target'
            target.write_text(json.dumps(fixture())); path.symlink_to(target)
            with self.assertRaises(OSError):
                repair.repair(path)
            path.unlink(); os.mkfifo(path)
            with self.assertRaises(ValueError):
                repair.repair(path)

    def test_missing_or_public_backup_directory_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; raw = json.dumps(fixture()).encode(); path.write_bytes(raw)
            backups = Path(directory) / 'public'; backups.mkdir(mode=0o755)
            for backup in (None, backups):
                with self.assertRaises(ValueError):
                    repair.repair(path, apply=True, backup_dir=backup)
                self.assertEqual(path.read_bytes(), raw)

    def test_observed_concurrent_writer_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; raw = json.dumps(fixture()).encode(); path.write_bytes(raw)
            backups = Path(directory) / 'backups'; concurrent = b'{"version":1,"theme":"dark"}'
            original = repair.assert_unchanged
            def change_then_check(*args):
                path.write_bytes(concurrent)
                return original(*args)
            with patch.object(repair, 'assert_unchanged', side_effect=change_then_check), self.assertRaises(ValueError):
                repair.repair(path, apply=True, backup_dir=backups)
            self.assertEqual(path.read_bytes(), concurrent)
            self.assertEqual(next(backups.iterdir()).read_bytes(), raw)
            self.assertEqual(list(Path(directory).glob('.native-settings-repair-*')), [])

    def test_bounded_input_and_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'; path.write_bytes(b' ' * (repair.MAX_BYTES + 1))
            with self.assertRaises(ValueError):
                repair.repair(path)
            path.write_text(json.dumps(fixture()))
            with patch.object(repair, 'MAX_BYTES', path.stat().st_size + 1), self.assertRaises(ValueError):
                repair.repair(path)


if __name__ == '__main__':
    unittest.main()
