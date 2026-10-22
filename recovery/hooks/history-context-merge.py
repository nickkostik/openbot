#!/usr/bin/env python3
"""Pure, provenance-linked history union for a detached recovery candidate.

Callers provide an explicit lineage and alias ledger. Names and timestamps are
never identity keys. This module makes no network, database, or provider calls.
"""
from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math

MAX_ROWS = 100_000
DATE_MAX_MS = 8_640_000_000_000_000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def valid_activity_time(value):
    return (type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= DATE_MAX_MS)


def owner_copy(entry, mapping):
    value = copy.deepcopy(entry)
    if isinstance(value.get('agentId'), str):
        value['agentId'] = mapping.get(value['agentId'], value['agentId'])
    return value


def checked_records(records):
    if not isinstance(records, list) or len(records) > MAX_ROWS:
        raise ValueError('History exceeds the reviewed row bound')
    result = {}
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError('History entry is not an object')
        key = entry.get('id')
        if (not isinstance(key, str) or not key or len(key.encode()) > 16_384
                or any(ord(c) < 32 for c in key) or key in result):
            raise ValueError('History entry identity is missing, duplicated, or unsupported')
        encoded(entry)
        result[key] = entry
    return result


def merge_history(baseline, current, aliases, owner_mapping, source_id):
    """Return the exact payload union in an order consistent with both inputs.

    A changed alias refuses recovery except for the reviewed native widget
    delivery annotation. Unrelated short IDs that collide retain a stable scoped
    ID. Long native UI IDs receive a reversible alias because the platform caps
    entry IDs at 128 UTF-8 bytes. Only the top-level owner and entry ID change.
    """
    base = checked_records(baseline); checked_records(current)
    if not isinstance(aliases, dict) or not isinstance(source_id, str) or not source_id:
        raise ValueError('Explicit source identity and aliases are required')
    if any(not isinstance(k, str) or not isinstance(v, str) or v not in base
           for k, v in aliases.items()):
        raise ValueError('Alias does not point to the preserved baseline')
    if len(set(aliases.values())) != len(aliases):
        raise ValueError('Alias ledger merges distinct source events')
    merged = {key: owner_copy(value, owner_mapping) for key, value in base.items()}
    source_order = []; source_aliases = {}; added = []; delivery_annotations = []
    for original in current:
        value = owner_copy(original, owner_mapping); key = value['id']
        if key in aliases:
            key = aliases[key]; value['id'] = key
            if encoded(value) != encoded(merged[key]):
                prior = merged[key]
                without_annotation = {k:v for k,v in value.items() if k != 'widgetSkipped'}
                # The platform may add this delivery result after the original
                # capture. Keep its current Boolean only when every other field
                # is byte-equivalent. No text, timestamp, or tool revision is
                # implicitly accepted; the original remains in its snapshot.
                if (prior.get('kind') != 'send-message' or 'widgetSkipped' in prior
                        or type(value.get('widgetSkipped')) is not bool
                        or encoded(without_annotation) != encoded(prior)):
                    raise ValueError('An aliased source event was revised; preserve the conflict before cutover')
                delivery_annotations.append({'id':key, 'field':'widgetSkipped',
                                             'originalSHA':digest(prior), 'currentSHA':digest(value)})
                merged[key] = value
        else:
            if key in merged:
                key = 'recovered-source-' + digest([source_id, key])
                if key in merged:
                    raise ValueError('Scoped source ID collision')
                value['id'] = key
            merged[key] = value; added.append(key)
        source_aliases[original['id']] = key; source_order.append(key)
    if len(merged) > MAX_ROWS:
        raise ValueError('Merged history exceeds the reviewed row bound')
    orderings = [list(base), source_order]
    edges = {key: set() for key in merged}; degree = {key: 0 for key in merged}
    for sequence in orderings:
        for left, right in zip(sequence, sequence[1:]):
            if left != right and right not in edges[left]:
                edges[left].add(right); degree[right] += 1
    ranks = {key: index for index, key in enumerate([*base, *added])}
    ready = [(ranks[key], key) for key in merged if degree[key] == 0]
    heapq.heapify(ready); order = []
    while ready:
        _, key = heapq.heappop(ready); order.append(key)
        for child in edges[key]:
            degree[child] -= 1
            if degree[child] == 0: heapq.heappush(ready, (ranks[child], child))
    if len(order) != len(merged):
        raise ValueError('The observed source orders contradict each other')
    positions = {key: index for index, key in enumerate(order)}
    if any(positions[a] >= positions[b] for sequence in orderings
           for a, b in zip(sequence, sequence[1:])):
        raise ValueError('A source order was lost')
    normalized = {key: key if len(key.encode()) <= 128 else
                  'recovered-entry-' + hashlib.sha256(key.encode()).hexdigest() for key in order}
    if len(set(normalized.values())) != len(order):
        raise ValueError('Native entry ID normalization collision')
    result = []
    for key in order:
        value = merged[key]; value['id'] = normalized[key]; result.append(value)
    checked_records(result)
    proof = {'baselineEntries': len(baseline), 'currentEntries': len(current),
             'newerEntries': len(added), 'mergedEntries': len(result),
             'baselineSHA': digest(baseline), 'currentSHA': digest(current),
             'mergedSHA': digest(result), 'bothSourceOrdersPreserved': True,
             'payloadsPreservedExceptOwnerIdAndDeliveryAnnotation': True,
             'deliveryAnnotations': delivery_annotations,
             'normalizedEntryIds': sum(k != v for k, v in normalized.items()),
             'baselineAliases': {key: normalized[key] for key in base},
             'currentAliases': {key: normalized[value] for key, value in source_aliases.items()}}
    return result, proof


def background_records(entries, original_ids=None):
    """Quote plain text as background; never promote a tool/attachment."""
    checked_records(entries); result = []
    for entry in entries:
        role = text = None
        if (entry.get('kind') == 'message' and entry.get('role') in ('user', 'assistant')
                and isinstance(entry.get('content'), str)):
            role, text = entry['role'], entry['content']
        elif (entry.get('kind') == 'send-message' and isinstance(entry.get('message'), dict)
              and entry['message'].get('type') == 'text'
              and isinstance(entry['message'].get('content'), str)):
            role, text = 'assistant', entry['message']['content']
        if role is None: continue
        timestamp = entry.get('timestampMs')
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            raise ValueError('Literal text has an unsupported timestamp representation')
        record = {'id': entry['id'], 'originalId': (original_ids or {}).get(entry['id'], entry['id']),
                  'role': role, 'text': text, 'kind': entry['kind'], 'literalText': True,
                  'timestampMs': timestamp, 'sourcePayloadSha256': digest(entry),
                  'attribution': {key: copy.deepcopy(entry[key]) for key in
                                  ('fromAgent', 'toAgent', 'channel', 'channelSender', 'wake', 'richText')
                                  if key in entry}}
        if not valid_activity_time(timestamp): record['timestampState'] = 'invalid-preserved'
        result.append(record)
    return result
