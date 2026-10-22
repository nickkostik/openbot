"""Restore explicit archived room membership through the native owner API.

This is membership recovery only. A verified receipt makes no assertion about
merged room history, working context, live replies or a complete fleet transfer.
The owner runner supplies reviewed identity mappings, immutable source snapshots
and a durable private checkpoint callback. No bot or routine is created.
"""
from __future__ import annotations

import copy
import uuid


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value,
            'Expected a canonical bot UUID')
    return value


def member_ids(values):
    require(isinstance(values, list) and len(values) <= 100, 'Unknown room membership schema')
    values = [identity(value) for value in values]
    require(len(values) == len(set(values)), 'Room membership is duplicated')
    return values


def native_rows(rpc):
    response = rpc('GrokBotService', 'ListGrokBotAgents', {})
    require(isinstance(response, dict) and isinstance(response.get('agents'), list),
            'Owner roster is incomplete')
    rows = {}
    for row in response['agents']:
        aid = identity(row.get('agentId'))
        require(aid not in rows, 'Native bot identity is ambiguous')
        rows[aid] = row
    return rows


def managed(row, kind):
    require(isinstance(row, dict) and row.get('harness') == 'temporal'
            and row.get('kind') == kind and row.get('viewerIsOwner') is True
            and row.get('viewerCanManage') is True, 'Owned Temporal identity is not verified')


def room_check(rows, plan):
    row = rows.get(plan['targetId'])
    managed(row, 'GROK_BOT_AGENT_KIND_ROOM')
    require(row.get('id') == plan['targetServerId'], 'Room server identity changed')
    actual = member_ids(row.get('memberAgentIds', []))
    require(actual in (plan['beforeMemberIds'], plan['memberIds']),
            'Room membership was edited; no replacement applied')
    for aid in plan['memberIds']:
        peer = rows.get(aid)
        managed(peer, 'GROK_BOT_AGENT_KIND_AGENT')
        require(peer.get('isHiddenFromSidebar') is not True
                and peer.get('isRemovedFromSidebar') is not True,
                'Room member is hidden or removed')
    return row, actual


def restore_memberships(plans, identity_mapping, canonical_agent_ids, rpc, checkpoint):
    """Restore reviewed rooms; uncertain writes are resolved by native readback.

    Each plan has sourceId, sourceMemberIds, targetId, targetServerId and
    beforeMemberIds from private preserved snapshots. The explicit mapping maps
    every archived member ID to a previously verified canonical Temporal bot.
    The canonical allowlist must be checked against native client visibility;
    the owner roster alone does not include that sidebar state.
    All rooms and members pass preflight before the first mutation.
    """
    require(isinstance(plans, list) and 0 < len(plans) <= 500, 'Invalid room fleet bound')
    require(isinstance(identity_mapping, dict), 'Explicit member identity mapping is required')
    mapping = {identity(key): identity(value) for key, value in identity_mapping.items()}
    canonical = member_ids(canonical_agent_ids)
    prepared = []; targets = set()
    for original in plans:
        source = identity(original['sourceId']); target = identity(original['targetId'])
        require(target not in targets, 'A room has multiple transfer plans')
        targets.add(target)
        source_members = member_ids(original['sourceMemberIds'])
        require(source_members and all(aid in mapping for aid in source_members),
                'Archived member identity mapping is incomplete')
        expected = member_ids([mapping[aid] for aid in source_members])
        require(all(aid in canonical for aid in expected), 'A member is outside the canonical fleet')
        before = member_ids(original['beforeMemberIds'])
        # An old complete membership can be explicitly captured for remapping,
        # but partial/interleaved user edits are never accepted implicitly.
        require(not before or before == source_members or before == expected,
                'Before membership is not the captured source or verified target')
        sid = original['targetServerId']
        require(isinstance(sid, str) and sid.isdecimal(), 'Exact room server ID is required')
        prepared.append({'sourceId': source, 'sourceMemberIds': source_members,
                         'targetId': target, 'targetServerId': sid,
                         'beforeMemberIds': before, 'memberIds': expected})
    rows = native_rows(rpc)
    for plan in prepared:
        room_check(rows, plan)
    journal = {'phase': 'preflight-verified', 'scope': 'room-memberships-only', 'rooms': []}
    checkpoint(copy.deepcopy(journal))
    for plan in prepared:
        before, actual = room_check(native_rows(rpc), plan)
        state = {'sourceId': plan['sourceId'], 'targetId': plan['targetId'],
                 'members': len(plan['memberIds']), 'phase': 'readback-required'}
        journal['rooms'].append(state)
        if actual != plan['memberIds']:
            state['phase'] = 'write-attempted'; checkpoint(copy.deepcopy(journal))
            rpc('GrokBotService', 'SetGrokBotRoomMembers', {
                'agentId': plan['targetId'], 'memberAgentIds': list(plan['memberIds'])})
        after, actual = room_check(native_rows(rpc), plan)
        require(actual == plan['memberIds'], 'Room membership readback differs')
        require({k:v for k,v in before.items() if k not in ('memberAgentIds', 'updatedAtMs')} ==
                {k:v for k,v in after.items() if k not in ('memberAgentIds', 'updatedAtMs')},
                'Unrelated room metadata or human membership changed')
        state['phase'] = 'verified'; checkpoint(copy.deepcopy(journal))
    journal['phase'] = 'verified'; checkpoint(copy.deepcopy(journal))
    return journal
