# croam Project Status

## Project Location

**IMPORTANT: Verify your location before working!**

- **Project Root**: `/home/tunc/Sync/Programs/croam`
- **Feature Docs**: `/home/tunc/Sync/Programs/croam/docs/agent/project-start`
- **Verify with**: `pwd` -> should output `/home/tunc/Sync/Programs/croam`

**Always work from the project root directory. All paths below are relative to project root.**

---

## Integrations

- **Git**: enabled
- **Branch**: feature/project-start
- **Jira Issue**: disabled
- **GitHub Repo**: N/A

### Deployment

- **Deploy Enabled**: disabled
- **SSH Host**: N/A
- **SSH User**: N/A
- **Target Path**: N/A
- **Service Name**: N/A
- **Restart Command**: N/A
- **Log Source**: N/A

### Verification

- **Live Verification**: enabled
- **Safety Posture**: cautious
- **Runtime Model**: binary (Python CLI invoked fresh per call; no daemon)
- **Restart Command**: N/A (no daemon)
- **Verification Command**: `uv run pytest`
- **Anti-Patterns**: never mock SSH or tmux subprocess in integration paths; never run tests against the user's real `~/.claude` or `~/.ssh` (HOME must be redirected to tmp_path); never write to syncthing share paths during tests

### Smoke Harness

- **Smoke Enabled**: disabled
- **Surface Type**: N/A
- **Surface Markers**: N/A
- **Target Details**: N/A
- **Prerequisites**: N/A
- **Helper Script**: N/A

### Conductor

- **Total Batches**: 8
- **Current Batch**: 0 (not started)
- **Pacing**: auto-refresh
- **Batches Per Session**: 4
- **Execution Plan**: docs/agent/project-start/EXECUTION_PLAN.md

---

**Last Updated:** 2026-04-30
**Current Phase:** 1 of 11
**Phase Name:** Foundation: project skeleton, logging, test harness
**Progress:** 0% (0/11 phases complete)

---

## Progress Bar

```
[-----------] 0% (0/11)
```

---

## Quick Phase Reference

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundation: project skeleton, logging, test harness | `[Current]` |
| 2 | Config & paths | `[Pending]` |
| 3 | Sessions & host probes | `[Pending]` |
| 4 | Ownership state | `[Pending]` |
| 5 | Tmux integration & claude shim | `[Pending]` |
| 6 | Picker & CLI dispatcher | `[Pending]` |
| 7 | Verbs: attach, peek, ls | `[Pending]` |
| 8 | Verbs: claim, fork (incl. ssh-strict, --here) | `[Pending]` |
| 9 | Sync mode & doctor | `[Pending]` |
| 10 | Integration tests round 1 | `[Pending]` |
| 11 | Polish, install, README | `[Pending]` |

---

## Instructions for Agents

1. Read `phase_plans/PHASE_01.md` for detailed requirements for Phase 1
2. This is the first phase - no previous summaries to read
3. Complete the phase following the build-verify-commit cycle
4. Create `summaries/PHASE_01_SUMMARY.md`
5. Update this file:
   - Mark Phase 1 as `[Complete]`
   - Set Phase 2 as `[Current]`
   - Update "Current Phase" to "2 of 11"
   - Update "Progress" percentage and count
   - Update progress bar (each `#` = completed phase, each `-` = remaining phase)

**Phase plans:** See `phase_plans/PHASE_XX.md`
**Project overview:** See `PROJECT_PLAN.md`

---

## Legend

- `[Complete]` - Phase finished and summary created
- `[Current]` - Phase currently being worked on
- `[Pending]` - Phase not yet started
- `[Blocked]` - Phase cannot proceed due to blocker
- `[InReview]` - Phase complete but needs review

---

## Notes

[Optional section for tracking blockers, decisions, or important notes. Conductor escalations write `BLOCKED:` lines here. Skipped gates are tracked separately in the next section.]

---

## Skipped Gates

> Populated by `/spark-conductor` when a user opts out of a quality gate via 4e-escalate `skip`. Empty on a clean run. Step 5 (Completion) surfaces this in the final progress display and the closing Jira comment.

| Batch | Gate | Date | Reason |
|-------|------|------|--------|

[No skipped gates -- delete this placeholder line when the first row is added.]
