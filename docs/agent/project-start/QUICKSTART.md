# AI Agent Quickstart Guide

**Welcome, AI Agent!** This guide will help you navigate and complete your assigned phase efficiently.

---

## Location & Paths

**CRITICAL: Verify your location before starting!**

```bash
pwd  # Should output: /home/tunc/Sync/Programs/croam
```

### Project Paths

- **Project Root**: `/home/tunc/Sync/Programs/croam`
- **Feature Docs**: `/home/tunc/Sync/Programs/croam/docs/agent/project-start`

### Path Usage Rules

1. **Stay in project root** - Do NOT `cd` to other directories
2. **All paths are relative to project root** - When you see `docs/agent/...`, it means `/home/tunc/Sync/Programs/croam/docs/agent/...`
3. **If confused about location** - Run `pwd` to verify you're in `/home/tunc/Sync/Programs/croam`
4. **Use relative paths in your work** - Reference files as `docs/agent/...` not absolute paths

---

## Your Mission

You are part of a phased development workflow. Your job is to:
1. **Verify your location** (run `pwd` -- should be `/home/tunc/Sync/Programs/croam`)
2. Identify which phase you're responsible for
3. Gather minimal necessary context
4. Complete your phase according to the plan -- building, verifying, and committing as you go
5. Document your work
6. Update the status for the next agent

---

## File Structure

```
project-root/  <- /home/tunc/Sync/Programs/croam (where pwd outputs)
+-- docs/
|   +-- agent/
|       +-- project-start/                 <- Your feature folder
|           +-- QUICKSTART.md              <- You are here
|           +-- PROJECT_PLAN.md            <- Project overview, architecture, cross-cutting
|           +-- STATUS.md                  <- Phase tracker + integrations + deploy config
|           +-- CODEBASE_CONTEXT.md        <- Cumulative codebase knowledge
|           +-- FUNCTIONAL_QA_STRATEGY.md  <- How to verify "actually works" in this project
|           +-- PHASE_SUMMARY_TEMPLATE.md  <- Summary template
|           +-- phase_plans/               <- Individual phase plans
|           |   +-- PHASE_01.md
|           |   +-- PHASE_02.md
|           |   +-- ...
|           +-- summaries/                 <- Completed phase summaries
|               +-- PHASE_01_SUMMARY.md
|               +-- PHASE_02_SUMMARY.md
|               +-- ...
+-- src/
|   +-- croam/                             <- Python package (created in Phase 1)
+-- tests/                                 <- Pytest suite (created in Phase 1)
+-- docs/specs/2026-04-30-croam-design.md  <- Original design spec (read for context, do not modify)
```

**All paths in this guide are relative to `/home/tunc/Sync/Programs/croam`**

---

## Your Workflow

### Step 1: Find Your Phase

Read `docs/agent/project-start/STATUS.md` to identify:
- Which phase is current (marked as `[Current]`)
- Your phase number and name
- Integration settings (Git, Jira, Deployment, Safety Posture)

### Step 2: Get Context

**2a. Read the codebase context** (always, before anything else):
- Read `docs/agent/project-start/CODEBASE_CONTEXT.md`
- This contains cumulative knowledge about the codebase from all previous phases
- Use this instead of re-exploring the codebase from scratch
- Only explore further if you need information not covered in this document

**2b. Read recent phase summaries** (up to 2 most recent):
- If you're on Phase 5, read `PHASE_04_SUMMARY.md` and `PHASE_03_SUMMARY.md`
- If you're on Phase 1 or 2, read what's available (or nothing if Phase 1)

**Location**: `docs/agent/project-start/summaries/`

### Step 3: Read Your Phase Plan

Open `docs/agent/project-start/phase_plans/PHASE_XX.md` where XX is your phase number (zero-padded: 01, 02, ..., 10, 11).

This file contains everything you need for your phase:
- Objective and deliverables
- Detailed requirements
- Dependencies and completion criteria
- Testing requirements

If you also need the big picture (architecture, cross-cutting concerns), read the relevant sections of `docs/agent/project-start/PROJECT_PLAN.md` -- but only as needed.

**Do NOT read all phase plan files** -- only read yours.

### Step 4: Build, Verify, Commit (Repeat)

Follow this cycle for each logical chunk of work in your phase. Do NOT code everything and test at the end -- build incrementally and verify as you go.

#### 4a. Code a Logical Chunk

Implement a coherent piece of functionality (a function, an endpoint, a module). Keep chunks small enough to verify independently.

#### 4b. Verify Locally

