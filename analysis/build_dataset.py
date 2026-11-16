"""Build the report datasets and the integrity check from the raw Harbor job directories.

usage: python3 -I analysis/build_dataset.py

Writes analysis/data/{trials.csv, discarded_attempts.csv, learning.csv, wifi_drops.txt, summary.json}
and analysis/integrity.md. Read-only on jobs/, livedin/ and invalid/.
"""
import csv
import json
import math
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import compare  # noqa: E402

OUT = ROOT / "analysis"
DATA = OUT / "data"
MODEL = "openrouter/deepseek/deepseek-v4.1-flash-1017"
MODEL_ID = "deepseek/deepseek-v4.1-flash-1017"
AGENT = {"hermes": "bench_agents:HermesHigh", "openbot": "bench_agents:OpenBotTB"}
HARNESSES = ("hermes", "openbot")
TRACKS = ("fresh", "livedin")
P_IN, P_OUT, P_CACHED = compare.PRICE_IN, compare.PRICE_OUT, compare.PRICE_CACHED


def ts(s):
    return compare.ts(s) if s else None


def read(p):
    return p.read_text(errors="replace") if p.exists() else ""


def cost(i, c, o):
    return i * P_IN + c * P_CACHED + o * P_OUT


def openbot_usage(agent_dir, since, until):
    db = agent_dir / "openbot.db"
    if not db.exists() or not since:
        return None, set()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tot = {"input": 0, "cached": 0, "output": 0}
    models = set()
    for occurred, model, tokens in c.execute("select occurred_at, model, tokens_json from agent_usage_records"):
        t0 = ts(occurred)
        if t0 < since or (until and t0 >= until):
            continue
        t = json.loads(tokens)
        tot["input"] += t.get("uncachedInput", 0) + t.get("cacheCreation", 0)
        tot["cached"] += t.get("cachedInput", 0)
        tot["output"] += t.get("output", 0)
        models.add(model)
    return tot, models


def openbot_efforts(agent_dir):
    db = agent_dir / "openbot.db"
    if not db.exists():
        return set()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    return {(m, e) for m, e in c.execute("select model, effort from projection_provider_sessions")}


def hermes_models(agent_dir, since):
    db = agent_dir / "state.db"
    if not db.exists() or not since:
        return set()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    return {m for (m,) in c.execute("select model from sessions where started_at >= ?", (since.timestamp() - 5,))}


