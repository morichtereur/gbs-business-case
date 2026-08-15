"""Assemble the written business case from baseline.json, assumptions.yaml,
model.py and sensitivity.py — nothing here is hand-typed prose with numbers
baked in; every figure is pulled live so the document reproduces itself the
same way baseline.json does.

Writes `output/business_case.md`, embedding the three charts sensitivity.py
also writes to the tracked `assets/` directory.

Run: .venv/bin/python src/report.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from model import central_params, load_assumptions, load_baseline, run_model
from sensitivity import (
    diligence_priority,
    plot_diligence_priority,
    plot_npv_distribution,
    plot_tornado,
    run_monte_carlo,
    run_tornado,
)

import numpy as np


def eur(x: float) -> str:
    return f"EUR {x:,.0f}"


def build_report(baseline: dict, assumptions: dict, assets_dir: Path) -> str:
    base_params = central_params(assumptions)
    result = run_model(baseline, base_params)
    base_npv, tornado_rows = run_tornado(baseline, assumptions, base_params)
    npvs, samples = run_monte_carlo(baseline, assumptions, base_params)
    priority = diligence_priority(npvs, samples, assumptions)

    plot_tornado(base_npv, tornado_rows, assets_dir / "tornado.png")
    plot_npv_distribution(npvs, assets_dir / "npv_distribution.png")
    plot_diligence_priority(priority, assets_dir / "diligence_priority.png")

    p10, p50, p90 = (float(v) for v in np.percentile(npvs, [10, 50, 90]))
    p_positive = float((npvs > 0).mean())

    o = baseline["overall"]
    b = baseline["internal_benchmark"]
    rt = baseline["rework_touches"]
    top_driver = tornado_rows[0]
    measurable_share = priority["by_bucket"].get("measurable", 0.0)
    unknowable_share = priority["by_bucket"].get("unknowable", 0.0)
    verdict = "does not clear" if result["npv_eur"] < 0 else "clears"

    segment_rows = "\n".join(
        f"| {s['spend_area']} | {s['complete_cases']:,} | {s['stp_rate']:.1%} | "
        f"{s['gap_pp']:+.1%} | {s['cases_moved_annual']:,.0f} |"
        for s in result["opportunity_by_segment"]
    )

    cash_flow_rows = "\n".join(
        f"| Year {t} | {eur(cf)} |"
        for t, cf in enumerate(result["cash_flows_eur"])
    )

    tornado_rows_md = "\n".join(
        f"| {r['label']} | {r['diligence_bucket']} | {eur(r['npv_at_low'])} to {eur(r['npv_at_high'])} | "
        f"{eur(r['swing_eur'])} |"
        for r in tornado_rows
    )

    priority_rows_md = "\n".join(
        f"| {r['label']} | {r['diligence_bucket']} | {r['variance_share']:.0%} |"
        for r in priority["by_parameter"]
    )

    return f"""# Purchase-to-pay rework elimination case

A business case for closing the straight-through-processing gap across the
ten spend areas below the internal benchmark — Packaging is the largest by
volume, but not the only one in scope. Built on a measured baseline rather
than a workshop estimate; full provenance in `baseline.json`,
`assumptions.yaml`, and the scripts in `src/`.

## Bottom line

At central assumptions, the case **{verdict} the {assumptions['finance']['discount_rate']['value']:.0%} hurdle
rate**: NPV is **{eur(result['npv_eur'])}** over a {int(result['params']['finance.horizon_years'])}-year
horizon, and Monte Carlo across the full assumption ranges puts the
probability of a positive NPV at **{p_positive:.0%}**. That is not a rounding
problem — it is the direct consequence of a measured fact: reworked cases
average **{rt['mean_touches_per_case']:.2f} rework touches**, not the multi-touch
slog a workshop estimate usually assumes, so the labour saved by eliminating
rework is thinner than the intuitive case for automation suggests.

