"""Compare Harbor job directories for the Hermes and OpenBot harnesses.

usage: python3 -I compare.py <hermes-job-root> <openbot-job-root>

Cost is recomputed from raw token counts at one flat OpenRouter rate for
deepseek-v4.1-flash-1017, because each harness self-reports cost from its own price table
and OpenRouter's price varies by time of day.
"""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PRICE_IN, PRICE_OUT, PRICE_CACHED = 0.15e-6, 0.60e-6, 0.003e-6


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def hermes_db_usage(db, since):
    """Every session the trial started, subagents included (the session export leaves them out,
    while OpenBot's usage table counts everything). Also the only record of a timed-out run."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(
        "select source, started_at, coalesce(ended_at, last_activity_at), input_tokens, "
        "cache_read_tokens, cache_write_tokens, output_tokens from sessions where started_at >= ?",
        (since.timestamp() - 5,),
    ).fetchall()
    if not rows:
        return None
    main = [r for r in rows if r[0] in ("oneshot", "cli")] or rows
    return {
        "input": sum((r[3] or 0) + (r[5] or 0) for r in rows),
        "cached": sum(r[4] or 0 for r in rows),
        "output": sum(r[6] or 0 for r in rows),
        "secs": (main[0][2] - main[0][1]) if main[0][2] else None,
    }


def hermes_usage(agent_dir, since=None):
    if since and (agent_dir / "state.db").exists():
        return hermes_db_usage(agent_dir / "state.db", since)
    f = agent_dir / "hermes-session.jsonl"
    if not f.exists() or not f.read_text().strip():
        return None
    r = json.loads(f.read_text().splitlines()[0])
    return {
        "input": r.get("input_tokens") or 0,
        "cached": r.get("cache_read_tokens") or 0,
        "output": r.get("output_tokens") or 0,
        "secs": (r["ended_at"] - r["started_at"]) if r.get("ended_at") and r.get("started_at") else None,
    }


def openbot_usage(agent_dir, since):
    db = agent_dir / "openbot.db"
    if not db.exists():
        return None
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tot = {"input": 0, "cached": 0, "output": 0}
    for occurred, tokens in c.execute("select occurred_at, tokens_json from agent_usage_records"):
        if ts(occurred) < since:
            continue
        t = json.loads(tokens)
        tot["input"] += t.get("uncachedInput", 0) + t.get("cacheCreation", 0)
        tot["cached"] += t.get("cachedInput", 0)
        tot["output"] += t.get("output", 0)
    return tot


def openbot_working_secs(agent_dir):
    """Instruction sent -> agent finished, minus the driver's 15 s idle confirmation. Excludes app startup."""
    f = agent_dir / "driver.txt"
    if not f.exists():
        return None
    stamps = {}
    for line in f.read_text().splitlines():
        for key in ("instruction sent", "agent finished"):
            if key in line:
                stamps[key] = ts(line.split(" ", 1)[0])
    if len(stamps) < 2:
        return None
    return max((stamps["agent finished"] - stamps["instruction sent"]).total_seconds() - 15, 0)


def trials(root, harness):
    for result in sorted(Path(root).glob("*/*/result.json")):
        d = json.loads(result.read_text())
        ex = d.get("agent_execution") or {}
        start = ts(ex["started_at"]) if ex.get("started_at") else None
        secs = (ts(ex["finished_at"]) - start).total_seconds() if ex.get("finished_at") and start else None
        agent_dir = result.parent / "agent"
        usage = hermes_usage(agent_dir, start) if harness == "hermes" else (openbot_usage(agent_dir, start) if start else None)
        if harness == "openbot":
            secs = openbot_working_secs(agent_dir) or secs
        elif usage and usage.get("secs"):
            secs = usage["secs"]
        reward = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        exc = (d.get("exception_info") or {}).get("exception_type")
        cost = None
        if usage:
            cost = usage["input"] * PRICE_IN + usage["cached"] * PRICE_CACHED + usage["output"] * PRICE_OUT
        yield {"task": d["task_name"], "reward": reward or 0.0, "exc": exc, "secs": secs, "usage": usage, "cost": cost}


def main():
    rows = {h: {t["task"]: t for t in trials(root, h)} for h, root in (("hermes", sys.argv[1]), ("openbot", sys.argv[2]))}
    tasks = sorted(set(rows["hermes"]) | set(rows["openbot"]))
    print(f"{'task':40s} | {'hermes':>6s} {'min':>5s} {'cost$':>7s} | {'openbot':>7s} {'min':>5s} {'cost$':>7s}")
    for task in tasks:
        line = f"{task[:40]:40s}"
        for h in ("hermes", "openbot"):
            t = rows[h].get(task)
            if not t:
                line += " |   (missing)           "
                continue
            mark = f"{t['reward']:.0f}" + ("!" if t["exc"] else "")
            mins = f"{t['secs'] / 60:.1f}" if t["secs"] else "-"
            cost = f"{t['cost']:.4f}" if t["cost"] is not None else "-"
            line += f" | {mark:>6s} {mins:>5s} {cost:>7s}"
        print(line)
    print("\n('!' = harness exception during the trial; scored as the verifier left it)\n")
    for h in ("hermes", "openbot"):
        ts_ = list(rows[h].values())
        n = len(ts_)
        if not n:
            continue
        passed = sum(t["reward"] for t in ts_)
        exc = sum(1 for t in ts_ if t["exc"])
        cost = sum(t["cost"] or 0 for t in ts_)
        mins = sum(t["secs"] or 0 for t in ts_) / 60
        tok = {k: sum((t["usage"] or {}).get(k) or 0 for t in ts_) for k in ("input", "cached", "output")}
        print(f"{h:8s} pass {passed:.0f}/{n} ({100 * passed / n:.0f}%)  exceptions {exc}  agent-time {mins:.1f} min  "
              f"cost ${cost:.3f}  tokens in {tok['input']:,} cached {tok['cached']:,} out {tok['output']:,}")


if __name__ == "__main__":
    main()
