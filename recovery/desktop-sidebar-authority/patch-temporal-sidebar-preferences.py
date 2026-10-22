#!/usr/bin/env python3
"""Use server sidebar preferences without depending on an awake legacy Computer."""
from __future__ import annotations

import importlib.util
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNTIME_STOCK = b'writeSidebarSections:async r=>{await n().updateGrokBotUserRuntimeSettings({sidebarSections:{sections:r.map(a=>({id:a.id,name:a.name,agentIds:[...a.agentIds]}))}},o)}'
RUNTIME_FIXED = b'readSidebarSections:async()=>{let{settings:r}=await n().getGrokBotUserRuntimeSettings({},o);return r?.sidebarSections?.sections??null},writeSidebarSections:async r=>{let{settings:a}=await n().updateGrokBotUserRuntimeSettings({sidebarSections:{sections:r}},o);return(0,Qat.invariant)(a?.sidebarSections!==void 0,"Missing sidebar sections"),a.sidebarSections.sections}'
HANDLERS_STOCK = b'getHostSidebarSections:async()=>(await e.readHostSettingsFromBox("background")).sidebarSections??null,setHostSidebarSections:async({sections:r})=>{let a=await UUn(e,"sidebarSections",r,"sidebar sections");if(a==null)return null;try{await e.grokBot.runtimeSettings.writeSidebarSections(a)}catch(i){throw(0,Jr.reportDesktopEdgeFailure)("host-settings","write",i),i}return a}'
HANDLERS_FIXED = b'getHostSidebarSections:()=>e.grokBot.runtimeSettings.readSidebarSections(),setHostSidebarSections:({sections:r})=>e.grokBot.runtimeSettings.writeSidebarSections(r)'
# Both main-process anchors occur in the same packed asset. Compensate there,
# rather than changing ASAR offsets or borrowing space from another asset.
_space = len(RUNTIME_STOCK) + len(HANDLERS_STOCK) - len(RUNTIME_FIXED) - len(HANDLERS_FIXED)
if _space < 0:
    raise ValueError('server preference recovery exceeds the reviewed asset budget')
HANDLERS_FIXED += b' ' * _space
SLEEP_STOCK = b'c=()=>s.noteBoxAsleep(r.snapshots.get()===`asleep`);c();let l=r.snapshots.subscribe(c);'
SLEEP_FIXED = b'c=()=>s.noteBoxAsleep(!1/*server-sidebar-v1*/);c();let l=r.snapshots.subscribe(c);'.ljust(len(SLEEP_STOCK), b' ')


def state(data: bytes) -> str:
    variants = (('stock', (RUNTIME_STOCK, HANDLERS_STOCK, SLEEP_STOCK)),
                ('fixed', (RUNTIME_FIXED, HANDLERS_FIXED, SLEEP_FIXED)))
    matches = [name for name, values in variants if all(data.count(v) == 1 for v in values)]
    if len(matches) != 1 or any(data.count(a) + data.count(b) != 1 for a, b in zip(variants[0][1], variants[1][1])):
        raise ValueError('unsupported or partially patched server sidebar layout')
    return matches[0]


def transform_preferences(data: bytes) -> bytes:
    if state(data) == 'fixed':
        return data
    result = data
    for old, new in ((RUNTIME_STOCK, RUNTIME_FIXED), (HANDLERS_STOCK, HANDLERS_FIXED), (SLEEP_STOCK, SLEEP_FIXED)):
        result = result.replace(old, new, 1)
    if len(result) != len(data) or state(result) != 'fixed':
        raise ValueError('server sidebar recovery changed archive size')
    return result


