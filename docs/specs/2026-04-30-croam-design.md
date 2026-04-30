# croam: cross-host claude-code session manager

Status: design / pre-implementation
Author: Tunc Yildirim
Date: 2026-04-30

## 1. Goal

A user with multiple personal computers (e.g., STORMTREE at home, VICAR at the office, CORPSEFIRE on the phone) wants their claude-code sessions to follow them. They start a session on one host, walk away, and want to pick up that exact session, or branch from it, on a different host - even if the original host is asleep or otherwise offline.

Today this is painful. `cctakeover` exists locally but kills processes indiscriminately, has no awareness of other hosts, and cannot reach a session whose origin is offline.

croam unifies session discovery, attachment, ownership transfer, and branching across all configured hosts, using SSH for live access, optional syncthing for offline-capable mirroring, and an explicit ownership model that avoids ambiguous data flows.

It also obsoletes `cctakeover` by making every claude session run inside a tmux session named for its UUID, attachable from any terminal locally and from any reachable host remotely.

## 2. Concepts

A claude-code session has two distinct kinds of state:

- **Living state**: a running `claude` process, on a host, optionally attached to a tmux pane. Bound to its host. Reachable only locally or via SSH to that host.
- **Persistent state**: the JSONL transcript at `~/.claude/projects/<encoded-cwd>/<sid>.jsonl`. Portable bytes.

Confusing the two leads to design mistakes. croam keeps them separate.

A session has exactly one **owner host** at any moment. Owner is the host whose JSONL is canonical for that session. Default owner = the host where the session was created. Ownership only changes via an explicit `claim` action.

A host's **reachability** is whether `ssh -o ConnectTimeout=2 -o BatchMode=yes HOST true` succeeds right now. Reachable hosts contribute live data; unreachable hosts contribute whatever is in their syncthing mirror, if any.

## 3. Verbs

```
croam              # picker (interactive fzf), filtered to $PWD by default
croam ls           # non-interactive list, scriptable, --json output
croam attach <sid> # adopt the live session, kill+relaunch in tmux if needed
croam peek <sid>   # read-only: live tmux -r if origin reachable, static transcript otherwise
croam claim <sid>  # transfer ownership to this host
croam fork <sid>   # create a new sessionId branched from the JSONL
croam launch       # start a new claude session inside tmux (invoked by the claude shim)
croam doctor       # diagnose config, ssh, syncthing, ownership inconsistencies
```

`attach` is the most common verb. It is recursive: if the owner is remote and reachable, croam SSHes to the owner and runs `croam attach` there. The owner-side then resolves locally (kill+relaunch in tmux if not already, attach).

`peek` is read-only and never modifies. Live mode uses `tmux attach -r` to deny keyboard input. Static mode renders the JSONL in a TUI/pager when the origin is unreachable.

`claim` moves ownership. With origin online, croam performs a cooperative handshake: SSH the owner to stop any live process, mark the assertion locally, copy the JSONL, write the new assertion. With origin offline, croam performs a forced claim: copies from local syncthing mirror, writes a "claimed away" marker for the origin to reconcile when it returns. Forced claim warns about possible data loss if origin had unsynced writes.

`fork` is always safe. Generates a new UUID, copies the JSONL, registers the new sid as owned here. Original is untouched. Lineage stored as croam metadata.

## 4. Picker UX (`croam`)

Renders a fzf list, filtered to sessions whose normalized cwd matches `$PWD` by default. Multi-select via TAB.

### Columns

```
STATUS  HOST       LAST  CWD                   NAME
●       stormtree  2m    ~/Programs/onlayer-x  iso27001 controls draft
●       stormtree  14m   ~/Programs/onlayer-x  fix migration on mart_*
●       vicar      1d    ~/Programs/croam      scope brainstorm
○       corpsefire 3h    ~/notes               phone log
●       stormtree  7m    ~/Programs/onlayer-x  iso27001 controls draft [abc123-F#1]
```

