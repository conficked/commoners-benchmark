"""Lived-in track: one persistent profile per harness carried through all TB2 tasks in a fixed order.

usage: python3 -I livedin.py <hermes|openbot> [--limit N]

Per task: Harbor runs and grades the task with the saved profile restored (LIVEDIN_STATE), keeping
the stopped container. Each harness gets its own native learning pass: Hermes after grading, by typing
/refine into its interactive CLI in the restarted container; OpenBot at the end of its trial, by
archiving the task thread in the still-open app, which starts its memory review (its turn counts live
in memory, so a restarted app has nothing to review; the review is text-only and writes only
OpenBot's memories, so it can't touch what the verifier grades). The resulting profile is saved for
the next task. Resumable: finished tasks
are skipped.
"""
import json
import os
import random
import shutil
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = "openrouter/deepseek/deepseek-v4.1-flash-1017"
SEED = 1710
AGENTS = {"hermes": "bench_agents:HermesHigh", "openbot": "bench_agents:OpenBotTB"}
STATE_PATHS = {
    "hermes": "--exclude=tmp/hermes/installs --exclude=tmp/hermes/cache tmp/hermes",
    "openbot": ("--exclude=root/.config/OpenBot/provider-runtimes --exclude='*Cache*' "
                "--exclude='Singleton*' --exclude=root/.config/OpenBot/logs root/.config/OpenBot root/OpenBot"),
}
BUN = "/opt/openbot/profile/provider-runtimes/bun/linux-x64/1.4.4/bin/bun"


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)


def task_order():
    path = ROOT / "livedin" / "order.txt"
    if not path.exists():
        tasks = sorted(p.parent.name for p in (ROOT / "tb2").glob("*/*/instruction.md"))
        random.Random(SEED).shuffle(tasks)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(tasks) + "\n")
    return path.read_text().split()


def openrouter_key():
    for line in (Path.home() / ".hermes" / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("OPENROUTER_API_KEY not found")


def container(result):
    # Harbor's compose project name (_sanitize_docker_compose_project_name): "install-windows-3.11"
    # runs as "install-windows-3-11__...".
    project = re.sub(r"[^a-z0-9_-]", "-", result["trial_name"].lower())
    return project, project + "__env-main-1"


def learn(harness, ctr, workdir, key, jobs):
    if harness == "hermes":
        py = sh(f"docker exec {ctr} bash -c 'ls /root/.hermes/tools/python-*/bin/python3 | head -1'").stdout.strip()
        sh(f"docker cp {ROOT}/hermes/refine.py {ctr}:/tmp/refine.py")
        r = sh(f"docker exec -w {workdir} -e OPENROUTER_API_KEY {ctr} {py} /tmp/refine.py {workdir}", timeout=1200,
               env=dict(os.environ, OPENROUTER_API_KEY=key))
        return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else f"refine failed: {r.stderr[-300:]}"
    # OpenBot's pass already ran inside the trial (OpenBotTB.run); its result is in the agent logs.
    f = next(jobs.glob("*/*/agent/learn.txt"), None)
    lines = f.read_text().strip().splitlines() if f else []
    return lines[-1] if lines else "learn.txt missing"


def main():
    harness = sys.argv[1]
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    base = ROOT / "livedin" / harness
    (base / "snapshots").mkdir(parents=True, exist_ok=True)
    state = base / "state.tar"
    key = openrouter_key()
    env = dict(os.environ, PYTHONPATH=str(ROOT), OPENROUTER_API_KEY=key, LIVEDIN_STATE=str(state))

    for idx, task in enumerate(task_order()[:limit], 1):
        tag = f"{idx:03d}-{task}"
        done = base / "done" / tag
        if done.exists():
            continue
        jobs = ROOT / "jobs" / f"livedin-{harness}" / tag
        jobs.parent.mkdir(parents=True, exist_ok=True)
        # A finished trial whose container is still there (the loop was restarted after Harbor exited)
        # is picked up rather than rerun.
        results = sorted(jobs.glob("*/*/result.json"), reverse=True)
        if not (results and sh(f"docker inspect {container(json.loads(results[0].read_text()))[1]}").returncode == 0):
            print(f"[{time.strftime('%H:%M:%S')}] {tag}: running", flush=True)
            extra = f"--ak version=v0.23.1" if harness == "hermes" else ""
            sh(f"harbor run -d terminal-bench@2.0 -a {AGENTS[harness]} -m {MODEL} {extra} -i {task} -n 1 "
               f"--ek keep_containers=true -o {jobs} > {jobs}.log 2>&1", env=env)
        else:
            print(f"[{time.strftime('%H:%M:%S')}] {tag}: resuming finished trial", flush=True)

        # Newest job first: a cancelled run that finished writing after being moved aside can leave an older one.
        results = sorted(jobs.glob("*/*/result.json"), reverse=True)
        if not results:
            print(f"  no result for {tag}; see {jobs}.log", flush=True)
            continue
        result = json.loads(results[0].read_text())
        reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        project, ctr = container(result)
        exc = (result.get("exception_info") or {}).get("exception_type")
        # The agent finished and the tests ran past their limit: scored as a fail, as in the Fresh track.
        # Harbor reports only the first exception, so an agent timeout followed by a grading timeout is
        # labelled AgentTimeoutError; the grading timeout is only in trial.log.
        trial_log = results[0].parent / "trial.log"
        verifier_timeout = reward is None and (exc == "VerifierTimeoutError" or (
            trial_log.exists() and "VerifierTimeoutError" in trial_log.read_text()))
        if verifier_timeout:
            reward = 0.0
        if reward is None:
            # The verifier never ran: an infrastructure failure, not a score. Stop rather than move
            # on, so no later task's learning lands before this task in the fixed order.
            # The container is kept so the trial can still be inspected or recovered.
            raise SystemExit(f"  {tag}: no verifier result ({exc}); stopping. Container {ctr} kept. "
                             f"Move {jobs} aside, remove the container and its network, and rerun.")

        sh(f"docker start {ctr}")
        workdir = sh(f"docker inspect -f '{{{{.Config.WorkingDir}}}}' {ctr}").stdout.strip() or "/app"
        review = learn(harness, ctr, workdir, key, jobs)
        sh(f"docker cp {ctr}:/tmp/refine-pty.txt {jobs}/learn-pty.txt" if harness == "hermes"
           else "true")
        tmp = state.with_suffix(".tar.tmp")
        r = sh(f"docker exec {ctr} bash -c \"tar -C / -cf - {STATE_PATHS[harness]} 2>/dev/null\" > {tmp}")
        if tmp.stat().st_size > 0:
            tmp.replace(state)
            shutil.copy(state, base / "snapshots" / f"{tag}.tar")
        sh(f"docker rm -f {ctr}; docker network rm {project}__env_default")

        done.parent.mkdir(exist_ok=True)
        done.write_text(json.dumps({"task": task, "reward": reward, "verifier_timeout": verifier_timeout, "review": review,
                                    "state_bytes": state.stat().st_size if state.exists() else 0}) + "\n")
        print(f"  reward={reward} review={review[:160]}", flush=True)


if __name__ == "__main__":
    main()
