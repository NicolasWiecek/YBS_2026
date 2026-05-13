"""
WAS Round 8 – Owner–Renter Wealth Gap Over Lifespan (ages 67 → 88)
====================================================================
v1 – initial implementation of the post-retirement extension.

Method spec:
  ../../Methodologies/Projected_wealth_gap_at_retirement/projected_wealth_gap_over_lifespan_method_note.md

Pipeline:
  Stage 1 — runs v4 (Projected_wealth_gap_at_retirement) via runpy to obtain
            the age-67 wealth state per household.
  Stage 2 — post-retirement engine (M2-M6 of the method note):
              M2  State Pension income (+0.5% real p.a., per adult)
              M3  Outflows: target consumption (IFS R209 age- and income-
                  piecewise schedule) + housing (rent for renters, zero
                  for owners) + £27k adaptation at age 75 (owners)
              M4  Drawdown engine: financial first, then pension
              M5  Illiquid asset growth: property (HPI), physical
              M6  Terminal wealth at 88 (undiscounted + Green-Book discounted)
            Then M7 (lifespan three-way decomposition), subgroup breakdowns,
            sensitivity scenarios, and trajectory chart.

Outputs are written to ./outputs_lifespan_v1/.

Run:
    python was_wealth_gap_lifespan_v1.py
"""

# ── 0. Imports & path setup ───────────────────────────────────────────────────
import warnings
import os
import sys
import runpy
from pathlib import Path

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".matplotlib-cache"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ── 1. Run v4 to get age-67 wealth state per household ───────────────────────
V4_SCRIPT = (SCRIPT_DIR / ".." / "Projected_wealth_gap_at_retirement"
             / "was_wealth_gap_analysis_v4.py").resolve()

print("=" * 72)
print(" Stage 1 — Running v4 to obtain age-67 wealth state per household")
print(f"   v4 script: {V4_SCRIPT}")
print("=" * 72)

if not V4_SCRIPT.exists():
    raise FileNotFoundError(f"v4 script not found at {V4_SCRIPT}")

v4_ns = runpy.run_path(str(V4_SCRIPT), run_name="__main__")

# Extract objects we need from the v4 namespace
ftb = v4_ns['ftb']
pp = v4_ns['pp']
wmean = v4_ns['wmean']
wmedian = v4_ns['wmedian']
project_wealth = v4_ns['project_wealth']
SCENARIO_OVERRIDES_V4 = v4_ns['SCENARIO_OVERRIDES']

REAL_HPI_GROWTH = v4_ns['REAL_HPI_GROWTH']
REAL_FINANCIAL_RETURN = v4_ns['REAL_FINANCIAL_RETURN']
REAL_PENSION_GROWTH = v4_ns['REAL_PENSION_GROWTH']
REAL_INCOME_GROWTH = v4_ns['REAL_INCOME_GROWTH']
REAL_WEALTH_GROWTH = v4_ns['REAL_WEALTH_GROWTH']
DISCOUNT_RATE = v4_ns['DISCOUNT_RATE']

wt = "R8xshhwgt"  # WAS household cross-sectional weight

print("\n" + "=" * 72)
print(" Stage 2 — Post-retirement extension (ages 67 → 88)")
print("=" * 72)

# ── 2. Lifespan parameters ────────────────────────────────────────────────────
RETIREMENT_AGE = 67
LIFESPAN_END_AGE = 88
N_POST_RETIREMENT_YEARS = LIFESPAN_END_AGE - RETIREMENT_AGE  # 21

# State Pension (April 2026 weekly rate × 52), per adult
SP_PER_ADULT_2026 = 241.30 * 52   # £12,547.60 in 2026 £
SP_REAL_GROWTH = 0.005            # +0.5% real p.a. (central)

# Consumption schedule (IFS R209)
G_PRE80_ABOVE = 0.010   # +1.0% real p.a., above-median income, ages 67–80
G_PRE80_BELOW = 0.000   # 0.0% real p.a., below-median income, ages 67–80
G_POST80     = -0.005   # −0.5% real p.a., all households, ages 81–88
BREAK_AGE = 80          # transition age
T_BREAK = BREAK_AGE - RETIREMENT_AGE  # year index of break (=13)

# Pre-retirement consumption growth (matches v4)
CONSUMPTION_INFL_PRE_RET = v4_ns['CONSUMPTION_INFL']  # 0.012

# Home adaptation
ADAPT_COST = 27_000
ADAPT_AGE = 75
T_ADAPT = ADAPT_AGE - RETIREMENT_AGE  # =8

OUTPUT_DIR = SCRIPT_DIR / "outputs_lifespan_v1"
OUTPUT_DIR.mkdir(exist_ok=True)

print(f"\n  Lifespan parameters:")
print(f"    Retirement age            : {RETIREMENT_AGE}")
print(f"    Lifespan endpoint         : {LIFESPAN_END_AGE} "
      f"({N_POST_RETIREMENT_YEARS} years of post-retirement)")
print(f"    State Pension per adult   : £{SP_PER_ADULT_2026:,.2f} "
      f"(2026 £, +{SP_REAL_GROWTH*100:.1f}% real p.a.)")
