"""Fill report/template.html from the analysis data into index.html.

usage: python3 -I report/build_report.py   (after analysis/build_dataset.py and analysis/build_page_data.py)
Every figure in the page's text and tables comes from here; the charts read the embedded page data.
"""
import base64
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "analysis" / "data"


def money(v, d=3):
    return f"${v:.{d}f}"


def main():
    pd = json.loads((DATA / "page_data.json").read_text())
    summary = json.loads((DATA / "summary.json").read_text())
    sb, fam, diff, par = pd["scoreboard"], pd["families"], pd["difficulty"], pd["paired"]
    fh, fo, lh, lo = sb["fresh/hermes"], sb["fresh/openbot"], sb["livedin/hermes"], sb["livedin/openbot"]
    pf, pl = par["fresh: hermes vs openbot"], par["livedin: hermes vs openbot"]
    gain_h, gain_o = lh["passed"] - fh["passed"], lo["passed"] - fo["passed"]
    assert gain_h == gain_o, "prose says both harnesses gained the same number of tasks"
    p_learn = par["hermes: livedin vs fresh"]["mcnemar_exact_p"]
    assert p_learn == par["openbot: livedin vs fresh"]["mcnemar_exact_p"]
    assert fam["Science and math"]["livedin/hermes"] == fam["Science and math"]["livedin/openbot"], "prose says OpenBot draws level"
    assert fh["passed"] > fo["passed"] and lh["passed"] > lo["passed"], "prose says Hermes leads both tracks"
    sens = pd["sensitivity"]
    assert sens["fresh/hermes"]["first"] > sens["fresh/openbot"]["first"] and sens["livedin/hermes"]["first"] > sens["livedin/openbot"]["first"]

    oom = list(csv.DictReader((DATA / "oom_kills.csv").open()))
    cc = next(k for k in oom if k["kept"] == "1" and k["task"] == "compile-compcert" and k["victim_is_harness"] == "1")
    cf = next(k for k in oom if k["kept"] == "1" and k["task"] == "caffe-cifar-10" and k["harness"] == "hermes" and k["victim_is_harness"] == "1")
    led = {e["task"]: e for e in pd["ledger"]}
    lo_out = pd["learning"]["openbot"]["outcomes"]
    learn = list(csv.DictReader((DATA / "learning.csv").open()))
    cells = summary["cells"]
    mem_limit = lambda task: pd["memory_limits"][task].replace("G", " GB")

    v = {
        "n_tasks": fh["n"], "n_trials": sum(s["n"] for s in sb.values()),
        "fh_pct": round(fh["rate"] * 100), "fo_pct": round(fo["rate"] * 100), "lh_pct": round(lh["rate"] * 100), "lo_pct": round(lo["rate"] * 100),
        "fh_n": fh["passed"], "fo_n": fo["passed"], "lh_n": lh["passed"], "lo_n": lo["passed"],
        "fh_ci": f"{round(fh['ci'][0] * 100)}–{round(fh['ci'][1] * 100)}%", "fo_ci": f"{round(fo['ci'][0] * 100)}–{round(fo['ci'][1] * 100)}%",
        "gap_f": round((fh["rate"] - fo["rate"]) * 100), "gap_l": round((lh["rate"] - lo["rate"]) * 100),
        "fh_cps": money(fh["cost_per_solved"]), "fo_cps": money(fo["cost_per_solved"]),
        "lh_cps_l": money(lh["cost_per_solved_incl_learning"]), "lo_cps_l": money(lo["cost_per_solved_incl_learning"]),
        "d_f_cps": money(fh["cost_per_solved"] - fo["cost_per_solved"]),
        "d_l_cps": money(lh["cost_per_solved_incl_learning"] - lo["cost_per_solved_incl_learning"]),
        "fh_mc": money(fh["median_cost"]), "fo_mc": money(fo["median_cost"]), "d_f_mc": money(fh["median_cost"] - fo["median_cost"]),
        "fh_mt": f"{fh['median_min']:.1f}", "fo_mt": f"{fo['median_min']:.1f}", "d_f_mt": f"{fh['median_min'] - fo['median_min']:.1f}",
        "fh_p95": f"{fh['p95_min']:.0f}", "fo_p95": f"{fo['p95_min']:.0f}",
        "fh_tok": f"{fh['median_tokens'] / 1000:,.0f}k", "fo_tok": f"{fo['median_tokens'] / 1000:,.0f}k",
        "tok_ratio": f"{fh['median_tokens'] / fo['median_tokens']:.1f}",
        "fh_to": fh["agent_timeouts"], "fo_to": fo["agent_timeouts"], "lh_to": lh["agent_timeouts"], "lo_to": lo["agent_timeouts"],
        "fh_cr": fh["crashes"], "fo_cr": fo["crashes"], "lh_cr": lh["crashes"], "lo_cr": lo["crashes"],
        "d_f_n": fh["passed"] - fo["passed"], "d_l_n": lh["passed"] - lo["passed"],
        "lh_lc": money(lh["learning_cost"], 2), "lo_lc": money(lo["learning_cost"], 2), "lh_tc": money(lh["task_cost"], 2),
        "f_only_h": pf["only_first"], "f_only_o": pf["only_second"], "f_chance": round(1 / pf["mcnemar_exact_p"]),
        "l_gain": gain_h, "l_chance": round(1 / p_learn),
        "fam_ss_h": fam["Systems and security"]["fresh/hermes"], "fam_ss_o": fam["Systems and security"]["fresh/openbot"], "fam_ss_n": fam["Systems and security"]["n"],
        "fam_sm_h": fam["Science and math"]["fresh/hermes"], "fam_sm_o": fam["Science and math"]["fresh/openbot"], "fam_sm_n": fam["Science and math"]["n"],
        "fam_sm_lo": fam["Science and math"]["livedin/openbot"],
        "d_hard_h": diff["hard"]["fresh/hermes"], "d_hard_o": diff["hard"]["fresh/openbot"], "d_hard_n": diff["hard"]["n"],
        "sk_start": pd["hermes_skills"]["bundled"], "sk_end": pd["hermes_skills"]["end"],
        "h_mem_tasks": sum(1 for l in learn if l["harness"] == "hermes" and "memory" in l["review_outcome"]),
        "o_rev": lo_out.get("review:memories", 0), "o_skip": lo_out.get("skipped_by_harness", 0), "o_mem": pd["learning"]["openbot"]["memories_end"],
        "q_cancel_h_min": f"{led['cancel-async-tasks']['fresh/hermes']['min']:.0f}",
        "q_cc_limit": mem_limit("compile-compcert"), "q_cc_victim": f"{cc['victim_rss_mb']} MB",
        "q_cc_task": f"{(int(cc['container_rss_mb']) - int(cc['harness_rss_mb'])) / 1000:.1f} GB",
        "q_caffe_limit": mem_limit("caffe-cifar-10"), "q_caffe_victim": f"{cf['victim_rss_mb']} MB",
        "oom_o": cells["fresh/openbot"]["trials_harness_process_oom_killed"] + cells["livedin/openbot"]["trials_harness_process_oom_killed"],
        "oom_h": cells["fresh/hermes"]["trials_harness_process_oom_killed"] + cells["livedin/hermes"]["trials_harness_process_oom_killed"],
        "disc_n": pd["discarded"]["count"], "disc_cost": money(pd["discarded"]["cost"], 2),
        "s_fh_k": sens["fresh/hermes"]["kept"], "s_fh_f": sens["fresh/hermes"]["first"], "s_fo_k": sens["fresh/openbot"]["kept"], "s_fo_f": sens["fresh/openbot"]["first"],
        "s_lh_k": sens["livedin/hermes"]["kept"], "s_lh_f": sens["livedin/hermes"]["first"], "s_lo_k": sens["livedin/openbot"]["kept"], "s_lo_f": sens["livedin/openbot"]["first"],
        "p_in": f"{pd['pricing']['input']:.2f}", "p_cached": f"{pd['pricing']['cached']:.3f}", "p_out": f"{pd['pricing']['output']:.2f}",
    }
    for h in ("hermes", "openbot"):
        v[f"icon_{h[0]}"] = "data:image/jpeg;base64," + base64.b64encode((ROOT / "report" / "icons" / f"{h}.jpg").read_bytes()).decode()
    page = (ROOT / "report" / "template.html").read_text()
    missing = sorted(set(re.findall(r"\{\{(\w+)\}\}", page)) - set(v))
    assert not missing, f"unfilled: {missing}"
    page = re.sub(r"\{\{(\w+)\}\}", lambda m: str(v[m.group(1)]), page)
    page = page.replace("/*DATA*/", json.dumps(pd, separators=(",", ":")))
    out = ROOT / "index.html"
    out.write_text(page)
    assert "sk-or-" not in page
    print(f"wrote {out} ({len(page) // 1024} KB)")
    print({k: v[k] for k in ("sk_start", "sk_end", "h_mem_tasks", "q_cc_task", "q_cc_victim", "q_cc_limit", "q_caffe_victim", "q_caffe_limit", "f_chance", "l_chance", "d_f_cps", "d_l_cps")})


if __name__ == "__main__":
    main()
