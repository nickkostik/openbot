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
   A native Temporal handoff does not guarantee legacy routine registration.
   `temporal-routine-transfer.py` lets the authenticated owner runner move the
   existing global routine IDs using `AutomationsService.CreateSandAutomation`
   with the original `sandAutomationId` and the verified new `sandAgentId`.
   Keep exact workflows and disabled status, then independently read back both
   bindings and native routine records, including real run history. Never mint
   new IDs for those routines or infer their enabled policy from a default.
   The helper accepts immutable source binding/record snapshots, an owner RPC
   adapter and a durable private checkpoint callback. It checks the whole fleet
   before writing; after an uncertain response, reuse the same snapshots and
   resolve the outcome by authoritative readback. Gate sidebar cutover on its
   final `verified` receipt. The helper does not enable routines or switch a
   harness and refuses active routines, unrelated target rows and edited inputs.
6. Recheck the original append boundary immediately before cutover. New activity
   requires incremental preservation. Remap sections, pins and explicit room
   members, then reveal verified replacements and hide originals. Preserve all
   original BOX data. Refresh the bot-readable roster and test a desktop restart.
   Account runtime section objects omit native persistence fields. Mirror them
   through `getHostSettings`/`setHostSettings`, retaining each Computer's existing
   `isCollapsed` values and supplying `agentIds: []` for an empty section. Do not
   copy raw account objects into native `settings.json`. If an earlier copy
   already made version-1 settings unreadable, use
   `repair-native-sidebar-settings.py` as described in the desktop recovery guide,
   then verify native preference writes and readback before cutover.

Room membership requires the complete owner API roster. Local gateway summaries
can flatten a Temporal room into a normal bot with an empty membership list.
`temporal-room-transfer.py` restores only the archived, explicitly mapped bot
members through `SetGrokBotRoomMembers`; it verifies ownership, exact server IDs,
unchanged human members and authoritative readback. It checks the whole plan
before writing and preserves a private checkpoint before each mutation. Reuse
the same immutable plan after an uncertain response. Its verified receipt is
strictly `room-memberships-only`: room transcript union, native working context
and a live room response need independent proof before a complete transfer.

Publish Temporal colleague identities with `temporal-peer-context.py` from that
same complete owner roster and an explicitly reviewed canonical identity list.
Check the allowlist against current native client visibility separately: the
owner roster alone does not contain sidebar hidden/removed state.
Use native room kinds and `memberAgentIds`, including empty human-only rooms;
never infer members or merge identities by matching names. The projection omits
descriptions, transcript bodies and account data. The owner runner writes it
atomically to the model-readable workflow path on the selected Computer.
The BOX background publisher preserves an existing publication in Official
mode, or when its own mode file is absent, instead of replacing it from stale
BOX summaries. This preservation rule does not select a global routing mode.

Old generated recovery notices can incorrectly tell a migrated bot to avoid
Temporal or use retired Computer paths. `official_notice` replaces only balanced,
known generated notice blocks, preserving the specialist role outside them.
It names the owner's current Computer and published roster, treats recovered
actions as historical data and keeps disabled routines disabled. An owner runner
must checkpoint the complete original profile, change only its description and
verify every other native field remains unchanged. This metadata repair sends
no bot message and does not replace a bot's merged native working state.

After handoff, the platform fences BOX transcript writers. Do not flip a bot
back to BOX or bypass that fence to append a late historical reply. Preserve the
original envelope and bytes privately, then use an explicitly authorized,
single native Temporal context synchronization turn containing quoted history,
its source ID, timestamp and payload digest. Clearly mark it as past data and
forbid replay of historical actions. Journal the send before calling it; verify
the exact input and a native reply before accepting that incremental boundary.
The quoted import is visible as a context synchronization message, rather than
an invented original Temporal transcript event. Preserve this distinction in
receipts. An old message may also acquire the platform's Boolean `widgetSkipped`
delivery annotation after a real turn. Accept only that reviewed addition when
every other field is identical; preserve both payload hashes and the original.

The helper does not imply that every archived byte fits a model context window.
Use the actual route capacity and retain complete source archives. Do not
increase a declared capacity merely to make a proof pass. Private account data,
conversation bodies, credentials, vendor bundles and receipts do not belong in
the public product export.

Run `python3 -m unittest discover -s recovery/hooks -p 'test_*.py'` for the pure
union, literal/provenance validation and side-effect-denial tests. Native proofs
additionally require the reviewed private artifacts and a detached fixture.
