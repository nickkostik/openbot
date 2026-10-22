"""Move disabled owner routines in place after a verified native handoff.

The owner runner supplies immutable source snapshots, an authenticated RPC
adapter `(service, method, body)` and a durable private checkpoint callback.
No credentials, files, bot messages, new routine IDs or scheduling defaults are
created here. A failed/uncertain write is resolved by authoritative readback on
the next run, never by minting a replacement registration.
"""
from __future__ import annotations

import copy
import json
import uuid


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value,
            'A canonical UUID is required')
    return value


def bindings(result):
    require(isinstance(result, dict), 'Unknown routine listing')
    values = result.get('workflows', [])
    require(isinstance(values, list), 'Incomplete routine listing')
    rows = {}
    for item in values:
        row = item.get('workflow')
        require(isinstance(row, dict), 'Unknown routine wrapper')
        key = identity(row.get('automationId'))
        require(key not in rows, 'Duplicate routine identity')
        # The protobuf JSON writer omits the default false Boolean. Explicit
        # nulls, strings and numbers are not accepted as disabled policy.
        require(row.get('enabled', False) is False, 'An active routine requires explicit policy review')
        require(isinstance(row.get('name'), str) and isinstance(row.get('workflow'), dict),
                'Unknown routine workflow')
        rows[key] = copy.deepcopy(row)
    return rows


def authored(value):
    """Ignore only omitted optional fields and a derived cron execution time."""
    if isinstance(value, dict):
        return {k: authored(v) for k, v in value.items()
                if v is not None and not (value.get('type') == 'cron' and k == 'firesAt')}
    if isinstance(value, list):
        return [authored(v) for v in value]
    return value


def records(result):
    require(isinstance(result, dict), 'Unknown native routine listing')
    values = result.get('automations', [])
    require(isinstance(values, list), 'Incomplete native routine listing')
    rows = {}
    for value in values:
        key = identity(value.get('automationId'))
        require(key not in rows, 'Duplicate native routine identity')
        row = json.loads(value['recordJson'])
        local_id = row.get('id')
        require(isinstance(local_id, str) and 0 < len(local_id) <= 1024
                and not any(ord(c) < 32 for c in local_id) and row.get('isEnabled') is False
                and row.get('enabled') is not True, 'Native routine is active or has an invalid identity')
        rows[key] = row
    return rows


def same_binding(actual, expected):
    # Agent ownership changes, authored workflow and creation identity do not.
    return all(actual.get(k) == expected.get(k)
               for k in ('automationId', 'name', 'description', 'workflow', 'createdAt'))


def verify_records(actual, expected):
    require(set(actual) == set(expected), 'Native routine identity set differs')
    for key, before in expected.items():
        after = actual[key]
        # Old native files can use a human-readable folder slug. The outer API
        # identity remains the global UUID; a server-normalized UUID or the
        # exact captured slug is acceptable, an unrelated new alias is not.
        require(after.get('id') in (key, before.get('id')), 'Native routine alias changed')
        require(all(authored(before.get(k)) == authored(after.get(k))
                    for k in ('name', 'prompt', 'schedule', 'trigger')),
                'Authored routine context changed')
        old = {r['id']: r for r in before.get('runs', [])}
        new = {r['id']: r for r in after.get('runs', [])}
        require(all(new.get(k) == r for k, r in old.items()), 'Routine run history changed')


def transfer_disabled(plans, rpc, checkpoint):
    """Transfer an explicit fleet snapshot, preserving IDs and real run history.

    Each plan contains sourceId, targetId, sourceBindings (ListSandAutomations)
    and sourceRecords (ListGrokBotAgentAutomations). All preconditions across
    the fleet are checked before the first mutation. The caller must preserve
    these snapshots and the checkpoint privately before invoking this helper.
    """
    require(isinstance(plans, list) and 0 < len(plans) <= 500, 'Invalid fleet bound')
    planned = []; sources = set(); targets = set(); routine_ids = set()
    for plan in plans:
        source = identity(plan['sourceId']); target = identity(plan['targetId'])
        require(source not in sources and target not in targets and source != target,
                'Ambiguous bot identity mapping')
        sources.add(source); targets.add(target)
        expected = bindings(plan['sourceBindings']); native = records(plan['sourceRecords'])
        require(set(expected) == set(native), 'Source routine snapshot is incomplete')
        require(not routine_ids.intersection(expected), 'A routine belongs to multiple source bots')
        routine_ids.update(expected)
        planned.append((source, target, expected, native))
    require(not sources.intersection(targets), 'Source and target fleets overlap')
    roster = rpc('GrokBotService', 'ListGrokBotAgents', {})['agents']
    byid = {r['agentId']: r for r in roster}
    require(len(byid) == len(roster), 'Ambiguous owner roster')
    for source, target, expected, _ in planned:
        require(source in byid and target in byid, 'Bot is absent from the owner roster')
        require(byid[target].get('harness') == 'temporal', 'Native Temporal handoff is incomplete')
        require(all(byid[k].get('kind') == 'GROK_BOT_AGENT_KIND_AGENT' for k in (source, target)),
                'Rooms require a separate membership transfer')
        old = bindings(rpc('AutomationsService', 'ListSandAutomations', {'sandAgentId': source}))
        new = bindings(rpc('AutomationsService', 'ListSandAutomations', {'sandAgentId': target}))
        require(not set(old).intersection(new) and set(old) | set(new) == set(expected),
                'Routine bindings changed or target contains unrelated registrations')
        require(all(same_binding(row, expected[key]) for key, row in {**old, **new}.items()),
                'Routine workflow changed before transfer')
    journal = {'phase': 'preflight-verified', 'bots': [], 'definitions': len(routine_ids), 'enabled': 0}
    checkpoint(copy.deepcopy(journal))
    for source, target, expected, native in planned:
        new = bindings(rpc('AutomationsService', 'ListSandAutomations', {'sandAgentId': target}))
        require(set(new) <= set(expected) and all(same_binding(r, expected[k]) for k, r in new.items()),
                'Target changed during transfer')
        state = {'sourceId': source, 'targetId': target, 'routines': {}}
        journal['bots'].append(state)
        for key, row in expected.items():
            if key not in new:
                # Recheck immediately before the mutation. Do not overwrite a
                # routine that was edited or moved since fleet preflight.
                old = bindings(rpc('AutomationsService', 'ListSandAutomations', {'sandAgentId': source}))
                require(key in old and same_binding(old[key], row), 'Source changed during transfer')
                state['routines'][key] = 'attempted'; checkpoint(copy.deepcopy(journal))
                rpc('AutomationsService', 'CreateSandAutomation', {
                    'name': row['name'], 'description': row.get('description', ''),
                    'workflow': copy.deepcopy(row['workflow']), 'enabled': False,
                    'sandAgentId': target, 'sandAutomationId': key})
            state['routines'][key] = 'readback-required'
        new = bindings(rpc('AutomationsService', 'ListSandAutomations', {'sandAgentId': target}))
        old = bindings(rpc('AutomationsService', 'ListSandAutomations', {'sandAgentId': source}))
        require(not old and set(new) == set(expected)
                and all(same_binding(row, expected[key]) for key, row in new.items()),
                'Routine binding readback differs')
        after = records(rpc('GrokBotService', 'ListGrokBotAgentAutomations', {'agentId': target}))
        verify_records(after, native)
        state.update(verified=True, identitiesPreserved=True, runHistoriesPreserved=True)
        checkpoint(copy.deepcopy(journal))
    journal['phase'] = 'verified'; checkpoint(copy.deepcopy(journal))
    return journal