print(f"    Consumption 67–80 (above) : +{G_PRE80_ABOVE*100:.1f}% real p.a.")
print(f"    Consumption 67–80 (below) : +{G_PRE80_BELOW*100:.1f}% real p.a.")
print(f"    Consumption 80–88 (all)   : {G_POST80*100:+.1f}% real p.a.")
print(f"    Adaptation cost (owners)  : £{ADAPT_COST:,} at age {ADAPT_AGE}")
print(f"    Discount rate (Green Bk)  : {DISCOUNT_RATE*100:.1f}% p.a.")

# ── 3. n_adults per household ────────────────────────────────────────────────
# Person file in WAS interviews all adults 16+ (excl. 16–18 in FT education).
# Count rows per CASER8 ≈ number of adults; cap at 2 for conservatism.
n_adults_per_hh = pp.groupby('CASER8').size().rename('n_adults_hh')
ftb = ftb.merge(n_adults_per_hh, on='CASER8', how='left')
ftb['n_adults_hh'] = ftb['n_adults_hh'].fillna(1).clip(upper=2).astype(float)
print(f"\n  Adults per household (capped at 2):")
print(f"    Weighted mean        : {wmean(ftb['n_adults_hh'], ftb[wt]):.2f}")
print(f"    Distribution         : {ftb['n_adults_hh'].value_counts().to_dict()}")

# ── 4. Cohort-median income for consumption-growth split ─────────────────────
cohort_median_income = wmedian(ftb['hh_net_income'], ftb[wt])
ftb['above_median_inc'] = (ftb['hh_net_income'] >= cohort_median_income).astype(int)
print(f"\n  Cohort median net HH income (2026 £): £{cohort_median_income:,.0f}")
print(f"  Above-median households: "
      f"{int(ftb['above_median_inc'].sum()):,} of {len(ftb):,}")
own_above = ftb[(ftb['tenure_binary']=='owner') & (ftb['above_median_inc']==1)].shape[0]
own_below = ftb[(ftb['tenure_binary']=='owner') & (ftb['above_median_inc']==0)].shape[0]
rnt_above = ftb[(ftb['tenure_binary']=='renter') & (ftb['above_median_inc']==1)].shape[0]
rnt_below = ftb[(ftb['tenure_binary']=='renter') & (ftb['above_median_inc']==0)].shape[0]
print(f"    Owners  – above/below median income: {own_above:,} / {own_below:,}")
print(f"    Renters – above/below median income: {rnt_above:,} / {rnt_below:,}")


