import copy
import importlib.util
import json
import pathlib
import unittest
import uuid

spec = importlib.util.spec_from_file_location('transfer', pathlib.Path(__file__).with_name('temporal-routine-transfer.py'))
transfer = importlib.util.module_from_spec(spec); spec.loader.exec_module(transfer)


def key(name):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


class Owner:
    def __init__(self):
        self.source = key('source.example'); self.target = key('target.example')
        self.rid = key('routine.example'); self.owner = {self.rid: self.source}
        self.row = {'automationId': self.rid, 'name': 'Synthetic reminder',
                    'description': '', 'enabled': False, 'createdAt': '1700000000',
                    'workflow': {'prompts': [{'prompt': 'Preserve this test instruction'}]}}
        self.record = {'id': self.rid, 'name': self.row['name'], 'isEnabled': False,
                       'prompt': 'Preserve this test instruction',
                       'trigger': {'type': 'cron', 'cron': '0 9 * * *', 'firesAt': 10},
                       'schedule': '0 9 * * *', 'runs': [{'id': 'run-1', 'status': 'completed'}]}
        self.rows = {self.rid: copy.deepcopy(self.row)}
        self.roster = [{'agentId': i, 'harness': 'temporal', 'kind': 'GROK_BOT_AGENT_KIND_AGENT'}
                       for i in (self.source, self.target)]
        self.calls = []; self.receipts = []; self.timeout = False; self.drop_run = False

    def listing(self, aid):
        return {'workflows': [{'workflow': copy.deepcopy(self.rows[k])}
                              for k, owner in self.owner.items() if owner == aid]}

    def native(self, aid):
        values = []
        for k, owner in self.owner.items():
            if owner == aid:
                record = copy.deepcopy(self.record); record['id'] = k
                if self.drop_run: record['runs'] = []
                values.append({'automationId': k, 'recordJson': json.dumps(record)})
        return {'automations': values}

    def plan(self):
        return [{'sourceId': self.source, 'targetId': self.target,
                 'sourceBindings': self.listing(self.source), 'sourceRecords': self.native(self.source)}]

    def rpc(self, service, method, body):
        self.calls.append((service, method, copy.deepcopy(body)))
        if method == 'ListGrokBotAgents': return {'agents': copy.deepcopy(self.roster)}
        if method == 'ListSandAutomations': return self.listing(body['sandAgentId'])
        if method == 'ListGrokBotAgentAutomations': return self.native(body['agentId'])
        if method == 'CreateSandAutomation':
            assert service == 'AutomationsService' and body['enabled'] is False
            assert self.receipts and self.receipts[-1]['bots'][-1]['routines'][self.rid] == 'attempted'
            self.owner[body['sandAutomationId']] = body['sandAgentId']
            if self.timeout:
                self.timeout = False
                raise TimeoutError('Uncertain write outcome')
            return {}
        raise AssertionError(method)

    def run(self, plan=None):
        return transfer.transfer_disabled(plan or self.plan(), self.rpc, self.receipts.append)


