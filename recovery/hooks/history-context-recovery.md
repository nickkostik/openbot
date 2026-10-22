# Recovering merged working context

Visible transcript history and the model's native working state are separate.
Copying one SDK head or publishing UI entries alone does not combine context
from earlier identities. These helpers support a reviewed, detached recovery;
they do not register agents, switch harnesses, send prompts, or change routines.

`history-context-merge.py` builds a union from an explicit lineage, two observed
orders, and a preserved alias ledger. It retains both orders instead of sorting
on timestamps. It preserves unknown fields and quoted colleague identities;
only top-level ownership and platform-bounded entry IDs are remapped. Its private
receipt provides both alias maps, source digests and the resulting digest.
Long IDs receive stable SHA256 aliases. Unrelated colliding short IDs remain
separate events. Revised content, ambiguous aliases, duplicate IDs, contradictory
orders and unsupported input refuse recovery. The one reviewed revision is a
new Boolean `widgetSkipped` annotation on an otherwise identical sent message;
the current platform annotation is retained and both digests are recorded.
Keep the original input snapshots and all receipts outside Git.

`background_records` extracts literal dialogue and preserves sender, recipient,
channel and rich-text attribution as quoted provenance. It does not turn tool,
attachment or widget records into executable requests. Full non-text entries
remain in the union and original native graph. Malformed finite dates retain
their literal values and an explicit provenance marker. Do not infer replacement
dates from them or use them as an activity timestamp.

`history-background-codec.mjs` imports bounded literal rounds into an independent
native candidate. A synthetic history notice marks each round as past context,
including earlier copies and inter-bot messages. Historical requests and tools
must not replay. Attribution rows align with the following literal messages.
Repeated rich-text strings reference slices of that same message or an existing
text part in the preserved native prompt prefix, keeping their parsed structure
without copying the body again. Full rich-text bytes,
event IDs and per-event hashes stay in the exact UI union and immutable source
plan; each notice includes its complete record-manifest digest. This is a
lossless representation of conversational metadata, not a history summary.
Rich-text node keys and repeated strings use a reversible table representation;
the importer decodes and compares the complete parsed document before writing.
An explicit `compressRepeatedLiteralText: true` plan can also encode exact
repeated passages of at least 4,096 UTF-16 code units. Each event retains its
role and position, with a checked reference to an earlier full native literal.
It never points to another reference or merges transcript identities. Short
repeated messages remain literal. Plain source text, IDs, original formatting
bytes and reference proofs all remain in the private recovery evidence.
For a larger conversation, an explicit `richTextAttribution: "conversation"`
plan keeps literal dialogue, extra rich-text passages, link targets and semantic
nodes such as colleague mentions in the prompt. Opaque renderer IDs and layout
formatting stay in the byte-exact UI transcript and immutable source plan. The
proof records this choice; the default `full` mode preserves the parsed rich-text
structure in prompt attribution. Neither option summarizes or drops dialogue.
The bridge requires exact reviewed host, worker and allocator
digests; those private vendor files are not distributed here. It installs process
network/tool denials before loading their codecs and refuses a live directory,
WAL sidecars, outstanding native tool calls, unknown schemas, changed plans,
missing graph references and insufficient context capacity.

Each proof verifies exact native round trips, unchanged prior prompt prefix and
other root fields, preserved turn graph and original root, literal UI payload
hashes, complete pagination, unique future IDs, conservative capacity, previews,
and zero provider/tool/network calls. Raw transcript rows remain unchanged by
the codec. Invalid dates are excluded from the activity frontier. A completed
ancestor must be reviewed separately for an interrupted branch; never clear a
pending tool call or mark historical work completed to pass validation.

Required live procedure:

1. Preserve full original data, SQLite snapshots, current platform history,
   explicit identity lineages, routines and account preferences privately.
2. Build and verify detached candidates. Preserve interrupted work and old
   completion queues with their original identity; do not replay them as a new
   bot. Preserve routine definitions, contexts and the owner's enabled policy.
3. Stage only hidden replacement identities with kickstart and introduction
   suppressed. Bind exact server IDs, publish the verified UI union and read it
   back. Never activate a partially verified candidate.
4. Use the native working-state exporter. Verify its complete durable closure
   and read back the root bytes and digest before the native Temporal handoff.
5. Read back the Temporal harness and full transcript, verify historical payloads
   and ordering, and run bounded live recall checks. A hop probe is insufficient.
6. Recheck the original append boundary immediately before cutover. New activity
   requires incremental preservation. Remap sections, pins and explicit room
   members, then reveal verified replacements and hide originals. Preserve all
   original BOX data. Refresh the bot-readable roster and test a desktop restart.

The helper does not imply that every archived byte fits a model context window.
Use the actual route capacity and retain complete source archives. Do not
increase a declared capacity merely to make a proof pass. Private account data,
conversation bodies, credentials, vendor bundles and receipts do not belong in
the public product export.

Run `python3 -m unittest discover -s recovery/hooks -p 'test_*.py'` for the pure
union, literal/provenance validation and side-effect-denial tests. Native proofs
additionally require the reviewed private artifacts and a detached fixture.
