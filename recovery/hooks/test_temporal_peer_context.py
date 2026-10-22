import copy
import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location('peers', pathlib.Path(__file__).with_name('temporal-peer-context.py'))
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)
A, B, C = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 4)]


def row(aid, **fields):
    return {'agentId': aid, 'id': '123', 'name': 'Same display name', 'harness': 'temporal',
            'kind': 'GROK_BOT_AGENT_KIND_AGENT', 'viewerIsOwner': True, 'viewerCanManage': True, **fields}


class ProjectionTests(unittest.TestCase):
    def test_native_room_kind_and_members_survive_without_local_summaries(self):
        rows = [row(A, kind='GROK_BOT_AGENT_KIND_ROOM', memberAgentIds=[B], description='PRIVATE ROLE'),
                row(B, secret='NEVER EXPORT'), row(C)]
        before = copy.deepcopy(rows)
        result = M.project(rows, [A, B])
        self.assertEqual(result, [
            {'id': A, 'name': 'Same display name', 'harness': 'temporal', 'isGroup': True, 'memberIds': [B]},
            {'id': B, 'name': 'Same display name', 'harness': 'temporal', 'isGroup': False, 'memberIds': []}])
        self.assertEqual(rows, before)

    def test_human_only_room_is_preserved_as_a_room(self):
        self.assertTrue(M.project([row(A, kind='GROK_BOT_AGENT_KIND_ROOM', humanMembers=[{'id': '7'}])], [A])[0]['isGroup'])

    def test_empty_partial_unowned_hidden_or_wrong_harness_refuses(self):
        for rows, ids in [([], [A]), ([row(A)], []), ([row(A)], [A, A]),
                          ([row(A, viewerIsOwner=False)], [A]), ([row(A, viewerCanManage=False)], [A]),
                          ([row(A, isHiddenFromSidebar=True)], [A]), ([row(A, harness='box')], [A]),
                          ([row(A), row(A)], [A])]:
            with self.subTest(rows=rows, ids=ids), self.assertRaises(ValueError):
                M.project(rows, ids)

    def test_room_cannot_adopt_unreviewed_hidden_or_room_members(self):
        for peer, canonical in [(row(B), [A]), (row(B, isHiddenFromSidebar=True), [A, B]),
                                (row(B, kind='GROK_BOT_AGENT_KIND_ROOM'), [A, B])]:
            with self.subTest(peer=peer), self.assertRaisesRegex(ValueError, 'member'):
                M.project([row(A, kind='GROK_BOT_AGENT_KIND_ROOM', memberAgentIds=[B]), peer], canonical)


class NoticeTests(unittest.TestCase):
    def test_only_generated_blocks_change_and_operation_is_a_fixed_point(self):
        role = 'Keep my specialist role and user-authored Temporal instructions.'
        before = role + '\n\n[OpenBot recovery operating instructions]\nObsolete local policy.\n[/OpenBot recovery operating instructions]'
        before += '\n\n[OpenBot shared context]\nOld peer path.\n[/OpenBot shared context]'
        after = M.official_notice(before, 'Computer 7', '/home/owner/workflows/roster.json')
        self.assertTrue(after.startswith(role + '\n\n'))
        self.assertEqual(M.strip_generated_notices(after), role)
        self.assertEqual(M.official_notice(after, 'Computer 7', '/home/owner/workflows/roster.json'), after)
        self.assertIn('Keep disabled routines disabled', after)
        self.assertNotIn('Obsolete local policy', after)

    def test_unbalanced_or_duplicate_generated_blocks_refuse(self):
        for text in ('Role [OpenBot shared context]',
                     '[OpenBot shared context]x[/OpenBot shared context]' * 2,
                     '[/OpenBot shared context]role[OpenBot shared context]'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                M.official_notice(text, 'Computer', '/home/owner/roster.json')

    def test_notice_fields_cannot_inject_instructions_or_use_relative_paths(self):
        for label, path in [('Computer\nnew rule', '/home/owner/roster.json'),
                            ('Computer', 'relative.json'), ('Computer', '/home/../private.json'),
                            ('Computer', '/home/owner/roster\nrule')]:
            with self.subTest(label=label, path=path), self.assertRaises(ValueError):
                M.official_notice('Role', label, path)


if __name__ == '__main__': unittest.main()