class TransferTests(unittest.TestCase):
    def test_moves_same_id_with_exact_workflow_and_real_runs(self):
        o = Owner(); original = copy.deepcopy(o.row); result = o.run()
        self.assertEqual(o.owner, {o.rid: o.target})
        self.assertEqual(o.rows[o.rid], original)
        writes = [body for _, method, body in o.calls if method == 'CreateSandAutomation']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['sandAutomationId'], o.rid)
        self.assertEqual(writes[0]['workflow'], original['workflow'])
        self.assertEqual(result['phase'], 'verified')
        self.assertTrue(result['bots'][0]['runHistoriesPreserved'])

    def test_uncertain_success_resumes_by_readback_without_new_create(self):
        o = Owner(); plan = o.plan(); o.timeout = True
        with self.assertRaises(TimeoutError): o.run(plan)
        result = o.run(plan)
        self.assertEqual(sum(method == 'CreateSandAutomation' for _, method, _ in o.calls), 1)
        self.assertEqual(result['phase'], 'verified')

    def test_active_source_refuses_before_any_write(self):
        o = Owner(); plan = o.plan(); o.rows[o.rid]['enabled'] = True
        with self.assertRaisesRegex(ValueError, 'active'): o.run(plan)
        self.assertFalse(any(m == 'CreateSandAutomation' for _, m, _ in o.calls))

    def test_new_target_registration_refuses_without_deleting_it(self):
        o = Owner(); plan = o.plan(); extra = key('extra.example')
        o.owner[extra] = o.target; o.rows[extra] = {**o.row, 'automationId': extra}
        with self.assertRaisesRegex(ValueError, 'unrelated'): o.run(plan)
        self.assertEqual(o.owner[extra], o.target)
        self.assertFalse(any(m == 'CreateSandAutomation' for _, m, _ in o.calls))

    def test_changed_prompt_refuses_before_write(self):
        o = Owner(); plan = o.plan(); o.rows[o.rid]['workflow']['prompts'][0]['prompt'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'workflow changed'): o.run(plan)
        self.assertEqual(o.owner[o.rid], o.source)

    def test_missing_run_history_never_marks_verified(self):
        o = Owner(); plan = o.plan(); o.drop_run = True
        with self.assertRaisesRegex(ValueError, 'run history'): o.run(plan)
        self.assertFalse(any(r['phase'] == 'verified' for r in o.receipts))

    def test_incomplete_native_handoff_refuses_before_write(self):
        o = Owner(); o.roster[1]['harness'] = 'box'
        with self.assertRaisesRegex(ValueError, 'handoff'): o.run()
        self.assertFalse(o.receipts)

    def test_checkpoint_failure_stops_before_network_mutation(self):
        o = Owner()
        def fail(_): raise OSError('Private snapshot not durable')
        with self.assertRaises(OSError): transfer.transfer_disabled(o.plan(), o.rpc, fail)
        self.assertEqual(o.owner[o.rid], o.source)

    def test_duplicate_and_overlapping_fleets_refuse(self):
        o = Owner(); plan = o.plan()
        with self.assertRaisesRegex(ValueError, 'Ambiguous'): o.run(plan + plan)
        second = copy.deepcopy(plan[0]); second['sourceId'] = o.target; second['targetId'] = key('other.example')
        second['sourceBindings']['workflows'] = []; second['sourceRecords']['automations'] = []
        with self.assertRaisesRegex(ValueError, 'overlap'): o.run(plan + [second])

    def test_only_derived_cron_time_and_optional_nulls_may_differ(self):
        o = Owner(); before = {o.rid: copy.deepcopy(o.record)}; after = copy.deepcopy(before)
        after[o.rid]['trigger']['firesAt'] = 20; after[o.rid]['optional'] = None
        transfer.verify_records(after, before)
        after[o.rid]['trigger']['cron'] = '1 9 * * *'
        with self.assertRaisesRegex(ValueError, 'context changed'): transfer.verify_records(after, before)

    def test_proto_default_false_and_empty_arrays_are_valid(self):
        o = Owner(); del o.rows[o.rid]['enabled']
        self.assertEqual(o.run()['phase'], 'verified')
        self.assertEqual(transfer.bindings({}), {})
        self.assertEqual(transfer.records({}), {})
        for invalid in (None, 0, '', 'false', True):
            row = {**o.row, 'enabled': invalid}
            with self.assertRaises(ValueError): transfer.bindings({'workflows': [{'workflow': row}]})

    def test_explicit_legacy_folder_slug_may_normalize_to_global_id(self):
        o = Owner(); source = o.native(o.source); before = json.loads(source['automations'][0]['recordJson'])
        before['id'] = 'synthetic-old-folder'; source['automations'][0]['recordJson'] = json.dumps(before)
        expected = transfer.records(source)
        actual = {o.rid: copy.deepcopy(o.record)}
        transfer.verify_records(actual, expected)
        actual[o.rid]['id'] = 'unrelated-folder'
        with self.assertRaisesRegex(ValueError, 'alias changed'): transfer.verify_records(actual, expected)


if __name__ == '__main__': unittest.main()
