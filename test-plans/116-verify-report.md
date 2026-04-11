---
issue: 116
pr: 117
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS
---

# Verify Report: Fix start.sh empty-array expansion crash under macOS bash 3.2

- **Issue**: liyoclaw1242/fund-attribution-mvp#116
- **PR**: #117 (`agent/ops-20260411-0043237/issue-116`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Origin**: Bug #3 from #106 live smoke — the bash bug I missed in my #105 static review.

## Acceptance Criteria

The issue had no formal AC list; inferred from the root cause I filed in #106:
1. `scripts/start.sh` no longer crashes under `set -u` + `/bin/bash` 3.2 when no arguments are passed
2. Both dev-mode (`PROFILE_ARGS=()`) and production-mode (`PROFILE_ARGS=(--profile production)`) code paths work
3. Fix is minimal; no scope drift

## Results

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Fix idiom correct (`${arr[@]+"${arr[@]}"}`) | PASS | Both expansion sites (`up -d` line 34, `ps` line 38) use the guarded form. |
| 2 | Works on system bash 3.2.57 | PASS | Live test: `/bin/bash --version` → `3.2.57(1)-release (arm64-apple-darwin25)`. Extracted the fixed script into a tmpdir via `git show 68a42c5:scripts/start.sh` and ran an isolated test: under `set -euo pipefail`, empty-array expansion gives 0 results, non-empty gives 2 results. No "unbound variable" error. |
| 3 | `bash -n` syntax check passes | PASS | `/bin/bash -n /tmp/.../start.sh` → exit 0. |
| 4 | No stray old pattern | PASS | `grep -n "PROFILE_ARGS" start.sh` → only 4 lines, all either declaration, assignment, or the new guarded form. |
| 5 | Scope drift | NONE | `git show 68a42c5 --stat`: `scripts/start.sh | 7 +++++--` — single file, 5 insertions / 2 deletions. |
| 6 | Header comment documents the fix | PASS | New comment block added: `# Compatible with bash 3.2+ (macOS default). Array expansions use the ${arr[@]+"${arr[@]}"} idiom so empty arrays don't trip set -u.` Future readers will understand why the extra `+` is there. |

## Diff Summary

```diff
+# Compatible with bash 3.2+ (macOS default). Array expansions use the
+# ${arr[@]+"${arr[@]}"} idiom so empty arrays don't trip `set -u`.

-docker compose "${PROFILE_ARGS[@]}" up -d
+docker compose ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} up -d

-docker compose "${PROFILE_ARGS[@]}" ps
+docker compose ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} ps
```

## Isolation Test Transcript

```bash
/bin/bash -c '
set -euo pipefail
PROFILE_ARGS=()
result=( ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} )
echo "empty: count=${#result[@]}"

PROFILE_ARGS=(--profile production)
result=( ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} )
echo "non-empty: count=${#result[@]} values=${result[*]}"
'
```

Output:
```
empty: count=0
non-empty: count=2 values=--profile production
```

No errors. No "unbound variable". Both branches of the `if` at line 27 now evaluate cleanly.

## Why I'm Not Running `bash scripts/start.sh` Directly

**Shared-worktree hazard**: during this session, I observed another agent concurrently modifying files in this repo (checked out a different branch out from under me, possibly uncommitted changes to `service/Dockerfile` + `service/requirements.txt` in progress). Running `start.sh` invokes `docker compose up -d` which would race against any other agent's docker operations, and the script reads `docker-compose.yml` from the working tree — which could be mid-edit by another process.

The isolation approach (extract via `git show <commit>:<path>`, test in a tmpdir, no working-tree dependency) is race-safe and gives equivalent signal for this specific fix.

## Verdict

**PASS**

The fix is correct, minimal, and well-documented. The bug I caught in #106 and missed in #105 is now closed. Bash-3.2-compatible idiom is used in both expansion sites.

## Recommendation

**Merge.** Closes Bug #3 from #106.

## #106 Status After This Merge

| Bug | Status |
|-----|--------|
| #1 service pandas | ❌ still open (no verified fix yet — working tree shows in-progress pandas addition by another agent) |
| #2 schema PK/partition | ✅ merged (#118 / #115) |
| #3 start.sh array expansion | ✅ merged via this PR (#117 / #116) |

**#106 can be re-verified full-stack once Bug #1 is also fixed.** Given the working-tree state suggests someone is already adding pandas to `service/requirements.txt`, that fix is likely in flight.

## Process Note for ARCH

This session surfaced a real shared-worktree race — another agent's branch checkout moved my HEAD out from under me between commands. Two of my git operations could have destroyed uncommitted WIP (I caught it when a subsequent `git status` showed an unexpected branch). I'm adopting stricter isolation for future verifications:
- Never `git reset --hard` unless I'm certain no other agent is working in this repo
- Use `git show <ref>:<path>` to read files instead of relying on the working tree
- Always re-check `git branch --show-current` before any write operation
- Commit report files directly on `main` with a tight `git add <specific-file> && commit && push` sequence

Recommend ARCH either (a) serialize QA/BE/OPS git operations in this shared worktree, or (b) move agents to `git worktree add` so each has an isolated working tree.