# ── 5. Post-retirement engine ────────────────────────────────────────────────
def project_post_retirement(
    ftb_in,
    *,
    sp_real_growth=SP_REAL_GROWTH,
    g_pre80_above=G_PRE80_ABOVE,
    g_pre80_below=G_PRE80_BELOW,
    g_post80=G_POST80,
    adapt_cost=ADAPT_COST,
    adapt_age=ADAPT_AGE,
    lifespan_end=LIFESPAN_END_AGE,
    real_hpi=None,        # if None, use REAL_HPI_GROWTH
    real_fin_ret=None,    # if None, use REAL_FINANCIAL_RETURN
    real_pen_ret=None,
    real_wlt_grw=None,
    real_inc_grw=None,
    cons_infl_pre_ret=CONSUMPTION_INFL_PRE_RET,
    pool_liquid=False,
    return_trajectory=False,
    income_split=True,
):
    """
    Run the year-by-year post-retirement engine on the v4 output dataframe.

    Returns a dataframe with appended columns:
      W_prop_88, W_fin_88, W_pen_88, W_phys_88, W_total_88, disc_W_total_88,
      cumulative_unfunded, first_deficit_age.
    If return_trajectory=True, also returns the per-household × per-year arrays
    used for the trajectory chart and decomposition.
    """
    real_hpi = REAL_HPI_GROWTH if real_hpi is None else real_hpi
    real_fin_ret = REAL_FINANCIAL_RETURN if real_fin_ret is None else real_fin_ret
    real_pen_ret = REAL_PENSION_GROWTH if real_pen_ret is None else real_pen_ret
    real_wlt_grw = REAL_WEALTH_GROWTH if real_wlt_grw is None else real_wlt_grw
    real_inc_grw = REAL_INCOME_GROWTH if real_inc_grw is None else real_inc_grw

    d = ftb_in.copy()
    N = len(d)
    n_years = lifespan_end - RETIREMENT_AGE
    t_adapt = adapt_age - RETIREMENT_AGE
    t_break = BREAK_AGE - RETIREMENT_AGE

    is_owner   = (d['tenure_binary'] == 'owner').values
    above_med  = d['above_median_inc'].values.astype(bool) if income_split \
                 else np.ones(N, dtype=bool)
    n_adults   = d['n_adults_hh'].values.astype(float)
    n_h        = d['years_to_retirement'].values.astype(float)
    cons_2026  = d['cons_cost'].values.astype(float)
    rent_2026  = d['ann_rent_paid'].values.astype(float)
    W_prop_67  = d['proj_prop_wealth'].values.astype(float)
    W_fin_67   = d['proj_fin_wealth'].values.astype(float)
    W_pen_67   = d['proj_pen_wealth'].values.astype(float)
    W_phys_67  = d['proj_phys_wealth'].values.astype(float)

    # Anchor consumption at age 67 (v4 pre-retirement growth)
    C_67 = cons_2026 * (1 + cons_infl_pre_ret) ** n_h
    # Pre-80 growth rate per household (income-differentiated, or uniform)
    if income_split:
        g_pre80 = np.where(above_med, g_pre80_above, g_pre80_below)
    else:
        g_pre80 = np.full(N, g_pre80_above)

    # Storage arrays — index 0 = age 67, index n_years = age 88
    W_prop  = np.zeros((N, n_years + 1))
    W_fin   = np.zeros((N, n_years + 1))
    W_pen   = np.zeros((N, n_years + 1))
    W_phys  = np.zeros((N, n_years + 1))
    outflows = np.zeros((N, n_years + 1))
    sp_income = np.zeros((N, n_years + 1))
    unfunded  = np.zeros((N, n_years + 1))
    cons_arr  = np.zeros((N, n_years + 1))
    rent_arr  = np.zeros((N, n_years + 1))
    deficit_age = np.full(N, np.nan)

    # t=0 anchor (age 67)
    W_prop[:, 0] = np.where(is_owner, W_prop_67, 0.0)
    W_fin[:, 0]  = W_fin_67
    W_pen[:, 0]  = W_pen_67
    W_phys[:, 0] = W_phys_67

    for t in range(1, n_years + 1):
        # Stocks grow on opening balances
        W_prop[:, t] = np.where(is_owner, W_prop[:, t-1] * (1 + real_hpi), 0.0)
        W_phys[:, t] = W_phys[:, t-1] * (1 + real_wlt_grw)
        fin_open = W_fin[:, t-1] * (1 + real_fin_ret)
        pen_open = W_pen[:, t-1] * (1 + real_pen_ret)

        # Consumption (piecewise)
        if t <= t_break:
            C_t = C_67 * (1 + g_pre80) ** t
        else:
            C_t = C_67 * (1 + g_pre80) ** t_break * (1 + g_post80) ** (t - t_break)

        # Housing
        H_renter_t = rent_2026 * (1 + real_inc_grw) ** (n_h + t)
        H_t = np.where(is_owner, 0.0, H_renter_t)

        # Adaptation (year of event only, owners only)
        A_t = np.where((t == t_adapt) & is_owner, adapt_cost, 0.0)

        Outflows_t = C_t + H_t + A_t
        SP_t = n_adults * SP_PER_ADULT_2026 * (1 + sp_real_growth) ** t
        gap_t = np.maximum(Outflows_t - SP_t, 0.0)

        # Drawdown
        if pool_liquid:
            liquid_open = fin_open + pen_open
            withdraw = np.minimum(gap_t, liquid_open)
            unfunded_t = gap_t - withdraw
            ratio = np.where(liquid_open > 0,
                             fin_open / np.maximum(liquid_open, 1e-9), 0.5)
            closing = liquid_open - withdraw
            W_fin[:, t] = closing * ratio
            W_pen[:, t] = closing * (1 - ratio)
        else:
            wd_fin = np.minimum(gap_t, fin_open)
            remaining = gap_t - wd_fin
            wd_pen = np.minimum(remaining, pen_open)
            unfunded_t = remaining - wd_pen
            W_fin[:, t] = fin_open - wd_fin
            W_pen[:, t] = pen_open - wd_pen

        outflows[:, t]  = Outflows_t
        sp_income[:, t] = SP_t
        unfunded[:, t]  = unfunded_t
        cons_arr[:, t]  = C_t
        rent_arr[:, t]  = H_t

        newly = (unfunded_t > 0) & np.isnan(deficit_age)
        deficit_age = np.where(newly, RETIREMENT_AGE + t, deficit_age)

    # Terminal
    W_prop_88 = W_prop[:, n_years]
    W_fin_88  = W_fin[:, n_years]
    W_pen_88  = W_pen[:, n_years]
    W_phys_88 = W_phys[:, n_years]
    W_total_88 = W_prop_88 + W_fin_88 + W_pen_88 + W_phys_88
    disc_factor = 1.0 / (1 + DISCOUNT_RATE) ** (n_h + n_years)
    disc_W_total_88 = W_total_88 * disc_factor

    d['W_prop_88']           = W_prop_88
    d['W_fin_88']            = W_fin_88
    d['W_pen_88']            = W_pen_88
    d['W_phys_88']           = W_phys_88
    d['W_total_88']          = W_total_88
    d['disc_W_total_88']     = disc_W_total_88
    d['cumulative_unfunded'] = unfunded.sum(axis=1)
    d['first_deficit_age']   = deficit_age

    if return_trajectory:
        return (d, dict(
            W_prop=W_prop, W_fin=W_fin, W_pen=W_pen, W_phys=W_phys,
            outflows=outflows, sp_income=sp_income, unfunded=unfunded,
            consumption=cons_arr, rent=rent_arr,
            n_years=n_years,
        ))
    return d


