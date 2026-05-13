"""
WAS Round 8 – Owner–Renter Wealth Gap Over Lifespan (ages 67 → 88)
====================================================================
v2 – streamlined single-file implementation.

This script inlines v4's data-loading + projection-to-retirement logic and adds
the post-retirement extension. It uses `usecols` when reading WAS .tab files so
it loads ~20 columns instead of ~4000, making the whole pipeline run in well
under a minute (compared to runpy-loading v4 in full).

Method spec:
  ../../Methodologies/Projected_wealth_gap_at_retirement/projected_wealth_gap_over_lifespan_method_note.md

Outputs are written to ./outputs_lifespan_v2/.

Run:
    python was_wealth_gap_lifespan_v2.py
"""

import warnings, os, sys, time
from pathlib import Path
warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", "/tmp/mpl-cache")
Path("/tmp/mpl-cache").mkdir(exist_ok=True)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from sklearn.linear_model import LinearRegression

T0 = time.time()

# ── Paths ─────────────────────────────────────────────────────────────────────
def find_project_root(start_dir):
    for p in (start_dir, *start_dir.parents):
        if (p / "source_data").is_dir():
            return p
    return start_dir

PROJECT_ROOT    = find_project_root(SCRIPT_DIR)
SOURCE_DATA_DIR = PROJECT_ROOT / "source_data"
WAS_DIR         = SOURCE_DATA_DIR / "WAS_data"
HHOLD_PATH      = WAS_DIR / "was_round_8_hhold.tab"
PERSON_PATH     = WAS_DIR / "was_round_8_person.tab"
CONSUMP_PATH    = SOURCE_DATA_DIR / "Consumption_deciles_split_owners_renters_weekly.csv"
HP_PATH         = SOURCE_DATA_DIR / "UK average house price data.xlsx"
WEALTH_PATH     = SOURCE_DATA_DIR / "Median household wealth.xlsx"
INCOME_PATH     = SOURCE_DATA_DIR / "Disposable income per head .xlsx"
CPI_PATH        = SOURCE_DATA_DIR / "CPI_Inflation.csv"

OUTPUT_DIR = SCRIPT_DIR / "outputs_lifespan_v2"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Model parameters (matched to v4) ─────────────────────────────────────────
RETIREMENT_AGE        = 67
SURVEY_YEAR           = 2021
MODEL_START_YEAR      = 2026
PENSION_CONT_RATE     = 0.08
CONSUMPTION_INFL      = 0.012
FALLBACK_MORT_RATE    = 0.050
DEFAULT_MORT_TERM     = 25
MORT_FLOOR_LONDON     = 317 * 52
MORT_FLOOR_OTHER      = 209 * 52
MORT_FLOOR_MIN        = 6_000
RENT_RATIO_PRIVATE    = 0.34
RENT_RATIO_SOCIAL     = 0.264
REAL_FINANCIAL_RETURN = 0.035
REAL_PENSION_GROWTH   = 0.030
DISCOUNT_RATE         = 0.035
AGE_BAND_MIDPOINTS_17 = {7: 32, 8: 37}
REGION_MAP = {1:"North East",2:"North West",4:"East Midlands",5:"West Midlands",
              6:"East of England",7:"London",8:"South East",9:"South West",
              10:"Wales",11:"Scotland",12:"Northern Ireland"}

# ── Lifespan-extension parameters ────────────────────────────────────────────
LIFESPAN_END_AGE = 88
N_POST_YRS       = LIFESPAN_END_AGE - RETIREMENT_AGE
SP_PER_ADULT_2026 = 241.30 * 52
SP_REAL_GROWTH    = 0.005
G_PRE80_ABOVE     = 0.010
G_PRE80_BELOW     = 0.000
G_POST80          = -0.005
BREAK_AGE         = 80
T_BREAK           = BREAK_AGE - RETIREMENT_AGE
ADAPT_COST        = 27_000
ADAPT_AGE         = 75
T_ADAPT           = ADAPT_AGE - RETIREMENT_AGE

# ── Helper functions ─────────────────────────────────────────────────────────
def wmean(s, w):
    m = s.notna() & w.notna() & (w > 0)
    if m.sum() == 0: return np.nan
    return float(np.average(s[m], weights=w[m]))

def wmedian(s, w):
    s = s.dropna(); w = w.loc[s.index].fillna(0)
    valid = w > 0
    s, w = s[valid].values, w[valid].values
    if len(s) == 0: return np.nan
    idx = np.argsort(s); s, w = s[idx], w[idx]
    cumw = np.cumsum(w)
    return float(s[np.searchsorted(cumw, cumw[-1] / 2.0)])

def fv_annuity(payment, rate, n):
    if n <= 0 or payment <= 0: return 0.0
    if rate == 0: return payment * n
    return float(payment * ((1 + rate)**n - 1) / rate)

def fv_lumpsum(value, rate, n):
    return np.asarray(value, dtype=float) * (1 + rate)**np.asarray(n, dtype=float)

def annuity_payment(balance, rate, term_years):
    if balance <= 0 or term_years <= 0: return 0.0
    r_m = rate / 12; n = int(round(term_years * 12))
    if r_m <= 0: return balance / term_years
    return float(balance * r_m * (1 + r_m)**n / ((1 + r_m)**n - 1) * 12)

# ── STEP 1: CPI + time series ────────────────────────────────────────────────
print("=" * 72)
print(" STEP 1 — Loading CPI + time series, computing real CAGRs and multipliers")
print("=" * 72)

cpi_raw = pd.read_csv(CPI_PATH)
cpi_raw.columns = ["Year", "CPI"]
cpi_raw["Year"] = cpi_raw["Year"].astype(int)
cpi_series = cpi_raw.set_index("Year")["CPI"].astype(float)

def cpi_deflator(f, t):
    return float(cpi_series.loc[t]) / float(cpi_series.loc[f])