For every claim you make about your code ("tests pass", "function returns X"), follow this verification gate:

1. **Identify** the command that proves the claim
2. **Run** it fresh -- not from a previous run, not from memory
3. **Read** the full output and check the exit code
4. **Confirm** the output actually proves what you claim

Never claim something works without running the verification command in this session and reading its output. Apply the gate to:

- **Tests**: Run them, read the output, paste the actual results in your summary
- **Live verification**: Actually run the code (see the Live Verification section below for details and safety rules)
- **Logs**: Verify your code produces appropriate log output. If something looks wrong, fix it before moving on

If something is wrong, fix it before continuing -- but follow the debugging protocol below. Do not guess-and-check.

#### When Verification Fails

When a test fails or code doesn't behave as expected, follow this protocol before attempting any fix:

1. **Investigate**: Read the full error output. Don't skim. Trace the failure to its origin -- which file, which line, which value was wrong.
2. **Compare**: Find working code in the same codebase that does something similar. Compare it against your failing code. The difference is usually the bug.
3. **Hypothesize**: Form one specific theory about the root cause. Test it minimally (add a log statement, check an intermediate value) before committing to a fix.
4. **Fix**: Apply a single targeted change. Re-run verification. If it fails again, return to step 1 with the new information -- do not retry the same fix.

Do not make multiple changes at once. One hypothesis, one fix, one verification cycle.

#### 4c. Commit

Stage the changes for this chunk and commit with a descriptive message.

**Format**: `[Phase {N}/{TOTAL}] {verb}: {what changed}`

**Verbs** (lowercase): `add`, `fix`, `update`, `refactor`, `remove`, `docs`

**Examples**:
- `[Phase 3/11] add: ssh reachability fanout with parallel ThreadPoolExecutor`
- `[Phase 3/11] add: claude session metadata join (PID -> sid)`
- `[Phase 3/11] fix: encoded-cwd off-by-one when cwd ends in /`
- `[Phase 3/11] docs: phase summary and context updates`

Get {N} and {TOTAL} from STATUS.md (e.g., "Current Phase: 3 of 11"). Multiple commits per phase is expected and encouraged.

#### 4d. Repeat

Continue the cycle (4a-4c) until all deliverables for your phase are complete.

### Step 5: Document Your Work

**5a. Update the codebase context**:
- Edit `docs/agent/project-start/CODEBASE_CONTEXT.md`
- Update the "Last updated by" line at the top to reflect your phase name and today's date
- Add any new files you created (to "Key Files & Modules")
- Add any new APIs, classes, or interfaces you built (to "Important APIs & Interfaces")
- Add any new data models (to "Data Models")
- Update any entries that changed due to your work (renamed files, modified APIs, etc.)
- Remove entries for things that no longer exist
- Keep updates incremental -- do not rewrite sections that are still accurate

**5b. Create your phase summary**:
- **Template**: `docs/agent/project-start/PHASE_SUMMARY_TEMPLATE.md`
- **Output location**: `docs/agent/project-start/summaries/PHASE_XX_SUMMARY.md`
- **Length**: Keep it concise (~400-500 lines max)

Include:
- What you built
- Files created/modified
- Completion criteria status
- Any challenges or deviations
- Notes for future phases
- **Functional QA Results** (if `Functional: yes`): one entry per Functional QA check from your phase plan, with surface, invocation command, observed outcome (pasted byte-for-byte, not paraphrased), and pass/fail verdict. Reference `docs/agent/project-start/FUNCTIONAL_QA_STRATEGY.md` for the project's user loops and verification mechanics.
- **Live Verification Results**: what else you verified during development and how (looser narrative; the structured per-check evidence lives in Functional QA Results above)
- List of all commits made during this phase

### Step 6: Update Status

Edit `docs/agent/project-start/STATUS.md`:
1. Mark your phase as Complete
2. Update "Current Phase" to next phase number
3. Update "Phase Name" to next phase name
4. Update "Last Updated" to today's date (YYYY-MM-DD format)

### Step 7: Final Commit

**Git**: Your code commits are already pushed from Step 4c. Now do a final commit for documentation:
1. Stage all doc changes (summary, STATUS.md, CODEBASE_CONTEXT.md)
2. Commit: `[Phase {N}/{TOTAL}] docs: phase summary and context updates`
3. Push: `git push origin feature/project-start` (only if remote is configured -- this project has no GitHub remote yet, so push is a no-op)

**Jira**: not configured for this feature -- skip.

### Step 8: Stop

Your work is complete! The next agent will handle the next phase.

---

## Environment Setup