# ── 6. Run central scenario & print summary ──────────────────────────────────
print("\n" + "=" * 72)
print(" Central scenario — IFS R209 calibration")
print("=" * 72)

ftb_88, traj = project_post_retirement(ftb, return_trajectory=True)
owners  = ftb_88[ftb_88['tenure_binary'] == 'owner']
renters = ftb_88[ftb_88['tenure_binary'] == 'renter']

def print_wealth_table(label_67_v4, label_88_new, owners_df, renters_df, weight=wt):
    print(f"  {'Component':<12} "
          f"{'Owners@67':>12} {'Renters@67':>12} {'Gap@67':>12}  |  "
          f"{'Owners@88':>12} {'Renters@88':>12} {'Gap@88':>12}")
    for lbl, c67, c88 in [
        ("Property",  "proj_prop_wealth",  "W_prop_88"),
        ("Financial", "proj_fin_wealth",   "W_fin_88"),
        ("Pension",   "proj_pen_wealth",   "W_pen_88"),
        ("Physical",  "proj_phys_wealth",  "W_phys_88"),
    ]:
        o67 = wmean(owners_df[c67],  owners_df[weight])
        r67 = wmean(renters_df[c67], renters_df[weight])
        o88 = wmean(owners_df[c88],  owners_df[weight])
        r88 = wmean(renters_df[c88], renters_df[weight])
        print(f"  {lbl:<12} £{o67:>11,.0f} £{r67:>11,.0f} £{o67-r67:>11,.0f}  |  "
              f"£{o88:>11,.0f} £{r88:>11,.0f} £{o88-r88:>11,.0f}")
    o67 = wmean(owners_df['proj_total_wealth'],  owners_df[weight])
    r67 = wmean(renters_df['proj_total_wealth'], renters_df[weight])
    o88 = wmean(owners_df['W_total_88'],  owners_df[weight])
    r88 = wmean(renters_df['W_total_88'], renters_df[weight])
    print(f"  {'TOTAL':<12} £{o67:>11,.0f} £{r67:>11,.0f} £{o67-r67:>11,.0f}  |  "
          f"£{o88:>11,.0f} £{r88:>11,.0f} £{o88-r88:>11,.0f}")

print()
print_wealth_table("@67 (v4)", "@88 (new)", owners, renters)

# Headline gaps
o67  = wmean(owners['proj_total_wealth'],  owners[wt])
r67  = wmean(renters['proj_total_wealth'], renters[wt])
o88  = wmean(owners['W_total_88'],         owners[wt])
r88  = wmean(renters['W_total_88'],        renters[wt])
o88d = wmean(owners['disc_W_total_88'],    owners[wt])
r88d = wmean(renters['disc_W_total_88'],   renters[wt])
o67d = wmean(owners['disc_total_wealth'],  owners[wt])
r67d = wmean(renters['disc_total_wealth'], renters[wt])

gap_67       = o67  - r67
gap_88       = o88  - r88
gap_67_disc  = o67d - r67d
gap_88_disc  = o88d - r88d

print(f"\n  ► GAP (mean, 2026 £):")
print(f"      @67 undiscounted  : £{gap_67:>14,.0f}")
print(f"      @67 discounted    : £{gap_67_disc:>14,.0f}")
print(f"      @88 undiscounted  : £{gap_88:>14,.0f}")
print(f"      @88 discounted    : £{gap_88_disc:>14,.0f}")
print(f"      Δ @88 vs @67 (un) : £{gap_88-gap_67:>14,.0f}  ({(gap_88/gap_67-1)*100:+.1f}%)")

# Median gaps
med_o67 = wmedian(owners['proj_total_wealth'], owners[wt])
med_r67 = wmedian(renters['proj_total_wealth'], renters[wt])
med_o88 = wmedian(owners['W_total_88'], owners[wt])
med_r88 = wmedian(renters['W_total_88'], renters[wt])
print(f"\n  ► GAP (median, 2026 £):")
print(f"      @67 undiscounted  : £{med_o67-med_r67:>14,.0f}")
print(f"      @88 undiscounted  : £{med_o88-med_r88:>14,.0f}")

# Deficit diagnostics
share_renter_def = (renters['first_deficit_age'].notna()).sum() / len(renters)
share_owner_def  = (owners['first_deficit_age'].notna()).sum() / len(owners)
mean_age_renter  = renters['first_deficit_age'].mean()
mean_age_owner   = owners['first_deficit_age'].mean()
print(f"\n  ► Deficit diagnostics (households running out of liquid wealth before 88):")
print(f"      Renter households in deficit : {share_renter_def*100:.1f}%  "
      f"(mean first-deficit age: {mean_age_renter:.1f})")
print(f"      Owner households in deficit  : {share_owner_def*100:.1f}%  "
      f"(mean first-deficit age: {mean_age_owner:.1f})")

# ── 7. Lifespan decomposition (M7) ───────────────────────────────────────────
print("\n" + "=" * 72)
print(" Lifespan three-way decomposition (M7)")
print("=" * 72)

# Channel A — Property capital gain at 88 (owners only)
gap_A = wmean(owners['W_prop_88'], owners[wt])

