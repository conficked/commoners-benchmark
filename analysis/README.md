# The Commoner's Benchmark: data

Hermes Agent v0.23.1 vs OpenBot 0.65.0 on Terminal-Bench 2.0 (89 tasks, commit 69671fba), both on
`deepseek/deepseek-v4.1-flash-1017` via OpenRouter at reasoning effort high, one attempt per task, stock TB2 timeouts.

Rebuild everything (read-only on the raw runs): `python3 -I analysis/build_dataset.py`

## Tracks

- **Fresh**: every task starts from a clean profile.
- **Lived-in**: one profile per harness carried through all 89 tasks in a fixed order (seed 1710, `livedin/order.txt`).
  After each task, the harness runs its own built-in learning step: Hermes `/refine` (skill and memory review),
  OpenBot archiving the task thread (memory review). The resulting profile is saved and restored for the next task.

## Files

| File | What it is |
|---|---|
| `integrity.md` | Automated integrity checks over all kept data |
| `disclosures.md` | Every incident, rerun and rollback, and what it means for the results |
| `data/trials.csv` | One row per kept trial (4 cells x 89 = 356) |
| `data/discarded_attempts.csv` | Every archived attempt (`invalid/`), with the reason it was discarded |
| `data/learning.csv` | Lived-in learning step after each task, both harnesses |
| `data/summary.json` | Per-cell results, paired comparisons, and the first-attempt sensitivity check |
| `data/oom_kills.csv` | Every kernel memory kill during the benchmark, matched to its trial, with the victim, its kill priority and the harness's own memory use (snapshot by `extract_oom.py`, because the kernel logs rotate) |
| `data/wifi_drops.txt` | WiFi drops during the benchmark (from syslog) |

## Key fields (`trials.csv`)

- `passed`: 1 if the verifier's reward is 1.0. A trial whose grading timed out counts as a fail
  (`verifier_timeout` = 1), as TB2 scores it.
- `agent_timeout`: the agent hit the task's TB2 time limit (graded on whatever it left behind).
- `working_secs`: the harness's own working time. Hermes: session start to end. OpenBot: instruction sent to agent
  finished, minus the driver's 15 s idle confirmation. App/CLI startup is excluded for both.
- `tokens_in` / `tokens_cached` / `tokens_out`: from each harness's own usage records (Hermes `state.db`, all sessions
  including subagents; OpenBot `agent_usage_records`, cut off at the learning step).
- `cost_usd`: tokens at one flat rate, $0.15 / $0.003 / $0.60 per million (input / cached / output). Each
  harness's self-reported cost uses its own price table, and OpenRouter's price for this model varies by time
  of day, so a flat rate keeps the comparison even. The flat total matched the actual OpenRouter spend to
  within $0.04.
- `models_seen`, `effort`: what the harness actually recorded for that trial (not just what was configured).
- `harness_errors`: `renderer_crashed` (OpenBot's Electron renderer died), `gateway_disconnected` (Hermes's gateway
  process died). In both cases the task was still graded.
- `provider_incidents`: times OpenBot's OpenRouter provider stayed in an error state long enough that the driver
  restarted the app.
- `oom_kills`, `oom_victims`, `oom_harness_process_killed`: kernel memory kills in the trial's container, and whether
  one hit the harness's own process.
- `wifi_drops_during`: WiFi drops inside the trial's time window.

## Key fields (`learning.csv`)

- `review_outcome`: Hermes `review:<what it saved>`; OpenBot `review:memories`, `skipped_by_harness` (OpenBot started
  no review), or `failed`.
- `review_*` tokens and `review_cost_usd`: the learning step's own usage, at the same flat rate. It is not part of the
  task's `cost_usd`.