This is a Python 3.11+ project managed with `uv`.

### First-time setup (Phase 1 creates this scaffold)

```bash
# Phase 1 establishes the project. Once Phase 1 is complete, all subsequent
# phases just need:
uv sync                  # installs dependencies from pyproject.toml + uv.lock
```

### Activation per session

`uv` does not require manual venv activation. Use `uv run <cmd>` to execute commands inside the project's environment:

```bash
uv run pytest                    # run the test suite
uv run pytest tests/test_paths.py -v   # run a specific test file
uv run croam --help              # run the croam CLI (after Phase 6+)
uv run python -c "import croam"  # ad-hoc import check
```

For long sessions you may prefer activating once:

```bash
source .venv/bin/activate
pytest
```

But the conductor and CI assume `uv run` works without activation.

### Common commands

```bash
uv run pytest                    # run all tests (Tier 1, synthetic fixtures only)
CROAM_E2E=1 uv run pytest        # include Tier 2 tests against /tmp/croam-e2e dummy
uv run pytest -v --lf            # rerun last failed
uv run ruff check src tests      # lint (Phase 1 sets up ruff)
uv run ruff format src tests     # format
uv run pyright src               # type check (Phase 1 sets up pyright)
uv run croam doctor              # diagnose config + reachability (after Phase 9)
```

### External dependencies (must be on PATH)

These are runtime requirements for croam itself, but they are also exercised by integration tests. Verify they exist with `which`:

- `fzf` (interactive picker)
- `tmux` (session multiplexer; `tmux 3.0+` for `display-popup`)
- `ssh` (cross-host fanout; uses `~/.ssh/config`)
- `claude` (the wrapped CLI -- the shim renames it to `claude-real` during install; if not yet installed, the shim falls back to whatever `claude` resolves to)

If any are missing, the test will skip with a clear message rather than fail spuriously.

---

## Development Discipline

### Test-First Development

For every behavior you implement: write a failing test first, watch it fail, then write the minimal code to pass it. This is non-negotiable.

1. **RED**: Write test describing expected behavior. Run it. Confirm it fails because the feature is missing (not because of a typo or import error).
2. **GREEN**: Write the simplest code that passes. No extras.
3. **REFACTOR**: Clean up while tests stay green.

Test command: `uv run pytest`
Run after every implementation chunk. If tests fail after your change, debug systematically (see Workflow step 4b) before attempting fixes.

Phase 1 establishes the test framework, the synthetic fixture infrastructure (HOME redirect, fake `~/.claude` tree, private tmux socket, SSH subprocess shim), and the `CROAM_E2E=1` opt-in for the real-claude dummy session at `/tmp/croam-e2e/`. Once Phase 1 is complete, all subsequent phases follow test-first development against those fixtures.

### Verification Honesty

Before claiming any task is done, run the verification command and read the output. "Should work" is not evidence. "Tests likely pass" is not evidence. Run it, read it, report what it actually says.

### Debugging Protocol

