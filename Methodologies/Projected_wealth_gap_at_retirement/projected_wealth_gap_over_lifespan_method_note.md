# Projected Wealth Gap Over Lifespan: Method Note

## 1. The claim

For households whose Household Reference Person (HRP) is currently aged 30–39 (Wealth and Assets Survey Round 8, DVAge17R8 bands 7 and 8), this analysis projects the gap in household wealth between owners and renters at two points in the life course:

- **At retirement (age 67)** — already produced by the existing v4 model (`was_wealth_gap_analysis_v4.py`).
- **At end of life (age 88)** — the post-retirement extension specified in this note.

All values are reported in constant 2026 GBP. The retirement age is 67. The lifespan endpoint is 88 (mean UK life expectancy at age 67, rounded). The "wealth at age 88" gap is the headline lifespan metric, with annual wealth trajectories, sensitivity scenarios, decompositions, and subgroup breakdowns produced alongside it.

## 2. Summary of approach

The pre-retirement v4 engine produces, for each WAS R8 household in the FTB cohort, a vector of projected wealth stocks at age 67: property, financial, pension, and physical wealth (all in 2026 £). This note specifies a year-by-year post-retirement engine that takes those stocks and runs them forward to age 88.

The post-retirement engine is deterministic and household-level. Each year between 68 and 88:

1. **Income** is the household's full new State Pension entitlement (one per adult in the household at survey observation), growing at +0.5% p.a. real (central case, anchored on the historical triple-lock excess over CPI; IFS R209).
2. **Outflows** are (i) target real consumption, set equal to each household's pre-retirement LCF-derived consumption at age 67 and then grown forward on an age-piecewise, income-differentiated schedule calibrated to IFS R209 (above-median households rise at +1.0% p.a. real to age 80 then fall at −0.5% p.a. to age 88; below-median households are flat to age 80 then fall at −0.5% p.a. to age 88), plus (ii) housing costs — rent for renters (continuing to grow with real income, as in v4) or zero for owners (mortgages assumed paid off by retirement; v4's mortgage cut-off rule already enforces this), plus (iii) a one-off home adaptation cost of £27,000 (2026 £) at age 75, paid by owners only. Renters are assumed to have adaptations provided via landlord or Disabled Facilities Grant and bear no out-of-pocket cost.
3. **Shortfall** between income and outflows is funded by drawing down liquid wealth: financial wealth first, then pension wealth. Liquid stocks earn their real returns (3.5% financial, 3.0% pension) on the balance held at the start of the year, before that year's withdrawal.
4. **Illiquid stocks** (property, physical) compound at their real growth rates throughout (REAL_HPI_GROWTH and REAL_WEALTH_GROWTH from v4). Property is held to age 88 — no equity release or downsizing.
5. If liquid wealth is exhausted, the household is recorded as in deficit for the rest of the projection, with consumption rationed to State Pension income. Property and physical stocks continue to grow but are not drawn down (per scoping decision).

Terminal wealth at age 88 is the sum of remaining property, financial, pension, and physical wealth, with both undiscounted and Green-Book-discounted versions reported. The owner–renter gap is then decomposed into a property channel, a housing-cost-savings channel, and a residual income/endowment channel, mirroring v4's three-way decomposition extended over the lifespan horizon. Sensitivity scenarios from v4 are re-run end-to-end.

## 3. Key external sources

