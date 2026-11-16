# Integrity check (2026-11-16 13:48)

24 passed, 2 known and disclosed, 0 failed (of 26).

- PASS: fresh/hermes: one kept trial per TB2 task
- PASS: fresh/openbot: one kept trial per TB2 task
- PASS: livedin/hermes: one kept trial per TB2 task
- PASS: livedin/openbot: one kept trial per TB2 task
- PASS: no older results left inside kept Lived-in task dirs
- PASS: Harbor config: right agent and model on every kept trial
- PASS: Hermes pinned to v0.23.1 on every trial
- PASS: only deepseek/deepseek-v4.1-flash-1017 was actually called (harness usage records)
- PASS: reasoning effort recorded as high on every trial
- PASS: no timeout multipliers (stock TB2 limits)
- PASS: all trials used the same TB2 commit
- PASS: same task checksum across all four cells
- PASS: token usage found for every kept trial
- PASS: every kept trial graded (verifier timeouts count as graded fails)
- PASS: no setup failures or failed OpenBot app restarts among kept trials
- KNOWN: no harness crashed mid-task (crashed trials are kept as graded fails) (fresh/hermes/caffe-cifar-10: gateway_disconnected; fresh/hermes/gpt2-codegolf: gateway_disconnected; livedin/hermes/caffe-cifar-10: gateway_disconnected; fresh/openbot/caffe-cifar-10: renderer_crashed; fresh/openbot/compile-compcert: renderer_crashed; livedin/openbot/caffe-cifar-10: renderer_crashed)
- PASS: livedin/hermes: tasks done in the fixed order
- PASS: livedin/hermes: a profile snapshot after every task
- PASS: livedin/hermes: loop's recorded reward matches the kept trial
- PASS: livedin/hermes: no failed learning passes
- PASS: livedin/openbot: tasks done in the fixed order
- PASS: livedin/openbot: a profile snapshot after every task
- PASS: livedin/openbot: loop's recorded reward matches the kept trial
- KNOWN: livedin/openbot: no failed learning passes (14 caffe-cifar-10: learn error: undefined is not an object (evaluating 'ws.onopen = resolve'))
- PASS: no leftover task containers, networks or runs
- PASS: no API key in the report datasets
