# Purchase-to-pay rework elimination case

A business case for closing the straight-through-processing gap across the
ten spend areas below the internal benchmark — Packaging is the largest by
volume, but not the only one in scope. Built on a measured baseline rather
than a workshop estimate; full provenance in `baseline.json`,
`assumptions.yaml`, and the scripts in `src/`.

## Bottom line

At central assumptions, the case **does not clear the 9% hurdle
rate**: NPV is **EUR -142,931** over a 5-year
horizon, and Monte Carlo across the full assumption ranges puts the
probability of a positive NPV at **26%**. That is not a rounding
problem — it is the direct consequence of a measured fact: reworked cases
average **1.48 rework touches**, not the multi-touch
slog a workshop estimate usually assumes, so the labour saved by eliminating
rework is thinner than the intuitive case for automation suggests.

The uncertainty that matters most is not, as might be expected, the
implementation cost quote — it is **Minutes per rework touch**, an assumption
diligence can resolve with a time study, not a vendor negotiation. **62%**
of NPV variance sits in that "could be measured" bucket against **38%**
in the "genuinely unknowable until later" bucket — see
[Diligence priority](#diligence-priority) for the work plan that follows from
that split.

## Measured baseline

From 251,734 purchase order line items, 183,677 of which
reach `Clear Invoice`:

| | |
|---|---|
| Straight-through rate | **63.2%** of completed cases |
| Rework penalty | **19.65** days (90.92 vs 71.27) |
| Touches per reworked case | mean **1.48** (median 1, p90 3) |
| Internal benchmark (target) | **70.5%**, demonstrated by Sales on 55,621 cases |

The touches figure is new since the baseline was first measured: mean
exceeds median because a long tail of multi-touch cases (SRM transfer
failures, repeated changes) pulls the average up from the typical single
touch. Pricing effort on the mean, not the median, is what keeps the labour
saving honest — see `p2p-process-mining/src/rework_touches.py`.

## Where the opportunity sits

Segments below the 70.5% target, sized by cases/year
that would move from reworked to touchless if the segment closed its gap to
target:

| Spend area | Complete cases | Current STP | Gap to target | Cases moved/yr |
|---|---|---|---|---|
| Packaging | 76,643 | 59.7% | +10.9% | 8,331 |
| Trading & End Products | 17,026 | 60.0% | +10.6% | 1,800 |
| Additives | 12,381 | 65.1% | +5.4% | 672 |
| CAPEX & SOCS | 5,305 | 62.2% | +8.4% | 446 |
| Latex & Monomers | 3,080 | 44.2% | +26.3% | 811 |
| (unclassified) | 1,625 | 45.7% | +24.9% | 404 |
| Solvents | 1,796 | 58.6% | +11.9% | 214 |
| Pigments & Colorants | 1,918 | 56.1% | +14.4% | 277 |
| Specialty Resins | 1,591 | 54.0% | +16.5% | 263 |
| Titanium Dioxides | 572 | 44.1% | +26.5% | 152 |

Total: **13,369 cases/year** move from
reworked to touchless at full target run-rate, saving
**EUR 12.46** of labour each — a per-case
figure that is itself the product of a measured touch count and two assumed
inputs (minutes per touch, hourly rate), which is exactly why it is the
model's most sensitive line, not the implementation cost.

Cycle time also compresses: **145,282
days/year** of case duration removed at target run-rate. Named as a benefit,
left unmonetised — the log carries cumulative net worth per event, not
invoice values, so a working-capital euro figure is not defensible from this
data (see `assumptions.yaml`, `finance.working_capital`).

## Central-case model

Linear ramp to target over 18 months,
EUR 450,000 upfront,
EUR 60,000/year run cost,
discounted at 9%:

| | |
|---|---|
| Year 0 | EUR -450,000 |
| Year 1 | EUR 141 |
| Year 2 | EUR 94,979 |
| Year 3 | EUR 106,545 |
| Year 4 | EUR 106,545 |
| Year 5 | EUR 106,545 |

| Metric | Value |
|---|---|
| NPV | EUR -142,931 |
| IRR | -2.3% |
| Payback (simple) | beyond the 5-year horizon |

## Sensitivity: what moves the answer

![NPV sensitivity by assumption, low vs high](../assets/tornado.png)

| Assumption | Diligence bucket | NPV range | Swing |
|---|---|---|---|
| Minutes per rework touch | measurable | EUR -413,155 to EUR 442,555 | EUR 855,710 |
| Implementation one-off cost | unknowable | EUR 57,069 to EUR -592,931 | EUR 650,000 |
| Fully loaded hourly rate | measurable | EUR -271,609 to EUR 62,954 | EUR 334,563 |
| Annual run cost | unknowable | EUR -45,690 to EUR -376,310 | EUR 330,620 |
| Volume growth, %/yr | unknowable | EUR -198,898 to EUR -81,303 | EUR 117,595 |
| Ramp duration (months) | unknowable | EUR -105,609 to EUR -214,360 | EUR 108,751 |
| Discount rate | measurable | EUR -111,869 to EUR -178,478 | EUR 66,609 |

The initial expectation for a case like this — cost-side uncertainty
dominating a well-measured benefit — does not hold here. **Minutes per rework touch**
outranks **Implementation one-off cost**
because the benefit is a 5-year discounted
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
| P(NPV > 9% hurdle, i.e. NPV > 0) | **26%** |
| Downside (P10) | EUR -476,222 |
| Median (P50) | EUR -169,685 |
| Upside (P90) | EUR 186,378 |

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
| Minutes per rework touch | measurable | 51% |
| Implementation one-off cost | unknowable | 30% |
| Fully loaded hourly rate | measurable | 10% |
| Annual run cost | unknowable | 6% |
| Ramp duration (months) | unknowable | 1% |
| Volume growth, %/yr | unknowable | 1% |
| Discount rate | measurable | 1% |

**62% of the uncertainty in this case is a work plan, not a
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