Status glyph and color encode two axes:

- Glyph: `●` host reachable, `○` host unreachable.
- Color: green = running idle, yellow = running busy, gray = archived (no live process), neutral gray for unreachable.

Cwd column is rendered fish-style when it would overflow (`/home/tunc/Programs/onlayer-x/internal/iam` -> `~/P/o/i/iam`). When the cwd path does not exist on the local host, the cwd column is rendered in dim red.

LAST column format:

| Range | Format |
|---|---|
| 0 to 59 min | `Nm` |
| 1 to 47 hr | `Nh` |
| 2 to 30 days | `ND` |
| 30 days and beyond | `NM` |

### Filterability

Hidden columns carry filter tokens that fzf searches but does not display. Internal row layout:

```
<sid>\t<glyph>\t<status_word>\t<reach_word>\t<cwd_word>\t<host>\t<last>\t<cwd>\t<name>
```

`fzf --with-nth=2,6,7,8,9 --delimiter=$'\t'` displays columns 2,6,7,8,9. Filter searches the whole line, so typing `busy`, `unreachable`, `missing-cwd`, `stormtree`, etc. all narrow correctly.

### Keybindings

```
enter       attach (or peek-fallback if origin unreachable)
tab         multi-select toggle
p           peek
c           claim                (refuses if cwd missing locally)
f           fork                 (refuses if cwd missing locally)
C           claim --here         (override: rebases to $PWD)
F           fork --here          (override: rebases to $PWD)
ctrl-r      reload state
?           show full keybinding help in preview
```

Lowercase verbs apply with default safety; capitalized variants enable `--here` rebasing (see section 11).

### Preview pane

Two blocks: dynamic metadata followed by a tail of the JSONL rendered as truncated conversation.

Metadata block adapts to the row state. Example for a remotely-owned, reachable, idle session with cwd present:

```
SESSION
  id       abc12345-6789-abcd-ef01-23456789abcd
  name     iso27001 controls draft
  cwd      ~/Programs/onlayer-x  [present]
  jsonl    34 KB, 287 messages

HOST
  origin   stormtree (this host) - reachable
  state    running, idle (PID 239799, up 3d, last activity 14m ago)
  tmux     claude-abc123  (attached: no)

ACTIONS
  attach   safe         adopts via tmux; kill+relaunch if not in tmux
  peek     safe         tmux attach -r (read-only)
  claim    handshake    transfers ownership here
  fork     safe         new id, branch
```

For a remotely-owned, unreachable session with cwd missing:

```
SESSION
  id       def45678-9abc-...
  name     refactor mart_* tables
  cwd      /home/work/onlayer-eu  [MISSING on this host]
  jsonl    121 KB, 942 messages (from synced mirror)

HOST
  origin   vicar - unreachable (last sync 3h ago)
  state    last known: running, idle (snapshot 4h old)

ACTIONS
  attach   unavailable  origin offline
  peek     limited      static transcript only
  claim    refused      cwd missing; press C for claim --here
  fork     refused      cwd missing; press F for fork --here
```

### Multi-select action filtering

When multiple rows are selected, the action key set in the header is the intersection of safe actions across all selected rows. Adapts in real time as rows are toggled (fzf `--bind 'select:transform-header(...)' deselect:transform-header(...)`).

```
1 selected:        enter:attach  p:peek  c:claim  f:fork
3 selected:        enter:attach  p:peek  f:fork                 (claim hidden: 1 row owned here, would no-op)
3 selected mixed:  p:peek  F:fork --here                        (cwd missing on some; only F universal)
```

Pressing a key not in the current intersection: inline status-line refusal naming the offending rows. No mode change, no surprise actions.

### Live status updates

Picker takes a snapshot at open. Manual refresh via `Ctrl-R`. Live polling deferred to v2; sessions do not flip busy/idle fast enough for a picker session to need it.

### Filters