def deflate_to_base(series, base_year):
    real = series.copy().astype(float)
    for yr in real.index:
        if yr in cpi_series.index:
            real.loc[yr] *= cpi_deflator(yr, base_year)
    return real

def load_excel_series(path):
    df = pd.read_excel(path, sheet_name="Data", header=0)
    df = df.dropna(subset=[df.columns[0], df.columns[1]])
    df.columns = ["Year", "Value"] + list(df.columns[2:])
    df["Year"]  = df["Year"].astype(int)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df = df.dropna(subset=["Value"])
    return df.set_index("Year")["Value"]

def fill_missing(series, target_years=range(2009, 2027)):
    s = series.copy().astype(float)
    df = s.reset_index(); df.columns = ["Year", "Value"]
    X = df["Year"].values.reshape(-1, 1); y = df["Value"].values
    m = LinearRegression().fit(X, y)
    missing = [y for y in target_years if y not in s.index]
    if missing:
        pred = m.predict(np.array(missing).reshape(-1, 1))
        for yr, v in zip(missing, pred):
            s.loc[yr] = v
    return s.sort_index()

def real_cagr(nom, obs_last):
    obs = nom[nom.index <= obs_last].dropna()
    first, last = int(obs.index.min()), int(obs.index.max())
    real = deflate_to_base(obs, last)
    return ((float(real.loc[last]) / float(real.loc[first])) ** (1 / (last - first)) - 1, first, last)

hp_nom  = fill_missing(load_excel_series(HP_PATH))
wlt_nom = fill_missing(load_excel_series(WEALTH_PATH))
inc_nom = fill_missing(load_excel_series(INCOME_PATH))

MULT_HP     = float(hp_nom.loc[MODEL_START_YEAR]  / hp_nom.loc[SURVEY_YEAR])
MULT_WEALTH = float(wlt_nom.loc[MODEL_START_YEAR] / wlt_nom.loc[SURVEY_YEAR])
MULT_INC    = float(inc_nom.loc[MODEL_START_YEAR] / inc_nom.loc[SURVEY_YEAR])

REAL_HPI_GROWTH,    _, _ = real_cagr(hp_nom,  2025)
REAL_INCOME_GROWTH, _, _ = real_cagr(inc_nom, 2025)
REAL_WEALTH_GROWTH, _, _ = real_cagr(wlt_nom, 2021)

print(f"  Multipliers: HP×{MULT_HP:.3f}, Wealth×{MULT_WEALTH:.3f}, Inc×{MULT_INC:.3f}")
print(f"  Real CAGR: HPI {REAL_HPI_GROWTH*100:+.2f}%, "
      f"Income {REAL_INCOME_GROWTH*100:+.2f}%, Wealth {REAL_WEALTH_GROWTH*100:+.2f}%")
print(f"  Elapsed: {time.time()-T0:.1f}s")