| Source | What it provides | URL / reference | Date accessed |
|---|---|---|---|
| ONS Wealth and Assets Survey Round 8 (April 2020 – March 2022) | Household-level wealth stocks, tenure, income, demographics, household composition. Same dataset as v4. | https://www.ons.gov.uk/peoplepopulationandcommunity/personalandhouseholdfinances/debt/methodologies/wealthandassetssurveyqmi | 2026-05-11 |
| ONS Living Costs and Food Survey, owners-vs-renters net consumption deciles (provided as `Consumption_deciles_split_owners_renters_weekly.csv`) | Target real consumption by income decile and tenure. Same input as v4. | https://www.ons.gov.uk/peoplepopulationandcommunity/personalandhouseholdfinances/expenditure/bulletins/familyspendingintheuk/april2023tomarch2024 | 2026-05-11 |
| DWP Benefit and pension rates 2026/27 | Full new State Pension £241.30/week (£12,547.60/year nominal April 2026), uprated by 4.8% under triple lock. Used to set State Pension income per qualifying adult. | https://commonslibrary.parliament.uk/research-briefings/cbp-10403/ | 2026-05-11 |
| Habinteg / Centre for Ageing Better — adaptations to older homes research | Estimate of ~£27,000 to retrofit a standard M4(1) home with the three most common later-life adaptations (grab rails, stairlift, wet room conversion). Used as the one-off owner adaptation cost at age 75. | https://www.habinteg.org.uk/latest-news/adaptations-to-older-homes-could-cost-households-thousands-habinteg-2478/ | 2026-05-11 |
| IFS Report R209 — *How does spending change through retirement?* (Crawford, Karjalainen & Sturrock, 2022) | Empirical source for the post-retirement consumption schedule. Reports that, controlling for birth cohort, real per-person spending rises at roughly 1% p.a. between ages 67 and 80 for above-median income households (1939–43 cohort, +7% over 8 years), is roughly flat for below-median income households over the same range, and falls at roughly 0.7% p.a. between 80 and 88 for both groups (1924–28 cohort, −6% over 6 years). Also evidence that triple-locked State Pension has historically outpaced CPI, supporting a +0.5% real growth central assumption. | https://ifs.org.uk/sites/default/files/2022-09/IFS-Report-R209-How-does-spending-change-through-retirement.pdf | 2026-05-11 |
| HM Treasury Green Book | 3.5% standard real social time-preference discount rate. Same as v4. | https://www.gov.uk/government/publications/the-green-book-appraisal-and-evaluation-in-central-government | 2026-05-11 |
| ONS National Life Tables — England and Wales | Period life expectancy at age 67 ≈ 17 years for males, 19 years for females; mid-point ~88 used as lifespan endpoint. | https://www.ons.gov.uk/peoplepopulationandcommunity/birthsdeathsandmarriages/lifeexpectancies | 2026-05-11 |

## 4. Key assumptions (non-source values)

These are model assumptions chosen for parsimony or modelling judgement and are not drawn from a single external source. They are exposed as parameters and varied in sensitivity scenarios.

| Assumption | Central value | Range tested | Rationale |
|---|---|---|---|
| Retirement age | 67 | — | Statutory State Pension age for the cohort. Inherited from v4. |
| Lifespan endpoint | 88 | 85 / 91 sensitivity | Period life expectancy at 67, gender-averaged, rounded. |
| State Pension entitlement | Full new State Pension × number of adults in household at WAS observation | 1× per HRP only; or means-tested phase-out | Assumes both adults in a couple accrue a full record by SPa. Conservative: applying to HRP only. |
| State Pension real growth | +0.5% p.a. real (central) | 0% p.a. (CPI-flat) / +1.0% p.a. (extended triple-lock) | Reflects historical triple-lock excess over CPI (≈0.4–0.6 p.p./yr). Promoted to the central case following IFS R209 evidence that rising State Pension income is a key reason total household income stays roughly flat in real terms through retirement. |
| Drawdown order | Financial first, then pension | Pension first; pooled at blended return | Reflects typical post-2015 pension-freedoms behaviour. Tax treatment is abstracted away. |
| Home adaptation cost (owners) | One-off £27,000 (2026 £) at age 75 | £15,000 (low) / £40,000 (high); also age 70 / age 80 timing sensitivity | Habinteg estimate for grab rails + stairlift + wet room in standard M4(1) housing. Applied only to owners — renters are assumed to access adaptations via landlord / Disabled Facilities Grant at no household cost. Not amortised: treated as a single year-8 cashflow event. |
| Property held to age 88 | No equity release or downsizing | Allow equity release if liquid wealth depleted | Per scoping decision. |
| Real consumption growth in retirement | Age-piecewise, income-differentiated schedule (see below) | Flat at v4's 1.2% (legacy) / no income split / steeper 80+ decline (−1.0%) | Calibrated to IFS R209. Income split uses cohort median of `hh_net_income` at WAS observation: deciles 1–5 = below median, 6–10 = above median. |
| Above-median income, ages 67–80 | +1.0% p.a. real | — | IFS R209: 1939–43 cohort spending rose 7% (≈0.9%/yr) between ages 67 and 75 for above-median households. Extended to age 80 on the basis that the rising pattern persists into late 70s. |
| Below-median income, ages 67–80 | 0.0% p.a. real (flat) | — | IFS R209: below-median spending falls 1% between 67 and 75 then is stable — essentially flat for modelling purposes. |
| All households, ages 80–88 | −0.5% p.a. real | — | IFS R209: 1924–28 cohort spending fell 6% between ages 82 and 88 (≈−1% p.a.). Used as −0.5% real to be conservative against the cohort uplift that future generations may experience. |
| Rent growth in retirement | At REAL_INCOME_GROWTH p.a. real | + sensitivity `real_rent_grw = 0.01` already in v4 scenarios | Continues v4 convention that long-run rents track incomes. |
| Discount rate | 3.5% real (HM Treasury Green Book standard) | Green Book declining schedule (3.5% → 3.0% after year 30) | Inherited from v4. |

