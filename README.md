# The Commoner's Benchmark

Hermes Agent v0.23.1 and OpenBot 0.65.0 on all 89 tasks of Terminal-Bench 2.0, both running DeepSeek V4.1 Flash
(`deepseek/deepseek-v4.1-flash-1017` on OpenRouter) at reasoning effort high. One attempt per task, standard time limits,
same machine.

**Report:** https://conficked.github.io/commoners-benchmark/

| | Hermes Agent | OpenBot |
|---|---|---|
| Clean start, tasks solved | 65 of 89 (73%, 95% CI 63–81%) | 58 of 89 (65%, 95% CI 55–74%) |
| Lived-in profile, tasks solved | 71 of 89 (80%) | 64 of 89 (72%) |
| Cost per solved task, clean start | $0.057 | $0.048 |
| Cost per solved task, lived-in, learning included | $0.080 | $0.045 |

Hermes solved 12 tasks that OpenBot missed and OpenBot solved 5 that Hermes missed (exact McNemar p = 0.14). The lead
is consistent across both tracks but within the margin of error for 89 tasks.

## Tracks

- **Clean start:** a fresh profile for every task.
- **Lived-in:** one profile per harness, carried through all 89 tasks in a fixed order (`livedin/order.txt`, seed 1710).
  After each task the harness runs its own learning step (Hermes `/refine`, OpenBot thread archiving and memory review),
  and the profile is saved and restored for the next task.

## What's here

| Path | What it is |
|---|---|
| `index.html` | The report. Built by `report/build_report.py`; every number in it comes from `analysis/data/` |
| `analysis/data/` | The datasets: one row per kept trial, discarded attempts, learning steps, memory kills, summary |
| `analysis/README.md` | Field definitions and how cost and time are measured |
| `analysis/disclosures.md` | Every incident, rerun and rollback, and how it affects the results |
| `analysis/integrity.md` | Output of the automated integrity checks |
| `bench_agents.py` | The two Harbor agents: `HermesHigh` and `OpenBotTB` |
| `livedin.py` | The lived-in loop: run a task, run the learning step, snapshot the profile |
| `hermes/refine.py` | Runs Hermes's `/refine` learning step inside the task container |
| `openbot/` | Runs the OpenBot desktop app on a virtual display inside each task container and drives it over the Chrome DevTools Protocol |

## Running it

Requirements: [Harbor](https://github.com/laude-institute/harbor) 0.25.0, Docker, an OpenRouter key in `OPENROUTER_API_KEY`.

```bash
# clean start, one harness at a time
harbor run -d terminal-bench@2.0 -a bench_agents:HermesHigh -m openrouter/deepseek/deepseek-v4.1-flash-1017 \
  --ak version=v0.23.1 -n 1 -o jobs/fresh-hermes
harbor run -d terminal-bench@2.0 -a bench_agents:OpenBotTB -m openrouter/deepseek/deepseek-v4.1-flash-1017 \
  -n 1 -o jobs/fresh-openbot

# lived-in
python3 -I livedin.py hermes
python3 -I livedin.py openbot
```

Both agents unpack a pre-built payload into each container instead of installing from the network. The payloads
are not published because they contain an API key and a signed-in app profile:

- `hermes/payload.tar`: a Hermes v0.23.1 install made with the official installer plus `hermes pm repair`, with an
  untouched data root at `/tmp/hermes`.
- `openbot/payload.tar`: the OpenBot 0.65.0 Linux app, a profile with one agent set to OpenRouter and effort High,
  and `rootshim.so` built from `openbot/rootshim.c`.

The raw job folders (transcripts, logs, harness databases) are not in this repo. They are large and still need to
be checked for keys before release.

To rebuild the datasets from raw runs: `python3 -I analysis/build_dataset.py`, then `analysis/build_page_data.py`
(which also needs the TB2 task files in `tb2/`). To rebuild the report from the published data alone:
`python3 -I report/build_report.py`.
