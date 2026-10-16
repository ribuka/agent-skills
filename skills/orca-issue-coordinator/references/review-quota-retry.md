# Reviewer quota retry

Read this when a worker report contains `reviewer-quota-exhausted: <agent>`
from `pr-cross-review`, or when a `review-retry:<run-id>:<pr>` wake-up fires.
`<quota-check>`, `<run-id>`, and `<agent>` mean the same as in `SKILL.md`.

A reviewer quota failure with a known reset time is transient: the answer is
always "retry after the reset", so do not ask the user.

## On the report

1. Run `bash ~/.agents/skills/pr-cross-review/scripts/review_status.sh <pr-number>`.
   - If `review-count` is higher than the count in the handoff, a review was
     posted after all: treat it as a normal review result.
   - Otherwise no review was posted, and the failed attempt does not count
     toward `MAX_REVIEWS`.
2. Block the PR and ask the user (`SKILL.md` **Asking the user**) instead of
   retrying when any of these holds:
   - `reviewer-quota-reset` is `unknown`, or no clock time can be read from it.
   - This PR's review already failed on reviewer quota once in this Run (the
     retry failed again).
3. Otherwise keep the PR blocked and compute the retry time: the reset time
   plus 2 minutes, rounded up to the minute, in the machine's local timezone.
   Resolve a reset phrase without a date against `reviewer-quota-detected-at`
   (its first occurrence after that time), never against the time you process
   the report. If the retry time has already passed, skip the wake-up and
   retry now as in **On wake-up** step 4.
4. Record in the Run checkpoint: PR, branch, worktree, the interrupted phase
   (Implementation or Merge preparation), review count, retry time, and the
   wake-up marker `review-retry:<run-id>:<pr>`. Release the worker terminal
   (`worker-release`).
5. Schedule exactly one wake-up per PR at the retry time:
   - **Claude Code:** run `CronList`; if the marker already exists, do not
     create another. Otherwise create one one-shot (`recurring: false`)
     `CronCreate` prompt containing the marker, the checkpoint path, this
     file's path
     (`~/.agents/skills/orca-issue-coordinator/references/review-quota-retry.md`),
     and the instruction to follow **On wake-up** in it.
   - **Codex:** follow the `quota-guard` skill's Codex Orca automation
     procedure with the automation name `review-retry:<run-id>:<pr>` and a
     `cron` for the retry time. Put the same marker, checkpoint path, file
     path, and instruction in the wake text. Record the automation ID.
6. Continue other Tasks and keep waiting as in `SKILL.md` **Waiting**.

## On wake-up

1. **Codex:** remove the `review-retry:<run-id>:<pr>` automation first.
2. If the quota is paused, follow `quota-pause.md` first; the retry waits
   until the Run resumes.
3. Run `review_status.sh <pr-number>` again and reconcile it with the
   checkpoint.
4. After a READY `<quota-check>`, and within `MAX_WORKERS`, start one fresh
   worker for the interrupted phase in the PR's worktree, with the model and
   effort of that phase:
   `worker-start --spec "<handoff>" --task-title "#<issue> PR #<pr> review retry" --worktree branch:<branch> --agent <agent>`.
   The handoff gives the mode and phase, the Issue, PR URL, branch,
   worktree, and review count, and tells the worker to resume at the
   cross-review: run `pr-cross-review`, address its findings, and report
   `worker_done` with the handoff fields as usual.
5. If that review fails again on reviewer quota, follow **On the report**,
   which blocks the PR and asks the user.
