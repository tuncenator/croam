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
- **Feature Docs**: `/home/tunc/Sync/Programs/croam/docs/agent/picker-spec-gaps`

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
|       +-- picker-spec-gaps/   <- Your feature folder
|           +-- QUICKSTART.md              <- You are here
|           +-- PROJECT_PLAN.md            <- Project overview, architecture, cross-cutting
|           +-- STATUS.md                  <- Phase tracker + integrations + deploy config
|           +-- CODEBASE_CONTEXT.md        <- Cumulative codebase knowledge
|           +-- PHASE_SUMMARY_TEMPLATE.md  <- Summary template
|           +-- phase_plans/               <- Individual phase plans
|           |   +-- PHASE_01.md
|           |   +-- PHASE_02.md
|           |   +-- PHASE_03.md
|           +-- summaries/                 <- Completed phase summaries
```

**All paths in this guide are relative to `/home/tunc/Sync/Programs/croam`**

---

## Your Workflow

### Step 1: Find Your Phase

Read `docs/agent/picker-spec-gaps/STATUS.md` to identify:
- Which phase is current (marked as CURRENT)
- Your phase number and name
- Integration settings (Git, Jira, Deployment, Safety Posture)

### Step 2: Get Context

**2a. Read the codebase context** (always, before anything else):
- Read `docs/agent/picker-spec-gaps/CODEBASE_CONTEXT.md`

**2b. Read recent phase summaries** (up to 2 most recent):
- If you're on Phase 3, read `PHASE_02_SUMMARY.md` and `PHASE_01_SUMMARY.md`
- If you're on Phase 1, nothing to read

**Location**: `docs/agent/picker-spec-gaps/summaries/`

### Step 3: Read Your Phase Plan

Open `docs/agent/picker-spec-gaps/phase_plans/PHASE_XX.md` where XX is your phase number.

### Step 4: Build, Verify, Commit (Repeat)

#### 4a. Code a Logical Chunk

Implement a coherent piece of functionality. Keep chunks small enough to verify independently.

#### 4b. Verify Locally

For every claim you make about your code:
1. **Identify** the command that proves the claim
2. **Run** it fresh
3. **Read** the full output and check the exit code
4. **Confirm** the output actually proves what you claim

#### When Verification Fails

1. **Investigate**: Read the full error output. Trace to origin.
2. **Compare**: Find working code doing something similar.
3. **Hypothesize**: One specific theory, test minimally.
4. **Fix**: Single targeted change. Re-run verification.

#### 4c. Commit

**Format**: `[Phase {N}/3] {verb}: {what changed}`

**Verbs** (lowercase): `add`, `fix`, `update`, `refactor`, `remove`, `docs`

### Step 5: Document Your Work

**5a. Update codebase context**: Edit `docs/agent/picker-spec-gaps/CODEBASE_CONTEXT.md`

**5b. Create phase summary**: `docs/agent/picker-spec-gaps/summaries/PHASE_XX_SUMMARY.md`

### Step 6: Update Status

Edit `docs/agent/picker-spec-gaps/STATUS.md`

### Step 7: Final Commit and Push

```
git push origin feature/picker-spec-gaps
```

### Step 8: Stop

Your work is complete! The next agent will handle the next phase.

---

## Environment Setup

**First-time setup:**
```bash
uv sync
```

**Activation (run before every session):**
```bash
source .venv/bin/activate
```

**Common commands:**
```bash
uv run pytest                    # Run all tests
uv run pytest tests/test_picker.py  # Run picker tests only
uv run pytest -x                 # Stop on first failure
uv run ruff check src/ tests/    # Lint
uv run ruff format src/ tests/   # Format
uv run pyright                   # Type check
```

---

## Development Discipline

### Test-First Development

For every behavior you implement: write a failing test first, watch it fail, then write the minimal code to pass it. This is non-negotiable.

1. **RED**: Write test describing expected behavior. Run it. Confirm it fails because the feature is missing (not because of a typo or import error).
2. **GREEN**: Write the simplest code that passes. No extras.
3. **REFACTOR**: Clean up while tests stay green.

Test command: `uv run pytest`
Run after every implementation chunk.

### Verification Honesty

Before claiming any task is done, run the verification command and read the output. 'Should work' is not evidence. 'Tests likely pass' is not evidence. Run it, read it, report what it actually says.

### Debugging Protocol

When something fails:
1. Read the FULL error (don't skim)
2. Trace backward to the source of the bad value
3. Form ONE hypothesis, test minimally
4. If 3 hypotheses fail: this is architectural, not a bug. Document and escalate.

---

## Project Helpers

No helpers configured for this feature.

---

## Live Verification

**Verify as you build, not just at the end.**

### Safety Posture

This project uses CAUTIOUS safety posture. Before performing any write operation to external systems, databases, or services -- even locally -- ASK the user for permission and explain why the operation could be risky. Read-only operations (GET requests, SELECT queries, log reading, running tests) can be performed freely without asking.

### Runtime Context

- **How this runs**: CLI tool invoked as `croam` (no persistent process)
- **Restart after changes**: N/A (stateless CLI, each invocation is fresh)
- **Verify it works**: `uv run pytest` for unit/integration tests; manual `uv run croam` for interactive verification
- **Never do this**: Don't mock fzf internals for verification; use the fake-fzf subprocess helper in `tests/_helpers/fake_fzf.py`

### What to Verify

Read `docs/agent/picker-spec-gaps/FUNCTIONAL_QA_STRATEGY.md` for project-specific verification mechanics.

---

## Context Budget

You have approximately **120k tokens** total (input + output + thinking).

TDD discipline uses ~30% more tokens than implementation-only. This is budgeted into phase sizing. Don't skip tests to save context.

---

## Important Notes

### Security -- No Credentials in Repository

**CRITICAL: Never store passwords, API keys, tokens, connection strings, or any secrets in repository files.**

### Logging

**Always check logs.** After running code, check application logs for errors or unexpected behavior.

### Phase Boundaries

**Respect phase boundaries.** Do not work on multiple phases at once, skip phases, or go back and refactor previous phases.

---

## Quick Checklist

Before you begin:
- [ ] **FIRST: Run `pwd` and verify you're in `/home/tunc/Sync/Programs/croam`**
- [ ] Read `docs/agent/picker-spec-gaps/STATUS.md`
- [ ] Read `docs/agent/picker-spec-gaps/CODEBASE_CONTEXT.md`
- [ ] Read recent phase summaries from `docs/agent/picker-spec-gaps/summaries/`
- [ ] Read your phase plan from `docs/agent/picker-spec-gaps/phase_plans/PHASE_XX.md`

During your work:
- [ ] Stay within your phase boundaries
- [ ] Build incrementally -- verify each chunk before moving on
- [ ] Commit after each verified chunk
- [ ] Write tests first

After completion:
- [ ] Update `docs/agent/picker-spec-gaps/CODEBASE_CONTEXT.md`
- [ ] Create phase summary
- [ ] Update `docs/agent/picker-spec-gaps/STATUS.md`
- [ ] Final commit for docs, push
