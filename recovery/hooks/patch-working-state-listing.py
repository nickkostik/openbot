#!/usr/bin/env python3
"""Opt into native hex-prefix listing for v2 working-state exports."""
import argparse
import importlib.util
import json
import pathlib

MARKER = '/* openbot-parallel-working-state-listing-v1 */'
ANCHOR = 'parallelListing: () => readWarmingConfig().parallelListing && boxStoreSync.isV2Enabled,'
REPLACEMENT = 'parallelListing: () => boxStoreSync.isV2Enabled, ' + MARKER


def patch(source):
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count(REPLACEMENT) != 1:
            raise ValueError('Existing working-state listing patch has drifted')
        return source
    # Retain the native implementation and its fixed worker bound. Refuse a
    # bundle which no longer exposes that implementation or the v2 fence.
    if source.count(ANCHOR) != 1 or any(token not in source for token in (
        'var DURABLE_BLOB_LIST_CONCURRENCY = 16;',
        'DURABLE_BLOB_HEX_PREFIXES,',
        'max: DURABLE_BLOB_LIST_CONCURRENCY',
        'this.deps.listDurableBlobHexIds({',
    )):
        raise ValueError('Unsupported native working-state listing code')
    return source.replace(ANCHOR, REPLACEMENT, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=pathlib.Path, required=True)
    parser.add_argument('--node', default='/exec-daemon/node')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    file = pathlib.Path(__file__).with_name('patch-computer-egress.py')
    spec = importlib.util.spec_from_file_location('openbot_atomic_node_patch', file)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    print(json.dumps(helper.install(args.host, args.node, args.apply,
        transform=patch, backup_label='working-state-listing')))


if __name__ == '__main__':
    main()