# Channel B — Housing cost savings (lifespan)
# Pre-retirement portion: re-use v4's existing computation by re-running
# v4's channel B with v4's own functions; v4 stored these in scope.
# We can re-derive using the same logic as v4 (Step 9 in v4).
fv_annuity = v4_ns['fv_annuity']
fv_lumpsum = v4_ns['fv_lumpsum']

owner_hcost_mean_pre   = wmean(owners['avg_housing_cost'],  owners[wt])
renter_hcost_mean_pre  = wmean(renters['avg_housing_cost'], renters[wt])
n_owner_ret  = wmean(owners['years_to_retirement'],  owners[wt])
n_renter_ret = wmean(renters['years_to_retirement'], renters[wt])
mort_term_mean = wmean(owners['mort_years_remaining'], owners[wt])
mort_active_mean = min(mort_term_mean, n_owner_ret)
post_mort_mean   = max(n_owner_ret - mort_active_mean, 0)

hcost_diff_during = max(renter_hcost_mean_pre - owner_hcost_mean_pre, 0)
fv_during        = fv_annuity(hcost_diff_during, REAL_FINANCIAL_RETURN, mort_active_mean)
fv_during_to_ret = fv_lumpsum(fv_during, REAL_FINANCIAL_RETURN, post_mort_mean)
fv_post          = fv_annuity(renter_hcost_mean_pre, REAL_FINANCIAL_RETURN, post_mort_mean)
gap_B_pre        = float(np.sum(fv_during_to_ret) + np.sum(fv_post))

# Roll forward to age 88 at financial return
gap_B_pre_to_88 = gap_B_pre * (1 + REAL_FINANCIAL_RETURN) ** N_POST_RETIREMENT_YEARS

# Post-retirement portion: owner pays £0 housing, renter pays rent.
# Year 8 has the £27k adaptation, which offsets the saving in that year.
renter_rent_year_t = np.array([
    wmean(pd.Series(traj['rent'][:, t][ftb_88['tenure_binary'] == 'renter']),
          renters[wt])
    for t in range(N_POST_RETIREMENT_YEARS + 1)
])  # mean rent for renter cohort each year, ages 67..88

diffs = renter_rent_year_t.copy()
diffs[T_ADAPT] = max(diffs[T_ADAPT] - ADAPT_COST, 0)
gap_B_post = 0.0
for t in range(1, N_POST_RETIREMENT_YEARS + 1):
    gap_B_post += diffs[t] * (1 + REAL_FINANCIAL_RETURN) ** (N_POST_RETIREMENT_YEARS - t)

gap_B = gap_B_pre_to_88 + gap_B_post

# Channel C — Income & endowment residual
gap_C = gap_88 - gap_A - gap_B

print(f"\n  Undiscounted (2026 £, lifespan gap at age 88):")
print(f"  A. Property capital gain         : £{gap_A:>14,.0f}  ({gap_A/gap_88*100:5.1f}%)")
print(f"  B. Housing cost savings (pre+post): £{gap_B:>14,.0f}  ({gap_B/gap_88*100:5.1f}%)")
print(f"      └ pre-retirement (rolled fwd)  : £{gap_B_pre_to_88:>14,.0f}")
print(f"      └ post-retirement (net adapt)  : £{gap_B_post:>14,.0f}")
print(f"  C. Income & endowment residual   : £{gap_C:>14,.0f}  ({gap_C/gap_88*100:5.1f}%)")
print(f"  TOTAL                            : £{gap_88:>14,.0f}  (100.0%)")

# ── 8. Annual trajectory (cohort weighted means) ─────────────────────────────
print("\n" + "=" * 72)
print(" Annual wealth trajectory (weighted means by tenure)")
print("=" * 72)

is_owner_mask = (ftb_88['tenure_binary'] == 'owner').values
is_renter_mask = ~is_owner_mask

def cohort_mean_at_t(arr, mask):
    w = ftb_88.loc[mask, wt].values
    return np.array([np.average(arr[mask, t], weights=w)
                     for t in range(arr.shape[1])])

ages = np.arange(RETIREMENT_AGE, LIFESPAN_END_AGE + 1)
traj_rows = []
for tenure, mask in [("owner", is_owner_mask), ("renter", is_renter_mask)]:
    prop = cohort_mean_at_t(traj['W_prop'], mask)
    fin  = cohort_mean_at_t(traj['W_fin'],  mask)
    pen  = cohort_mean_at_t(traj['W_pen'],  mask)
    phys = cohort_mean_at_t(traj['W_phys'], mask)
    tot  = prop + fin + pen + phys
    for i, age in enumerate(ages):
        traj_rows.append(dict(age=age, tenure=tenure,
                              W_prop=prop[i], W_fin=fin[i],
                              W_pen=pen[i], W_phys=phys[i], W_total=tot[i]))
traj_df = pd.DataFrame(traj_rows)

# Show key ages
print(f"\n  Owner cohort mean total wealth (2026 £):")
for age in [67, 70, 75, 80, 85, 88]:
    v = traj_df.query("tenure == 'owner' and age == @age")['W_total'].values[0]
    print(f"    Age {age}: £{v:>14,.0f}")
