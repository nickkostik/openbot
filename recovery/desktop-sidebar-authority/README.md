# Linux desktop sidebar recovery

Opt-in recovery for the reviewed Grok Bot 0.75.0 Linux renderer after a
BOX-to-Temporal transfer. Install it separately on each affected desktop.
Repairing the Computer does not clear another client's persistence.

The affected desktop retained 172 cached UUIDs against 45 current server UUIDs.
Retired BOX rows survived the merge; current rows also retained old filesystem
paths, hidden flags and generated test titles. Twelve current rooms were absent
from that client's cache. The earlier recovery was installed only on computer
870 and bypassed normal Hide controls.

## Renderer repair

`patch-sidebar-authority.py` accepts the reviewed stock merge or the earlier
five-patch recovery. It removes cached rows missing from a complete authoritative
roster regardless of their previous harness, retains pending/protected rows,
and copies current routing/visibility fields while preserving previews and
activity timestamps. Incomplete roster loads never prune cached rows.

The patch restores the earlier visibility bypasses to stock so Hide and Unhide
continue to work. It also guards both transcript date dividers and individual
message timestamps against finite values outside JavaScript Date's range. Such
messages retain their content and IDs; their unknown dates are omitted rather
than guessed or rewritten. This fixes the reproduced `Invalid time value`
renderer crash. It preserves asset lengths and ASAR offsets, recomputes changed
asset SHA256 integrity hashes, creates a backup, and installs atomically. Unknown
layouts are refused without changing the archive. This supports the reviewed
Linux build; it is not a compatibility promise for future releases or other OSes.

```bash
# Quit the desktop normally first.
sudo env GROKBOT_ASAR_PATCH_BACKUPS="$HOME/.local/share/openbot/desktop-sidebar-backups" \
  GROKBOT_CODE_CACHE_DIR="$HOME/.config/Grok Bot/v8-code-cache" \
  python3 recovery/desktop-sidebar-authority/patch-temporal-sidebar-preferences.py
```

The composite installer also repairs section preferences for Temporal. Stock
0.75 reads sections from the old Computer and requires a successful Computer
write before saving them to the server. With that Computer asleep, recovered
bots can remain in stale sections and ordinary section edits fail. The repair
reads and writes the existing account runtime settings directly, as pins already
do. It returns the server's saved sections, propagates read/write failures, and
removes the renderer's Computer-sleep gate for this preference store only. It
does not wake the old Computer or change bot execution. Unset preferences remain
distinct from an explicit empty list. Existing section IDs and member order are
preserved. Both main-process replacements must remain in the same packed asset;
unknown or partial layouts are refused before installation.

The native main-process loader stores V8 bytecode by build ID. Keeping ASAR
asset lengths unchanged can leave old bytecode accepted for changed source.
The composite installer therefore refuses a running desktop, backs up and
invalidates only its `main-app-*.v8` caches before changing the main process,
and preserves other caches. Set `GROKBOT_CODE_CACHE_DIR` explicitly for a custom
profile. `--check` validates the archive without writes. See the
[Node V8 code-cache contract](https://nodejs.org/api/vm.html#new-vmscriptcode-options).

`GROKBOT_ASAR` overrides the installed archive path. The systemd examples assume
the scripts are installed in `~/.local/share/openbot/desktop-sidebar-recovery/`
and an existing `grokbot-desktop.service`. Keep that service's original GUI flags.
The start hook reapplies compatible patches; the timer checks every 30 seconds
and restarts the managed app only when the archive changes. An unsupported update
leaves the new archive intact and writes a local alert. `KillMode=mixed` allows
the Electron main process to close its children normally during restart. These hooks require the
owner's existing passwordless sudo permission; they do not create a sudo policy.

For the existing `openbot-870-tunnel.service` deployment, the optional
`systemd/openbot-870-tunnel.service.d/panel-singleton.conf` drop-in removes its
dependency on a second panel launcher. Use it only when the app/CLI already owns
the unified listener on 9280. A readiness check precedes each tunnel start. This
recovered the named public tunnel without starting another server or changing
its saved credentials. Keep the tunnel's existing restart policy and enable it
for the user's default target. Deployments that use the standalone panel service
should retain their service dependency instead.

## One-time cache recovery

Export fresh `ListGrokBotAgents` and `GetGrokBotUserRuntimeSettings` responses
privately using the signed-in owner session. Review the canonical UUIDs, section
membership and pins. Quit the affected app normally before applying; the script
refuses writes while an Electron main process is running.

```bash
python3 recovery/desktop-sidebar-authority/repair-client-cache.py \
  --roster /private/current-roster.json \
  --settings /private/current-runtime-settings.json \
  --restore-visible
```

This is a dry run. Add `--apply` to back up the three affected persistence blobs
and write the reconciled cache atomically. `--restore-visible` explicitly clears
stale visibility flags for this recovery; omit it to retain visibility choices.
Only authoritative UUIDs are retained. Same-name bots and rooms remain distinct;
names are never used to infer identity or delete history.

If a current UUID is absent from this client's cache, provide `--fallback-cache`
with a verified **same-account** `roster.last-roster` blob from another healthy
client. Only absent UUIDs use that metadata. Missing metadata, mixed harnesses,
multiple account caches, or incomplete/duplicate section coverage refuse repair.
Keep these private exports and backups outside Git. No transcript, attachment,
profile, routine definition, or server agent is deleted by these scripts.

## Verification

```bash
python3 -m unittest discover -s recovery/desktop-sidebar-authority -p 'test_*.py'
```

Twelve tests cover the actual replacement JavaScript, incomplete roster loads,
pending rows, same-name rooms, visibility, history metadata, legacy-patch upgrade,
ASAR integrity, atomic/idempotent installation, and rewritten Electron process
titles, invalid date dividers and message dates. CI runs these tests and the product export includes this recovery.

For each client, compare all UUIDs and section membership with the fresh server
roster. Scroll through the virtualized sidebar to inspect every entry. Open old
conversations and rooms, exercise Hide/Unhide and restore the original preference,
send one bounded UI prompt, then restart and repeat the roster/transcript checks.

The October 22 desktop check found 45 rendered UUIDs, no retired/hidden rows,
correct 3/16/17/9 section counts, and zero Unassigned entries. Selected old
conversations and rooms opened, a bounded UI send received its reply, and restart
preserved the restored state. A subsequent audit reproduced malformed dates in
five chats. After the date repair, every one of the 45 conversations on 870
loaded and rendered without an error boundary; both Linux clients received the
same patch. Sanitized evidence is in `evidence/client-verification.json`.

Roster and render recovery do not merge histories or SDK contexts. The separate
context audit found archived merged entries missing from active profiles and
confirmed that Temporal refuses BOX transcript writes. Neither that context
transfer nor mobile behavior is established by these renderer checks.

Routine state is a separate check. At this checkpoint the owner requested all
routines disabled. Cloud copies, both Computers' local definitions and local
schedulers were backed up and paused, and the desktop's complete routine list
reported zero enabled. The sidebar patch itself does not toggle routines.
