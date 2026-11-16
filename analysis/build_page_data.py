"""Derive every figure the published report shows from the datasets, into analysis/data/page_data.json.

usage: python3 -I analysis/build_page_data.py   (after build_dataset.py)
"""
import csv
import json
import re
import statistics
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "analysis" / "data"
FAMILIES = {
    "software-engineering": "Software engineering",
    "system-administration": "Systems and security", "security": "Systems and security",
    "data-science": "Data", "data-processing": "Data", "data-querying": "Data",
    "scientific-computing": "Science and math", "mathematics": "Science and math",
    "model-training": "Machine learning", "machine-learning": "Machine learning",
}
FAMILY_ORDER = ["Software engineering", "Systems and security", "Data", "Science and math", "Machine learning", "Other"]


def meta():
    out = {}
    for p in (ROOT / "tb2").glob("*/*/task.toml"):
        t = p.read_text()
        cat = re.search(r'^category\s*=\s*"([^"]+)"', t, re.M).group(1)
        diff = re.search(r'^difficulty\s*=\s*"([^"]+)"', t, re.M).group(1)
        out[p.parent.name] = {"category": cat, "family": FAMILIES.get(cat, "Other"), "difficulty": diff}
    return out


def hermes_skills():
    snaps = ROOT / "livedin" / "hermes" / "snapshots"
    with tarfile.open(next(snaps.glob("001-*.tar"))) as t:
        bundled = sum(1 for l in t.extractfile("tmp/hermes/skills/.bundled_manifest").read().decode().splitlines() if ":" in l)
    with tarfile.open(next(snaps.glob("089-*.tar"))) as t:
        end = sum(1 for n in t.getnames() if n.startswith("tmp/hermes/skills/") and n.endswith("/SKILL.md"))
    return {"bundled": bundled, "end": end}


def memory_limits():
    out = {}
    for p in (ROOT / "tb2").glob("*/*/task.toml"):
        m = re.search(r'^memory\s*=\s*"([^"]+)"', p.read_text(), re.M)
        if m:
            out[p.parent.name] = m.group(1)
    return out


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def main():
    m = meta()
    rows = list(csv.DictReader((DATA / "trials.csv").open()))
    summary = json.loads((DATA / "summary.json").read_text())
    learn = list(csv.DictReader((DATA / "learning.csv").open()))
    order = (ROOT / "livedin" / "order.txt").read_text().split()
    cell = {}
    for r in rows:
        cell.setdefault(f"{r['track']}/{r['harness']}", {})[r["task"]] = r

    scoreboard = {}
    for key, rs in cell.items():
        v = list(rs.values())
        mins = [float(r["working_secs"]) / 60 for r in v]
        costs = [float(r["cost_usd"]) for r in v]
        toks = [int(r["tokens_in"]) + int(r["tokens_cached"]) + int(r["tokens_out"]) for r in v]
        s = summary["cells"][key]
        scoreboard[key] = {
            "passed": s["passed"], "n": s["n"], "rate": s["rate"], "ci": s["wilson95"],
            "median_cost": round(statistics.median(costs), 4), "cost_per_solved": s["cost_per_solved_usd"],
            "cost_per_solved_incl_learning": s.get("cost_per_solved_incl_learning_usd"),
            "task_cost": s["task_cost_usd"], "learning_cost": s.get("learning_cost_usd"),
            "median_min": round(statistics.median(mins), 2), "p95_min": round(pct(mins, 0.95), 1),
            "median_tokens": int(statistics.median(toks)),
            "median_output_tokens": int(statistics.median(int(r["tokens_out"]) for r in v)),
            "agent_timeouts": s["agent_timeouts"], "verifier_timeouts": s["verifier_timeouts"],
            "crashes": sum(1 for r in v if r["harness_errors"]),
        }

    fam = {}
    for f in FAMILY_ORDER:
        tasks = [t for t in m if m[t]["family"] == f]
        fam[f] = {"n": len(tasks), **{k: sum(int(cell[k][t]["passed"]) for t in tasks) for k in cell}}
    diff = {}
    for d in ("easy", "medium", "hard"):
        tasks = [t for t in m if m[t]["difficulty"] == d]
        diff[d] = {"n": len(tasks), **{k: sum(int(cell[k][t]["passed"]) for t in tasks) for k in cell}}

    curve = {}
    for key in cell:
        acc, pts = 0, []
        for t in order:
            acc += int(cell[key][t]["passed"])
            pts.append(acc)
        curve[key] = pts

    ledger = []
    for t in sorted(m):
        e = {"task": t, "family": m[t]["family"], "category": m[t]["category"], "difficulty": m[t]["difficulty"],
             "order": order.index(t) + 1}
        for key, rs in cell.items():
            r = rs[t]
            e[key] = {"p": int(r["passed"]), "min": round(float(r["working_secs"]) / 60, 1),
                      "cost": round(float(r["cost_usd"]), 3), "to": int(r["agent_timeout"]),
                      "vto": int(r["verifier_timeout"]), "crash": r["harness_errors"]}
        ledger.append(e)

    lr = {h: [l for l in learn if l["harness"] == h] for h in ("hermes", "openbot")}
    out = {
        "scoreboard": scoreboard, "paired": summary["paired"], "families": fam, "difficulty": diff,
        "curve": curve, "ledger": ledger, "sensitivity": {k: {"kept": v["passed_kept"], "first": v["passed_first_graded"]}
                                                           for k, v in summary["sensitivity_first_graded_attempt"].items()},
        "learning": {h: {"outcomes": summary["cells"][f"livedin/{h}"]["learning_outcomes"],
                         "cost": summary["cells"][f"livedin/{h}"]["learning_cost_usd"],
                         "memories_end": next((l["memories_after"] for l in reversed(lr[h]) if l["memories_after"]), ""),
                         "state_mb_end": round(int(lr[h][-1]["state_bytes"]) / 1e6, 1)} for h in lr},
        "discarded": {"count": sum(summary["discarded_attempts"].values()), "cost": summary["discarded_cost_usd"]},
        "pricing": summary["pricing_usd_per_mtok"],
        "hermes_skills": hermes_skills(), "memory_limits": memory_limits(),
    }
    (DATA / "page_data.json").write_text(json.dumps(out, separators=(",", ":")))
    print(json.dumps({k: out[k] for k in ("scoreboard", "families", "difficulty", "sensitivity", "learning")}, indent=1))


if __name__ == "__main__":
    main()
