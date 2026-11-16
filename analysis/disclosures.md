# Disclosures

Everything that went wrong or needed a judgment call, and how it was handled. Counts come from `data/summary.json`;
discarded attempts are kept in `invalid/` and listed in `data/discarded_attempts.csv`.

## Rule for discarding an attempt

An attempt was discarded and rerun only when our own setup or automation broke it, never because of how the agent
did. Two kinds:

1. **The agent never got a fair run**: the setup failed before the agent started, or our driver failed to restart
   the app.
2. **Lived-in only: our automation lost the learning step**. The score was valid, but the profile carried into the
   next task would have been wrong. The task was rerun from the previous saved profile. Any later tasks already
   run on that profile were rolled back and rerun too, because they had started from it.

The same rule was applied to both harnesses. Because a rerun can change a result either way, the
first-attempt sensitivity check below scores every task by its first graded attempt instead.

## Sensitivity: first graded attempt

| Cell | Kept | First graded attempt |
|---|---|---|
| Fresh Hermes | 65 | 65 |
| Fresh OpenBot | 58 | 57 |
| Lived-in Hermes | 71 | 69 |
| Lived-in OpenBot | 64 | 63 |

Hermes leads by 7 (Fresh) and 7 (Lived-in) as kept, and by 8 and 6 on first graded attempts. The task-level
differences are listed in `summary.json`. The Lived-in first attempts mostly come from rolled-back sequences, so
they ran on a different profile than the kept ones.

## Discarded attempts (US$3.46 of model usage, not counted in any result)

| Archive | Attempts | Cause | Harness affected |
|---|---|---|---|
| `livedin-hermes-run1` | 9 | Learning-step script reopened the wrong Hermes session (tasks 1–8, first run) | Hermes |
| `livedin-*-netfail` | 28 + 27 | Our cleanup removed the wrong Docker networks, exhausting Docker's address pool; both runs rolled back (Nov 12) | Both |
| `fresh-hermes-aptfail`, `livedin-*-aptfail` | 2 + 1 + 1 | Debian 11 security mirrors return 404 (Nov 12); Harbor's install of curl/git failed before the agent ran. Fixed with an archive.debian.org fallback for the harness's own dependencies only | Both |
| `livedin-hermes-reviewfail` | 33 | After a task timeout, Hermes keeps the killed turn open and refuses `/refine`; 6 learning steps (tasks 27–58) failed silently. Fixed by closing and reopening the session; rolled back to task 26 | Hermes |
| `fresh-openbot-restartfail`, `livedin-openbot-restartfail` | 4 + 14 | Our driver relaunched OpenBot before the old app released its debug port. 4 Fresh tasks were rerun; Lived-in tasks 61 and 69 were hit, so the run was rolled back to task 60 | OpenBot |
| `livedin-openbot-dotname`, `livedin-hermes-dotname` | 36 + 1 | Task 32 (`install-windows-3.11`, the only dotted name) broke our container lookup, so the profile after task 32 was not saved. Hermes's was recovered from the kept container; OpenBot was rolled back to task 31 | Both |
| `livedin-hermes-wifidrop` | 1 | A WiFi drop during Hermes's install step on task 40 (DNS failure before the agent ran) | Hermes |
| `livedin-hermes-verifiertimeout` | 2 | Tasks 68 and 80: grading ran past its limit, and our loop deleted the container, losing the learning step. Rerun from the previous profile; the loop now scores these as fails and keeps the container | Hermes |
| `fresh-cancelled-pause` | 2 | Cancelled mid-run when the operator paused the benchmark | Both |

## Kept as genuine results

- **Agent timeouts** (graded on what the agent left behind): Fresh Hermes 8, Fresh OpenBot 10, Lived-in Hermes 10,
  Lived-in OpenBot 14.
- **Grading timeouts** (counted as fails): Fresh Hermes 1 (query-optimize), Fresh OpenBot 2 (query-optimize,
  torch-tensor-parallelism). filter-js-from-html's grading normally takes 8–13 of its 15 minutes.
- **Harness crashed mid-task** (graded as fails). The kernel's records of each memory kill, matched to trials by
  container start time (`data/oom_kills.csv`), show the cause:
  - OpenBot, caffe-cifar-10 (both tracks) and compile-compcert (Fresh): the agent's parallel build filled the task
    container's memory, and the kernel killed OpenBot's own app processes first. Its Chromium renderer is marked
    `oom_score_adj 300` ("kill me first", Chromium's default), so a 64 MB renderer was chosen ahead of compiler
    processes using 150–480 MB each. Losing the renderer ends the session ("Target crashed").
  - Hermes, caffe-cifar-10 (Lived-in): same kind of build. Hermes's processes carry no such mark, so the kernel
    killed the largest single process, which was Hermes's own gateway (267 MB).
  - Hermes, gpt2-codegolf (Fresh): the agent's own script used 3.8 GB of the 4 GB limit and was the process killed;
    Hermes's gateway (not killed) disconnected 7 s later.
  - Hermes, caffe-cifar-10 (Fresh): no memory kill in that container; the gateway disconnected during the build for
    a reason its logs (lost with the container) don't record.
- **Memory footprint and kills**: OpenBot's app plus helpers used about 80–700 MB at kill time (more with a
  Lived-in profile), Hermes about 220–440 MB. In kept trials, OpenBot's own processes were killed in 5 trials
  (Fresh 2, Lived-in 3; in 2 of them the app survived), Hermes's in 1. The difference comes from the kill
  priority above, not from OpenBot being larger.
- **OpenBot provider incident**: on Fresh qemu-alpine-ssh, OpenBot's OpenRouter provider stayed in an error state;
  the driver restarted the app (as a user would) and the task then timed out.
- **Debian 11 tasks** (qemu-startup, qemu-alpine-ssh): the agents in both harnesses hit the same 404s from inside the
  task.

## Lived-in learning step

- Hermes: 89/89 completed (42 saved skills, 46 skills and memories, 1 memory only). Cost US$1.88, separate from
  task cost.
- OpenBot: 72 memory reviews, 16 skipped by OpenBot, 1 failed. Cost US$0.07. OpenBot natively skips the review
  after a stopped (timed-out) turn (12 of the 16) and when the agent already saved its memories during the task (4).
  The failure was task 14 (caffe-cifar-10): the renderer had crashed, so there was no app left to archive the
  thread in. OpenBot's background review runs at the lowest reasoning effort; that is OpenBot's design, not our
  setting.

## Network

The machine was on WiFi. Of 13 brief drops (about 4 s each) during the benchmark period, one broke a setup step
(Hermes, Lived-in task 40, rerun above); every kept trial ran to a graded result.

## Not changed from stock

Both harnesses ran with their default built-in skills and settings (Hermes's bundled skills, OpenBot's 3 built-in
skills), in fresh profiles on a throwaway account. Only the model, effort and a shared one-line prompt prefix
(`Working directory for this task: <pwd>`) were set, identically for both.