def trial(result, harness, track, tag=None):
    d = json.loads(result.read_text())
    tdir = result.parent
    agent_dir = tdir / "agent"
    ex = d.get("agent_execution") or {}
    start, end = ts(ex.get("started_at")), ts(ex.get("finished_at"))
    reward = ((d.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    exc = (d.get("exception_info") or {}).get("exception_type")
    trial_log = read(tdir / "trial.log")
    verifier_timeout = reward is None and (exc == "VerifierTimeoutError" or "VerifierTimeoutError" in trial_log)
    agent_timeout = exc == "AgentTimeoutError"
    cfg = d.get("config") or {}
    agent_cfg = cfg.get("agent") or {}
    row = {
        "track": track, "harness": harness, "task": d["task_name"], "order": int(tag[:3]) if tag else "",
        "trial": d["trial_name"], "path": str(tdir.relative_to(ROOT)),
        "reward_raw": reward, "passed": int((reward or 0) >= 1.0), "exception": exc or "",
        "agent_timeout": int(agent_timeout), "verifier_timeout": int(verifier_timeout),
        "graded": int(reward is not None or verifier_timeout),
        "trial_started": d.get("started_at"), "trial_finished": d.get("finished_at"),
        "agent_started": ex.get("started_at"), "agent_finished": ex.get("finished_at"),
        "agent_wall_secs": round((end - start).total_seconds(), 1) if start and end else "",
        "agent_name": agent_cfg.get("name"), "model_name": agent_cfg.get("model_name"),
        "agent_version": (agent_cfg.get("kwargs") or {}).get("version", ""),
        "timeout_multiplier": cfg.get("timeout_multiplier"),
        "task_commit": ((d.get("task_id") or {}).get("git_commit_id")), "task_checksum": d.get("task_checksum"),
    }
    if harness == "hermes":
        usage = compare.hermes_usage(agent_dir, start)
        models = hermes_models(agent_dir, start)
        row["effort"] = "high" if re.search(r"reasoning_effort:\s*high", trial_log) else ""
        row["working_secs"] = round(usage["secs"], 1) if usage and usage.get("secs") else row["agent_wall_secs"]
        row["harness_errors"] = "gateway_disconnected" if "Gateway disconnected" in read(agent_dir / "hermes.txt") else ""
        row["provider_incidents"] = 0
    else:
        learn = read(agent_dir / "learn.txt")
        m = re.match(r"(\S+Z) archived", learn)
        usage, models = openbot_usage(agent_dir, start, ts(m.group(1)) if m else None)
        efforts = openbot_efforts(agent_dir)
        row["effort"] = "/".join(sorted({e for _, e in efforts if e})) if efforts else ""
        models |= {mm for mm, _ in efforts}
        ws = compare.openbot_working_secs(agent_dir)
        row["working_secs"] = round(ws, 1) if ws else row["agent_wall_secs"]
        driver = read(agent_dir / "driver.txt")
        errs = []
        if "Target crashed" in read(agent_dir / "openbot-app.log") + driver:
            errs.append("renderer_crashed")
        if re.search(r"never appeared|never became available|timed out waiting for OpenBot UI", driver):
            errs.append("app_restart_failed")
        row["harness_errors"] = "+".join(errs)
        row["provider_incidents"] = driver.count("INCIDENT")
    row["models_seen"] = "|".join(sorted(m for m in models if m))
    u = usage or {}
    row["tokens_in"], row["tokens_cached"], row["tokens_out"] = u.get("input", 0), u.get("cached", 0), u.get("output", 0)
    row["usage_found"] = int(bool(usage))
    row["cost_usd"] = round(cost(row["tokens_in"], row["tokens_cached"], row["tokens_out"]), 6)
    return row


def kept_trials():
    rows = []
    for h in HARNESSES:
        for r in sorted((ROOT / "jobs" / f"fresh-{h}").glob("*/*/result.json")):
            rows.append(trial(r, h, "fresh"))
        for tagdir in sorted(p for p in (ROOT / "jobs" / f"livedin-{h}").iterdir() if p.is_dir()):
            results = sorted(tagdir.glob("*/*/result.json"), reverse=True)
            for i, r in enumerate(results):
                row = trial(r, h, "livedin", tagdir.name)
                row["superseded_in_dir"] = int(i > 0)
                rows.append(row)
    return rows


def discarded_attempts():
    rows = []
    for r in sorted((ROOT / "invalid").rglob("result.json")):
        d = json.loads(r.read_text())
        if "task_name" not in d:
            continue
        name = ((d.get("config") or {}).get("agent") or {}).get("name", "")
        h = "hermes" if "Hermes" in name else "openbot"
        reason = r.relative_to(ROOT / "invalid").parts[0]
        track = "fresh" if reason.startswith("fresh") else "livedin"
        tag = next((p for p in r.parts if re.match(r"\d{3}-", p)), None)
        row = trial(r, h, track, tag)
        row["archive"] = reason
        rows.append(row)
    return rows


def parse_review(s):
    g = lambda k: int(m.group(1)) if (m := re.search(rf"\b{k}=(\d+)", s)) else 0
    if s.startswith("Background review complete"):
        outcome = "review:" + (re.search(r"result=(\S+)", s).group(1) if "result=" in s else "?")
    elif s.startswith("Memory review complete"):
        outcome = "review:memories"
    elif s.startswith("No memory review"):
        outcome = "skipped_by_harness"
    else:
        outcome = "failed"
    mem = re.search(r"memories=(\d+)->(\d+)", s)
    return {"outcome": outcome, "calls": g("calls"), "in": g("in"), "out": g("out"), "cached": g("cache_read"),
            "mem_before": mem.group(1) if mem else "", "mem_after": mem.group(2) if mem else ""}


def learning_rows():
    rows = []
    for h in HARNESSES:
        for f in sorted((ROOT / "livedin" / h / "done").iterdir()):
            d = json.loads(f.read_text())
            p = parse_review(d["review"])
            rows.append({"harness": h, "order": int(f.name[:3]), "task": d["task"], "reward": d["reward"],
                         "verifier_timeout": int(bool(d.get("verifier_timeout"))), "state_bytes": d["state_bytes"],
                         "review_outcome": p["outcome"], "review_calls": p["calls"], "review_in": p["in"],
                         "review_cached": p["cached"], "review_out": p["out"],
                         "review_cost_usd": round(cost(p["in"], p["cached"], p["out"]), 6),
                         "memories_before": p["mem_before"], "memories_after": p["mem_after"],
                         "snapshot": int((ROOT / "livedin" / h / "snapshots" / f"{f.name}.tar").exists()),
                         "review_raw": d["review"][:200]})
    return rows


def wifi_drops():
    # The system journal rotates, so the drops are kept in a fixed record (see its header for sources).
    src = (OUT / "wifi_drops_observed.txt").read_text()
    (DATA / "wifi_drops.txt").write_text(src)
    return [datetime.fromisoformat(l) for l in src.splitlines() if l and not l.startswith("#")]


def wilson(k, n, z=1.96):
    if not n:
        return (0, 0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(centre - half, 4), round(centre + half, 4))


def mcnemar(b, c):
    n = b + c
    if not n:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return round(min(1.0, 2 * tail), 4)


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    tasks = sorted(p.parent.name for p in (ROOT / "tb2").glob("*/*/instruction.md"))
    order = (ROOT / "livedin" / "order.txt").read_text().split()
    all_rows = kept_trials()
    rows = [r for r in all_rows if not r.get("superseded_in_dir")]
    discarded = discarded_attempts()
    learn = learning_rows()
    drops = wifi_drops()

    oom = list(csv.DictReader((DATA / "oom_kills.csv").open())) if (DATA / "oom_kills.csv").exists() else []
    for r in rows + discarded:
        a, b = ts(r["trial_started"]), ts(r["trial_finished"])
        hit = [d for d in drops if a and b and a <= d <= b]
        r["wifi_drops_during"] = len(hit)
        k = [o for o in oom if o["trial_path"] == r["path"]]
        r["oom_kills"] = len(k)
        r["oom_harness_process_killed"] = int(any(o["victim_is_harness"] == "1" for o in k))
        r["oom_victims"] = "|".join(o["victim"] for o in k)

    checks = []

    def check(name, ok, detail="", known=False):
        checks.append((name, "PASS" if ok else ("KNOWN" if known else "FAIL"), detail))

    cells = {(t, h): [r for r in rows if r["track"] == t and r["harness"] == h] for t in TRACKS for h in HARNESSES}
    for (t, h), rs in cells.items():
        names = [r["task"] for r in rs]
        dup = sorted({n for n in names if names.count(n) > 1})
        check(f"{t}/{h}: one kept trial per TB2 task", len(rs) == 89 and set(names) == set(tasks) and not dup,
              f"{len(rs)} trials, {len(set(names))} tasks, missing {sorted(set(tasks) - set(names))}, dupes {dup}")
    sup = [r["path"] for r in all_rows if r.get("superseded_in_dir")]
    check("no older results left inside kept Lived-in task dirs", not sup, "; ".join(sup))

    bad = [r["path"] for r in rows if r["agent_name"] != AGENT[r["harness"]] or r["model_name"] != MODEL]
    check("Harbor config: right agent and model on every kept trial", not bad, "; ".join(bad[:10]))
    bad = [r["path"] for r in rows if r["harness"] == "hermes" and r["agent_version"] != "v0.23.1"]
    check("Hermes pinned to v0.23.1 on every trial", not bad, "; ".join(bad[:10]))
    bad = [r["path"] for r in rows if r["models_seen"] != MODEL_ID]
    check(f"only {MODEL_ID} was actually called (harness usage records)", not bad,
          "; ".join(f"{p}: {next(r['models_seen'] for r in rows if r['path'] == p)!r}" for p in bad[:15]))
    bad = [r["path"] for r in rows if r["effort"] != "high"]
    check("reasoning effort recorded as high on every trial", not bad,
          "; ".join(f"{p}: {next(r['effort'] for r in rows if r['path'] == p)!r}" for p in bad[:15]))
    bad = [r["path"] for r in rows if r["timeout_multiplier"] != 1.0]
    check("no timeout multipliers (stock TB2 limits)", not bad, "; ".join(bad[:10]))
    commits = {r["task_commit"] for r in rows}
    check("all trials used the same TB2 commit", len(commits) == 1, ", ".join(sorted(map(str, commits))))
    sums = {}
    for r in rows:
        sums.setdefault(r["task"], set()).add(r["task_checksum"])
    bad = [t for t, s in sums.items() if len(s) > 1]
    check("same task checksum across all four cells", not bad, ", ".join(bad))
    bad = [r["path"] for r in rows if not r["usage_found"]]
    check("token usage found for every kept trial", not bad, "; ".join(bad[:15]))

    ungraded = [r for r in rows if not r["graded"]]
    check("every kept trial graded (verifier timeouts count as graded fails)", not ungraded,
          "; ".join(f"{r['track']}/{r['harness']}/{r['task']}: {r['exception']}" for r in ungraded))
    infra = [r for r in rows if (r["exception"] and not r["agent_started"]) or "app_restart_failed" in r["harness_errors"]]
    check("no setup failures or failed OpenBot app restarts among kept trials", not infra,
          "; ".join(f"{r['track']}/{r['harness']}/{r['task']}" for r in infra))
    crashed = [r for r in rows if r["harness_errors"]]
    check("no harness crashed mid-task (crashed trials are kept as graded fails)", not crashed,
          "; ".join(f"{r['track']}/{r['harness']}/{r['task']}: {r['harness_errors']}" for r in crashed), known=True)

    for h in HARNESSES:
        lr = [l for l in learn if l["harness"] == h]
        seq = [l["task"] for l in sorted(lr, key=lambda l: l["order"])]
        check(f"livedin/{h}: tasks done in the fixed order", seq == order and [l["order"] for l in sorted(lr, key=lambda l: l["order"])] == list(range(1, 90)))
        check(f"livedin/{h}: a profile snapshot after every task", all(l["snapshot"] for l in lr),
              ", ".join(str(l["order"]) for l in lr if not l["snapshot"]))
        kept = {r["task"]: r for r in cells[("livedin", h)]}
        mism = [l["task"] for l in lr if (1.0 if kept[l["task"]]["passed"] else 0.0) != (l["reward"] or 0.0)]
        check(f"livedin/{h}: loop's recorded reward matches the kept trial", not mism, ", ".join(mism))
        failed = [f"{l['order']} {l['task']}: {l['review_raw']}" for l in lr if l["review_outcome"] == "failed"]
        crashed_tasks = {r["task"] for r in cells[("livedin", h)] if r["harness_errors"]}
        check(f"livedin/{h}: no failed learning passes", not failed, "; ".join(failed),
              known=all(l["task"] in crashed_tasks for l in lr if l["review_outcome"] == "failed"))

    leak = subprocess.run("docker ps -a --format '{{.Names}}' | grep -c __env-main; docker network ls --format '{{.Name}}' "
                          "| grep -c __env_default; pgrep -fc '^python3 -I livedin[.]py|[h]arbor run'", shell=True,
                          capture_output=True, text=True).stdout.split()
    check("no leftover task containers, networks or runs", leak == ["0", "0", "0"], " ".join(leak))

    write_csv(DATA / "trials.csv", rows)
    write_csv(DATA / "discarded_attempts.csv", discarded)
    write_csv(DATA / "learning.csv", learn)

    summary = {"pricing_usd_per_mtok": {"input": P_IN * 1e6, "cached": P_CACHED * 1e6, "output": P_OUT * 1e6},
               "cells": {}, "paired": {}, "sensitivity_first_graded_attempt": {}}
    for (t, h), rs in cells.items():
        k, n = sum(r["passed"] for r in rs), len(rs)
        c = sum(r["cost_usd"] for r in rs)
        mins = sorted((r["working_secs"] or 0) / 60 for r in rs)
        cell = {"passed": k, "n": n, "rate": round(k / n, 4), "wilson95": wilson(k, n), "task_cost_usd": round(c, 4),
                "cost_per_solved_usd": round(c / k, 4) if k else None,
                "median_working_min": round(mins[n // 2], 2), "total_working_min": round(sum(mins), 1),
                "agent_timeouts": sum(r["agent_timeout"] for r in rs),
                "verifier_timeouts": sum(r["verifier_timeout"] for r in rs),
                "exceptions": {e: sum(1 for r in rs if r["exception"] == e) for e in sorted({r["exception"] for r in rs} - {""})},
                "harness_errors": {e: sum(1 for r in rs if e in r["harness_errors"]) for e in ("renderer_crashed", "gateway_disconnected")},
                "provider_incidents": sum(r["provider_incidents"] for r in rs),
                "trials_with_wifi_drop": sum(1 for r in rs if r["wifi_drops_during"]),
                "trials_with_oom_kill": sum(1 for r in rs if r["oom_kills"]),
                "trials_harness_process_oom_killed": sum(r["oom_harness_process_killed"] for r in rs)}
        if t == "livedin":
            lr = [l for l in learn if l["harness"] == h]
            lc = sum(l["review_cost_usd"] for l in lr)
            cell["learning_cost_usd"] = round(lc, 4)
            cell["cost_per_solved_incl_learning_usd"] = round((c + lc) / k, 4) if k else None
            cell["learning_outcomes"] = {o: sum(1 for l in lr if l["review_outcome"] == o) for o in sorted({l["review_outcome"] for l in lr})}
        summary["cells"][f"{t}/{h}"] = cell

    def paired(a, b):
        A = {r["task"]: r["passed"] for r in a}
        B = {r["task"]: r["passed"] for r in b}
        both = sum(1 for t in A if A[t] and B[t])
        only_a = sum(1 for t in A if A[t] and not B[t])
        only_b = sum(1 for t in A if B[t] and not A[t])
        return {"both": both, "only_first": only_a, "only_second": only_b, "neither": 89 - both - only_a - only_b,
                "mcnemar_exact_p": mcnemar(only_a, only_b)}

    for t in TRACKS:
        summary["paired"][f"{t}: hermes vs openbot"] = paired(cells[(t, "hermes")], cells[(t, "openbot")])
    for h in HARNESSES:
        summary["paired"][f"{h}: livedin vs fresh"] = paired(cells[("livedin", h)], cells[("fresh", h)])

    for (t, h), rs in cells.items():
        alt = {r["task"]: r for r in rs}
        changed = []
        for d in sorted((d for d in discarded if d["track"] == t and d["harness"] == h and d["graded"]),
                        key=lambda d: d["trial_started"], reverse=True):
            if ts(d["trial_started"]) < ts(alt[d["task"]]["trial_started"]):
                alt[d["task"]] = d
        for task, r in alt.items():
            kept = next(x for x in rs if x["task"] == task)
            if r is not kept and r["passed"] != kept["passed"]:
                changed.append({"task": task, "kept": kept["passed"], "first_graded": r["passed"], "archive": r["archive"]})
        summary["sensitivity_first_graded_attempt"][f"{t}/{h}"] = {
            "passed_kept": sum(r["passed"] for r in rs), "passed_first_graded": sum(r["passed"] for r in alt.values()),
            "tasks_that_differ": changed}
    summary["discarded_attempts"] = {a: sum(1 for d in discarded if d["archive"] == a) for a in sorted({d["archive"] for d in discarded})}
    summary["discarded_cost_usd"] = round(sum(d["cost_usd"] for d in discarded), 4)
    summary["wifi_drops"] = len(drops)
    (DATA / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")

    leaked = subprocess.run(["grep", "-rlE", "sk-or-v1-[0-9a-f]{20}", str(DATA)], capture_output=True, text=True).stdout.strip()
    check("no API key in the report datasets", not leaked, leaked)

    lines = [f"# Integrity check ({datetime.now().strftime('%Y-%m-%d %H:%M')})", "",
             f"{sum(s == 'PASS' for _, s, _ in checks)} passed, {sum(s == 'KNOWN' for _, s, _ in checks)} known and disclosed, "
             f"{sum(s == 'FAIL' for _, s, _ in checks)} failed (of {len(checks)}).", ""]
    for name, status, detail in checks:
        lines.append(f"- {status}: {name}" + (f" ({detail})" if detail and status != "PASS" else ""))
    (OUT / "integrity.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