print(f"\n  Renter cohort mean total wealth (2026 £):")
for age in [67, 70, 75, 80, 85, 88]:
    v = traj_df.query("tenure == 'renter' and age == @age")['W_total'].values[0]
    print(f"    Age {age}: £{v:>14,.0f}")

# ── 9. Subgroup breakdowns at age 88 ─────────────────────────────────────────
print("\n" + "=" * 72)
print(" Subgroup breakdowns at age 88")
print("=" * 72)

def gap_by_group(df, group_col, weight=wt, min_n=10):
    rows = []
    for grp, sub in df.groupby(group_col, observed=True):
        o = sub[sub['tenure_binary'] == 'owner']
        r = sub[sub['tenure_binary'] == 'renter']
        if len(o) < min_n or len(r) < min_n:
            continue
        ow = wmean(o['W_total_88'], o[weight])
        rw = wmean(r['W_total_88'], r[weight])
        ow_med = wmedian(o['W_total_88'], o[weight])
        rw_med = wmedian(r['W_total_88'], r[weight])
        ow_d = wmean(o['disc_W_total_88'], o[weight])
        rw_d = wmean(r['disc_W_total_88'], r[weight])
        rows.append(dict(group=grp, owner_wealth_88=ow, renter_wealth_88=rw,
                         gap_88=ow-rw,
                         owner_wealth_88_med=ow_med, renter_wealth_88_med=rw_med,
                         gap_88_med=ow_med-rw_med,
                         owner_wealth_88_disc=ow_d, renter_wealth_88_disc=rw_d,
                         gap_88_disc=ow_d-rw_d,
                         n_owners=len(o), n_renters=len(r)))
    return pd.DataFrame(rows)

# Use the same decile boundaries as v4
decile_edges = np.nanpercentile(ftb_88['hh_net_income'].dropna(),
                                np.arange(0, 101, 10))
def decile_label(i):
    return f"D{i} (£{decile_edges[i-1]:,.0f}–£{decile_edges[i]:,.0f})"

ftb_88['income_decile_lbl'] = pd.qcut(
    ftb_88['hh_net_income'].rank(method='first'), 10,
    labels=[decile_label(i) for i in range(1, 11)])

gap_decile = gap_by_group(ftb_88, 'income_decile_lbl', min_n=5)
gap_region = gap_by_group(ftb_88, 'region_name')
gap_educ   = gap_by_group(ftb_88, 'degree_plus')
gap_educ['group'] = gap_educ['group'].map({0: 'No degree', 1: 'Degree+'})

print(f"\n  By income decile (n=5+ minimum each side):")
print(f"  {'Decile':<28} {'Owner@88':>12} {'Renter@88':>12} {'Gap@88':>12}")
print("  " + "-" * 70)
for _, row in gap_decile.iterrows():
    print(f"  {str(row['group']):<28} £{row['owner_wealth_88']:>11,.0f} "
          f"£{row['renter_wealth_88']:>11,.0f} £{row['gap_88']:>11,.0f}")

print(f"\n  By region (sorted by undiscounted gap):")
print(f"  {'Region':<22} {'Owner@88':>12} {'Renter@88':>12} {'Gap@88':>12}")
for _, row in gap_region.sort_values('gap_88', ascending=False).iterrows():
    print(f"  {str(row['group']):<22} £{row['owner_wealth_88']:>11,.0f} "
          f"£{row['renter_wealth_88']:>11,.0f} £{row['gap_88']:>11,.0f}")

print(f"\n  By education:")
print(f"  {'Education':<14} {'Owner@88':>12} {'Renter@88':>12} {'Gap@88':>12}")
for _, row in gap_educ.iterrows():
    print(f"  {str(row['group']):<14} £{row['owner_wealth_88']:>11,.0f} "
          f"£{row['renter_wealth_88']:>11,.0f} £{row['gap_88']:>11,.0f}")

# ── 10. Sensitivity scenarios ────────────────────────────────────────────────
print("\n" + "=" * 72)
print(" Sensitivity scenarios (re-run end-to-end)")
print("=" * 72)

# Each scenario specifies overrides applied to the post-retirement engine;
# the v4 inputs are unchanged from the central run (we keep age-67 stocks fixed).
# v4 SCENARIO_OVERRIDES re-runs require re-running the full v4 pipeline with
# new growth rates and are handled separately below by re-calling project_wealth().

# Scenarios that only override post-retirement params (no v4 re-run needed)
post_only_scenarios = {
    "Central (IFS-calibrated)": {},
    "Low adaptation cost (£15k)": dict(adapt_cost=15_000),
    "High adaptation cost (£40k)": dict(adapt_cost=40_000),
    "Earlier adaptation (age 70)": dict(adapt_age=70),
    "Later adaptation (age 80)":   dict(adapt_age=80),
    "No adaptation cost":          dict(adapt_cost=0),
    "Lifespan short (age 85)":     dict(lifespan_end=85),
    "Lifespan long (age 91)":      dict(lifespan_end=91),
    "State Pension flat (CPI-only)": dict(sp_real_growth=0.0),
    "State Pension +1.0% real":      dict(sp_real_growth=0.010),
    "Legacy flat 1.2% consumption":  dict(g_pre80_above=0.012, g_pre80_below=0.012,
                                          g_post80=0.012, income_split=False),
    "No income split (uniform cons.)": dict(income_split=False),
    "Steeper 80+ decline":           dict(g_post80=-0.010),
    "Pooled liquid drawdown":        dict(pool_liquid=True),
}

