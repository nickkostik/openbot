import copy
import importlib.util
import pathlib
import unittest

SPEC = importlib.util.spec_from_file_location('rooms', pathlib.Path(__file__).with_name('temporal-room-transfer.py'))
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)
A, B, C, D, E = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 6)]


def row(aid, kind='AGENT', **fields):
    return {'agentId': aid, 'id': '123' if aid == A else '456', 'harness': 'temporal',
            'kind': 'GROK_BOT_AGENT_KIND_' + kind, 'viewerIsOwner': True, 'viewerCanManage': True,
            'name': 'Existing name', **fields}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.rows = [row(A, 'ROOM', humanMembers=[{'userId': '7'}]), row(B), row(E, 'ROOM')]
        self.plan = [{'sourceId': C, 'sourceMemberIds': [D], 'targetId': A,
                      'targetServerId': '123', 'beforeMemberIds': []}]
        self.calls = []; self.checkpoints = []; self.timeout_after_write = False

    def rpc(self, service, method, body):
        self.calls.append((service, method, copy.deepcopy(body)))
        self.assertEqual(service, 'GrokBotService')
        if method == 'ListGrokBotAgents': return {'agents': copy.deepcopy(self.rows)}
        self.assertEqual(method, 'SetGrokBotRoomMembers')
        self.assertEqual(self.checkpoints[-1]['rooms'][-1]['phase'], 'write-attempted')
        room = next(r for r in self.rows if r['agentId'] == body['agentId'])
        room['memberAgentIds'] = body['memberAgentIds']; room['updatedAtMs'] = '999'
        if self.timeout_after_write: raise TimeoutError('Uncertain network outcome')
        return {'agent': copy.deepcopy(room)}

    def run_transfer(self, plans=None, mapping=None):
        return M.restore_memberships(plans or self.plan, mapping or {D: B}, [B], self.rpc, self.checkpoints.append)

    def writes(self): return [call for call in self.calls if call[1] != 'ListGrokBotAgents']


class TransferTests(Fixture):
    def test_exact_members_restore_and_receipt_does_not_claim_histories(self):
        before = copy.deepcopy(self.rows); source = copy.deepcopy(self.plan)
        receipt = self.run_transfer()
        self.assertEqual(self.rows[0]['memberAgentIds'], [B])
        self.assertEqual(self.rows[0]['humanMembers'], before[0]['humanMembers'])
        self.assertEqual(self.rows[1:], before[1:]); self.assertEqual(self.plan, source)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(receipt['scope'], 'room-memberships-only')
        self.assertEqual(receipt['phase'], 'verified')
        self.assertNotIn('historiesVerified', receipt)
        self.assertNotIn('completeTransfer', receipt)

    def test_repeated_run_has_no_writes(self):
        self.run_transfer(); self.calls = []
        self.assertEqual(self.run_transfer()['phase'], 'verified')
        self.assertEqual(self.writes(), [])

    def test_uncertain_response_is_resolved_by_readback_without_replaying(self):
        self.timeout_after_write = True
        with self.assertRaises(TimeoutError): self.run_transfer()
        self.timeout_after_write = False; self.calls = []
        self.assertEqual(self.run_transfer()['phase'], 'verified')
        self.assertEqual(self.writes(), [])

    def test_whole_fleet_validation_precedes_any_mutation(self):
        plans = copy.deepcopy(self.plan)
        plans.append({**plans[0], 'targetId': E, 'targetServerId': 'wrong'})
        with self.assertRaises(ValueError): self.run_transfer(plans)
        self.assertEqual(self.writes(), [])

    def test_fresh_user_membership_edit_is_preserved(self):
        self.rows[0]['memberAgentIds'] = [E]
        with self.assertRaisesRegex(ValueError, 'edited'): self.run_transfer()
        self.assertEqual(self.rows[0]['memberAgentIds'], [E]); self.assertEqual(self.writes(), [])

    def test_missing_mapping_and_wrong_server_identity_fail_before_writing(self):
        for key, value in [('sourceMemberIds', [C]), ('targetServerId', '888')]:
            plan = [{**self.plan[0], key: value}]
            with self.subTest(key=key), self.assertRaises(ValueError): self.run_transfer(plan)
        self.assertEqual(self.writes(), [])

    def test_hidden_or_unowned_member_and_wrong_harness_refuse(self):
        for key, value in [('isHiddenFromSidebar', True), ('viewerIsOwner', False),
                           ('viewerCanManage', False), ('harness', 'box'),
                           ('kind', 'GROK_BOT_AGENT_KIND_ROOM')]:
            before = copy.deepcopy(self.rows[1]); self.rows[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.run_transfer()
            self.rows[1] = before
        self.assertEqual(self.writes(), [])

    def test_collapsed_member_mapping_does_not_merge_distinct_source_members(self):
        self.plan[0]['sourceMemberIds'] = [C, D]
        with self.assertRaisesRegex(ValueError, 'duplicated'): self.run_transfer(mapping={C: B, D: B})
        self.assertEqual(self.writes(), [])

    def test_unrelated_human_membership_change_is_detected(self):
        original = self.rpc
        def edited(service, method, body):
            response = original(service, method, body)
            if method == 'SetGrokBotRoomMembers': self.rows[0]['humanMembers'] = []
            return response
        with self.assertRaisesRegex(ValueError, 'human membership'):
            M.restore_memberships(self.plan, {D:B}, [B], edited, self.checkpoints.append)


if __name__ == '__main__': unittest.main()