def load_authority():
    path = Path(__file__).with_name('patch-sidebar-authority.py')
    spec = importlib.util.spec_from_file_location('openbot_sidebar_authority', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transform_archive(data: bytes, authority) -> bytes:
    # Refuse anchors moved across assets: total archive length alone would not
    # protect the packed-file lengths and offsets in that case.
    import json, struct
    _, header_size, _, json_size = struct.unpack_from('<IIII', data)
    header = json.loads(data[16:16 + json_size]); start = 8 + header_size
    owners = {}
    for index, entry in enumerate(authority.packed_files(header)):
        offset, size = start + int(entry['offset']), int(entry['size'])
        if offset < start or offset + size > len(data):
            raise ValueError('packed asset outside archive')
        content = data[offset:offset + size]
        for name, variants in [('runtime', (RUNTIME_STOCK, RUNTIME_FIXED)),
                               ('handlers', (HANDLERS_STOCK, HANDLERS_FIXED)),
                               ('sleep', (SLEEP_STOCK, SLEEP_FIXED))]:
            if any(v in content for v in variants):
                if name in owners:
                    raise ValueError('duplicate server sidebar asset')
                owners[name] = index
    if set(owners) != {'runtime', 'handlers', 'sleep'} or owners['runtime'] != owners['handlers']:
        raise ValueError('unsupported server sidebar asset placement')
    return transform_preferences(data)


def desktop_running(binary: Path) -> bool:
    for directory in Path('/proc').glob('[0-9]*'):
        try:
            if (directory / 'exe').resolve() == binary.resolve() and b'--type=' not in (directory / 'cmdline').read_bytes():
                return True
        except OSError:
            continue
    return False


def invalidate_code_cache(cache: Path, backups: Path) -> dict:
    """The native loader keys code cache by build ID, not changed source bytes.

    V8 can accept old bytecode for equal-length source. Move only main-app cache
    files after the desktop has quit; retain independent copies for rollback.
    """
    if not cache.exists():
        return {'moved': 0}
    if cache.is_symlink() or not cache.is_dir():
        raise ValueError('code cache must be a regular directory')
    files = [p for p in cache.iterdir() if re.fullmatch(r'main-app-[A-Za-z0-9-]+\.v8(?:\.\d{1,10})?', p.name)]
    for p in files:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 64 * 1024**2:
            raise ValueError('unexpected main-app code cache file')
    if not files:
        return {'moved': 0}
    owner = cache.stat(); stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backups / ('main-app-code-cache-' + stamp)
    backup.mkdir(mode=0o700, parents=True)
    if os.geteuid() == 0:
        os.chown(backup, owner.st_uid, owner.st_gid)
    for p in files:
        target = backup / p.name
        shutil.copy2(p, target)
        if target.read_bytes() != p.read_bytes():
            raise ValueError('code cache backup did not verify')
        os.chmod(target, 0o600)
        if os.geteuid() == 0:
            os.chown(target, owner.st_uid, owner.st_gid)
    for p in files:
        p.unlink()
    return {'moved': len(files), 'backup': str(backup)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate without writing or touching code cache')
    args = parser.parse_args()
    authority = load_authority()
    original_transform = authority.transform
    authority.transform = lambda data: transform_archive(original_transform(data), authority)
    original = authority.ASAR.read_bytes()
    patched = authority.refresh_integrity(original, authority.transform(original))
    if args.check:
        print(json.dumps({'changed': original != patched, 'valid': True}))
        return 0
    if original != patched:
        if desktop_running(authority.ASAR.parent.parent / 'grok-bot'):
            raise ValueError('Quit the desktop normally before changing its main-process code')
        cache_dir = os.environ.get('GROKBOT_CODE_CACHE_DIR')
        if not cache_dir:
            raise ValueError('Set GROKBOT_CODE_CACHE_DIR to this desktop profile\'s v8-code-cache directory')
        print(json.dumps({'codeCache': invalidate_code_cache(Path(cache_dir), authority.BACKUP_ROOT)}))
    return authority.main()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as error:
        print(f'grokbot-server-sidebar-patch: {error}', file=sys.stderr)
        raise SystemExit(2)