# v4-derived scenarios (re-run v4 with overrides then post-retirement)
def run_v4_then_lifespan(v4_overrides):
    zg = v4_overrides.pop('zero_gifts', False) if isinstance(v4_overrides, dict) else False
    kw = {"real_hpi": REAL_HPI_GROWTH, "real_fin_ret": REAL_FINANCIAL_RETURN,
          "real_pen_ret": REAL_PENSION_GROWTH, "real_inc_grw": REAL_INCOME_GROWTH,
          "real_wlt_grw": REAL_WEALTH_GROWTH, "real_rent_grw": 0.0,
          **(v4_overrides or {})}
    ftb_scn = project_wealth(ftb.copy(), zero_gifts=zg, **kw)
    # Merge in n_adults_hh and above_median_inc which were added after v4 run
    if 'n_adults_hh' not in ftb_scn.columns:
        ftb_scn = ftb_scn.merge(n_adults_per_hh, on='CASER8', how='left')
        ftb_scn['n_adults_hh'] = ftb_scn['n_adults_hh'].fillna(1).clip(upper=2).astype(float)
    ftb_scn['above_median_inc'] = (ftb_scn['hh_net_income'] >= cohort_median_income).astype(int)
    # Map v4 growth-rate overrides into the post-retirement engine where applicable
    pr_kw = {}
    if 'real_hpi' in kw: pr_kw['real_hpi'] = kw['real_hpi']
    if 'real_fin_ret' in kw: pr_kw['real_fin_ret'] = kw['real_fin_ret']
    if 'real_pen_ret' in kw: pr_kw['real_pen_ret'] = kw['real_pen_ret']
    if 'real_inc_grw' in kw: pr_kw['real_inc_grw'] = kw['real_inc_grw']
    if 'real_wlt_grw' in kw: pr_kw['real_wlt_grw'] = kw['real_wlt_grw']
    return project_post_retirement(ftb_scn, **pr_kw)

sens_rows = []
print(f"\n  {'Scenario':<38} {'Gap@67':>14} {'Gap@88':>14} {'Δ vs central':>14}")
print("  " + "-" * 80)

# Run post-only scenarios
central_gap_88 = None
for name, overrides in post_only_scenarios.items():
    ftb_scn = project_post_retirement(ftb, **overrides)
    o = ftb_scn[ftb_scn['tenure_binary'] == 'owner']
    r = ftb_scn[ftb_scn['tenure_binary'] == 'renter']
    g67 = wmean(o['proj_total_wealth'], o[wt]) - wmean(r['proj_total_wealth'], r[wt])
    g88 = wmean(o['W_total_88'], o[wt])        - wmean(r['W_total_88'], r[wt])
    g88_disc = wmean(o['disc_W_total_88'], o[wt]) - wmean(r['disc_W_total_88'], r[wt])
    if central_gap_88 is None:
        central_gap_88 = g88
    delta = g88 - central_gap_88
    sens_rows.append(dict(scenario=name, gap_67=g67, gap_88=g88,
                          gap_88_disc=g88_disc, delta_vs_central=delta))
    print(f"  {name:<38} £{g67:>12,.0f}  £{g88:>12,.0f}  £{delta:>12,.0f}")

# Run v4-pipeline scenarios
for name, overrides in SCENARIO_OVERRIDES_V4.items():
    if name == "Central":
        continue  # already covered
    ftb_scn = run_v4_then_lifespan(dict(overrides))
    o = ftb_scn[ftb_scn['tenure_binary'] == 'owner']
    r = ftb_scn[ftb_scn['tenure_binary'] == 'renter']
    g67 = wmean(o['proj_total_wealth'], o[wt]) - wmean(r['proj_total_wealth'], r[wt])
    g88 = wmean(o['W_total_88'], o[wt])        - wmean(r['W_total_88'], r[wt])
    g88_disc = wmean(o['disc_W_total_88'], o[wt]) - wmean(r['disc_W_total_88'], r[wt])
    delta = g88 - central_gap_88
    label = f"v4: {name}"
    sens_rows.append(dict(scenario=label, gap_67=g67, gap_88=g88,
                          gap_88_disc=g88_disc, delta_vs_central=delta))
    print(f"  {label:<38} £{g67:>12,.0f}  £{g88:>12,.0f}  £{delta:>12,.0f}")

sens_df = pd.DataFrame(sens_rows)

# ── 11. Deficit diagnostic by income decile ──────────────────────────────────
deficit_diag = ftb_88.copy()
deficit_diag['in_deficit'] = deficit_diag['first_deficit_age'].notna().astype(int)
deficit_by_decile = (deficit_diag
                     .groupby(['income_decile_lbl', 'tenure_binary'], observed=True)
                     .apply(lambda g: pd.Series(dict(
                         n=len(g),
                         share_in_deficit=g['in_deficit'].mean(),
                         mean_first_deficit_age=g['first_deficit_age'].mean(),
                     )))
                     .reset_index())