```
croam                # default: cwd == $PWD, last 30 days, all hosts, all statuses
croam -A             # all sessions, all dirs
croam -p             # walk up to git root, match anything below
croam --host vicar   # scope to single host
croam --last 90      # extend window to 90 days
croam --orphans      # show only orphan JSONLs (no backing assertion)
```

## 5. Data model

### Session metadata (per-host)

Each host maintains:

- `~/.claude/sessions/*.json` - claude-native, contains `pid`, `procStart`, `cwd`, `status` etc. for currently-running sessions on this host. Host-local; PID etc. only meaningful on origin.
- `~/.claude/projects/<encoded-cwd>/<sid>.jsonl` - claude-native conversation transcripts. Authoritative content for each session.

croam adds (paths follow XDG; in syncthing mode, state files live under the host's subtree of `shared_root` instead, see section 9):

- `<state>/ownership.json` - per-host assertions about session ownership. Each host writes only its own.
- `<state>/lineage.json` - per-host fork lineage. Maps `<fork-sid>` to `{parent_sid, fork_n}`. Read at picker render time to compose the `[abc123-F#1]` display tag.
- `<state>/host-cache.json` - last-known state of each peer (last seen reachable, last sync activity), used for the LAST column on unreachable hosts.

Where `<state>` resolves to:
- ssh-only mode: `~/.local/share/croam/`
- syncthing or hybrid mode: `<shared_root>/<HOSTNAME>/` (so other hosts can read it via the mirror)

Config (read-only after load) lives at `~/.config/croam/config.toml` regardless of mode.

### ownership.json structure

```json
{
  "abc12345-6789-abcd-ef01-23456789abcd": {
    "owner": "stormtree",
    "asserted_at": "2026-04-30T10:00:00Z",
    "action": "create",
    "cwd_normalized": "~/Programs/onlayer-x"
  },
  "def45678-9abc-...": {
    "owner": "stormtree",
    "asserted_at": "2026-04-29T22:30:00Z",
    "action": "claim",
    "previous_owner": "vicar",
    "cwd_normalized": "~/Programs/croam"
  }
}
```

Each host writes only entries asserting its own ownership claims. Reading determines current ownership by merging all hosts' files and applying most-recent-`asserted_at`-wins per sid.

### Path normalization

cwds are stored in `cwd_normalized` form: home-rooted (`~/...`) when under origin's `$HOME`, absolute otherwise. The `~` resolves to the local host's `$HOME` at display and match time.

Implementation: croam config declares `home` per peer host (autodetected as `os.path.expanduser("~")` for the local host; explicit override per peer when usernames differ).

## 6. Aliveness

At the start of each croam invocation, fan out parallel reachability probes:

```
ssh -o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=no HOST true
```

Use `~/.ssh/config` for ports/keys/jumphosts. `BatchMode=yes` prevents password prompts. Result cached for 30 s within the invocation.

No port-22 assumption. No heartbeat-file dependency. Heartbeat tells you the origin is alive somewhere; reachability tells you the origin is reachable from here. The latter is what croam needs.

## 7. Ownership and reconciliation

### Per-host assertions, read-time merge

Each host writes only to its own `ownership.json`. To determine "who owns sid X," croam reads all hosts' files (via syncthing mirror or SSH; see section 9) and applies most-recent-`asserted_at`-wins.

This avoids syncthing write conflicts entirely (no two hosts ever write to the same file). Conflict resolution becomes deterministic and runs at read time, idempotent across all hosts.

### Flatten on every run

After read-time merge, croam rewrites its own `ownership.json` keeping only entries where the local host is currently the winning owner. Older superseded entries are dropped. File stays bounded by the count of currently-owned sessions.

### Conflict detection

When croam reads its own assertion and finds a later assertion from another host (i.e., this host was outclaimed), it triggers loss reconciliation:

1. Detect: my local Claude dir at `~/.claude/projects/.../<sid>.jsonl` corresponds to a session I no longer own.
2. Compare: local JSONL line count vs. the snapshot at the time my assertion was made.
3. If local has new lines added after the conflicting claim, prompt:
   ```
   Session abc123 was claimed by corpsefire at 2026-04-30T13:01:00Z.
   Your local copy has 7 messages added after the conflicting claim.
   [F]ork these into a new session, or [d]iscard?
   ```
4. Fork: copy local JSONL to a new sid owned by this host (lineage recorded). Discard: delete local JSONL.

### claim_verify mode

Configurable in `~/.config/croam/config.toml`:

- `claim_verify = "local"` - read-time merge of locally-available assertions only. Fast.
- `claim_verify = "ssh-strict"` (default) - on `claim`, before writing the assertion, SSH-fetch live `ownership.json` from every reachable peer. Merge with local view. Proceed only if the merge agrees this is a legal transition. Adds ~100-500 ms per claim. Reads (`peek`, `attach`, `ls`) stay fast.

`ssh-strict` does not mean ssh-only. For unreachable peers, croam falls back to the syncthing mirror (when syncthing mode is enabled). The merge uses the most authoritative source available per peer: live SSH for reachable hosts, syncthing for unreachable hosts with mirrors, gap (and a warning logged) for unreachable hosts in ssh-only mode.

Limit: ssh-strict cannot defend against a host that is offline at claim time and made a conflicting assertion locally before going offline. Such a race resolves through fork-or-discard on next convergence. This is acknowledged as the inherent limit of distributed coordination without a central authority.

### Orphans

A JSONL present in some host's projects subtree without a backing assertion is an orphan. Caused by interrupted operations, partial syncs, or corrupted state. croam:

- Excludes orphans from the default picker view.
- Lists them under `croam --orphans` with a `[orphan]` label.
- Allows `fork` (recover content as a new owned session); refuses `attach` and `claim` (no owner declared = ambiguous state).

## 8. Always-tmux / claude shim

Every interactive claude session runs inside a tmux session named `claude-<sid>`. Predictable name uses the full UUID, never the autoname (autonames change with /rename).

The shim wraps `claude`:

```python
# pseudocode
if not_in_tmux() and is_interactive_tty() and not opt_out():
    sid = generate_or_resume_sid(args)
    exec_tmux_new(session_name=f"claude-{sid}", command=["claude-real", *args])
else:
    exec(["claude-real", *args])
```

Opt-out:

- `CROAM_NO_TMUX=1` env var.
- `--no-tmux` flag (passes through to nothing; stripped before exec).
- Detect non-TTY (scripts, `claude --print`, `ssh HOST claude ...` without `-t`).

The shim is installed by replacing the `claude` alias in user shell rc:

```zsh
alias claude='croam launch --effort max'
alias cc='croam launch --effort max --model "claude-opus-4-6[1m]"'
```

The user's existing `cctakeover` alias is retired; an alias `cctakeover='croam'` is offered for muscle memory during transition.

## 9. Modes: syncthing, ssh-only, hybrid

croam supports three discovery modes, configured in `config.toml`:

```toml
[discovery]
mode = "syncthing"  # "syncthing" | "ssh" | "hybrid"
```

### Syncthing mode

Each host's metadata (ownership.json, lineage.json) and JSONLs are mirrored under a configured shared root, e.g., `~/Sync/croam/<HOSTNAME>/...`. Other hosts read the local mirror for offline visibility. Online hosts can additionally be SSH-queried for live data when ssh-strict is enabled.

Layout under shared root:

```
~/Sync/croam/
  stormtree/
    ownership.json
    lineage.json
    projects/
      home-tunc-Programs-onlayer-x/
        abc12345-...jsonl
  vicar/
    ownership.json
    ...
```

Each host's local Claude data is mirrored to its own subtree (via a watchdog rsync, inotify-driven, or symlinking - implementation choice in the code phase).

### SSH-only mode

No shared filesystem. All cross-host operations fan out parallel SSH:

- `croam ls` -> `ssh HOST croam --emit-state` per configured host, merged client-side.
- Offline hosts simply do not contribute. Their sessions are invisible until they come back online.

User accepts the invisibility-while-offline tradeoff in exchange for not running syncthing.

### Hybrid mode

Some hosts use syncthing, others are SSH-only. Per-host config:

```toml
[hosts.stormtree]
ssh = "stormtree"
home = "/home/tunc"
sync = true     # this host participates in the syncthing mirror

[hosts.acme]
ssh = "acme"
home = "/home/me"
sync = false    # this host is SSH-only
```

croam aggregates both sources at query time.

### Fallback semantics

Source priority per peer:

1. Live SSH if peer reachable AND ssh-strict mode (or claim verb).
2. Syncthing mirror if peer has `sync = true` AND mirror data exists.
3. Cached last-known state for display-only purposes (LAST column).
4. Gap, with a warning logged to a session-debug file.

## 10. Configuration

Single file: `~/.config/croam/config.toml`. Created on first run by `croam doctor` or first interactive invocation.

```toml
[self]
hostname = "vicar"           # default os.uname().nodename, override if needed

[hosts.stormtree]
ssh = "stormtree"
home = "/home/tunc"          # optional; autodetected for same-username case
sync = true

[hosts.vicar]
ssh = "vicar"
home = "/home/tunc"
sync = true

[hosts.corpsefire]
ssh = "corpsefire"
home = "/home/tunc"
sync = true

[discovery]
mode = "syncthing"

[discovery.syncthing]
shared_root = "~/Sync/croam"

[ownership]
claim_verify = "ssh-strict"  # "local" | "ssh-strict"

[picker]
default_filter = "exact-pwd" # "exact-pwd" | "project-root"
last_window_days = 30

[shim]
enabled = true               # whether the claude shim auto-launches in tmux
opt_out_env = "CROAM_NO_TMUX"
```

## 11. Cross-host path translation

A session's recorded cwd is absolute on the origin host. To render and match on a different host, croam normalizes:

- Origin host writes `cwd_normalized = "~/Programs/onlayer-x"` if cwd is under origin's `$HOME`.
- Otherwise, cwd_normalized is the absolute path verbatim.
- At display time on any host, `~` resolves to the local host's `$HOME`.
- At match time against `$PWD`, both sides are normalized then compared.

Same-username case requires no per-host config. Different-username case requires `home = "/home/me"` in the peer's `[hosts.X]` block.

### `--here` override

When the user `claim --here` or `fork --here` for a session whose normalized cwd differs from `$PWD`, croam:

1. Writes the JSONL into `~/.claude/projects/<encoded-$PWD>/<sid>.jsonl` on this host. Encoding follows claude-code's exact convention (slashes to dashes; verify exact escape rules from claude source during implementation).
2. Updates croam's metadata `cwd_normalized` for this session to the new value.
3. Does NOT modify the JSONL's body. The conversational history references absolute paths from origin; those become stale references in the new location, but claude does not enforce historical-path consistency, so the session resumes cleanly.

If implementation reveals that claude does enforce a recorded cwd field (a single line at the top of the JSONL, e.g., `{"type": "system", "cwd": "..."}`), `--here` performs a surgical rewrite of that single line. Conversation history remains untouched.

`--here` is opt-in only. The default behavior refuses to claim/fork into a mismatched cwd. No automatic cloning, no automatic mkdir, no path-aware reasoning. The user accepts the mismatch explicitly.

## 12. Implementation

- Language: Python 3.11+
- CLI library: typer (modern, type-hinted, good UX)
- fzf integration: subprocess.Popen with `--bind`, `--expect`, `--with-nth`
- SSH fanout: concurrent.futures.ThreadPoolExecutor for parallel probes; subprocess for each ssh call
- Syncthing integration: read-only filesystem access to the shared root; no API calls (syncthing is just bytes for us)
- Tmux integration: shell-out to `tmux` binary
- Persistence: TOML for config, JSON for state files
- Tests: pytest, with fixtures for mock SSH and synthetic syncthing trees

### Project layout

```
~/Programs/croam/
  README.md
  pyproject.toml
  docs/
    specs/
      2026-04-30-croam-design.md
  src/
    croam/
      __init__.py
      cli.py              # typer entry point
      shim.py             # claude wrapper
      picker.py           # fzf orchestration
      ownership.py        # assertion read/write/merge
      sessions.py         # claude session metadata
      hosts.py            # ssh probe, fanout
      sync.py             # syncthing mirror access
      paths.py            # path normalization
      tmux.py             # tmux session management
      doctor.py           # croam doctor
      config.py           # config loading
  tests/
    test_ownership.py
    test_paths.py
    test_picker.py
    test_hosts.py
    fixtures/
```

Install via `pipx install -e ~/Programs/croam` for development; eventual AUR / pip publish.

## 13. Edge cases

- **Self-fork same host**: works; original keeps running in its tmux, new sid spawns in a fresh tmux. Snapshot atomicity ensured by validating the last line of the copy parses as JSON and truncating if not.
- **Multi-select mixed states**: action key set adapts in real time to the intersection of safe actions.
- **Cwd missing locally**: claim/fork refused by default; `--here` override (capital `C` / `F` in picker) accepts and rebases.
- **Non-interactive claude invocations**: shim detects non-TTY and passes through without tmux.
- **Origin offline at claim time**: forced claim with warning. Reconciliation when origin returns: origin sees its assertion was superseded, removes its local JSONL, runs loss reconciliation if it had unsynced post-snapshot writes.
- **Two hosts claim simultaneously**: most-recent-`asserted_at` wins. Loser detects on next read, runs fork-or-discard.
- **Orphan JSONL** (transcript with no backing assertion): hidden from default view, listed under `--orphans`, fork-only.
- **Different SSH ports**: handled by `~/.ssh/config`, not croam's problem.
- **Tailscale not used**: irrelevant; croam only uses `ssh` and the local filesystem.
- **Syncthing conflict file appearing on a JSONL**: croam detects `*.sync-conflict-*` files, surfaces them under `--orphans` for user-driven recovery.

## 14. Out of scope (v1)

- Live status updates in picker (Ctrl-R only).
- Auto-clone / auto-mkdir of missing project directories.
- Full-text search over JSONL content (basic substring search OK; advanced indexing later).
- Remote autoname propagation (each host autonames its own).
- Web UI / HTTP API.
- Mobile (CORPSEFIRE) - phone is excluded from croam initially; sessions started there are visible if the phone runs croam, but the use case is desktop-first.

## 15. Open questions and future work

- Exact format of claude's encoded-cwd directory naming (verify from claude source during implementation).
- Whether claude enforces recorded-cwd consistency on resume (current assumption: no; verify).
- Live status updates in the picker (deferred).
- Integration with ccswap: whether croam's shim swap mechanism overlaps and should be unified, or whether ccswap remains independent. Initial v1 keeps them separate; revisit after both work standalone.

## 16. Acceptance criteria

croam v1 is complete when:

1. On a single host: `croam` opens a fzf picker showing local sessions in `$PWD`, with multi-select and the documented action keybindings working.
2. The claude shim launches new sessions inside tmux with predictable names; existing sessions are reachable by tmux name from any local terminal.
3. With two hosts in the config, `croam --all` lists sessions from both via SSH, and `croam attach <sid>` for a remote session SSHes and attaches to the remote tmux.
4. `croam claim` transfers ownership from origin to current host, updating both hosts' ownership.json correctly. Old owner releases its local JSONL on next croam invocation.
5. `croam fork` creates a branched session with lineage visible in the picker.
6. Forced claim with origin offline produces a correct ownership state on origin's return.
7. `croam doctor` reports config sanity, SSH reachability, syncthing health, and ownership inconsistencies.
8. Test suite covers: ownership merge logic, path normalization, conflict reconciliation (fork/discard), shim launch decisions, multi-select action filtering.
