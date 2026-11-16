"""Snapshot the kernel's out-of-memory kills during the benchmark into analysis/data/oom_kills.csv.

usage: python3 -I analysis/extract_oom.py

Run while /var/log/kern.log* and syslog* still cover the runs (they rotate). Each kill's container is matched to
its trial by the container's first start time (systemd "Started docker-<id>.scope") against the trial's
environment setup start. The kernel's process table at each kill gives the harness's own memory use
and the kill priority (oom_score_adj) of every process.
"""
import csv
import gzip
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = Path("/var/log")
SINCE = "2026-11-12"
HARNESS_PROCS = {"hermes", "openbot", "pi", "Xvfb", "bun", "chrome_crashpad"}


def lines(pattern):
    for p in sorted(LOGS.glob(pattern), reverse=True):
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt", errors="replace") as f:
            for line in f:
                if line[:10] >= SINCE:
                    yield line


def main():
    kills, table, cur = [], [], None
    for line in lines("kern.log*"):
        msg = line.split(" kernel: ", 1)[-1]
        if "invoked oom-killer" in msg:
            table = []
        elif re.match(r"\[\s*\d+\]", msg):
            f = msg.split()
            table.append({"name": f[-1], "rss_mb": int(f[-8]) * 4 / 1024, "adj": int(f[-2])})
        elif msg.startswith("oom-kill:"):
            cur = re.search(r"cpuset=docker-([0-9a-f]{12})", msg)
        elif "Killed process" in msg and cur:
            m = re.search(r"Killed process \d+ \(([^)]*)\).*anon-rss:(\d+)kB.*oom_score_adj:(-?\d+)", msg)
            harness_mb = sum(p["rss_mb"] for p in table if p["name"] in HARNESS_PROCS or p["name"].startswith("hermes"))
            largest = max(table, key=lambda p: p["rss_mb"]) if table else {}
            kills.append({"time": line.split()[0][:19], "container": cur.group(1), "victim": m.group(1),
                          "victim_rss_mb": round(int(m.group(2)) / 1024), "victim_oom_score_adj": int(m.group(3)),
                          "harness_rss_mb": round(harness_mb), "container_rss_mb": round(sum(p["rss_mb"] for p in table)),
                          "largest_process": largest.get("name", ""), "largest_rss_mb": round(largest.get("rss_mb", 0))})
            cur = None

    ids = {k["container"] for k in kills}
    starts = {}
    for line in lines("syslog*"):
        if "Started docker-" in line:
            m = re.search(r"Started docker-([0-9a-f]{12})", line)
            if m and m.group(1) in ids:
                starts.setdefault(m.group(1), datetime.fromisoformat(line.split()[0]))

    trials = []
    for r in list((ROOT / "jobs").rglob("result.json")) + list((ROOT / "invalid").rglob("result.json")):
        d = json.loads(r.read_text())
        if "task_name" not in d:
            continue
        es = (d.get("environment_setup") or {}).get("started_at") or d["started_at"]
        trials.append((datetime.fromisoformat(es.replace("Z", "+00:00")), d, r.parent))
    for k in kills:
        t = starts.get(k["container"])
        best = min(trials, key=lambda x: abs((x[0] - t).total_seconds())) if t else None
        off = abs((best[0] - t).total_seconds()) if best else None
        if best and off <= 30:
            d = best[1]
            k.update({"match_offset_s": round(off), "harness": "hermes" if "Hermes" in d["config"]["agent"]["name"] else "openbot",
                      "task": d["task_name"], "trial_path": str(best[2].relative_to(ROOT)),
                      "kept": int(str(best[2]).startswith(str(ROOT / "jobs" / "fresh-")) or str(best[2]).startswith(str(ROOT / "jobs" / "livedin-")))})
        else:
            k.update({"match_offset_s": off, "harness": "", "task": "", "trial_path": "", "kept": 0})
        k["victim_is_harness"] = int(k["victim"] in HARNESS_PROCS or k["victim"].startswith("hermes"))

    out = ROOT / "analysis" / "data" / "oom_kills.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(kills[0]))
        w.writeheader()
        w.writerows(kills)
    print(f"{len(kills)} kills, {sum(1 for k in kills if k['trial_path'])} matched to trials -> {out}")


if __name__ == "__main__":
    main()