# ── 12. Save outputs ─────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print(" Saving outputs")
print("=" * 72)

# Summary table
summary_rows = []
for label, col_67, col_88 in [
    ("Property",  "proj_prop_wealth",  "W_prop_88"),
    ("Financial", "proj_fin_wealth",   "W_fin_88"),
    ("Pension",   "proj_pen_wealth",   "W_pen_88"),
    ("Physical",  "proj_phys_wealth",  "W_phys_88"),
    ("Total",     "proj_total_wealth", "W_total_88"),
]:
    o67  = wmean(owners[col_67],  owners[wt])
    r67  = wmean(renters[col_67], renters[wt])
    o88  = wmean(owners[col_88],  owners[wt])
    r88  = wmean(renters[col_88], renters[wt])
    summary_rows.append(dict(component=label,
                             owner_at_67=o67, renter_at_67=r67, gap_67=o67-r67,
                             owner_at_88=o88, renter_at_88=r88, gap_88=o88-r88))
summary_rows.append(dict(component='Total (discounted)',
                         owner_at_67=o67d, renter_at_67=r67d, gap_67=o67d-r67d,
                         owner_at_88=o88d, renter_at_88=r88d, gap_88=o88d-r88d))
summary_rows.append(dict(component='Total (median)',
                         owner_at_67=med_o67, renter_at_67=med_r67, gap_67=med_o67-med_r67,
                         owner_at_88=med_o88, renter_at_88=med_r88, gap_88=med_o88-med_r88))
summary_df = pd.DataFrame(summary_rows)
summary_df.to_csv(OUTPUT_DIR / "lifespan_summary_table.csv", index=False)

# Trajectory
traj_df.to_csv(OUTPUT_DIR / "lifespan_trajectory.csv", index=False)

# Decomposition
decomp_df = pd.DataFrame([
    dict(channel='A. Property capital gain',     value=gap_A, share=gap_A/gap_88),
    dict(channel='B. Housing cost savings',      value=gap_B, share=gap_B/gap_88),
    dict(channel='  B.1 pre-retirement (rolled)', value=gap_B_pre_to_88, share=gap_B_pre_to_88/gap_88),
    dict(channel='  B.2 post-retirement (net adapt)', value=gap_B_post, share=gap_B_post/gap_88),
    dict(channel='C. Income & endowment residual', value=gap_C, share=gap_C/gap_88),
    dict(channel='TOTAL',                         value=gap_88, share=1.0),
])
decomp_df.to_csv(OUTPUT_DIR / "lifespan_decomposition.csv", index=False)

# Subgroups
gap_decile.to_csv(OUTPUT_DIR / "lifespan_by_decile.csv", index=False)
gap_region.to_csv(OUTPUT_DIR / "lifespan_by_region.csv", index=False)
gap_educ.to_csv(OUTPUT_DIR / "lifespan_by_education.csv", index=False)

# Sensitivity
sens_df.to_csv(OUTPUT_DIR / "lifespan_sensitivity.csv", index=False)

# Deficit diagnostic
deficit_by_decile.to_csv(OUTPUT_DIR / "lifespan_deficit_diagnostic.csv", index=False)

# ── 13. Trajectory chart ─────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
for ax, tenure in zip(axes, ['owner', 'renter']):
    sub = traj_df[traj_df['tenure'] == tenure].set_index('age')
    components = ['W_prop', 'W_pen', 'W_fin', 'W_phys']
    colors = ['#1f77b4', '#2ca02c', '#ff7f0e', '#9467bd']
    labels = ['Property', 'Pension', 'Financial', 'Physical']
    ax.stackplot(sub.index, [sub[c]/1e3 for c in components],
                 labels=labels, colors=colors, alpha=0.85)
    ax.set_title(f'{tenure.title()}s — mean wealth trajectory', fontsize=12)
    ax.set_xlabel('Age')
    ax.set_ylabel('Wealth (£ thousand, 2026 prices)')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'£{x:,.0f}k'))
    ax.axvline(ADAPT_AGE, color='grey', linestyle='--', linewidth=0.8, alpha=0.7,
               label=f'Age {ADAPT_AGE} adaptation')
    ax.axvline(BREAK_AGE, color='black', linestyle=':', linewidth=0.8, alpha=0.5,
               label=f'Age {BREAK_AGE} consumption break')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(alpha=0.3)
plt.suptitle('Owner vs renter wealth trajectory in retirement (IFS R209-calibrated central)',
             fontsize=13)
plt.tight_layout()
chart_path = OUTPUT_DIR / "lifespan_trajectory_chart.png"
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close(fig)

print(f"\n  Outputs written to: {OUTPUT_DIR}")
for f in sorted(OUTPUT_DIR.iterdir()):
    print(f"    {f.name}")

print("\n" + "=" * 72)
print(" Done.")
print("=" * 72)