## 5. Top-down description

The full lifespan model is a two-stage pipeline. Stage 1 is the existing v4 model; Stage 2 is the new post-retirement engine specified in mechanisms M1–M7 below.

```
WAS R8 cohort (HRP age 32/37 in 2021)
        │
        ▼
[v4 PRE-RETIREMENT ENGINE]   ─────  produces, per household:
  • W_prop(67)
  • W_fin(67)
  • W_pen(67)
  • W_phys(67)
  • years_to_retirement
        │
        ▼  ── hand-off (M1)
[POST-RETIREMENT ENGINE, ages 68 → 88]
  M2  state pension income                       ┐
  M3  costs: consumption, housing,               │  year-by-year
       one-off £27k adaptation at age 75 (owners)│  cashflow
  M4  drawdown: financial → pension              ┘
  M5  illiquid growth: property, physical
        │
        ▼  ── terminal stocks at 88 (M6)
W_prop(88), W_fin(88), W_pen(88), W_phys(88)
        │
        ▼
W_total(88) per household
        │
        ▼
Weighted owner–renter gap at 88
        │
        ├──▶ M7 three-way decomposition (lifespan version)
        ├──▶ subgroup breakdowns (income decile, region, education)
        ├──▶ sensitivity scenarios re-run
        └──▶ annual trajectory chart (ages 67 → 88)
```

The post-retirement engine is a per-household time-series loop over 21 years (t = 1, …, 21 corresponding to ages 68, …, 88). For each household h and each year t, the order of operations is fixed:

