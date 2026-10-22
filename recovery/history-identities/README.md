# Recovering oversized history identities

An earlier history merge appended a full branch digest to an existing message
identifier. Three recovered Dating Coach entries consequently had 159-byte IDs.
The platform accepted the preceding 578 entries and rejected the next entry.
After preparing bounded IDs, all 1,111 timeline entries published and read back
with their prepared payloads intact. This verifies timeline publication only;
model context import and inference require separate end-to-end verification.

`normalize_history_entry_ids.py` operates on a completed, detached SQLite
snapshot. It writes a new database and a private alias receipt. It preserves
sequence order, timestamps, sender metadata, quoted text, all other payload
fields, and the SDK tables. Original archives remain unchanged. Unknown long
identifiers, structured links needing remapping, SQLite sidecars, existing output
paths, and symlink sources are refused.

```sh
python3 recovery/history-identities/normalize_history_entry_ids.py /private/snapshot.db \
  --detached-snapshot --output /private/normalized.db \
  --proof /private/normalized-identities.json
python3 -m unittest discover -s recovery/history-identities -p 'test_*.py'
```

The helper does not upload data, modify a running profile, clear conversations,
replay historical tools, or change routine settings. Publish only through the
native publisher or an authenticated BOX writer after reviewing the receipt.
Keep databases, alias receipts, transcripts, and vendor bundles out of Git.