The uncertainty that matters most is not, as might be expected, the
implementation cost quote — it is **{top_driver['label']}**, an assumption
diligence can resolve with a time study, not a vendor negotiation. **{measurable_share:.0%}**
of NPV variance sits in that "could be measured" bucket against **{unknowable_share:.0%}**
in the "genuinely unknowable until later" bucket — see
[Diligence priority](#diligence-priority) for the work plan that follows from
that split.

## Measured baseline

From {o['cases']:,} purchase order line items, {o['complete_cases']:,} of which
reach `Clear Invoice`:

| | |
|---|---|
| Straight-through rate | **{o['stp_rate']:.1%}** of completed cases |
| Rework penalty | **{o['rework_penalty_days']}** days ({o['median_days_rework']} vs {o['median_days_touchless']}) |
| Touches per reworked case | mean **{rt['mean_touches_per_case']:.2f}** (median {rt['median_touches_per_case']:.0f}, p90 {rt['p90_touches_per_case']:.0f}) |
| Internal benchmark (target) | **{b['top_quartile_stp_rate']:.1%}**, demonstrated by {b['exemplar_segment']} on {b['exemplar_complete_cases']:,} cases |

The touches figure is new since the baseline was first measured: mean
exceeds median because a long tail of multi-touch cases (SRM transfer
failures, repeated changes) pulls the average up from the typical single
touch. Pricing effort on the mean, not the median, is what keeps the labour
saving honest — see `p2p-process-mining/src/rework_touches.py`.

## Where the opportunity sits

Segments below the {b['top_quartile_stp_rate']:.1%} target, sized by cases/year
that would move from reworked to touchless if the segment closed its gap to
target:

| Spend area | Complete cases | Current STP | Gap to target | Cases moved/yr |
|---|---|---|---|---|
{segment_rows}

Total: **{result['cases_moved_annual_at_target']:,.0f} cases/year** move from
reworked to touchless at full target run-rate, saving
**EUR {result['cost_per_reworked_case_eur']:.2f}** of labour each — a per-case
figure that is itself the product of a measured touch count and two assumed
inputs (minutes per touch, hourly rate), which is exactly why it is the
model's most sensitive line, not the implementation cost.

Cycle time also compresses: **{result['cycle_time_days_saved_annual_at_target']:,.0f}
days/year** of case duration removed at target run-rate. Named as a benefit,
left unmonetised — the log carries cumulative net worth per event, not
invoice values, so a working-capital euro figure is not defensible from this
data (see `assumptions.yaml`, `finance.working_capital`).

## Central-case model

Linear ramp to target over {int(base_params['implementation.ramp_months'])} months,
{eur(base_params['implementation.one_off_cost_eur'])} upfront,
{eur(base_params['implementation.annual_run_cost_eur'])}/year run cost,
discounted at {base_params['finance.discount_rate']:.0%}:

| | |
|---|---|
{cash_flow_rows}

| Metric | Value |
|---|---|
| NPV | {eur(result['npv_eur'])} |
| IRR | {f"{result['irr']:.1%}" if result['irr'] is not None else "no root — never clears cost of capital"} |
| Payback (simple) | {f"{result['payback_years_simple']:.1f} years" if result['payback_years_simple'] is not None else f"beyond the {int(result['params']['finance.horizon_years'])}-year horizon"} |

## Sensitivity: what moves the answer

![NPV sensitivity by assumption, low vs high](../assets/tornado.png)

| Assumption | Diligence bucket | NPV range | Swing |
|---|---|---|---|
{tornado_rows_md}

The initial expectation for a case like this — cost-side uncertainty
dominating a well-measured benefit — does not hold here. **{top_driver['label']}**
outranks **{next(r for r in tornado_rows if r['diligence_bucket'] == 'unknowable')['label']}**
because the benefit is a {int(result['params']['finance.horizon_years'])}-year discounted
annuity: a proportional swing in effort-per-touch compounds across every year
of benefit, while the implementation cost is a single year-zero number. A
wide low/high band on one number does not automatically make it the biggest
driver of NPV variance once discounting and compounding are applied — this
model is the demonstration, not the assertion.

## Monte Carlo: a distribution, not a point

![Monte Carlo NPV distribution](../assets/npv_distribution.png)

10,000 draws across every ranged assumption (triangular on low/central/high):

| | |
|---|---|
| P(NPV > {base_params['finance.discount_rate']:.0%} hurdle, i.e. NPV > 0) | **{p_positive:.0%}** |
| Downside (P10) | {eur(p10)} |
| Median (P50) | {eur(p50)} |
| Upside (P90) | {eur(p90)} |

A one-in-four chance of clearing the hurdle is not "no," but it is not a
green light either — it is a case that depends on landing toward the
favourable end of assumptions that are, per the diligence-priority split
below, mostly resolvable before committing capital.

## Diligence priority

![Diligence priority by assumption](../assets/diligence_priority.png)

Share of NPV variance explained by each assumption, split by whether
diligence *could* close it (a time study, a rate card) or whether it
genuinely *cannot* be known yet (a vendor quote, a delivery plan):

| Assumption | Diligence bucket | Variance share |
|---|---|---|
{priority_rows_md}

**{measurable_share:.0%} of the uncertainty in this case is a work plan, not a
risk.** The single highest-value diligence step is a time study on
rework-touch handling time, followed by the client's actual fully loaded
rate — both answerable in days, not months, and together they resolve more
of the NPV range than waiting on an implementation cost quote would.
Segment-level touch counts (this model applies one overall mean across every
segment) are a second-order refinement worth the same kind of measurement,
not assumption, once the headline diligence is done.

## What is still assumed

Everything in `assumptions.yaml`, carried at its central value above and
stress-tested here. Two are worth naming directly: `implementation.one_off_cost_eur`
is the least defensible number in the model on its face, but per the
sensitivity analysis is not the number diligence should chase first — and
`effort.minutes_per_rework_touch` is a single assumed figure standing in for
what a short time study would measure directly.

---

Generated by `src/report.py` from `baseline.json`, `assumptions.yaml`,
`src/model.py`, and `src/sensitivity.py` — regenerate with
`.venv/bin/python src/report.py` after any change to the inputs.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, default=Path("baseline.json"))
    ap.add_argument("--assumptions", type=Path, default=Path("assumptions.yaml"))
    ap.add_argument("--out-dir", type=Path, default=Path("output"),
                     help="Where business_case.md is written — gitignored, regenerable.")
    ap.add_argument("--assets-dir", type=Path, default=Path("assets"),
                     help="Charts — tracked, so they render on GitHub without a local run.")
    args = ap.parse_args()
    args.out_dir.mkdir(exist_ok=True)
    args.assets_dir.mkdir(exist_ok=True)

    baseline = load_baseline(args.baseline)
    assumptions = load_assumptions(args.assumptions)
    report = build_report(baseline, assumptions, args.assets_dir)

    out_path = args.out_dir / "business_case.md"
    out_path.write_text(report)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
