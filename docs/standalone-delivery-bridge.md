# Standalone app delivery bridge core

The original standalone Grok Bot mobile sender uses the platform's
`SendGrokBotUserMessage` endpoint even for BOX bots. In the inspected signed
Android client, semantic `send/agent-unavailable` refusals stop that send. Its
uncertain-send recovery also consults `GetGrokBotSendStatus`. Returning a made-up
success or replacing only the send response cannot establish delivery.

`recovery/hooks/standalone-dispatch.py` supplies a receipt-backed core for an
optional private transport. It does not open a listener, change the original
app, install a certificate, configure a phone, enable a proxy, or change model,
roster, history, scheduler or box settings. Ordinary installation and panel
startup do not activate it. Native-phone delivery remains unverified.

A supplied transport first makes the original platform send. Only an explicit
HTTP 200 unavailable refusal can admit a new local claim. The original caller's
authenticated roster must uniquely bind the numeric target to an owned BOX UUID;
the native gateway must contain that same target and local work must be explicitly
allowed. Accepted sends, quota/no-access failures and uncertain platform transport
never trigger a second route.

The original message UUID becomes the native client nonce. A private SQLite
journal commits its content digest and target before one native dispatch. Every
retry rechecks caller ownership and never dispatches a claimed nonce again.
Acceptance requires a matching native ledger receipt, rather than the gateway's
immediate `accepted` boolean. Confirmed terminal receipt metadata persists across
worker restarts and native ledger eviction. No keys, prompts or transcript text
are stored in this journal. Preserve it during recovery; deleting it is not a
retry mechanism.

Native accepted, pending, rejected and unknown receipt states map into the
original app's status protocol, with the real echo identifier and timestamp.
Unknown durability may leave a message unexecuted after a crash between claim and
dispatch; suppressing replay prevents duplicate execution but does not guarantee
exactly-once execution. The supported inspected mobile subset includes ordinary
text, rich text, reply/fork and attachment metadata. The optional 1Password
capability remains a boolean; the six inspected message-initiator wire enums map
to the native gateway's corresponding internal strings. These fields passed a
genuine owner/native acceptance-and-reply check. Extra fields and nonempty session
routing are withheld from local handoff until their native contracts are validated.

The prepared transport is `recovery/hooks/standalone-dispatch-addon.py`, with
`standalone-transport.py` and the optional pinned mitmproxy dependency in
`requirements-standalone-proxy.txt`. Its `openbot_standalone_enabled` option is
false by default. Ordinary installation and box startup do not load the addon or
install its optional dependency. Enabling it requires an owned absolute
`openbot_sand_data` path, a private owned proxy configuration directory, an
explicit private bind address, regular proxy mode, verified upstream TLS, and
disabled flow capture and sticky credentials. It does not create a certificate
or configure a device itself.

The proxy permits only `api2.cursor.sh:443`. It handles JSON POSTs for send and
send-status; other platform API calls stay on their original path. The original
caller login and version headers go to the fixed platform URL. A separate owned
private `gateway.json` supplies credentials only to `127.0.0.1:1340`. Neither set
of credentials crosses to the other destination. Redirects and ambiguous
transport failures never cause a native retry. Original upstream failures retain
their real status and bytes. Global pause and the local-only/mode policy are
checked before even attempting an original send. Stale Temporal targets,
unowned rows and paused work are refused without a platform turn. Recognized
sends with unsupported encoding or malformed/unauthenticated input are rejected
locally; unsupported read-only status requests can keep their upstream path.
Unknown send fields and unvalidated session routing cannot receive a native
handoff. The core still requires the original explicit unavailable refusal;
an already accepted upstream send remains authoritative and never causes a
second native dispatch. This preflight cannot change the platform's backend or
eliminate a platform-state race after the check.

At most twelve adapter operations run concurrently on a dedicated worker pool;
other event-loop executor users cannot consume its worker capacity. A cancelled
client keeps its worker counted until that worker actually completes. Shutdown
stops new admissions and lets admitted receipt work finish. A failure response is
reserved before admission, so a worker or response-encoding error after a native
send cannot fall through to another platform send. The journal lives at
`<sand-data>/.openbot-standalone-dispatch/receipts.sqlite3`; preserve it across
restarts. It contains receipt metadata, not prompts or credentials.

The unchanged app still needs a separately authorized HTTPS route to this
transport. The platform's server cannot be edited by a local addon. Client
certificate trust and routing must be tested on the actual installed iOS/Android
app; a user certificate alone does not establish Android app trust. No phone
setup or activation command is included in this prototype. See the official
[mitmproxy TLS documentation](https://docs.mitmproxy.org/stable/concepts/certificates/)
for the trust boundary.

Tests exercise simultaneous retries, crash/restart, ledger eviction, content/target
conflicts, current caller ownership, malformed receipts and transport ambiguity.
These tests and a native gateway probe are distinct from a message delivered and
displayed in the original installed mobile app. Configuration details are in
[`skills/openbot-config/reference.md`](../skills/openbot-config/reference.md#prepared-standalone-app-dispatch-receipts).

`standalone-proxy-check.py` exercises an actual loopback CONNECT/TLS connection
using a temporary certificate and synthetic authenticated platform/native
services. It covers acceptance, send-status, twelve concurrent retries with one
native dispatch, a two-thread client executor, uncertain receipts, cancellation,
shutdown with work in flight, pause, quota/ownership gates, response-encoding
failure, destination restriction and rejection without trusted TLS. These are
transport tests, not a twelve-bot load benchmark or physical-phone
delivery proof. CI installs the optional dependency to run them; ordinary
OpenBot installation does not.