1. Grow stocks forward by one year on opening balances (property, physical, fin and pen on whatever liquid balances remain).
2. Determine outflows for the year (consumption + housing cost + one-off £27,000 adaptation cost if it is the owner's age-75 year).
3. Compute net cashflow gap = outflows − State Pension.
4. If positive, withdraw from financial; if financial reaches zero, withdraw from pension; if pension also reaches zero, record deficit.
5. Carry closing balances into next year.

Wealth at age 88 is read off after the t = 21 loop iteration.

## 6. Mechanism-by-mechanism description

### M1 — Hand-off from v4

**Definition.** For each WAS household h in the FTB cohort (HRP currently aged 32 or 37), extract the projected wealth stocks at age 67 from the v4 output dataframe `ftb`.

**Inputs.** v4's `project_wealth()` output: columns `proj_prop_wealth`, `proj_fin_wealth`, `proj_pen_wealth`, `proj_phys_wealth`, plus `tenure_binary`, `R8xshhwgt`, `gross_prop_value` (final year), `mort_years_remaining`, `ann_rent_paid`, `cons_cost`, household-composition fields from WAS R8, and demographics.

**Estimation approach.** No transformation — direct read of v4 output. Confirm via an assertion that `proj_total_wealth ≈ proj_prop_wealth + proj_fin_wealth + proj_pen_wealth + proj_phys_wealth` for each row.

**Functional form.**
```
W_prop(67, h)  = proj_prop_wealth_h
W_fin(67, h)   = proj_fin_wealth_h
W_pen(67, h)   = proj_pen_wealth_h
W_phys(67, h)  = proj_phys_wealth_h
```

The pre-retirement model already ensures (for v4 central scenario) that mortgages of households with `mort_years_remaining + hrp_age_mid < 67` are fully repaid by age 67 — verify and flag any exceptions.

### M2 — Post-retirement income (State Pension only)

**Definition.** Annual State Pension income received by each household, in constant 2026 £.

**Inputs.** Full new State Pension weekly rate from DWP April 2026 uprating (£241.30/week × 52 = £12,547.60/year nominal April 2026); household composition (number of adults aged 16+ at WAS observation, derived from `pp[CASER8]` person counts excluding dependants).

**Estimation approach.** Deflate the 2026/27 nominal rate to constant 2026 calendar-year £ using CPI (April 2026 → calendar-year 2026 implied factor ≈ 1.0; treat as numerically identical for simplicity). Multiply by number of qualifying adults per household.

**Functional form.**
```
n_adults_h        = count of adults 16+ in household h at survey (from person file)
SP_per_adult      = 241.30 × 52                                  (£12,547.60 in 2026 £)
sp_real_growth    = 0.005                                        (+0.5% p.a. real, central)
SP_income(t, h)   = n_adults_h × SP_per_adult × (1 + sp_real_growth)^t
                                                                  for t = 1, …, 21
```

State Pension grows at +0.5% real p.a. in the central case, anchored on the historical triple-lock excess over CPI inflation (IFS R209). Sensitivity scenarios test 0% (CPI-flat) and +1.0% (extended triple-lock) real growth.

### M3 — Post-retirement outflows

**Definition.** Annual outflows from each household, comprising target consumption, housing cost (rent for renters; zero for owners), plus a one-off home adaptation cost for owners at age 75. All in 2026 £.

**Inputs.**
- v4's `cons_cost` (LCF-derived target consumption at age 67, in 2026 £).
- v4's `ann_rent_paid` (2026 £, age 67 base for renters).
- v4's `hh_net_income` (used to classify each household as above- or below-cohort-median for the consumption-growth split).
- `CONSUMPTION_INFL_PRE_RET` = 0.012 (real, p.a.) — used by v4 in the pre-retirement projection only.
- Post-retirement consumption growth schedule, calibrated to IFS R209:
  - `g_pre80_above` = +0.010 (above-median income households, ages 67–80)
  - `g_pre80_below` = 0.000 (below-median income households, ages 67–80)
  - `g_post80` = −0.005 (all households, ages 81–88)
- `REAL_INCOME_GROWTH` (v4 CAGR — used to grow rents).
- One-off adaptation cost `A = £27,000` in 2026 £ at age 75 (t = 8); applied to owners only.

**Estimation approach.** Establish the age-67 consumption level by carrying `cons_cost_h` forward from 2026 at the v4 pre-retirement rate (`CONSUMPTION_INFL_PRE_RET = 1.2%`) over `n_h` years. From age 67 onward, switch to the IFS-calibrated piecewise schedule: above-median households grow consumption at +1.0% p.a. real until age 80 then decline at −0.5% p.a. to age 88; below-median households are flat to age 80 then decline at −0.5% p.a. to age 88. The income split is determined by where the household's `hh_net_income` (in 2026 £ at WAS observation) sits relative to the cohort median (equivalent to the `Q3 / Q4 / Q5` boundary in the v4 quintile breakdown, or the `D6` lower bound in the decile breakdown).

Rent for renters continues to track income growth as in v4. Owners face no recurring housing cost. At age 75 (model year t = 8), owners incur a single £27,000 adaptation cost in 2026 £, drawn from liquid wealth in that year alongside normal outflows.

**Functional form.** Define the income-group indicator:
```
above_median(h) = 1 if hh_net_income_h >= cohort_median_income,  else 0
g_pre80(h)      = g_pre80_above  if above_median(h) = 1
                  g_pre80_below  otherwise
```

Anchor consumption at age 67:
```
C(0, h) = cons_cost_h × (1 + CONSUMPTION_INFL_PRE_RET)^(n_h)
```

Apply piecewise post-retirement growth:
```
For 1 <= t <= 13   (ages 68–80):
    C(t, h) = C(0, h) × (1 + g_pre80(h))^t

For 14 <= t <= 21  (ages 81–88):
    C(t, h) = C(0, h) × (1 + g_pre80(h))^13 × (1 + g_post80)^(t - 13)
```

Housing and adaptation outflows are unchanged:
```
H_owner(t, h)   = 0
H_renter(t, h)  = ann_rent_paid_h × (1 + REAL_INCOME_GROWTH)^(n_h + t)

A_owner(t, h)   = A   if t = 8 and household h is an owner,  else 0
A_renter(t, h)  = 0   for all t

Outflows(t, h)  = C(t, h) + H_owner_or_renter(t, h) + A_owner_or_renter(t, h)
```

Notes:
- The income-group split is applied at the cohort level (single median value), not at the owner/renter sub-group level. This is deliberate: applying separate medians within tenure would risk circularity, since tenure correlates strongly with income and the goal is to measure the wealth gap given tenure.
- The £27,000 figure is held in constant 2026 £ — no further uprating between 2026 and the year the household reaches 75. Since the figure itself is a present-day Habinteg estimate, this is internally consistent; if the analyst wants to project the adaptation cost in line with broader construction-cost inflation, that becomes a sensitivity scenario rather than the central case.
- Renters are assumed to access adaptations via the Disabled Facilities Grant or landlord-funded provision and bear no out-of-pocket cost, consistent with the standard UK rental-sector treatment of accessibility adaptations.
- The age-80 break-point reflects the IFS R209 finding that the inflection from rising to falling spending occurs around age 80. The transition is modelled as a step change rather than a smooth taper; a smooth-taper variant could be added as a sensitivity if desired.

### M4 — Liquid drawdown engine (financial first, then pension)

**Definition.** Each year, the household funds the gap between outflows and State Pension income by withdrawing from liquid wealth. Withdrawal order is financial wealth first, then pension wealth.

**Inputs.** Opening balances W_fin(t−1, h) and W_pen(t−1, h); real returns REAL_FINANCIAL_RETURN = 0.035, REAL_PENSION_GROWTH = 0.030; outflows from M3; income from M2.

**Estimation approach.** Apply this year's real return to the opening balance, then withdraw the gap. If financial is fully drawn down, the remaining gap comes from pension. If both are exhausted, the household is in deficit for the rest of the projection — track this as a binary flag and a cumulative deficit £ figure for diagnostics, but per the scoping decision, do not draw from property or physical wealth.

**Functional form.** For each year t = 1, …, 21:
```
Gap(t, h)        = max(Outflows(t, h) − SP_income(t, h), 0)
W_fin_open(t)    = W_fin(t−1, h) × (1 + REAL_FINANCIAL_RETURN)
W_pen_open(t)    = W_pen(t−1, h) × (1 + REAL_PENSION_GROWTH)

withdraw_fin(t)  = min(Gap(t, h), W_fin_open(t))
remaining_gap(t) = Gap(t, h) − withdraw_fin(t)
withdraw_pen(t)  = min(remaining_gap(t), W_pen_open(t))
unfunded(t, h)   = remaining_gap(t) − withdraw_pen(t)

W_fin(t, h)      = W_fin_open(t) − withdraw_fin(t)
W_pen(t, h)      = W_pen_open(t) − withdraw_pen(t)
```

`unfunded(t, h)` is recorded as a diagnostic — it tracks consumption-shortfall years. It does NOT propagate as a debt or reduce other wealth stocks (consistent with the "hold property to death" scoping decision).

### M5 — Illiquid asset growth (property and physical)

**Definition.** Property and physical wealth are held to age 88 and grow at their respective real rates.

**Inputs.** v4's REAL_HPI_GROWTH (CAGR of CPI-deflated UK house price index); v4's REAL_WEALTH_GROWTH (CAGR of CPI-deflated median household wealth).

**Estimation approach.** Lump-sum compounding from the age-67 opening balance.

**Functional form.** For each year t = 1, …, 21:
```
W_prop(t, h)  = W_prop(67, h) × (1 + REAL_HPI_GROWTH)^t       (owners only; 0 for renters)
W_phys(t, h)  = W_phys(67, h) × (1 + REAL_WEALTH_GROWTH)^t
```

(Computed via accumulation rather than re-compounding from year 67 each year, to keep the loop clean.)

### M6 — Terminal wealth at age 88

**Definition.** The headline metric. Total household wealth at the end of the lifespan horizon (t = 21), in 2026 £.

**Inputs.** All four post-retirement stock series from M4 and M5.

**Estimation approach.** Sum across the four wealth components. Produce a discounted version using the same 3.5% Green Book rate as v4, with discount horizon from the 2026 model year (i.e. the discount factor is `1 / (1 + DISCOUNT_RATE)^(n_h + 21)`, where n_h = years to retirement).

**Functional form.**
```
W_total(88, h)      = W_prop(88, h) + W_fin(88, h) + W_pen(88, h) + W_phys(88, h)
disc_factor_h       = 1 / (1 + 0.035)^(n_h + 21)
disc_W_total(88, h) = W_total(88, h) × disc_factor_h
```

Owner–renter gap at 88:
```
Gap_88_undisc = wmean(W_total(88), R8xshhwgt | owners)
              − wmean(W_total(88), R8xshhwgt | renters)

Gap_88_disc   = wmean(disc_W_total(88), R8xshhwgt | owners)
              − wmean(disc_W_total(88), R8xshhwgt | renters)
```

Median versions are also reported using v4's `wmedian()` function for robustness against the right tail.

### M7 — Lifespan decomposition

**Definition.** Decompose the lifespan owner–renter wealth gap at 88 into three channels analogous to v4's three-way decomposition, but extended to capture the additional 21 years of post-retirement dynamics.

**Inputs.** Per-household trajectories from M4 and M5; cohort means of consumption, housing cost, State Pension, returns.

**Estimation approach.** Three additive channels:

- **Channel A — Property capital gain (lifespan).** Owner's property wealth at age 88. This is M5's `W_prop(88)` averaged across owners — by construction zero for renters.

  ```
  Gap_A_lifespan = wmean(W_prop(88), R8xshhwgt | owners)
  ```

- **Channel B — Housing cost savings (lifespan).** The future value at age 88 of housing-cost savings accumulated over both pre-retirement (already captured in v4) and post-retirement (new). Post-retirement, owners pay £0 in recurring housing costs while renters pay rent, so the full rent is the annual saving; the one-off £27,000 adaptation cost in year 8 reduces the saving in that year.

  ```
  diff_t = H_renter(t, mean)                       for t ≠ 8
  diff_8 = max( H_renter(8, mean) − A, 0 )         (year-of-adaptation; A = £27,000)

  Gap_B_post = Σ_{t=1}^{21} diff_t × (1 + REAL_FINANCIAL_RETURN)^(21 − t)
  Gap_B_lifespan = Gap_B_retirement_v4 × (1 + REAL_FINANCIAL_RETURN)^21  +  Gap_B_post
  ```

  Where `Gap_B_retirement_v4` is v4's existing housing-cost-savings channel at age 67, rolled forward to age 88 at the financial return. If `H_renter(8, mean) < A`, the year-8 contribution to Gap_B is floored at zero (the adaptation cost wipes out the housing-cost advantage for that one year) and the residual `A − H_renter(8, mean)` is implicitly absorbed into Channel C as a negative adjustment, since C is computed as a residual.

- **Channel C — Income & endowment (residual).** Closes the identity:

  ```
  Gap_C_lifespan = Gap_88_undisc − Gap_A_lifespan − Gap_B_lifespan
  ```

  This captures all remaining wealth differences: higher pre-retirement income trajectories, larger starting endowments (gifts/inheritance), differential drawdown effects post-retirement, and any compositional effects.

**Functional form.** As above. Discounted versions apply the same percentage shares to `Gap_88_disc`, matching v4's convention.

### M8 — Subgroup breakdowns and sensitivity scenarios

**Definition.** Re-run the lifespan engine with v4's existing sensitivity overrides and produce the same subgroup splits.

**Inputs.** v4's `SCENARIO_OVERRIDES` dictionary; income decile, region, education breakdowns from v4.

**Estimation approach.** For each scenario:
1. Re-run v4 with the scenario overrides to produce age-67 wealth stocks (already done in v4).
2. Run the post-retirement engine (M2–M6) on the scenario's age-67 stocks.
3. Report Gap_88_undisc and Gap_88_disc per scenario.

For subgroup breakdowns, re-use v4's `gap_by_group()` helper applied to `W_total(88)` and `disc_W_total(88)` columns.

Additional lifespan-specific sensitivity scenarios to add to the v4 set:

| Scenario name | Overrides |
|---|---|
| Low adaptation cost (£15k) | `adapt_cost = 15000` |
| High adaptation cost (£40k) | `adapt_cost = 40000` |
| Earlier adaptation (age 70) | `adapt_age = 70` (event year shifts to t = 3) |
| Later adaptation (age 80) | `adapt_age = 80` (event year shifts to t = 13) |
| No adaptation cost | `adapt_cost = 0` (counterfactual; pure tenure-cost gap) |
| Lifespan short (age 85) | `lifespan_end = 85` (truncate loop at t = 18) |
| Lifespan long (age 91) | `lifespan_end = 91` (extend loop to t = 24) |
| State Pension flat (CPI-only) | `sp_real_growth = 0.000` |
| State Pension +1.0% real | `sp_real_growth = 0.010` |
| Legacy flat 1.2% consumption | Disable piecewise schedule; apply `g = 0.012` to all households for all 21 years |
| No income split (uniform consumption) | Apply +1.0% to all households ages 67–80, −0.5% ages 80–88 (drops the median split only) |
| Steeper 80+ decline | `g_post80 = -0.010` (matches IFS 1924–28 cohort point estimate) |
| Pooled liquid drawdown | Combine fin + pen at weighted return, withdraw proportionally |

## 7. Outputs

| Output | Format | Description |
|---|---|---|
| `lifespan_summary_table.csv` | CSV | Owner / renter means, medians, gaps (undiscounted & discounted) at ages 67 and 88. |
| `lifespan_trajectory.csv` | CSV | Annual wealth-component values for owners and renters, ages 67 → 88 (weighted means). |
| `lifespan_decomposition.csv` | CSV | Channels A / B / C at age 88, undiscounted and discounted. |
| `lifespan_by_decile.csv` | CSV | Gap at 88 by income decile (mean & median). |
| `lifespan_by_region.csv` | CSV | Gap at 88 by region. |
| `lifespan_by_education.csv` | CSV | Gap at 88 by degree-plus vs no-degree. |
| `lifespan_sensitivity.csv` | CSV | Gap at 88 across all scenarios (v4 + lifespan-specific). |
| `lifespan_trajectory_chart.png` | PNG | Stacked-area chart of wealth components over time, owners vs renters side-by-side. |
| `lifespan_deficit_diagnostic.csv` | CSV | Share of renter households entering deficit (unfunded > 0) by age, by income decile. |

## 8. Sense checks

**SC1 — Order-of-magnitude consistency with v4.** At age 67, lifespan-engine outputs at t = 0 should equal v4's outputs exactly (the engine should reproduce v4 numbers at retirement). This is a regression test on the hand-off in M1.

**SC2 — Property capital gain at 88 (back-of-envelope).** Mean v4 projected property value at age 67 ≈ £450k–£550k (in 2026 £, central scenario, owner cohort). Compounding for 21 years at v4's REAL_HPI_GROWTH (~1–1.5% real p.a.) gives a multiplier of ~1.23–1.37, so owners' average property wealth at 88 should land in roughly £560k–£750k. If the model produces values materially outside this band, investigate.

**SC3 — Renter financial-wealth depletion timeline.** At retirement, mean renter liquid wealth (fin + pen) in v4 is roughly £100k–£200k (2026 £). Under the IFS-calibrated central assumptions, State Pension covers ~£12.5k/yr per adult (≈£21k/household at 1.7 adults) growing at +0.5% real p.a.; renter consumption is flat-to-modestly-rising depending on the household's income group; rent at age 67 is in the range £10k–£20k and continues growing with `REAL_INCOME_GROWTH`. Average annual shortfall in the first decade of retirement should sit in the £8k–£20k range — a narrower band than under the legacy 1.2% flat-consumption assumption. With ~3% real growth on liquid balance, depletion timeline is roughly 8–15 years — i.e. many renter households should hit deficit between ages 75 and 82. The IFS refinements push the depletion-age band slightly later than the v1 of this note; if the model shows depletion ages before 73 or beyond 85, recheck the M2/M3 calibration and the income-group split.

**SC4 — Owner wealth dynamics.** Owners face no recurring housing cost in retirement and only one cost shock (the £27,000 at age 75). Most owners are in the above-median income group, so their consumption rises at +1.0% real p.a. up to age 80 — but they also benefit from rising State Pension (+0.5% real p.a.) and zero housing costs, so liquid wealth should still trend upward in real terms through the pre-75 period. After age 75 the trajectory should resume rising (step down then climb), and after age 80 the consumption decline should reinforce the upward path. A visible "step down" at age 75 in the trajectory chart is expected. If mean owner liquid wealth is falling in real terms before age 75 in the above-median sub-cohort, recheck `cons_cost` calibration — it is likely too high relative to State Pension income.

**SC5 — Cross-check with ONS Pensioner Income Series.** ONS PIS shows average pensioner gross income ~£30k–£35k (2024). State Pension (≈£12.5k × ~1.7 adults/household ≈ £21k) plus our modelled investment-income draw (rough order of magnitude) should bracket this figure. If our implied income for a representative retired owner sits far outside this range, the consumption-target rule may be overstating drawdown.

**SC6 — Decomposition adds to total.** A + B + C = Gap_88_undisc by construction. Verify numerically that the residual is ~0 (within rounding).

**SC7 — Mortality-anchor alternative.** As a Fermi cross-check, compute Gap_88 ignoring all post-67 dynamics except property growth (i.e. freeze fin / pen / phys at age 67, grow property at HPI to 88). The result is a hard floor on the property channel's contribution. Channel A in the full decomposition should not be larger than this hard floor.

## 9. Quality checks before delivery

- [ ] Each mechanism has an explicit functional form.
- [ ] All external sources are cited with URLs in §3.
- [ ] All non-source numerical assumptions are declared in §4.
- [ ] The top-down description in §5 makes the pipeline clear.
- [ ] Sense checks in §8 use genuinely independent reasoning.
- [ ] The approach reproduces v4 outputs exactly at t = 0 (regression test SC1).
- [ ] The decomposition identity holds numerically (SC6).
- [ ] Renter deficit timing and owner liquid dynamics pass plausibility checks (SC3, SC4).

## 10. Implementation notes (for the analyst writing the code)

The cleanest place to extend v4 is to add a single function `project_post_retirement(ftb_v4_output, **scenario_overrides)` that consumes the v4 output dataframe and appends new columns (`W_prop_88`, `W_fin_88`, `W_pen_88`, `W_phys_88`, `W_total_88`, `disc_W_total_88`, plus the trajectory dataframe). All v4 scenarios should be re-run through this function in the same loop that produces v4's existing sensitivity table.

Key implementation pitfalls:

1. **Discount horizon.** The Green Book factor must use `n_h + 21` years from the 2026 base, not 21 years from age 67 — the discounting is relative to the model start year, matching v4.
2. **Mortgage at retirement.** Verify (don't assume) that v4's mortgage payment schedule has finished by age 67 for the full cohort. If some households still have residual mortgage debt at 67, this needs explicit handling — either continued mortgage payments in retirement, or a mortgage-paid-off-at-67 truncation assumption that should be flagged as a model choice.
3. **Adaptation cost timing.** The £27,000 cost lands in year t = 8 (age 75). If the household's liquid wealth (financial + pension after that year's growth and normal outflows) is less than £27,000 in year 8, the drawdown engine must handle the shortfall the same way as any other gap: draw what's available from financial then pension, record the unfunded balance as a one-off `unfunded(8, h)` figure, and continue. The adaptation cost does NOT propagate into property or physical wealth — consistent with the "hold property to death" scoping decision.

4. **Cohort median for income split.** The IFS consumption schedule requires classifying each household as above- or below-median income. Compute the median **once** on the full FTB cohort using the survey-weighted version of `hh_net_income` (i.e. `wmedian(ftb['hh_net_income'], ftb['R8xshhwgt'])`), then assign the indicator to every household. Do NOT recompute the median within tenure sub-groups — applying separate medians within owners and renters would introduce circularity, since tenure correlates strongly with income and the goal of the analysis is to isolate the tenure effect.

5. **State Pension uprating compounding.** With +0.5% real p.a. for 21 years, the cumulative real uplift is (1.005)^21 ≈ 1.11 — i.e. State Pension at age 88 is ~11% higher in real terms than at age 67. This is an empirically large but historically supported uplift; flagged here because it materially changes the renter wealth depletion arithmetic relative to a flat-real central case.
4. **Number of adults per household.** Build `n_adults_h` from the WAS person file (`pp`), counting persons aged 16+ per `CASER8`. Cap at 2 for a conservative central case if multi-generational households appear in the cohort.
5. **Deflation of the State Pension rate.** The £241.30/week rate is the April 2026 uprated figure. Treat it as 2026 £ for consistency with the rest of the model. Strictly, calendar-year 2026 average prices differ from April 2026 prices, but the difference is small (<1%) and can be absorbed into the existing real-flat assumption.
