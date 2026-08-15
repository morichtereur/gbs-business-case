"""Tornado, Monte Carlo, and diligence priority.

Three questions, in order of how much they change what the reader should do:

1. Tornado — one assumption at a time, low vs high, everything else held at
   its central value. Which single number moves the NPV most?
2. Monte Carlo — every ranged assumption drawn at once (triangular on its
   low/value/high), N times. Not "NPV is EUR X" but the probability of
   clearing the hurdle rate the discounting already bakes in, plus an
   explicit downside case.
3. Diligence priority — the tornado/Monte Carlo answer "which assumption,"
   this answers "which *kind* of assumption": variance explained by things
   that could be measured in diligence (a time study, a rate card) versus
   things that cannot be known until later (a vendor quote, a delivery
   plan). `diligence_bucket` on each assumptions.yaml entry is the split;
   the share of NPV variance each bucket explains is a work plan, not just
   a caveat.

Run: .venv/bin/python src/sensitivity.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model import (
    ASSUMPTION_PATHS,
    central_params,
    dotted,
    load_assumptions,
    load_baseline,
    param_range,
    run_model,
)

N_MONTE_CARLO = 10_000
RNG_SEED = 42

LABELS = {
    "effort.minutes_per_rework_touch": "Minutes per rework touch",
    "cost.fully_loaded_hourly_rate_eur": "Fully loaded hourly rate",
    "implementation.one_off_cost_eur": "Implementation one-off cost",
    "implementation.annual_run_cost_eur": "Annual run cost",
    "implementation.ramp_months": "Ramp duration (months)",
    "finance.discount_rate": "Discount rate",
    "finance.volume_growth_pct": "Volume growth, %/yr",
}

PALETTE = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
}
BUCKET_COLOR = {"measurable": "#2a78d6", "unknowable": "#eb6834"}


def _style(ax, fig):
    fig.patch.set_facecolor(PALETTE["surface"])
    ax.set_facecolor(PALETTE["surface"])
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(PALETTE["axis"])
    ax.tick_params(colors=PALETTE["ink2"], labelsize=9)
    ax.xaxis.label.set_color(PALETTE["ink2"])
    ax.yaxis.label.set_color(PALETTE["ink2"])


def run_tornado(baseline: dict, assumptions: dict, base_params: dict) -> tuple[float, list[dict]]:
    base_npv = run_model(baseline, base_params, skip_irr=True)["npv_eur"]
    rows = []
    for section, key in ASSUMPTION_PATHS:
        low, _, high, bucket = param_range(assumptions, section, key)
        name = dotted((section, key))
        p_low = dict(base_params, **{name: low})
        p_high = dict(base_params, **{name: high})
        npv_low = run_model(baseline, p_low, skip_irr=True)["npv_eur"]
        npv_high = run_model(baseline, p_high, skip_irr=True)["npv_eur"]
        rows.append({
            "assumption": name,
            "label": LABELS[name],
            "diligence_bucket": bucket,
            "low_value": low,
            "high_value": high,
            "npv_at_low": npv_low,
            "npv_at_high": npv_high,
            "swing_eur": abs(npv_high - npv_low),
        })
    rows.sort(key=lambda r: r["swing_eur"], reverse=True)
    return base_npv, rows


def run_monte_carlo(
    baseline: dict, assumptions: dict, base_params: dict, n: int = N_MONTE_CARLO, seed: int = RNG_SEED
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    samples: dict[str, np.ndarray] = {}
    for section, key in ASSUMPTION_PATHS:
        low, value, high, _ = param_range(assumptions, section, key)
        name = dotted((section, key))
        samples[name] = rng.triangular(low, value, high, size=n)

    npvs = np.empty(n)
    for i in range(n):
        params = dict(base_params)
        for name, arr in samples.items():
            params[name] = arr[i]
        npvs[i] = run_model(baseline, params, skip_irr=True)["npv_eur"]
    return npvs, samples


def diligence_priority(npvs: np.ndarray, samples: dict[str, np.ndarray], assumptions: dict) -> dict:
    """Variance share per assumption, via R^2 of a simple linear fit against
    NPV. Inputs are drawn independently, so summing per-parameter R^2
    approximates the share of total variance each one explains — the same
    logic a tornado chart uses, just computed from the Monte Carlo draws
    instead of an at-a-time swing.
    """
    shares = {}
    for section, key in ASSUMPTION_PATHS:
        name = dotted((section, key))
        r = np.corrcoef(samples[name], npvs)[0, 1]
        shares[name] = r ** 2

    total = sum(shares.values()) or 1.0
    by_parameter = [
        {
            "assumption": name,
            "label": LABELS[name],
            "diligence_bucket": assumptions[name.split(".")[0]][name.split(".")[1]].get("diligence_bucket", "unknown"),
            "variance_share": share / total,
        }
        for name, share in shares.items()
    ]
    by_parameter.sort(key=lambda r: r["variance_share"], reverse=True)

    by_bucket: dict[str, float] = {}
    for row in by_parameter:
        by_bucket[row["diligence_bucket"]] = by_bucket.get(row["diligence_bucket"], 0.0) + row["variance_share"]

    return {"by_parameter": by_parameter, "by_bucket": by_bucket}


def plot_tornado(base_npv: float, rows: list[dict], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(rows) + 1.5))
    _style(ax, fig)

    y = np.arange(len(rows))[::-1]
    for yi, row in zip(y, rows):
        lo, hi = sorted([row["npv_at_low"], row["npv_at_high"]])
        color = BUCKET_COLOR[row["diligence_bucket"]]
        ax.barh(yi, hi - lo, left=lo, height=0.55, color=color, edgecolor=PALETTE["surface"], linewidth=2)
        ax.text(hi + (hi - lo) * 0.02 + 1, yi, f"low {row['low_value']:,g} / high {row['high_value']:,g}",
                va="center", ha="left", fontsize=8, color=PALETTE["ink2"])

    ax.set_ylim(-1.1, len(rows) - 0.3)
    ax.axvline(base_npv, color=PALETTE["ink"], linewidth=1.5, zorder=3)
    ax.text(base_npv, -0.85, "central\nestimate", color=PALETTE["ink"], fontsize=8, ha="center", va="top")
    ax.axvline(0, color=PALETTE["muted"], linewidth=1, linestyle=(0, (3, 3)), zorder=2)
    ax.text(0, -0.85, "breakeven", color=PALETTE["muted"], fontsize=8, ha="center", va="top")

    ax.set_yticks(y)
    ax.set_yticklabels([r["label"] for r in rows], color=PALETTE["ink"], fontsize=9)
    ax.set_xlabel("NPV (EUR)")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v/1000:,.0f}k")
    ax.grid(axis="x", color=PALETTE["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in BUCKET_COLOR.values()]
    ax.legend(handles, [b.capitalize() for b in BUCKET_COLOR], loc="lower right", frameon=False,
              fontsize=9, labelcolor=PALETTE["ink2"])
    ax.set_title("NPV sensitivity by assumption, low vs high", color=PALETTE["ink"], fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


def plot_npv_distribution(npvs: np.ndarray, out: Path) -> None:
    p_positive = (npvs > 0).mean()
    p10, p50, p90 = np.percentile(npvs, [10, 50, 90])

    fig, ax = plt.subplots(figsize=(8, 4.5))
    _style(ax, fig)
    ax.hist(npvs / 1000, bins=60, color="#2a78d6", alpha=0.85, edgecolor=PALETTE["surface"], linewidth=0.3)
    ax.axvline(0, color="#e34948", linewidth=1.5, linestyle=(0, (3, 3)))
    ax.text(0, ax.get_ylim()[1] * 0.97, f"  breakeven — P(NPV>0) = {p_positive:.0%}",
            color="#e34948", fontsize=9, va="top")
    ax.axvline(p50 / 1000, color=PALETTE["ink"], linewidth=1.2)
    ax.text(p50 / 1000, ax.get_ylim()[1] * 0.88, f"  median {p50/1000:,.0f}k",
            color=PALETTE["ink"], fontsize=8, va="top")

    ax.set_xlabel("NPV (EUR thousands)")
    ax.set_ylabel("Draws")
    ax.grid(axis="y", color=PALETTE["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_title(f"Monte Carlo NPV distribution (n={len(npvs):,}) — "
                 f"downside P10 {p10/1000:,.0f}k, upside P90 {p90/1000:,.0f}k",
                 color=PALETTE["ink"], fontsize=10.5, loc="left")
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


def plot_diligence_priority(priority: dict, out: Path) -> None:
    rows = priority["by_parameter"]
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(rows) + 1.5))
    _style(ax, fig)

    y = np.arange(len(rows))[::-1]
    colors = [BUCKET_COLOR[r["diligence_bucket"]] for r in rows]
    ax.barh(y, [r["variance_share"] * 100 for r in rows], color=colors, height=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels([r["label"] for r in rows], color=PALETTE["ink"], fontsize=9)
    ax.set_xlabel("Share of NPV variance explained (%)")
    ax.grid(axis="x", color=PALETTE["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    by_bucket = priority["by_bucket"]
    subtitle = " · ".join(f"{b}: {s:.0%}" for b, s in sorted(by_bucket.items(), key=lambda kv: -kv[1]))
    ax.set_title(f"Diligence priority — {subtitle}", color=PALETTE["ink"], fontsize=10.5, loc="left")

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in BUCKET_COLOR.values()]
    ax.legend(handles, [b.capitalize() for b in BUCKET_COLOR], loc="lower right", frameon=False,
              fontsize=9, labelcolor=PALETTE["ink2"])
    fig.tight_layout()
    fig.savefig(out, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, default=Path("baseline.json"))
    ap.add_argument("--assumptions", type=Path, default=Path("assumptions.yaml"))
    ap.add_argument("--out-dir", type=Path, default=Path("output"))
    ap.add_argument("--n", type=int, default=N_MONTE_CARLO)
    args = ap.parse_args()
    args.out_dir.mkdir(exist_ok=True)

    baseline = load_baseline(args.baseline)
    assumptions = load_assumptions(args.assumptions)
    base_params = central_params(assumptions)

    base_npv, tornado_rows = run_tornado(baseline, assumptions, base_params)
    npvs, samples = run_monte_carlo(baseline, assumptions, base_params, n=args.n)
    priority = diligence_priority(npvs, samples, assumptions)

    p10, p50, p90 = (float(v) for v in np.percentile(npvs, [10, 50, 90]))
    mc_summary = {
        "n": args.n,
        "p_npv_positive": float((npvs > 0).mean()),
        "npv_mean_eur": float(npvs.mean()),
        "npv_p10_eur": p10,
        "npv_p50_eur": p50,
        "npv_p90_eur": p90,
    }

    result = {
        "central_npv_eur": base_npv,
        "tornado": tornado_rows,
        "monte_carlo": mc_summary,
        "diligence_priority": priority,
    }
    (args.out_dir / "sensitivity.json").write_text(json.dumps(result, indent=2) + "\n")

    plot_tornado(base_npv, tornado_rows, args.out_dir / "tornado.png")
    plot_npv_distribution(npvs, args.out_dir / "npv_distribution.png")
    plot_diligence_priority(priority, args.out_dir / "diligence_priority.png")

    print(f"wrote {args.out_dir/'sensitivity.json'}, tornado.png, npv_distribution.png, diligence_priority.png\n")
    print(f"Central NPV: EUR {base_npv:,.0f}")
    print("\nTornado (ranked by swing):")
    for r in tornado_rows:
        print(f"  {r['label']:<32} EUR {r['npv_at_low']:>12,.0f}  to  EUR {r['npv_at_high']:>12,.0f}  "
              f"[{r['diligence_bucket']}]")
    print(f"\nMonte Carlo (n={args.n:,}):")
    print(f"  P(NPV > 0):     {mc_summary['p_npv_positive']:.1%}")
    print(f"  NPV P10/P50/P90: EUR {p10:,.0f} / {p50:,.0f} / {p90:,.0f}")
    print("\nDiligence priority (share of NPV variance):")
    for b, s in sorted(priority["by_bucket"].items(), key=lambda kv: -kv[1]):
        print(f"  {b:<12} {s:.0%}")
    for r in priority["by_parameter"]:
        print(f"    {r['label']:<32} {r['variance_share']:.1%}  [{r['diligence_bucket']}]")


if __name__ == "__main__":
    main()