# ── STEP 2: Consumption table ────────────────────────────────────────────────
print("\n STEP 2 — Loading consumption table")
cons_raw = pd.read_csv(CONSUMP_PATH); cons = cons_raw.iloc[:10].copy()
cons["lower_weekly"] = pd.to_numeric(
    cons["Lower_boundary_group"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
cons["annual_lower"]       = cons["lower_weekly"] * 52
cons["annual_cons_owner"]  = cons["Average_net_consumption_owners"] * 52
cons["annual_cons_renter"] = cons["Average_net_consumption_renters"] * 52
cons["annual_upper"]       = cons["annual_lower"].shift(-1).fillna(np.inf)

def lookup_cons(inc, is_owner):
    col = "annual_cons_owner" if is_owner else "annual_cons_renter"
    for _, r in cons.iterrows():
        if inc < r["annual_upper"]:
            return r[col]
    return cons.iloc[-1][col]

# ── STEP 3: WAS loading with usecols ─────────────────────────────────────────
print("\n STEP 3 — Loading WAS Round 8 data (selected columns only)")

HHOLD_COLS = ["CASER8", "R8xshhwgt", "ten1r8_i", "TotMortR8", "HPropWR8",
              "HFINWR8_SUM", "HphysWR8", "TOTPENR8_aggr", "DVTotInc_BHCR8",
              "MEndY101R8", "MIntRate1R8", "GORR8", "HRPEdLevelR8", "HGiftR8",
              "HRPNSSEC3R8", "HRPSexR8"]
PERSON_COLS = ["CASER8", "DVAge17R8", "hrp_respr8", "totpen_oldr8", "PenFlagR8"]

t1 = time.time()
hh = pd.read_csv(HHOLD_PATH, sep="\t", usecols=HHOLD_COLS, low_memory=False)
print(f"  Households loaded: {len(hh):,} ({time.time()-t1:.1f}s)")
t1 = time.time()
pp = pd.read_csv(PERSON_PATH, sep="\t", usecols=PERSON_COLS, low_memory=False)
print(f"  Persons loaded:    {len(pp):,} ({time.time()-t1:.1f}s)")
print(f"  Cumulative elapsed: {time.time()-T0:.1f}s")

# ── STEP 4: HRP age merge ────────────────────────────────────────────────────
hrp_age = pp[pp["hrp_respr8"] == 1][["CASER8", "DVAge17R8"]] \
            .rename(columns={"DVAge17R8": "HRP_DVAge17R8"})
hh = hh.merge(hrp_age, on="CASER8", how="left")

# ── STEP 5: Clean + uplift to 2026 ───────────────────────────────────────────
print("\n STEP 5 — Cleaning + uplifting household variables to 2026")
hh["is_owner"] = hh["ten1r8_i"].isin([1, 2, 3]).astype(int)
hh["mort_balance"]     = pd.to_numeric(hh["TotMortR8"], errors="coerce").fillna(0).clip(lower=0)
hh["net_prop_wealth"]  = hh["HPropWR8"].clip(lower=0)
hh["gross_prop_value"] = (hh["net_prop_wealth"] + hh["mort_balance"]) * MULT_HP
hh["fin_wealth"]       = hh["HFINWR8_SUM"] * MULT_WEALTH
hh["phys_wealth"]      = hh["HphysWR8"].clip(lower=0) * MULT_WEALTH
hh["pen_wealth_hh"]    = hh["TOTPENR8_aggr"].clip(lower=0) * MULT_WEALTH
hh["mort_balance"]     = hh["mort_balance"] * MULT_HP
hh["hh_net_income"]    = hh["DVTotInc_BHCR8"].clip(lower=0) * MULT_INC
hh["gross_income_bhc"] = hh["DVTotInc_BHCR8"].clip(lower=0) * MULT_INC

hh["mort_years_remaining"] = pd.to_numeric(hh["MEndY101R8"], errors="coerce")
hh["mort_years_remaining"] = hh["mort_years_remaining"].where(
    hh["mort_years_remaining"].between(1, 50), DEFAULT_MORT_TERM)
hh["mort_rate"] = pd.to_numeric(hh["MIntRate1R8"], errors="coerce") / 100
hh["mort_rate"] = hh["mort_rate"].where(hh["mort_rate"].between(0.001, 0.30),
                                        FALLBACK_MORT_RATE)
hh["ann_mort_computed"] = hh.apply(
    lambda r: annuity_payment(r["mort_balance"], r["mort_rate"], r["mort_years_remaining"])
              if r["mort_balance"] > 0 else 0.0, axis=1)

is_london = hh["GORR8"] == 7
floor = np.where(is_london, MORT_FLOOR_LONDON, MORT_FLOOR_OTHER)
needs_floor = (hh["ann_mort_computed"] > 0) & (hh["ann_mort_computed"] < MORT_FLOOR_MIN)
hh["ann_mort_payment"] = np.where(needs_floor, floor, hh["ann_mort_computed"])
hh.loc[hh["mort_balance"] == 0, "ann_mort_payment"] = 0.0

hh["ann_rent_paid"] = 0.0
hh.loc[hh["ten1r8_i"] == 4, "ann_rent_paid"] = hh.loc[hh["ten1r8_i"] == 4, "gross_income_bhc"] * RENT_RATIO_PRIVATE
hh.loc[hh["ten1r8_i"] == 5, "ann_rent_paid"] = hh.loc[hh["ten1r8_i"] == 5, "gross_income_bhc"] * RENT_RATIO_SOCIAL
hh["ann_housing_cost"] = np.where(hh["is_owner"] == 1, hh["ann_mort_payment"], hh["ann_rent_paid"])

hh["cons_cost"] = hh.apply(
    lambda r: lookup_cons(r["hh_net_income"], r["is_owner"] == 1), axis=1)
hh["degree_plus"] = (hh["HRPEdLevelR8"] == 1).astype(int)
hh["has_gift"]    = hh["HGiftR8"].isin([1, 2, 3]).astype(int)
hh["region_name"] = hh["GORR8"].map(REGION_MAP)

# ── STEP 6: Pension wealth ───────────────────────────────────────────────────
pp["pen_wealth_indiv"] = pd.to_numeric(pp["totpen_oldr8"], errors="coerce").fillna(0) * MULT_WEALTH
pen_agg = (pp.groupby("CASER8")
             .agg(pen_wealth_person_sum=("pen_wealth_indiv", "sum"),
                  n_with_pension=("PenFlagR8", "sum"),
                  n_adults_hh=("CASER8", "size"))
             .reset_index())
hh = hh.merge(pen_agg, on="CASER8", how="left")
hh["n_adults_hh"] = hh["n_adults_hh"].fillna(1).clip(upper=2).astype(float)

# ── STEP 7: FTB cohort ───────────────────────────────────────────────────────
print("\n STEP 7 — FTB cohort selection (HRP age bands 7–8)")
ftb = hh[hh["HRP_DVAge17R8"].isin([7, 8])].copy()
ftb["tenure_binary"]        = np.where(ftb["is_owner"] == 1, "owner", "renter")
ftb["hrp_age_mid"]          = ftb["HRP_DVAge17R8"].map(AGE_BAND_MIDPOINTS_17)
ftb["years_to_retirement"]  = RETIREMENT_AGE - ftb["hrp_age_mid"]
wt = "R8xshhwgt"
print(f"  Cohort size: {len(ftb):,} (owners {(ftb['tenure_binary']=='owner').sum():,}, "
      f"renters {(ftb['tenure_binary']=='renter').sum():,})")
print(f"  Cumulative elapsed: {time.time()-T0:.1f}s")

# ── STEP 8: Projection engine to age 67 (v4 logic) ───────────────────────────
def project_wealth(df, real_hpi=REAL_HPI_GROWTH, real_fin_ret=REAL_FINANCIAL_RETURN,
                   real_pen_ret=REAL_PENSION_GROWTH, real_inc_grw=REAL_INCOME_GROWTH,
                   real_wlt_grw=REAL_WEALTH_GROWTH, real_rent_grw=0.0,
                   cons_infl=CONSUMPTION_INFL, pen_cont_rate=PENSION_CONT_RATE,
                   zero_gifts=False):
    d = df.copy()
    if zero_gifts: d["has_gift"] = 0
    N = len(d)
    n_arr     = d["years_to_retirement"].values.astype(float)
    inc0      = d["hh_net_income"].values.astype(float)
    cons0     = d["cons_cost"].values.astype(float)
    is_own    = (d["tenure_binary"] == "owner").values
    mort_yrs  = d["mort_years_remaining"].values.astype(float)
    ann_mort  = d["ann_mort_payment"].values.astype(float)
    ann_rent0 = d["ann_rent_paid"].values.astype(float)
    fin0      = d["fin_wealth"].clip(lower=0).values.astype(float)
    pen0      = d["pen_wealth_person_sum"].clip(lower=0).values.astype(float)
    phys0     = d["phys_wealth"].clip(lower=0).values.astype(float)
    gross_val = d["gross_prop_value"].clip(lower=0).values.astype(float)

    proj_prop  = np.zeros(N); proj_fin = np.zeros(N)
    proj_pen   = np.zeros(N); proj_phys = np.zeros(N)
    acc_surplus = np.zeros(N); acc_hcost = np.zeros(N); acc_cons = np.zeros(N)

    for i in range(N):
        n_i = int(round(n_arr[i]))
        if n_i <= 0: continue
        proj_prop[i] = gross_val[i] * (1 + real_hpi)**n_i if is_own[i] else 0.0
        proj_phys[i] = phys0[i] * (1 + real_wlt_grw)**n_i
        fin_pot = fin0[i] * (1 + real_fin_ret)**n_i
        pen_pot = pen0[i] * (1 + real_pen_ret)**n_i
        mort_cutoff = int(round(mort_yrs[i]))
        for t in range(1, n_i + 1):
            yrs_left = n_i - t
            inc_t  = inc0[i]  * (1 + real_inc_grw)**t
            cons_t = cons0[i] * (1 + cons_infl)**t
            if is_own[i]:
                hcost_t = ann_mort[i] if t <= mort_cutoff else 0.0
            else:
                hcost_t = ann_rent0[i] * (1 + real_inc_grw + real_rent_grw)**t
            surplus_t = max(inc_t - cons_t - hcost_t, 0.0)
            fin_pot += surplus_t * (1 - pen_cont_rate) * (1 + real_fin_ret)**yrs_left
            pen_pot += surplus_t * pen_cont_rate       * (1 + real_pen_ret)**yrs_left
            acc_surplus[i] += surplus_t; acc_hcost[i] += hcost_t; acc_cons[i] += cons_t
        proj_fin[i] = fin_pot; proj_pen[i] = pen_pot

    n_safe = np.where(n_arr > 0, n_arr, 1.0)
    d["avg_surplus_during"] = acc_surplus / n_safe
    d["avg_housing_cost"]   = acc_hcost   / n_safe
    d["avg_cons"]           = acc_cons    / n_safe
    d["proj_prop_wealth"]   = proj_prop
    d["proj_fin_wealth"]    = proj_fin
    d["proj_pen_wealth"]    = proj_pen
    d["proj_phys_wealth"]   = proj_phys
    d["proj_total_wealth"]  = proj_prop + proj_fin + proj_pen + proj_phys

    disc_factor = 1.0 / (1 + DISCOUNT_RATE)**n_arr
    d["disc_prop_wealth"]   = d["proj_prop_wealth"]  * disc_factor
    d["disc_fin_wealth"]    = d["proj_fin_wealth"]   * disc_factor
    d["disc_pen_wealth"]    = d["proj_pen_wealth"]   * disc_factor
    d["disc_phys_wealth"]   = d["proj_phys_wealth"]  * disc_factor
    d["disc_total_wealth"]  = d["proj_total_wealth"] * disc_factor
    return d

print("\n STEP 8 — Projecting v4 wealth stocks to age 67")
ftb = project_wealth(ftb)
print(f"  Cumulative elapsed: {time.time()-T0:.1f}s")

# ── STEP 9: Cohort-median income split ───────────────────────────────────────
cohort_median_income = wmedian(ftb["hh_net_income"], ftb[wt])
ftb["above_median_inc"] = (ftb["hh_net_income"] >= cohort_median_income).astype(int)
print(f"\n  Cohort median net HH income (2026 £): £{cohort_median_income:,.0f}")
print(f"  Above-median households: {int(ftb['above_median_inc'].sum()):,} "
      f"of {len(ftb):,}")

# ── STEP 10: Post-retirement engine ──────────────────────────────────────────
def project_post_retirement(ftb_in,
        sp_real_growth=SP_REAL_GROWTH,
        g_pre80_above=G_PRE80_ABOVE, g_pre80_below=G_PRE80_BELOW,
        g_post80=G_POST80, adapt_cost=ADAPT_COST, adapt_age=ADAPT_AGE,
        lifespan_end=LIFESPAN_END_AGE,
        real_hpi=None, real_fin_ret=None, real_pen_ret=None,
        real_wlt_grw=None, real_inc_grw=None,
        cons_infl_pre_ret=CONSUMPTION_INFL,
        pool_liquid=False, return_trajectory=False, income_split=True):
    real_hpi     = REAL_HPI_GROWTH       if real_hpi     is None else real_hpi
    real_fin_ret = REAL_FINANCIAL_RETURN if real_fin_ret is None else real_fin_ret
    real_pen_ret = REAL_PENSION_GROWTH   if real_pen_ret is None else real_pen_ret
    real_wlt_grw = REAL_WEALTH_GROWTH    if real_wlt_grw is None else real_wlt_grw
    real_inc_grw = REAL_INCOME_GROWTH    if real_inc_grw is None else real_inc_grw

    d = ftb_in.copy(); N = len(d)
    n_years = lifespan_end - RETIREMENT_AGE
    t_adapt = adapt_age - RETIREMENT_AGE
    t_break = BREAK_AGE - RETIREMENT_AGE

    is_owner  = (d["tenure_binary"] == "owner").values
    above_med = d["above_median_inc"].values.astype(bool) if income_split else np.ones(N, bool)
    n_adults  = d["n_adults_hh"].values.astype(float)
    n_h       = d["years_to_retirement"].values.astype(float)
    cons_2026 = d["cons_cost"].values.astype(float)
    rent_2026 = d["ann_rent_paid"].values.astype(float)
    W_prop_67 = d["proj_prop_wealth"].values.astype(float)
    W_fin_67  = d["proj_fin_wealth"].values.astype(float)
    W_pen_67  = d["proj_pen_wealth"].values.astype(float)
    W_phys_67 = d["proj_phys_wealth"].values.astype(float)

    C_67 = cons_2026 * (1 + cons_infl_pre_ret) ** n_h
    g_pre80 = np.where(above_med, g_pre80_above, g_pre80_below) if income_split \
              else np.full(N, g_pre80_above)

    W_prop = np.zeros((N, n_years + 1)); W_fin = np.zeros((N, n_years + 1))
    W_pen  = np.zeros((N, n_years + 1)); W_phys= np.zeros((N, n_years + 1))
    outflows  = np.zeros((N, n_years + 1)); sp_income = np.zeros((N, n_years + 1))
    unfunded  = np.zeros((N, n_years + 1)); cons_arr  = np.zeros((N, n_years + 1))
    rent_arr  = np.zeros((N, n_years + 1))
    deficit_age = np.full(N, np.nan)

    W_prop[:, 0] = np.where(is_owner, W_prop_67, 0.0)
    W_fin[:, 0]  = W_fin_67
    W_pen[:, 0]  = W_pen_67
    W_phys[:, 0] = W_phys_67

    for t in range(1, n_years + 1):
        W_prop[:, t] = np.where(is_owner, W_prop[:, t-1] * (1 + real_hpi), 0.0)
        W_phys[:, t] = W_phys[:, t-1] * (1 + real_wlt_grw)
        fin_open = W_fin[:, t-1] * (1 + real_fin_ret)
        pen_open = W_pen[:, t-1] * (1 + real_pen_ret)

        if t <= t_break:
            C_t = C_67 * (1 + g_pre80) ** t
        else:
            C_t = C_67 * (1 + g_pre80) ** t_break * (1 + g_post80) ** (t - t_break)

        H_renter_t = rent_2026 * (1 + real_inc_grw) ** (n_h + t)
        H_t = np.where(is_owner, 0.0, H_renter_t)
        A_t = np.where((t == t_adapt) & is_owner, adapt_cost, 0.0)
        Outflows_t = C_t + H_t + A_t
        SP_t = n_adults * SP_PER_ADULT_2026 * (1 + sp_real_growth) ** t
        gap_t = np.maximum(Outflows_t - SP_t, 0.0)

        if pool_liquid:
            liquid_open = fin_open + pen_open
            withdraw = np.minimum(gap_t, liquid_open)
            unfunded_t = gap_t - withdraw
            ratio = np.where(liquid_open > 0, fin_open / np.maximum(liquid_open, 1e-9), 0.5)
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

    W_total_88 = W_prop[:,n_years] + W_fin[:,n_years] + W_pen[:,n_years] + W_phys[:,n_years]
    disc_factor = 1.0 / (1 + DISCOUNT_RATE) ** (n_h + n_years)
    d["W_prop_88"]            = W_prop[:, n_years]
    d["W_fin_88"]             = W_fin[:, n_years]
    d["W_pen_88"]             = W_pen[:, n_years]
    d["W_phys_88"]            = W_phys[:, n_years]
    d["W_total_88"]           = W_total_88
    d["disc_W_total_88"]      = W_total_88 * disc_factor
    d["cumulative_unfunded"]  = unfunded.sum(axis=1)
    d["first_deficit_age"]    = deficit_age
    if return_trajectory:
        return (d, dict(W_prop=W_prop, W_fin=W_fin, W_pen=W_pen, W_phys=W_phys,
                        outflows=outflows, sp_income=sp_income, unfunded=unfunded,
                        consumption=cons_arr, rent=rent_arr, n_years=n_years))
    return d

print("\n STEP 10 — Running central post-retirement scenario (IFS-calibrated)")
ftb_88, traj = project_post_retirement(ftb, return_trajectory=True)
owners  = ftb_88[ftb_88["tenure_binary"] == "owner"]
renters = ftb_88[ftb_88["tenure_binary"] == "renter"]
print(f"  Cumulative elapsed: {time.time()-T0:.1f}s")

# ── STEP 11: Summary print ───────────────────────────────────────────────────
def W(s, w): return wmean(s, w)
print("\n" + "=" * 72)
print(" RESULTS — Mean wealth (2026 £, weighted by R8xshhwgt)")
print("=" * 72)
print(f"  {'Component':<12} {'Owners@67':>13} {'Renters@67':>13} {'Gap@67':>13}  |  "
      f"{'Owners@88':>13} {'Renters@88':>13} {'Gap@88':>13}")
for lbl, c67, c88 in [("Property","proj_prop_wealth","W_prop_88"),
                      ("Financial","proj_fin_wealth","W_fin_88"),
                      ("Pension","proj_pen_wealth","W_pen_88"),
                      ("Physical","proj_phys_wealth","W_phys_88")]:
    o67=W(owners[c67],owners[wt]);   r67=W(renters[c67],renters[wt])
    o88=W(owners[c88],owners[wt]);   r88=W(renters[c88],renters[wt])
    print(f"  {lbl:<12} £{o67:>12,.0f} £{r67:>12,.0f} £{o67-r67:>12,.0f}  |  "
          f"£{o88:>12,.0f} £{r88:>12,.0f} £{o88-r88:>12,.0f}")
o67=W(owners["proj_total_wealth"],owners[wt]); r67=W(renters["proj_total_wealth"],renters[wt])
o88=W(owners["W_total_88"],owners[wt]);        r88=W(renters["W_total_88"],renters[wt])
o67d=W(owners["disc_total_wealth"],owners[wt]); r67d=W(renters["disc_total_wealth"],renters[wt])
o88d=W(owners["disc_W_total_88"],owners[wt]);   r88d=W(renters["disc_W_total_88"],renters[wt])
gap67=o67-r67; gap88=o88-r88; gap67d=o67d-r67d; gap88d=o88d-r88d
print(f"  {'TOTAL':<12} £{o67:>12,.0f} £{r67:>12,.0f} £{gap67:>12,.0f}  |  "
      f"£{o88:>12,.0f} £{r88:>12,.0f} £{gap88:>12,.0f}")

print(f"\n  ► HEADLINE GAPS:")
print(f"      @67 undiscounted : £{gap67:,.0f}")
print(f"      @67 discounted   : £{gap67d:,.0f}")
print(f"      @88 undiscounted : £{gap88:,.0f}    "
      f"(Δ vs @67: £{gap88-gap67:+,.0f}, {(gap88/gap67-1)*100:+.1f}%)")
print(f"      @88 discounted   : £{gap88d:,.0f}")
med_o67=wmedian(owners["proj_total_wealth"],owners[wt])
med_r67=wmedian(renters["proj_total_wealth"],renters[wt])
med_o88=wmedian(owners["W_total_88"],owners[wt])
med_r88=wmedian(renters["W_total_88"],renters[wt])
print(f"      @67 median gap   : £{med_o67-med_r67:,.0f}")
print(f"      @88 median gap   : £{med_o88-med_r88:,.0f}")

share_rdef = (renters["first_deficit_age"].notna()).sum() / len(renters)
share_odef = (owners["first_deficit_age"].notna()).sum() / len(owners)
print(f"\n  ► DEFICITS:")
print(f"      Renter households in deficit before 88 : {share_rdef*100:5.1f}%  "
      f"(mean first-deficit age: {renters['first_deficit_age'].mean():.1f})")
print(f"      Owner households in deficit before 88  : {share_odef*100:5.1f}%  "
      f"(mean first-deficit age: {owners['first_deficit_age'].mean():.1f})")

# ── STEP 12: Decomposition ───────────────────────────────────────────────────
gap_A = W(owners["W_prop_88"], owners[wt])
owner_hcost_mean  = W(owners["avg_housing_cost"],  owners[wt])
renter_hcost_mean = W(renters["avg_housing_cost"], renters[wt])
n_owner_ret  = W(owners["years_to_retirement"],  owners[wt])
n_renter_ret = W(renters["years_to_retirement"], renters[wt])
mort_term_mean = W(owners["mort_years_remaining"], owners[wt])
mort_active_mean = min(mort_term_mean, n_owner_ret)
post_mort_mean   = max(n_owner_ret - mort_active_mean, 0)
hcost_diff_during = max(renter_hcost_mean - owner_hcost_mean, 0)
fv_during        = fv_annuity(hcost_diff_during, REAL_FINANCIAL_RETURN, mort_active_mean)
fv_during_to_ret = fv_lumpsum(fv_during, REAL_FINANCIAL_RETURN, post_mort_mean)
fv_post          = fv_annuity(renter_hcost_mean, REAL_FINANCIAL_RETURN, post_mort_mean)
gap_B_pre        = float(np.sum(fv_during_to_ret) + np.sum(fv_post))
gap_B_pre_to_88  = gap_B_pre * (1 + REAL_FINANCIAL_RETURN) ** N_POST_YRS

is_rent_mask = (ftb_88["tenure_binary"] == "renter").values
r_weights = ftb_88.loc[is_rent_mask, wt].values
renter_rent_yr = np.array([np.average(traj["rent"][is_rent_mask, t], weights=r_weights)
                           for t in range(N_POST_YRS + 1)])
diffs = renter_rent_yr.copy()
diffs[T_ADAPT] = max(diffs[T_ADAPT] - ADAPT_COST, 0)
gap_B_post = sum(diffs[t] * (1 + REAL_FINANCIAL_RETURN)**(N_POST_YRS - t)
                 for t in range(1, N_POST_YRS + 1))
gap_B = gap_B_pre_to_88 + gap_B_post
gap_C = gap88 - gap_A - gap_B

print("\n" + "=" * 72)
print(" DECOMPOSITION (M7) — undiscounted 2026 £")
print("=" * 72)
print(f"  A. Property capital gain          : £{gap_A:>14,.0f}  ({gap_A/gap88*100:5.1f}%)")
print(f"  B. Housing cost savings (lifespan): £{gap_B:>14,.0f}  ({gap_B/gap88*100:5.1f}%)")
print(f"     ├ pre-retirement (rolled to 88) : £{gap_B_pre_to_88:>14,.0f}")
print(f"     └ post-retirement (net adapt)   : £{gap_B_post:>14,.0f}")
print(f"  C. Income & endowment residual    : £{gap_C:>14,.0f}  ({gap_C/gap88*100:5.1f}%)")
print(f"  TOTAL                             : £{gap_88:=>14,.0f}  (100.0%)" if False
      else f"  TOTAL                             : £{gap88:>14,.0f}  (100.0%)")

# ── STEP 13: Trajectory dataframe ────────────────────────────────────────────
is_own_mask = (ftb_88["tenure_binary"] == "owner").values
ages = np.arange(RETIREMENT_AGE, LIFESPAN_END_AGE + 1)
def cohort_mean(arr, mask):
    w = ftb_88.loc[mask, wt].values
    return np.array([np.average(arr[mask, t], weights=w) for t in range(arr.shape[1])])

traj_rows = []
for tenure_lbl, mask in [("owner", is_own_mask), ("renter", ~is_own_mask)]:
    prop = cohort_mean(traj["W_prop"], mask); fin = cohort_mean(traj["W_fin"], mask)
    pen  = cohort_mean(traj["W_pen"],  mask); phys= cohort_mean(traj["W_phys"],mask)
    tot  = prop + fin + pen + phys
    for i, age in enumerate(ages):
        traj_rows.append(dict(age=int(age), tenure=tenure_lbl,
                              W_prop=prop[i], W_fin=fin[i],
                              W_pen=pen[i], W_phys=phys[i], W_total=tot[i]))
traj_df = pd.DataFrame(traj_rows)

# ── STEP 14: Subgroups ───────────────────────────────────────────────────────
def gap_by_group(df, gcol, min_n=10):
    rows=[]
    for grp, sub in df.groupby(gcol, observed=True):
        o=sub[sub["tenure_binary"]=="owner"]; r=sub[sub["tenure_binary"]=="renter"]
        if len(o)<min_n or len(r)<min_n: continue
        ow=W(o["W_total_88"],o[wt]); rw=W(r["W_total_88"],r[wt])
        ow_d=W(o["disc_W_total_88"],o[wt]); rw_d=W(r["disc_W_total_88"],r[wt])
        ow_m=wmedian(o["W_total_88"],o[wt]); rw_m=wmedian(r["W_total_88"],r[wt])
        rows.append(dict(group=grp, owner_88=ow, renter_88=rw, gap_88=ow-rw,
                         owner_88_disc=ow_d, renter_88_disc=rw_d, gap_88_disc=ow_d-rw_d,
                         owner_88_med=ow_m, renter_88_med=rw_m, gap_88_med=ow_m-rw_m,
                         n_owners=len(o), n_renters=len(r)))
    return pd.DataFrame(rows)

decile_edges = np.nanpercentile(ftb_88["hh_net_income"].dropna(), np.arange(0, 101, 10))
def dl(i): return f"D{i} (£{decile_edges[i-1]:,.0f}–£{decile_edges[i]:,.0f})"
ftb_88["income_decile_lbl"] = pd.qcut(ftb_88["hh_net_income"].rank(method="first"),
                                       10, labels=[dl(i) for i in range(1, 11)])
gap_decile = gap_by_group(ftb_88, "income_decile_lbl", min_n=5)
gap_region = gap_by_group(ftb_88, "region_name")
gap_educ   = gap_by_group(ftb_88, "degree_plus")
gap_educ["group"] = gap_educ["group"].map({0:"No degree",1:"Degree+"})

print("\n" + "=" * 72)
print(" SUBGROUPS — Gap at age 88")
print("=" * 72)
print(f"\n  By income decile:")
for _, r in gap_decile.iterrows():
    print(f"    {str(r['group']):<28} Gap £{r['gap_88']:>11,.0f}  "
          f"(disc £{r['gap_88_disc']:>10,.0f})  n=({r['n_owners']:>3}/{r['n_renters']:>3})")
print(f"\n  By region:")
for _, r in gap_region.sort_values("gap_88", ascending=False).iterrows():
    print(f"    {str(r['group']):<22} Gap £{r['gap_88']:>11,.0f}  (disc £{r['gap_88_disc']:>10,.0f})")
print(f"\n  By education:")
for _, r in gap_educ.iterrows():
    print(f"    {str(r['group']):<14} Gap £{r['gap_88']:>11,.0f}  (disc £{r['gap_88_disc']:>10,.0f})")

# ── STEP 15: Sensitivity ─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print(" SENSITIVITY SCENARIOS")
print("=" * 72)

post_scenarios = {
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
    "No income split":               dict(income_split=False),
    "Steeper 80+ decline":           dict(g_post80=-0.010),
    "Pooled liquid drawdown":        dict(pool_liquid=True),
}

V4_SCENARIOS = {
    "Low HPI (real 0%)":     {"real_hpi": 0.00},
    "High HPI (real +3%)":   {"real_hpi": 0.03},
    "Rent escalation +1%":   {"real_rent_grw": 0.01},
    "DC underperformance":   {"real_pen_ret": 0.02},
    "No parental transfers": {"zero_gifts": True},
}

sens_rows=[]; central_gap_88=None
print(f"\n  {'Scenario':<38} {'Gap@67':>14} {'Gap@88':>14} {'Δ vs central':>14}")
for name, ov in post_scenarios.items():
    out = project_post_retirement(ftb, **ov)
    o=out[out["tenure_binary"]=="owner"]; r=out[out["tenure_binary"]=="renter"]
    g67=W(o["proj_total_wealth"],o[wt])-W(r["proj_total_wealth"],r[wt])
    g88=W(o["W_total_88"],o[wt])-W(r["W_total_88"],r[wt])
    g88d=W(o["disc_W_total_88"],o[wt])-W(r["disc_W_total_88"],r[wt])
    if central_gap_88 is None: central_gap_88 = g88
    sens_rows.append(dict(scenario=name, gap_67=g67, gap_88=g88, gap_88_disc=g88d,
                          delta=g88-central_gap_88))
    print(f"  {name:<38} £{g67:>12,.0f}  £{g88:>12,.0f}  £{g88-central_gap_88:>12,.0f}")

for name, ov in V4_SCENARIOS.items():
    zg = ov.pop("zero_gifts", False) if isinstance(ov, dict) else False
    kw = {"real_hpi": REAL_HPI_GROWTH, "real_fin_ret": REAL_FINANCIAL_RETURN,
          "real_pen_ret": REAL_PENSION_GROWTH, "real_inc_grw": REAL_INCOME_GROWTH,
          "real_wlt_grw": REAL_WEALTH_GROWTH, "real_rent_grw": 0.0, **(ov or {})}
    ftb_scn = project_wealth(ftb.copy(), zero_gifts=zg, **kw)
    ftb_scn["n_adults_hh"] = ftb["n_adults_hh"].values
    ftb_scn["above_median_inc"] = (ftb_scn["hh_net_income"] >= cohort_median_income).astype(int)
    pr_kw = {k: kw[k] for k in ("real_hpi","real_fin_ret","real_pen_ret",
                                "real_inc_grw","real_wlt_grw") if k in kw}
    out = project_post_retirement(ftb_scn, **pr_kw)
    o=out[out["tenure_binary"]=="owner"]; r=out[out["tenure_binary"]=="renter"]
    g67=W(o["proj_total_wealth"],o[wt])-W(r["proj_total_wealth"],r[wt])
    g88=W(o["W_total_88"],o[wt])-W(r["W_total_88"],r[wt])
    g88d=W(o["disc_W_total_88"],o[wt])-W(r["disc_W_total_88"],r[wt])
    label = f"v4: {name}"
    sens_rows.append(dict(scenario=label, gap_67=g67, gap_88=g88, gap_88_disc=g88d,
                          delta=g88-central_gap_88))
    print(f"  {label:<38} £{g67:>12,.0f}  £{g88:>12,.0f}  £{g88-central_gap_88:>12,.0f}")

sens_df = pd.DataFrame(sens_rows)

# ── STEP 16: Deficit diagnostic ──────────────────────────────────────────────
deficit_diag = ftb_88.copy()
deficit_diag["in_deficit"] = deficit_diag["first_deficit_age"].notna().astype(int)
deficit_by_decile = (deficit_diag
    .groupby(["income_decile_lbl","tenure_binary"], observed=True)
    .apply(lambda g: pd.Series(dict(n=len(g),
                                    share_in_deficit=g["in_deficit"].mean(),
                                    mean_first_deficit_age=g["first_deficit_age"].mean())))
    .reset_index())

# ── STEP 17: Save outputs ────────────────────────────────────────────────────
print("\n" + "=" * 72)
print(" SAVING OUTPUTS")
print("=" * 72)

summary_rows=[]
for lbl, c67, c88 in [("Property","proj_prop_wealth","W_prop_88"),
                      ("Financial","proj_fin_wealth","W_fin_88"),
                      ("Pension","proj_pen_wealth","W_pen_88"),
                      ("Physical","proj_phys_wealth","W_phys_88"),
                      ("Total","proj_total_wealth","W_total_88")]:
    o67=W(owners[c67],owners[wt]); r67=W(renters[c67],renters[wt])
    o88=W(owners[c88],owners[wt]); r88=W(renters[c88],renters[wt])
    summary_rows.append(dict(component=lbl, owner_at_67=o67, renter_at_67=r67,
                             gap_67=o67-r67, owner_at_88=o88, renter_at_88=r88,
                             gap_88=o88-r88))
summary_rows.append(dict(component="Total (discounted)", owner_at_67=o67d,
                         renter_at_67=r67d, gap_67=o67d-r67d, owner_at_88=o88d,
                         renter_at_88=r88d, gap_88=o88d-r88d))
summary_rows.append(dict(component="Total (median)", owner_at_67=med_o67,
                         renter_at_67=med_r67, gap_67=med_o67-med_r67,
                         owner_at_88=med_o88, renter_at_88=med_r88, gap_88=med_o88-med_r88))
pd.DataFrame(summary_rows).to_csv(OUTPUT_DIR / "lifespan_summary_table.csv", index=False)

traj_df.to_csv(OUTPUT_DIR / "lifespan_trajectory.csv", index=False)
pd.DataFrame([
    dict(channel="A. Property capital gain", value=gap_A, share=gap_A/gap88),
    dict(channel="B. Housing cost savings (total)", value=gap_B, share=gap_B/gap88),
    dict(channel="  B.1 pre-retirement (rolled)", value=gap_B_pre_to_88, share=gap_B_pre_to_88/gap88),
    dict(channel="  B.2 post-retirement (net adapt)", value=gap_B_post, share=gap_B_post/gap88),
    dict(channel="C. Income & endowment residual", value=gap_C, share=gap_C/gap88),
    dict(channel="TOTAL", value=gap88, share=1.0),
]).to_csv(OUTPUT_DIR / "lifespan_decomposition.csv", index=False)
gap_decile.to_csv(OUTPUT_DIR / "lifespan_by_decile.csv", index=False)
gap_region.to_csv(OUTPUT_DIR / "lifespan_by_region.csv", index=False)
gap_educ.to_csv(OUTPUT_DIR / "lifespan_by_education.csv", index=False)
sens_df.to_csv(OUTPUT_DIR / "lifespan_sensitivity.csv", index=False)
deficit_by_decile.to_csv(OUTPUT_DIR / "lifespan_deficit_diagnostic.csv", index=False)

# Chart
fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
for ax, tenure in zip(axes, ["owner","renter"]):
    sub = traj_df[traj_df["tenure"] == tenure].set_index("age")
    comps  = ["W_prop","W_pen","W_fin","W_phys"]
    colors = ["#1f77b4","#2ca02c","#ff7f0e","#9467bd"]
    labels = ["Property","Pension","Financial","Physical"]
    ax.stackplot(sub.index, [sub[c]/1e3 for c in comps],
                 labels=labels, colors=colors, alpha=0.85)
    ax.set_title(f"{tenure.title()}s — mean wealth trajectory", fontsize=12)
    ax.set_xlabel("Age")
    ax.set_ylabel("Wealth (£ thousand, 2026 prices)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"£{x:,.0f}k"))
    ax.axvline(ADAPT_AGE, color="grey", linestyle="--", linewidth=0.8, alpha=0.7,
               label=f"Age {ADAPT_AGE} adaptation")
    ax.axvline(BREAK_AGE, color="black", linestyle=":", linewidth=0.8, alpha=0.5,
               label=f"Age {BREAK_AGE} consumption break")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
plt.suptitle("Owner vs renter wealth trajectory in retirement (IFS R209-calibrated central)",
             fontsize=13)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "lifespan_trajectory_chart.png", dpi=150, bbox_inches="tight")
plt.close(fig)

print(f"\n  Outputs written to: {OUTPUT_DIR}")
for f in sorted(OUTPUT_DIR.iterdir()):
    print(f"    {f.name}")

print(f"\n  TOTAL ELAPSED: {time.time()-T0:.1f}s")
print("=" * 72)
print(" Done.")
print("=" * 72)
