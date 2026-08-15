"""Extract the measured baseline from the p2p-process-mining outputs.

Everything this writes is measured from the event log. Nothing here is
assumed, estimated or benchmarked from outside the data — assumptions live
in `assumptions.yaml` and are kept structurally separate so the business
case can never blur the line between what was observed and what was
supposed.

The result is committed as `baseline.json`, so this repo reproduces its own
numbers without needing the 695 MB log present.

Usage:
    python src/baseline.py [--p2p-output ../p2p-process-mining/output]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import duckdb

# A segment needs enough completed cases for its rate to mean anything.
# Below this the STP rate is reported but flagged unusable for sizing.
MIN_COMPLETE_CASES = 500

# A segment must carry at least this share of completed cases before its rate
# is allowed to set the target. Without it the benchmark lands on whichever
# tiny segment happens to score highest — Marketing scores 78.2% on 0.7% of
# volume, which says nothing about whether Packaging could reach it.
BENCHMARK_MIN_VOLUME_SHARE = 0.05


def _weighted_quantile(pairs: list[tuple[float, int]], q: float) -> float:
    """Case-weighted quantile of segment rates.

    `pairs` is (rate, weight). Weighting by case count is what makes this a
    statement about the population rather than about the segment list.
    """
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    target = q * total
    seen = 0
    for rate, weight in ordered:
        seen += weight
        if seen >= target:
            return rate
    return ordered[-1][0]


def _git_rev(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def build(p2p_output: Path) -> dict:
    touchless = p2p_output / "touchless_cases.parquet"
    rework = p2p_output / "rework_cases.parquet"
    drivers = p2p_output / "rework_penalty_by_activity.parquet"
    for path in (touchless, rework, drivers):
        if not path.exists():
            raise SystemExit(f"missing {path} — run the p2p analysis scripts first")

    con = duckdb.connect()
    con.execute(f"CREATE VIEW tc AS SELECT * FROM '{touchless}'")
    con.execute(f"CREATE VIEW rc AS SELECT * FROM '{rework}'")
    con.execute(f"CREATE VIEW rd AS SELECT * FROM '{drivers}'")

    # Cases joined to their duration, excluding the 1948-2020 timestamp
    # corruption flagged during the process mining.
    con.execute("""
        CREATE VIEW cases AS
        SELECT tc.*, rc.duration, rc.has_bad_ts,
               (tc.is_complete AND NOT tc.has_rework) AS is_touchless,
               epoch(rc.duration) / 86400.0 AS duration_days
        FROM tc JOIN rc USING (case_id)
    """)

    one = lambda sql: con.execute(sql).fetchone()
    rows = lambda sql: con.execute(sql).fetchall()

    total, complete, touchless_n, bad_ts = one("""
        SELECT count(*), sum(is_complete::INT), sum(is_touchless::INT), sum(has_bad_ts::INT)
        FROM cases
    """)

    cycle = {
        bool(r[0]): {"cases": r[1], "median_days": round(r[2], 2)}
        for r in rows("""
            SELECT has_rework, count(*), median(duration_days)
            FROM cases WHERE is_complete AND NOT has_bad_ts
            GROUP BY 1
        """)
    }
    penalty = round(cycle[True]["median_days"] - cycle[False]["median_days"], 2)

    segments = []
    for area, n, comp, tl, med_tl, med_rw in rows("""
        SELECT coalesce(nullif(spend_area, ''), '(unclassified)') AS area,
               count(*),
               sum(is_complete::INT),
               sum(is_touchless::INT),
               median(CASE WHEN is_complete AND NOT has_rework AND NOT has_bad_ts
                           THEN duration_days END),
               median(CASE WHEN is_complete AND has_rework AND NOT has_bad_ts
                           THEN duration_days END)
        FROM cases GROUP BY 1 ORDER BY count(*) DESC
    """):
        usable = comp >= MIN_COMPLETE_CASES
        segments.append({
            "spend_area": area,
            "cases": n,
            "complete_cases": comp,
            "touchless_cases": tl,
            "stp_rate": round(tl / comp, 4) if comp else None,
            "median_days_touchless": round(med_tl, 2) if med_tl is not None else None,
            "median_days_rework": round(med_rw, 2) if med_rw is not None else None,
            "usable_for_sizing": usable,
            "excluded_reason": None if usable
                else f"only {comp} completed cases (< {MIN_COMPLETE_CASES}); rate not reliable",
        })

    usable = [s for s in segments if s["usable_for_sizing"] and s["stp_rate"] is not None]
    usable_complete = sum(s["complete_cases"] for s in usable)

    # Target = case-weighted top quartile across usable segments.
    top_quartile = _weighted_quantile(
        [(s["stp_rate"], s["complete_cases"]) for s in usable], 0.75
    )
    # Reported alongside it: the best segment large enough to be a credible
    # exemplar, so the target has a named reference point and not just a number.
    material = [
        s for s in usable
        if s["complete_cases"] / usable_complete >= BENCHMARK_MIN_VOLUME_SHARE
    ]
    exemplar = max(material, key=lambda s: s["stp_rate"]) if material else None

    match_types = [
        {"item_category": cat, "cases": n, "complete_cases": comp,
         "stp_rate": round(tl / comp, 4) if comp else None}
        for cat, n, comp, tl in rows("""
            SELECT item_category, count(*), sum(is_complete::INT), sum(is_touchless::INT)
            FROM cases GROUP BY 1 ORDER BY count(*) DESC
        """)
    ]

    rework_drivers = [
        {"activity": a, "cases": n, "median_days": round(m, 2), "delta_days": round(d, 2)}
        for a, m, n, d in rows("SELECT activity, median_days, n, delta_days FROM rd ORDER BY n DESC")
    ]

    return {
        "provenance": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_dataset": "BPI Challenge 2019 — SAP purchase-to-pay event log",
            "source_url": "https://data.4tu.nl/articles/dataset/BPI_Challenge_2019/12715853/1",
            "derived_from": "p2p-process-mining",
            "derived_from_rev": _git_rev(p2p_output.parent),
            "scripts": ["touchless.py", "rework.py"],
            "note": "All values below are measured from the event log. "
                    "Assumptions are kept in assumptions.yaml, never here.",
        },
        "overall": {
            "cases": total,
            "complete_cases": complete,
            "touchless_cases": touchless_n,
            "stp_rate": round(touchless_n / complete, 4),
            "completion_rate": round(complete / total, 4),
            "cases_with_corrupt_timestamps": bad_ts,
            "median_days_touchless": cycle[False]["median_days"],
            "median_days_rework": cycle[True]["median_days"],
            "rework_penalty_days": penalty,
        },
        "internal_benchmark": {
            "top_quartile_stp_rate": round(top_quartile, 4),
            "method": "Case-weighted 75th percentile of STP across segments with at "
                      f"least {MIN_COMPLETE_CASES} completed cases.",
            "exemplar_segment": exemplar["spend_area"] if exemplar else None,
            "exemplar_stp_rate": exemplar["stp_rate"] if exemplar else None,
            "exemplar_complete_cases": exemplar["complete_cases"] if exemplar else None,
            "exemplar_rule": f"Best segment carrying at least "
                             f"{BENCHMARK_MIN_VOLUME_SHARE:.0%} of completed cases.",
            "rationale": "The target is demonstrated inside the same organisation, on "
                         "the same system and process, rather than taken from an "
                         "external benchmark or assumed in a workshop. Weighting by "
                         "case count stops a small segment setting the target: "
                         "Marketing reaches 78.2% on 0.7% of volume, which is not "
                         "evidence that Packaging could.",
        },
        "segments": segments,
        "match_types": match_types,
        "rework_drivers": rework_drivers,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p2p-output", type=Path, default=Path("../p2p-process-mining/output"))
    ap.add_argument("--out", type=Path, default=Path("baseline.json"))
    args = ap.parse_args()

    baseline = build(args.p2p_output.resolve())
    args.out.write_text(json.dumps(baseline, indent=2) + "\n")

    o = baseline["overall"]
    b = baseline["internal_benchmark"]
    print(f"wrote {args.out}")
    print(f"  {o['cases']:,} cases · {o['complete_cases']:,} complete · STP {o['stp_rate']:.1%}")
    print(f"  rework penalty: {o['rework_penalty_days']} days "
          f"({o['median_days_rework']} vs {o['median_days_touchless']})")
    print(f"  target (weighted top quartile): {b['top_quartile_stp_rate']:.1%}")
    if b["exemplar_segment"]:
        print(f"  exemplar: {b['exemplar_segment']} at {b['exemplar_stp_rate']:.1%} "
              f"on {b['exemplar_complete_cases']:,} completed cases")
    usable = sum(s["usable_for_sizing"] for s in baseline["segments"])
    print(f"  segments: {usable} usable of {len(baseline['segments'])}")
    for s in baseline["segments"]:
        if not s["usable_for_sizing"]:
            print(f"    excluded — {s['spend_area']}: {s['excluded_reason']}")


if __name__ == "__main__":
    main()
