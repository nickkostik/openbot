#!/usr/bin/env python3
"""Repair response lifetimes and opt native manifest reads into pinned ranges."""
import argparse
import importlib.util
import json
import pathlib

MARKER = '/* openbot-store-transport-v1 */'
CLASS = 'var SandBoxStoreServiceObjectStore = class {'
END = '\n// src/host/extensions/box-store-sync/box-object-store.ts'
CONDITIONAL = '''    let response = await putOnce();
    if (classifyConditionalPutStatus(response.status) === "concurrent-write") {
      response = await putOnce();
    }'''
MUTABLE = '''    let response = await putOnce();
    if (response.status === 409) {
      response = await putOnce();
    }'''


def release(block):
    return block.replace('    let response = await putOnce();',
        '    let response = await putOnce();\n    await response.body?.cancel();', 1).replace(
        '      response = await putOnce();',
        '      response = await putOnce();\n      await response.body?.cancel();')


def patch(source, reader):
    if not isinstance(reader, str) or not reader.startswith('/') or '\x00' in reader:
        raise ValueError('An absolute range-reader path is required')
    helper = f'''{MARKER}
async function openbotReadStoreObject(url, key) {{
  if (key !== BOX_STORE_MANIFEST_REL_PATH) return fetchAgentStoreObjectFromUrl(url, key);
  const response = await require({json.dumps(reader)}).fetch(url);
  if (response.status === 404) return null;
  if (!response.ok) throw new SandBoxStoreSyncError("Pinned store manifest read failed");
  return new Uint8Array(await response.arrayBuffer());
}}
'''
    if source.count(CLASS) != 1:
        raise ValueError('Unsupported native object-store boundaries')
    start = source.index(CLASS)
    if source[start:].count(END) != 1:
        raise ValueError('Unsupported native object-store boundary after class')
    end = source.index(END, start)
    block = source[start:end]
    reads = (
        ('await fetchAgentStoreObjectFromUrl(cached2.url, key)',
         'await openbotReadStoreObject(cached2.url, key)'),
        ('return fetchAgentStoreObjectFromUrl(url2, key);',
         'return openbotReadStoreObject(url2, key);'),
    )
    pairs = [(CONDITIONAL, release(CONDITIONAL)), (MUTABLE, release(MUTABLE)), *reads]
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count(helper) != 1 or any(
            block.count(after) != 1 or before in block for before, after in pairs
        ):
            raise ValueError('Existing store transport patch has drifted')
        return source
    if 'openbotReadStoreObject' in source or any(block.count(before) != 1 for before, _ in pairs):
        raise ValueError('Unsupported native store transport; original preserved')
    for before, after in pairs:
        block = block.replace(before, after, 1)
    return source[:start] + helper + block + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=pathlib.Path, required=True)
    parser.add_argument('--range-reader', type=pathlib.Path, required=True)
    parser.add_argument('--node', default='/exec-daemon/node')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.range_reader.is_absolute() or args.range_reader.is_symlink() or not args.range_reader.is_file():
        parser.error('Install the reviewed range reader at an absolute regular-file path first')
    spec = importlib.util.spec_from_file_location('openbot_atomic_node_patch',
        pathlib.Path(__file__).with_name('patch-computer-egress.py'))
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    print(json.dumps(installer.install(args.host, args.node, args.apply,
        transform=lambda source: patch(source, str(args.range_reader)), backup_label='store-transport')))


if __name__ == '__main__':
    main()
