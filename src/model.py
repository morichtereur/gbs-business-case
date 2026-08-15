"""Opportunity sizing, cash flows, NPV and payback.

Reads exactly two inputs, kept deliberately separate:

- `baseline.json` — measured facts (STP rates, cycle times, touches per
  reworked case). Nothing here is a judgement call.
- `assumptions.yaml` — everything the log cannot tell us (effort, cost,
  implementation, finance), each carrying a central value and a low/high
  range. `sensitivity.py` runs the model across that range; this module
  only needs the central value, plus an optional override for a single run.

The model itself: segments below the internal-benchmark STP target close
their gap linearly over `ramp_months`. Each case that moves from reworked to
touchless saves `mean_touches_per_case * minutes_per_rework_touch` of labour
at `fully_loaded_hourly_rate_eur`. That benefit stream, net of run cost, is
discounted at `discount_rate` against the upfront `one_off_cost_eur`.

Run: .venv/bin/python src/model.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

# Every assumption the model actually consumes, as (yaml section, key).
# sensitivity.py imports this list rather than its own copy, so "what varies"
# has one definition. Assumptions not listed here (offshore_hourly_rate_eur,
# horizon_years, working_capital) are either out of scope for this model
# variant or fixed by convention rather than uncertain.
ASSUMPTION_PATHS = [
    ("effort", "minutes_per_rework_touch"),
    ("cost", "fully_loaded_hourly_rate_eur"),
    ("implementation", "one_off_cost_eur"),
    ("implementation", "annual_run_cost_eur"),
    ("implementation", "ramp_months"),
    ("finance", "discount_rate"),
    ("finance", "volume_growth_pct"),
]

# Fixed by convention, not by a range — sourced from assumptions.yaml so it
# still isn't hardcoded here, but sensitivity.py never varies it.
FIXED_PATHS = [
    ("finance", "horizon_years"),
]


def dotted(path: tuple[str, str]) -> str:
    return f"{path[0]}.{path[1]}"


def load_baseline(path: Path = Path("baseline.json")) -> dict:
    return json.loads(path.read_text())


def load_assumptions(path: Path = Path("assumptions.yaml")) -> dict:
    return yaml.safe_load(path.read_text())


def central_params(assumptions: dict) -> dict[str, float]:
    """The point-estimate value for every modelled assumption, ranged or fixed."""
    params = {}
    for section, key in ASSUMPTION_PATHS + FIXED_PATHS:
        entry = assumptions[section][key]
        if entry["value"] is None:
            raise SystemExit(
                f"{dotted((section, key))} has no value — measure it before modelling"
            )
        params[dotted((section, key))] = entry["value"]
    return params


def param_range(assumptions: dict, section: str, key: str) -> tuple[float, float, float, str]:
    """(low, value, high, diligence_bucket) for one assumption."""
    entry = assumptions[section][key]
    return entry["low"], entry["value"], entry["high"], entry.get("diligence_bucket", "unknown")


def _irr(cash_flows: list[float]) -> float | None:
    """IRR via bisection. None if the cash-flow sign never changes (no root)."""
    def npv_at(r: float) -> float:
        return sum(cf / (1 + r) ** t for t, cf in enumerate(cash_flows))

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv_at(lo), npv_at(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv_at(mid)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _payback_years(cash_flows: list[float]) -> float | None:
    """Fractional-year payback by linear interpolation within the crossing year.

    `cash_flows` is indexed by year, [0] being the upfront outlay. None if
    cumulative cash flow never turns positive within the horizon.
    """
    cumulative = 0.0
    prev_cumulative = 0.0
    for t, cf in enumerate(cash_flows):
        prev_cumulative = cumulative
        cumulative += cf
        if cumulative >= 0 and t > 0:
            if cf == 0:
                return float(t)
            return (t - 1) + (-prev_cumulative / cf)
    return None


def run_model(baseline: dict, params: dict[str, float], skip_irr: bool = False) -> dict:
    target = baseline["internal_benchmark"]["top_quartile_stp_rate"]
    mean_touches = baseline["rework_touches"]["mean_touches_per_case"]

    minutes_per_touch = params["effort.minutes_per_rework_touch"]
    hourly_rate = params["cost.fully_loaded_hourly_rate_eur"]
    one_off_cost = params["implementation.one_off_cost_eur"]
    annual_run_cost = params["implementation.annual_run_cost_eur"]
    ramp_months = params["implementation.ramp_months"]
    discount_rate = params["finance.discount_rate"]
    volume_growth = params["finance.volume_growth_pct"]
    horizon_years = int(params["finance.horizon_years"])

    cost_per_reworked_case = mean_touches * (minutes_per_touch / 60) * hourly_rate

    opportunity = []
    cycle_time_days_total = 0.0
    for s in baseline["segments"]:
        if not s["usable_for_sizing"] or s["stp_rate"] is None:
            continue
        gap_pp = target - s["stp_rate"]
        if gap_pp <= 0:
            continue
        cases_moved = s["complete_cases"] * gap_pp
        opportunity.append({
            "spend_area": s["spend_area"],
            "complete_cases": s["complete_cases"],
            "stp_rate": s["stp_rate"],
            "gap_pp": round(gap_pp, 4),
            "cases_moved_annual": cases_moved,
        })
        if s["median_days_rework"] is not None and s["median_days_touchless"] is not None:
            cycle_time_days_total += cases_moved * (s["median_days_rework"] - s["median_days_touchless"])

    cases_moved_total = sum(o["cases_moved_annual"] for o in opportunity)
    annual_benefit_at_target = cases_moved_total * cost_per_reworked_case

    # Monthly ramp: STP gap closes linearly to `ramp_months`, volume grows
    # (or shrinks) by whole-year steps off the measured base-year cohort.
    benefit_by_year = [0.0] * (horizon_years + 1)  # index 0 unused (no benefit before go-live)
    for month in range(1, horizon_years * 12 + 1):
        year = (month - 1) // 12 + 1
        ramp_fraction = min(1.0, month / ramp_months)
        growth_factor = (1 + volume_growth) ** (year - 1)
        benefit_by_year[year] += annual_benefit_at_target * ramp_fraction * growth_factor / 12

    cash_flows = [-one_off_cost]
    for year in range(1, horizon_years + 1):
        cash_flows.append(benefit_by_year[year] - annual_run_cost)

    npv = sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows))
    irr = None if skip_irr else _irr(cash_flows)
    payback_simple = _payback_years(cash_flows)
    discounted_cfs = [cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows)]
    payback_discounted = _payback_years(discounted_cfs)

    return {
        "params": params,
        "target_stp_rate": target,
        "cost_per_reworked_case_eur": round(cost_per_reworked_case, 2),
        "opportunity_by_segment": opportunity,
        "cases_moved_annual_at_target": round(cases_moved_total, 1),
        "annual_benefit_at_target_eur": round(annual_benefit_at_target, 2),
        "cycle_time_days_saved_annual_at_target": round(cycle_time_days_total, 1),
        "benefit_by_year_eur": [round(b, 2) for b in benefit_by_year],
        "cash_flows_eur": [round(cf, 2) for cf in cash_flows],
        "npv_eur": round(npv, 2),
        "irr": round(irr, 4) if irr is not None else None,
        "payback_years_simple": round(payback_simple, 2) if payback_simple is not None else None,
        "payback_years_discounted": round(payback_discounted, 2) if payback_discounted is not None else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, default=Path("baseline.json"))
    ap.add_argument("--assumptions", type=Path, default=Path("assumptions.yaml"))
    ap.add_argument("--out", type=Path, default=Path("output/model_result.json"))
    args = ap.parse_args()

    baseline = load_baseline(args.baseline)
    assumptions = load_assumptions(args.assumptions)
    result = run_model(baseline, central_params(assumptions))

    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")

    print(f"wrote {args.out}\n")
    print(f"Target STP rate: {result['target_stp_rate']:.1%}")
    print(f"Cost per reworked case eliminated: EUR {result['cost_per_reworked_case_eur']:.2f}")
    print("\nOpportunity by segment (cases moved/year at full target):")
    for o in result["opportunity_by_segment"]:
        print(f"  {o['spend_area']:<28} {o['cases_moved_annual']:>8,.0f} cases  "
              f"(gap {o['gap_pp']:+.1%})")
    print(f"\nTotal cases moved/year at target: {result['cases_moved_annual_at_target']:,.0f}")
    print(f"Annual benefit at full target run-rate: EUR {result['annual_benefit_at_target_eur']:,.0f}")
    print(f"Cycle-time days saved/year at target (unmonetised): "
          f"{result['cycle_time_days_saved_annual_at_target']:,.0f}")
    print(f"\nNPV: EUR {result['npv_eur']:,.0f}")
    print(f"IRR: {result['irr']:.1%}" if result["irr"] is not None else "IRR: no root found")
    print(f"Payback (simple): {result['payback_years_simple']} years"
          if result["payback_years_simple"] is not None else "Payback (simple): beyond horizon")
    print(f"Payback (discounted): {result['payback_years_discounted']} years"
          if result["payback_years_discounted"] is not None else "Payback (discounted): beyond horizon")


if __name__ == "__main__":
    main()
