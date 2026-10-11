"""Apply a bounded recovery notice to existing local bots, without reminting."""
import argparse
import concurrent.futures
import json
import pathlib
import re
import time
import urllib.error
import urllib.request
import uuid

SD = pathlib.Path('/home/box/sand-data')
WORKING = '87c7460c-b7c4-41bb-bf5a-862cd63b61df'
START = '[OpenBot recovery operating instructions]'
END = '[/OpenBot recovery operating instructions]'
NOTICE = '''Your existing role and the user's latest instructions still apply.
This installation runs on this computer using OpenBot. Do not attempt to repair routing by creating replacement bots, registering identities with the platform, migrating to temporal, or changing harness/bindings.
Use your current bot id. Old bot ids in recovered transcripts are historical; resolve colleagues through /home/box/agent-data/workflows/openbot-fleet/roster.json and the current roster. Do not send to retired copies or invent group members.
Do not change OpenBot model/provider selection, per-bot reasoning, host patches, watchers, tunnels, sidebar membership, secrets, or shared configuration as background housekeeping. Acknowledge faults accurately and leave fleet infrastructure repairs to the current authorized repair session; perform infrastructure changes only on a new explicit user request.
Honor the selected OpenBot route and any deliberate per-bot override. Never silently fall back to metered Grok, MetaKey, or n5. Do not print credentials.
Keep disabled automations disabled. Do not restart stale plans, repair loops, or broadcasts from recovered history. Continue only current user-directed work.
When asked for a reply, use the normal user-message tool. Do not claim delivery, app visibility, cache performance, or a repair is verified without fresh evidence. On an actual failure, report it once with the observed error; do not make repeated configuration edits.
'''


def gw(method, body=None):
    token = json.loads((SD / 'gateway.json').read_text())['token']
    req = urllib.request.Request('http://127.0.0.1:1340/api/' + method,
        data=json.dumps(body or {}).encode(), headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'{method}: HTTP {exc.code}: {exc.read(500).decode()}') from exc


def write(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def prepare():
    journal = json.loads((SD / 'openbot-local-migration.json').read_text())
    rows = {row['id']: row for row in gw('listAgents')}
    entries = [e for e in journal['entries'] if not re.search(r'\bprobe\b|verification', e['name'], re.I)]
    entries.append({'name': rows[WORKING]['name'], 'newId': WORKING, 'oldId': None})
    targets = []
    for entry in entries:
        aid = entry['newId']
        profile = json.loads((SD / 'agents' / aid / 'profile.json').read_text())
        if profile.get('harness') != 'box':
            raise RuntimeError(f'Refusing non-box profile: {aid}')
        row = rows.get(aid)
        if not row:
            raise RuntimeError(f'Local bot missing from gateway roster: {aid}')
        targets.append({**entry, 'isGroup': row.get('isGroup', False), 'profile': profile})
    run = SD / 'recovery-snapshots' / (time.strftime('%Y%m%d-%H%M%S') + '-fleet-instructions')
    write(run / 'profiles-before.json', targets)
    write(run / 'host-settings-before.json', gw('getHostSettings'))
    roster = [{'id': e['newId'], 'retiredId': e['oldId'], 'name': e['name'], 'isGroup': e['isGroup']} for e in targets]
    write('/home/box/agent-data/openbot-recovery/roster.json', roster)
    write(run / 'plan.json', {'targets': targets, 'results': []})
    print(str(run), flush=True)
    return run


def persist(run):
    plan = json.loads((run / 'plan.json').read_text())
    for entry in plan['targets']:
        aid = entry['newId']
        profile = json.loads((SD / 'agents' / aid / 'profile.json').read_text())
        original = re.sub(re.escape(START) + r'[\s\S]*?' + re.escape(END), '', profile.get('description', '')).strip()
        allowed = {k: profile[k] for k in ('name', 'title', 'avatarShape', 'avatarColor') if k in profile}
        allowed['description'] = (original + '\n\n' if original else '') + START + '\n' + NOTICE + END
        try:
            result = gw('updateAgent', {'id': aid, 'profile': allowed})
            if result is None:
                raise RuntimeError('updateAgent returned no bot')
            after = json.loads((SD / 'agents' / aid / 'profile.json').read_text())
            if START not in after.get('description', '') or after.get('harness') != 'box':
                raise RuntimeError('Persistent notice or local harness verification failed')
            gw('setAgentHiddenFromSidebar', {'id': aid, 'isHidden': False})
            outcome = {'id': aid, 'name': entry['name'], 'persisted': True}
        except Exception as exc:
            outcome = {'id': aid, 'name': entry['name'], 'error': str(exc)}
        plan['results'].append(outcome)
        write(run / 'plan.json', plan)
        print(json.dumps(outcome), flush=True)


def send_one(entry, run):
    aid = entry['newId']
    receipt = 'RECOVERY-ACK-' + aid[:8]
    nonce = str(uuid.uuid4())
    record = {'id': aid, 'name': entry['name'], 'receipt': receipt, 'nonce': nonce, 'startedAtMs': int(time.time() * 1000)}
    prompt = ('The user requests a fleet-wide recovery instruction update. Read and follow this notice now:\n' +
        NOTICE + '\nThis is an acknowledgment-only turn. Do not inspect or edit files, run commands, contact colleagues, or start any background work. Use SendToUser to reply with exactly ' + receipt + ' then stop.')
    try:
        record['acceptance'] = gw('sendPrompt', {'agentId': aid, 'prompt': prompt, 'clientNonce': nonce})
        write(run / (aid + '.json'), record)
        print(json.dumps({k: record[k] for k in ('id', 'name', 'acceptance')}), flush=True)
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            tail = gw('getAgentTranscriptTail', {'id': aid, 'limit': 10})
            replies = [e for e in tail.get('entries', []) if e.get('kind') == 'send-message' and
                e.get('timestampMs', 0) >= record['startedAtMs'] and receipt in json.dumps(e.get('message', {}))]
            if replies:
                record['reply'] = replies[-1]
                record['acknowledged'] = True
                break
            time.sleep(3)
        if not record.get('acknowledged'):
            record['error'] = 'Accepted but no acknowledgment in transcript within 100 seconds'
    except Exception as exc:
        record['error'] = str(exc)
    write(run / (aid + '.json'), record)
    print(json.dumps({k: record.get(k) for k in ('id', 'name', 'acknowledged', 'error')}), flush=True)
    return record


def send(run, pilot=False):
    plan = json.loads((run / 'plan.json').read_text())
    ok = {r['id'] for r in plan['results'] if r.get('persisted')}
    targets = [e for e in plan['targets'] if not e['isGroup'] and e['newId'] in ok]
    if pilot:
        targets = [e for e in targets if e['name'] == 'Q']
    else:
        targets = [e for e in targets if not (run / (e['newId'] + '.json')).exists()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(lambda entry: send_one(entry, run), targets))
    print(json.dumps({'sent': len(records), 'acknowledged': sum(bool(r.get('acknowledged')) for r in records),
        'failures': [r['id'] for r in records if r.get('error')]}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'persist', 'pilot', 'send'])
    parser.add_argument('run', nargs='?')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    else:
        run = pathlib.Path(args.run)
        if args.action == 'persist':
            persist(run)
        else:
            send(run, pilot=args.action == 'pilot')
