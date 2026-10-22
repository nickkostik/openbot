# Computer network recovery

These opt-in helpers repair or diagnose Computer network access. They do not
change bot harnesses, enable routines, replace conversations, or write a store
manifest. Keep credentials, signed URLs, vendor bundles and backup data outside
Git.

## Supervised host egress

`patch-computer-egress.py` gives the native host child access to the Computer's
already configured loopback CONNECT listener through Node's built-in proxy
support. It requires a Node release supporting `NODE_USE_ENV_PROXY`, such as
22.21 or later. See the [Node network configuration guide](https://nodejs.org/learn/http/enterprise-network-configuration).

First inspect the staged change without modifying the supervisor:

```sh
python3 recovery/hooks/patch-computer-egress.py \
  --supervisor /usr/local/bin/sand-supervisor.mjs --node /exec-daemon/node
```

With the Computer idle, apply the reviewed launch change using `--apply`.
The helper requires one known launch anchor, checks Node syntax, saves an
independent private backup and replaces the file atomically. Existing patches
must match exactly; unknown launch code and drift are refused. It does not
restart services. Use the native supervisor lifecycle to load the new child
environment and verify the actual host PID afterwards.

The helper uses `SAND_EGRESS_TUNNEL_PROXY_ADDR` only when it names localhost,
127.0.0.1 or ::1 and a valid port. Existing proxy settings or an explicit
`NODE_USE_ENV_PROXY=0` take precedence. Both uppercase and lowercase HTTP(S)
proxy variables agree, and local gateway traffic bypasses the proxy. No new
network service or route is created.

After a supervisor update, repeat the dry run against the installed source.
Successful HTTP probes alone do not establish a successful working-state
export or migration: check the native export outcome and the platform harness
and test the resulting conversation separately.

## Slow working-state listings

`patch-working-state-listing.py` opts a reviewed native host into its existing
16-worker hex-prefix listing implementation for v2 stores. A large accumulated
working-state namespace can make the serial scan outlast the migration export
deadline even when the individual requests succeed. This patch preserves the
native v2 fence, prefix partitioning, object contents and export validation.
It does not change server admission, migration completion or a bot's harness.

```sh
python3 recovery/hooks/patch-working-state-listing.py \
  --host /opt/sand/sand-host/host-main.cjs --node /exec-daemon/node
```

The default is a syntax-checked dry run. Add `--apply` after reviewing it; a
private backup precedes atomic installation. The adjacent
`patch-computer-egress.py` supplies the common atomic installer and must be
present. Unknown implementations or worker bounds are refused. Reload through
the native supervisor only when idle. A later native host update can replace
this opt-in patch; inspect the new source rather than blindly restoring old
bundle bytes. Verify export duration and the actual migrated conversation.

## Large immutable reads

`box-store-range-read.cjs` exports `createReader(options)` and a default `fetch`
reader for an already authorized presigned HTTPS Amazon S3 object URL. It is a
standalone read helper; installing OpenBot does not substitute it for the
native store transport.

The first range must return an exact length and a strong ETag. Every remaining
range uses `If-Match` with the same ETag. Version changes, malformed ranges,
unexpected content encoding, oversized or truncated bodies and ignored ranges
fail without returning partial bytes. Only transient transport and HTTP errors
receive bounded retries. The caller can cancel the whole read with an abort
signal. Missing objects retain HTTP 404 semantics.

Defaults are 8 MiB ranges, two workers, three attempts per range, a 30-second
attempt deadline and a 1 GiB object limit. Choose a smaller `maxBytes` for a
smaller expected object. The result buffers the complete object in memory;
native decoding, integrity checks and any subsequent writes remain the
caller's responsibility. Never print or commit the signed URL.

Run the targeted checks with:

```sh
python3 -m unittest discover -s recovery/hooks -p test_patch_computer_egress.py
node --test recovery/hooks/test_box_store_range_read.mjs
```
