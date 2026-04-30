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
- **Current Batch**: 3
- **Pacing**: auto-refresh
- **Batches Per Session**: 4
- **Execution Plan**: docs/agent/project-start/EXECUTION_PLAN.md

---

**Last Updated:** 2026-04-30
**Current Phase:** 3 of 11
**Phase Name:** Sessions & host probes
**Progress:** 18% (2/11 phases complete)

---

## Progress Bar

```
[##------------------] 18% (2/11)
```

---

## Quick Phase Reference

| Phase | Name | Status |
|-------|------|--------|
| 1 | Foundation: project skeleton, logging, test harness | `[Complete]` |
| 2 | Config & paths | `[Complete]` |
| 3 | Sessions & host probes | `[Current]` |
| 4 | Ownership state | `[Current]` |
| 5 | Tmux integration & claude shim | `[Current]` |
| 6 | Picker & CLI dispatcher | `[Pending]` |
| 7 | Verbs: attach, peek, ls | `[Pending]` |
| 8 | Verbs: claim, fork (incl. ssh-strict, --here) | `[Pending]` |
| 9 | Sync mode & doctor | `[Pending]` |
| 10 | Integration tests round 1 | `[Pending]` |
| 11 | Polish, install, README | `[Pending]` |

---

## Instructions for Agents

Batch 3 runs Phases 3, 4, 5 in parallel under separate worktrees. Each agent should:

1. Read its assigned `phase_plans/PHASE_0X.md`
2. Read the 2 most recent phase summaries (`summaries/PHASE_02_SUMMARY.md`, `summaries/PHASE_01_SUMMARY.md`)
3. Complete the phase following the build-verify-commit cycle
4. Create `summaries/PHASE_0X_SUMMARY.md`
5. Do NOT update STATUS.md, do NOT post to Jira, do NOT push -- the conductor handles all of that

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