When something fails:
1. Read the FULL error (don't skim)
2. Trace backward to the source of the bad value
3. Form ONE hypothesis, test minimally
4. If 3 hypotheses fail: this is architectural, not a bug. Document and escalate.

---

## Project Helpers

This project ships verified helper scripts under `scripts/` that wrap mechanical tasks so agents don't need to reconstruct them from scratch each phase.

**Coding agents:** consult ONLY the helpers listed in your phase plan's "Helpers Required" section. Do NOT scan this catalog by default -- it exists for reference, for the planner, and for the user. Reaching past your phase plan's allocation usually means the planner under-specified the phase; if you genuinely need a helper that isn't listed, do the work manually this time and record it under your phase summary's "Helper Issues -> Unlisted helpers attempted" subsection.

**Checkpoint agent:** uses deploy/verify-deploy/smoke helpers automatically when configured -- not applicable for this feature (deploy disabled).

No helpers configured for this feature. (Deploy is disabled, Jira is disabled, no smoke harness; planners did not propose any cross-phase shell helpers.)

**On any helper failure:** read the script's `# MANUAL FALLBACK:` comment block, do the work manually, record the failure in your phase summary's "Helper Issues" section. Never edit the helper yourself -- the checkpoint agent owns repairs.

**Self-check:** every helper supports `--self-check` to verify its prerequisites without performing the main action.

---

## Live Verification

**Verify as you build, not just at the end.**

This project uses live verification: every logical chunk of code should be tested against reality before moving on. Do not wait until all deliverables are complete to run the program for the first time.

### Safety Posture

Check `docs/agent/project-start/STATUS.md` for the current safety posture.

This project uses CAUTIOUS safety posture. Before performing any write operation to external systems, databases, or services -- even locally -- ASK the user for permission and explain why the operation could be risky. Read-only operations (GET requests, SELECT queries, log reading, running tests) can be performed freely without asking.

**For croam specifically, "writes you must ask about" include:**
- Anything that would modify the user's real `~/.claude/projects/` or `~/.claude/sessions/` (the safe path is to redirect HOME to a tmp_path in tests; if you have a real reason to touch the real tree, ASK).
- Anything that would create or kill a real tmux session named `claude-<sid>` (use the private socket `tmux -S /tmp/croam-tests/sock-<pid>` for tests).
- Anything that would SSH out to a real configured peer (probe localhost only in tests, or use the SSH subprocess shim).
- Modifying or deleting files under the user's syncthing share at `~/Sync/...`.

### Runtime Context

- **How this runs**: Python CLI invoked from the user's shell. No daemon, no systemd, no docker. Each invocation is a fresh process.
- **Restart after changes**: N/A -- the next invocation picks up new code automatically. For installed-via-pipx use, `uv run croam ...` always uses the latest source.
- **Verify it works**: `uv run pytest` for unit/integration tests. For higher-fidelity manual checks once the CLI is built (Phase 6+): `uv run croam doctor`, `uv run croam ls --json`.
- **Never do this**:
  - Don't run the full test suite without HOME redirection -- the conftest guard refuses, but never override it
  - Don't mock SSH or tmux subprocess in integration paths -- use the real subprocess shim or a real private-socket tmux server
  - Don't write Tier 1 tests that depend on `CROAM_E2E=1` being set -- that defeats the safety boundary

Always verify against the running system described above. Unit tests are necessary but NOT sufficient to claim a feature works. If you cannot test end-to-end, state that explicitly in your phase summary rather than substituting unit tests.

### What to Verify

The project-specific answer lives in `docs/agent/project-start/FUNCTIONAL_QA_STRATEGY.md`. Read it once at the start of the phase. It captures:

- **Surface Inventory** -- what this feature exposes (CLI verbs, the shim, the picker)
- **User Loop** -- the minimal sequence a real user performs and what they observe
- **Verification Mechanics** -- the concrete harness (private tmux socket, SSH subprocess shim, synthetic `~/.claude` tree, opt-in real dummy)
- **Anti-Patterns** -- project-specific traps (mocked subprocesses, real-HOME contamination, fake encoded-cwd that doesn't match claude's actual format)
- **Required Harness Deliverables** -- scaffolding owned by Phase 1

Your phase plan's "Functional QA" section names the specific checks for THIS phase, derived from the strategy. Run each one against the real surface using the verification mechanics, capture the actual command and actual output byte-for-byte, and record pass/fail in your phase summary's "Functional QA Results" section.

### Write Operation Safety

When you need to test write operations (creating tmux sessions, writing ownership.json, copying JSONL files):

1. **Prefer safe patterns**: Always operate on `tmp_path`-rooted fakes (HOME redirect) or the private tmux socket. Real claude trees are off-limits unless `CROAM_E2E=1` AND the operation is explicitly read-only.
2. **Verify before touching**: Before writing to a path, confirm it is under `tmp_path` or `/tmp/croam-tests/...`. Assert this with `assert tmp_path in path.parents` if uncertain.
3. **Never touch production data**: The user's real `~/.claude/projects/` and `~/Sync/croam` are sacred. Even read access goes through the test fixture, not directly.
4. **If no safe method exists**: Discuss with the user. Explain what you want to test and why a fixture cannot cover it.

### Verify Before Coding

If your phase involves interacting with claude's actual data layout (encoded-cwd format, JSONL header schema, sessions metadata fields):
1. Check CODEBASE_CONTEXT.md first -- the dummy session at `/tmp/croam-e2e/` was already inspected during setup
2. If you need fresh observation, set `CROAM_E2E=1` and read (only read!) from the dummy
3. THEN write your integration code based on actual observed behavior, not assumptions
4. Do NOT code based on what the spec says claude does -- verify against the dummy first

---

## Context Budget

You have approximately **120k tokens** total (input + output + thinking).

TDD discipline (test-first for every behavior) uses ~30% more tokens than implementation-only. This is budgeted into phase sizing. Don't skip tests to save context.

**Be strategic**:
- Read only what you need
- Follow the workflow above exactly
- Keep summaries concise
- Don't read entire files when you need one function
- Don't read all phase plans when you need one phase
- Don't explore unrelated code

Each phase is designed to fit within one agent session. If you run out of context:
- Note this in your summary
- Document what's incomplete
- Suggest splitting the phase

---

## Important Notes

### Security -- No Credentials in Repository

**CRITICAL: Never store passwords, API keys, tokens, connection strings, or any secrets in repository files.**

croam itself does not handle credentials -- SSH uses `~/.ssh/config` and key-based auth (`BatchMode=yes` prevents passphrase prompts). Tests must never put real ssh keys, real hostnames-with-secrets, or real syncthing tokens in fixtures.

A pre-commit hook is active on this repository to catch accidental credential leaks and to redact `[LABEL]` markers in agent docs.

#### Pre-commit hook block: bypass procedure

Most blocks are real. The hook redacts `[LABEL]` markers and matches secret-shaped patterns. False positives happen but are not the common case.

**Do NOT bypass with `git commit --no-verify` if any of these are true:**

- The blocked file is under `src/`, `tests/`, `scripts/`
- The blocked file matches `.env*` (any dotenv variant)
- The matched value looks like a real token or private key

**Bypass procedure (only when none of the above hold):**

1. Print to your output: full path of blocked file, the matched pattern (redacted with `[LABEL]` if you can identify a label), and one-sentence justification.
2. Add a `Bypass-reason:` trailer to the commit message: `git commit --no-verify -m "..." -m "Bypass-reason: <one-line reason>"`.
3. Commit. The bypass and reason are now in git history for review.

### Secret Tagging in Documentation

When you reference infrastructure-specific values (hostnames, IP addresses, server paths, port numbers) in agent framework documentation files under `docs/agent/`, use inline tags:

```
[LABEL]
```

Examples:
- `[HOST_STORMTREE]` -- the pre-commit hook redacts this to `[HOST_STORMTREE]` before commit
- `[SYNC_PATH]` -- becomes `[SYNC_PATH]` in the committed file

You always see the real values in your local working copy. Only the committed version is redacted.

### Logging

**Always check logs.** After running code or tests:
1. Check loguru output (stderr) for warnings
2. If `--debug` was used, check `~/.local/state/croam/croam.log` (only if test fixtures redirected this path)
3. Include relevant log observations in your phase summary

### Phase Boundaries

**Respect phase boundaries.** Do not:
- Work on multiple phases at once
- Skip phases
- Go back and refactor previous phases (unless your phase plan says to)

### Dependencies

If your phase depends on previous phases:
- Check that those phases are marked complete in STATUS.md
- Read their summaries to understand what was built
- Note any blockers in your summary if dependencies are incomplete

### Blockers

If you encounter blockers:
- Document them clearly in your summary
- Mark affected completion criteria as incomplete
- Suggest solutions or next steps
- Do NOT mark your phase as complete if critical items are blocked

---

## Quick Checklist

Before you begin:
- [ ] **FIRST: Run `pwd` and verify you're in `/home/tunc/Sync/Programs/croam`**
- [ ] Read `docs/agent/project-start/STATUS.md` to identify your phase and check safety posture
- [ ] Read `docs/agent/project-start/CODEBASE_CONTEXT.md` for codebase knowledge
- [ ] Read the 2 most recent phase summaries from `docs/agent/project-start/summaries/`
- [ ] Read your phase plan from `docs/agent/project-start/phase_plans/PHASE_XX.md`
- [ ] Understand your deliverables and completion criteria

During your work:
- [ ] Stay within your phase boundaries
- [ ] Run `uv sync` once before first command if dependencies changed
- [ ] Build incrementally -- verify each chunk before moving on
- [ ] Check loguru output after running tests
- [ ] Use `[LABEL]` for sensitive values in doc files
- [ ] Commit after each verified chunk (multiple commits per phase is fine)
- [ ] Write tests if required (test-first; see Development Discipline)

After completion:
- [ ] Update `docs/agent/project-start/CODEBASE_CONTEXT.md` with new discoveries and changes
- [ ] Create phase summary using the template (include functional QA section if applicable)
- [ ] Verify all completion criteria are met (or document why not)
- [ ] Update `docs/agent/project-start/STATUS.md`
- [ ] Final commit for docs (see Step 7)
- [ ] Do NOT start the next phase

---

## Ready to Start?

1. Read `docs/agent/project-start/STATUS.md`
2. Follow the workflow above
3. Build, verify, commit -- repeat
4. Document and update status

**Good luck, Agent!**

---

*This quickstart is designed for AI agents working in a phased development workflow.*
