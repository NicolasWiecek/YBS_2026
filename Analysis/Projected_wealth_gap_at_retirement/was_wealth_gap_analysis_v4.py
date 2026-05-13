"""
WAS Round 8 – Homeownership Wealth Gap at Retirement
=====================================================
v4 – changes from v3
---------------------
1.  INCOME VARIABLE      : Replaced equivalised income (NetEquIncAnn_BHCR8)
                           with total net household income (DVTotInc_BHCR8),
                           which equals HHNetIncMthR8 × 12. This is the raw
                           unadjusted household net income before housing costs.

2.  INFLATION TO 2026    : WAS R8 is from 2020-22 (survey midpoint ~2021).
                           The model start year is now 2026. All monetary
                           WAS variables are uplifted to 2026 prices using
                           multipliers derived from three external time series:
                             • House prices    : UK_average_house_price_data.xlsx
                             • Household wealth: Median_household_wealth.xlsx
                             • Income          : Disposable_income_per_head_.xlsx
                           For each series, missing years are filled by linear
                           regression (matching the reference code exactly), and
                           the multiplier is value(2026) / value(2021).
                           [Note: 2026 is extrapolated where data ends before
                           that year (income ends 2025, wealth ends 2021).]

3.  FORWARD GROWTH RATES : Real house price, income and wealth growth rates
                           are derived from the same time series (CPI-deflated
                           CAGR over full observed span) and ALL now feed into
                           the projection via a year-by-year time-series loop:
                             REAL_HPI_GROWTH    → property value growth
                             REAL_INCOME_GROWTH → income grows each year in the
                               surplus loop (previously computed but unused)
                             REAL_WEALTH_GROWTH → physical wealth grows each year
                               (previously held flat)
                           Rent grows at the same rate as income (real_inc_grw)
                           plus an additional real rent escalation term
                           (real_rent_grw, default 0 in central scenario).
                           Setting real_rent_grw=0.01 in the sensitivity
                           scenario makes rent grow 1pp faster than income.

4.  CONSUMPTION          : LCF values are already in 2025 prices; no uplift
                           applied. Thresholds converted from weekly to annual
                           (×52) only.

Data files required in the repository source_data folder:
    source_data/WAS_data/was_round_8_hhold.tab
    source_data/WAS_data/was_round_8_person.tab
    source_data/Consumption_deciles_split_owners_renters_weekly.csv
    source_data/UK average house price data.xlsx
    source_data/Median household wealth.xlsx
    source_data/Disposable income per head .xlsx
    source_data/CPI_Inflation.csv
"""

# ── 0. Imports ────────────────────────────────────────────────────────────────
import warnings
import os
import sys
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
from scipy import stats
from sklearn.linear_model import LinearRegression

# ── Paths ─────────────────────────────────────────────────────────────────────

def find_project_root(start_dir: Path) -> Path:
    for path in (start_dir, *start_dir.parents):
        if (path / "source_data").is_dir():
            return path
    return start_dir


PROJECT_ROOT = find_project_root(SCRIPT_DIR)
SOURCE_DATA_DIR = PROJECT_ROOT / "source_data"
WAS_DATA_DIR = SOURCE_DATA_DIR / "WAS_data"

HHOLD_PATH    = WAS_DATA_DIR / "was_round_8_hhold.tab"
PERSON_PATH   = WAS_DATA_DIR / "was_round_8_person.tab"
CONSUMP_PATH  = SOURCE_DATA_DIR / "Consumption_deciles_split_owners_renters_weekly.csv"
HP_PATH       = SOURCE_DATA_DIR / "UK average house price data.xlsx"
WEALTH_PATH   = SOURCE_DATA_DIR / "Median household wealth.xlsx"
INCOME_PATH   = SOURCE_DATA_DIR / "Disposable income per head .xlsx"
CPI_PATH      = SOURCE_DATA_DIR / "CPI_Inflation.csv"
OUTPUT_DIR    = SCRIPT_DIR / "outputs_v4"

required_inputs = {
    "WAS household file": HHOLD_PATH,
    "WAS person file": PERSON_PATH,
    "consumption table": CONSUMP_PATH,
    "house price series": HP_PATH,
    "household wealth series": WEALTH_PATH,
    "income series": INCOME_PATH,
    "CPI series": CPI_PATH,
}
missing_inputs = [f"{label}: {path}" for label, path in required_inputs.items() if not path.is_file()]
if missing_inputs:
    expected_layout = (
        "Expected layout: <repo>/source_data/WAS_data/*.tab plus the CSV/XLSX "
        "inputs directly under <repo>/source_data."
    )
    raise FileNotFoundError("Required input files not found:\n" + "\n".join(missing_inputs) + "\n" + expected_layout)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Fixed model parameters ────────────────────────────────────────────────────
RETIREMENT_AGE        = 67
SURVEY_YEAR           = 2021    # WAS R8 reference year for inflation uplift
MODEL_START_YEAR      = 2026    # target year for inflated values
PENSION_CONT_RATE     = 0.08    # combined employer+employee DC rate
CONSUMPTION_INFL      = 0.012   # real consumption cost growth p.a. based on ONS LCF survey April 2024 - March 2024, real terms mean weekly expenditure growth (2012-2024): https://www.ons.gov.uk/peoplepopulationandcommunity/personalandhouseholdfinances/expenditure/bulletins/familyspendingintheuk/april2023tomarch2024
# Mortgage
FALLBACK_MORT_RATE    = 0.050   # 5% fallback
DEFAULT_MORT_TERM     = 25
MORT_FLOOR_LONDON     = 317 * 52   # £16,484  (ONS EHS 2023-2024 Annex Table 2.3 - https://www.gov.uk/government/collections/english-housing-survey-2023-to-2024-headline-findings-on-demographics-and-household-resilience#annex-tables)
MORT_FLOOR_OTHER      = 209 * 52   # £10,868
MORT_FLOOR_MIN        = 6_000

# Rent ratios  (ONS EHS 2023-2024 Annex Table 2.5 - https://www.gov.uk/government/collections/english-housing-survey-2023-to-2024-headline-findings-on-demographics-and-household-resilience#annex-tables)
RENT_RATIO_PRIVATE    = 0.34
RENT_RATIO_SOCIAL     = 0.264

# Real financial / pension return (kept fixed – not in the time series files)
REAL_FINANCIAL_RETURN = 0.035
REAL_PENSION_GROWTH   = 0.030 # broadly accepted proxy based on DWP model (IPEN), extrapolated from underlying assumptions here: https://www.gov.uk/government/statistics/analysis-of-future-pension-incomes-2025/analysis-of-future-pension-incomes-2025?utm_source=chatgpt.com#about-these-statistics

# Discount rate (HM Treasury Green Book standard for UK public policy analysis)
DISCOUNT_RATE         = 0.035

AGE_BAND_MIDPOINTS_17 = {7: 32, 8: 37}

REGION_MAP = {
    1:"North East", 2:"North West", 4:"East Midlands",
    5:"West Midlands", 6:"East of England", 7:"London",
    8:"South East", 9:"South West", 10:"Wales",
    11:"Scotland", 12:"Northern Ireland"
}

SCENARIO_OVERRIDES = {
    "Central"              : {},
    "Low HPI (real 0%)"    : {"real_hpi": 0.00},
    "High HPI (real +3%)"  : {"real_hpi": 0.03},
    "Rent escalation +1%"  : {"real_rent_grw": 0.01},   # +1pp above income growth
    "DC underperformance"  : {"real_pen_ret": 0.02},
    "No parental transfers": {"zero_gifts": True},
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – LOAD TIME SERIES & DERIVE MULTIPLIERS / GROWTH RATES
# ─────────────────────────────────────────────────────────────────────────────
print("="*65)
print("STEP 1 – Loading CPI + time series; computing real CAGRs and multipliers")
print("="*65)

# ── Load CPI index ────────────────────────────────────────────────────────────
cpi_raw = pd.read_csv(CPI_PATH)
cpi_raw.columns = ["Year", "CPI"]
cpi_raw["Year"] = cpi_raw["Year"].astype(int)
cpi_series = cpi_raw.set_index("Year")["CPI"].astype(float)

def cpi_deflator(from_year, to_year):
    """
    Return the factor to convert a value in from_year prices to to_year prices.
    factor = CPI[to_year] / CPI[from_year]
    Multiply a nominal value in from_year £ by this factor to express it in
    to_year £.
    """
    return float(cpi_series.loc[to_year]) / float(cpi_series.loc[from_year])

def deflate_series_to_base(series, base_year):
    """
    Convert every value in a nominal time series to base_year £ using CPI.
    Returns a new Series with the same index but values expressed in base_year £.
    Only deflates years present in both the series index and the CPI index.
    """
    real = series.copy().astype(float)
    for yr in real.index:
        if yr in cpi_series.index:
            real.loc[yr] = real.loc[yr] * cpi_deflator(yr, base_year)
    return real

def load_excel_series(path):
    """Load a two-column (Year, Value) Excel sheet into a pandas Series."""
    df = pd.read_excel(path, sheet_name="Data", header=0)
    df = df.dropna(subset=[df.columns[0], df.columns[1]])
    df.columns = ["Year", "Value"] + list(df.columns[2:])
    df["Year"]  = df["Year"].astype(int)
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df = df.dropna(subset=["Value"])
    return df.set_index("Year")["Value"]

def fill_missing_values(series, target_years=range(2009, 2027)):
    """
    Fill missing years using linear regression on observed data, then predict.
    Replicates the reference notebook's fill_missing_values() exactly.
    Applied to NOMINAL series before deflation.
    """
    series = series.copy().astype(float)
    df = series.reset_index()
    df.columns = ["Year", "Value"]
    X_train = df["Year"].values.reshape(-1, 1)
    y_train = df["Value"].values
    model = LinearRegression()
    model.fit(X_train, y_train)
    missing = [y for y in target_years if y not in series.index]
    if missing:
        y_pred = model.predict(np.array(missing).reshape(-1, 1))
        for yr, val in zip(missing, y_pred):
            series.loc[yr] = val
    return series.sort_index()

def find_increase_from_year(year_survey, year_want, series):
    """Return series[year_want] / series[year_survey]. Mirrors reference code."""
    return float(series.loc[year_want]) / float(series.loc[year_survey])

def real_cagr_full_series(nominal_series, obs_last_year):
    """
    Compute the real CAGR over the full observed span of a series.

    Method (reporting in £2026 prices):
      1. Restrict to observed years only (up to obs_last_year).
      2. Deflate every value to obs_last_year £ using CPI — this removes
         general inflation so only the real change in the variable remains.
      3. Compute CAGR from the first to the last observed year on the
         real (inflation-adjusted) series.

    This gives the average annual growth rate in excess of CPI, which is
    the appropriate rate to use when projecting forward in constant 2026 £.
    """
    obs = nominal_series[nominal_series.index <= obs_last_year].dropna()
    first_yr = int(obs.index.min())
    last_yr  = int(obs.index.max())
    real_obs = deflate_series_to_base(obs, last_yr)
    cagr = (float(real_obs.loc[last_yr]) / float(real_obs.loc[first_yr])) ** \
           (1 / (last_yr - first_yr)) - 1
    return cagr, first_yr, last_yr

# ── Load nominal series & fill gaps ──────────────────────────────────────────
hp_series_nom  = fill_missing_values(load_excel_series(HP_PATH))
wlt_series_nom = fill_missing_values(load_excel_series(WEALTH_PATH))
inc_series_nom = fill_missing_values(load_excel_series(INCOME_PATH))

# ── Uplift multipliers (nominal, 2021 → 2026) ────────────────────────────────
# These convert WAS 2021 £ values to 2026 £ values using each variable's own
# index, so they reflect actual price changes in that asset class.
MULT_HP    = find_increase_from_year(SURVEY_YEAR, MODEL_START_YEAR, hp_series_nom)
MULT_WEALTH= find_increase_from_year(SURVEY_YEAR, MODEL_START_YEAR, wlt_series_nom)
MULT_INC   = find_increase_from_year(SURVEY_YEAR, MODEL_START_YEAR, inc_series_nom)

# ── Real CAGRs over full observed spans ───────────────────────────────────────
# Each series is deflated to its own final observed year's prices, then CAGR
# is computed on the real values. This strips out CPI and gives the genuine
# real growth rate to use in projections expressed in constant 2026 £.
REAL_HPI_GROWTH,    HP_FIRST,  HP_LAST  = real_cagr_full_series(hp_series_nom,  2025)
REAL_INCOME_GROWTH, INC_FIRST, INC_LAST = real_cagr_full_series(inc_series_nom, 2025)
REAL_WEALTH_GROWTH, WLT_FIRST, WLT_LAST = real_cagr_full_series(wlt_series_nom, 2021)

print(f"\n  CPI index loaded: {int(cpi_series.index.min())}–{int(cpi_series.index.max())}")
print(f"\n  Nominal uplift multipliers ({SURVEY_YEAR} → {MODEL_START_YEAR}):")
print(f"    House prices : ×{MULT_HP:.4f}  ({(MULT_HP-1)*100:.1f}% total)")
print(f"    Wealth       : ×{MULT_WEALTH:.4f}  ({(MULT_WEALTH-1)*100:.1f}% total)")
print(f"    Income       : ×{MULT_INC:.4f}  ({(MULT_INC-1)*100:.1f}% total)")
print(f"\n  Real CAGR (CPI-deflated, full series span):")
print(f"    House prices  ({HP_FIRST}–{HP_LAST},  {HP_LAST-HP_FIRST} yrs): {REAL_HPI_GROWTH*100:+.2f}% p.a. real")
print(f"    Income        ({INC_FIRST}–{INC_LAST}, {INC_LAST-INC_FIRST} yrs): {REAL_INCOME_GROWTH*100:+.2f}% p.a. real")
print(f"    Wealth        ({WLT_FIRST}–{WLT_LAST},  {WLT_LAST-WLT_FIRST} yrs): {REAL_WEALTH_GROWTH*100:+.2f}% p.a. real")
print(f"\n  Note: REAL_FINANCIAL_RETURN ({REAL_FINANCIAL_RETURN*100:.1f}%) and")
print(f"        REAL_PENSION_GROWTH ({REAL_PENSION_GROWTH*100:.1f}%) remain fixed assumptions.")
print(f"  Discount rate: {DISCOUNT_RATE*100:.1f}% p.a. (HM Treasury Green Book)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – LOAD CONSUMPTION TABLE (uplift to 2026)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 2 – Loading consumption table (2025 LCF prices, no uplift)")
print("="*65)

cons_raw = pd.read_csv(CONSUMP_PATH)
cons = cons_raw.iloc[:10].copy()

cons["lower_weekly"]  = pd.to_numeric(
    cons["Lower_boundary_group"].astype(str).str.replace(",", ""), errors="coerce"
).fillna(0)

# Weekly → annual (no income uplift: LCF values are already 2025 prices)
cons["annual_lower"]        = cons["lower_weekly"]                           * 52
cons["annual_cons_owner"]   = cons["Average_net_consumption_owners"]         * 52
cons["annual_cons_renter"]  = cons["Average_net_consumption_renters"]        * 52
cons["annual_upper"]        = cons["annual_lower"].shift(-1).fillna(np.inf)

print("\n  Consumption lookup (2025 LCF prices, annual £, no uplift applied):")
print(f"  {'Decile':<14} {'Threshold £':>12} {'Owner cons £':>13} {'Renter cons £':>14}")
for _, r in cons.iterrows():
    print(f"  {r['Income_Decile']:<14} {r['annual_lower']:>12,.0f} "
          f"{r['annual_cons_owner']:>13,.0f} {r['annual_cons_renter']:>14,.0f}")

def lookup_consumption(annual_income, is_owner):
    col = "annual_cons_owner" if is_owner else "annual_cons_renter"
    for _, row in cons.iterrows():
        if annual_income < row["annual_upper"]:
            return row[col]
    return cons.iloc[-1][col]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – LOAD WAS DATA
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 3 – Loading WAS Round 8 data")
print("="*65)

hh = pd.read_csv(HHOLD_PATH,  sep="\t")
pp = pd.read_csv(PERSON_PATH, sep="\t", low_memory=False)
print(f"  Households : {len(hh):,}  |  Persons : {len(pp):,}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – MERGE HRP AGE FROM PERSON FILE
# ─────────────────────────────────────────────────────────────────────────────
hrp_age = (pp[pp["hrp_respr8"] == 1][["CASER8", "DVAge17R8"]]
           .rename(columns={"DVAge17R8": "HRP_DVAge17R8"}))
hh = hh.merge(hrp_age, on="CASER8", how="left")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – CLEAN & UPLIFT HOUSEHOLD VARIABLES TO 2026
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 5 – Cleaning and uplifting household variables to 2026")
print("="*65)

# ── Tenure ────────────────────────────────────────────────────────────────────
hh["is_owner"] = hh["ten1r8_i"].isin([1, 2, 3]).astype(int)

# ── Wealth components (uplifted by wealth multiplier) ────────────────────────
hh["mort_balance"]     = pd.to_numeric(hh["TotMortR8"], errors="coerce").fillna(0).clip(lower=0)
hh["net_prop_wealth"]  = hh["HPropWR8"].clip(lower=0)
hh["gross_prop_value"] = (hh["net_prop_wealth"] + hh["mort_balance"]) * MULT_HP
hh["fin_wealth"]       = hh["HFINWR8_SUM"]                            * MULT_WEALTH
hh["phys_wealth"]      = hh["HphysWR8"].clip(lower=0)                 * MULT_WEALTH
hh["pen_wealth_hh"]    = hh["TOTPENR8_aggr"].clip(lower=0)            * MULT_WEALTH
# Mortgage balance also uplifts (outstanding debt in today's £)
hh["mort_balance"]     = hh["mort_balance"] * MULT_HP

# ── Income (uplifted by income multiplier) ────────────────────────────────────
# CHANGED: use DVTotInc_BHCR8 = total net household income (NOT equivalised)
# This equals HHNetIncMthR8 × 12. It is before housing costs (BHC).
hh["hh_net_income"]    = hh["DVTotInc_BHCR8"].clip(lower=0) * MULT_INC
# Gross BHC also uplifted (used for rent ratio calculation)
hh["gross_income_bhc"] = hh["DVTotInc_BHCR8"].clip(lower=0) * MULT_INC

# ── Mortgage term ─────────────────────────────────────────────────────────────
hh["mort_years_remaining"] = pd.to_numeric(hh["MEndY101R8"], errors="coerce")
hh["mort_years_remaining"] = hh["mort_years_remaining"].where(
    hh["mort_years_remaining"].between(1, 50), DEFAULT_MORT_TERM
)

# ── Mortgage interest rate ────────────────────────────────────────────────────
hh["mort_rate"] = pd.to_numeric(hh["MIntRate1R8"], errors="coerce") / 100
hh["mort_rate"] = hh["mort_rate"].where(
    hh["mort_rate"].between(0.001, 0.30), FALLBACK_MORT_RATE
)

# ── Mortgage payment ─────────────────────────────────────────────────────────
def annuity_payment(balance, annual_rate, term_years):
    if balance <= 0 or term_years <= 0:
        return 0.0
    r_m = annual_rate / 12
    n   = int(round(term_years * 12))
    if r_m <= 0:
        return balance / term_years
    return float(balance * r_m * (1 + r_m)**n / ((1 + r_m)**n - 1) * 12)

hh["ann_mort_computed"] = hh.apply(
    lambda r: annuity_payment(r["mort_balance"], r["mort_rate"], r["mort_years_remaining"])
              if r["mort_balance"] > 0 else 0.0, axis=1
)

is_london    = hh["GORR8"] == 7
floor        = np.where(is_london, MORT_FLOOR_LONDON, MORT_FLOOR_OTHER)
needs_floor  = (hh["ann_mort_computed"] > 0) & (hh["ann_mort_computed"] < MORT_FLOOR_MIN)
hh["ann_mort_payment"] = np.where(needs_floor, floor, hh["ann_mort_computed"])
hh.loc[hh["mort_balance"] == 0, "ann_mort_payment"] = 0.0

# ── Rent ──────────────────────────────────────────────────────────────────────
hh["ann_rent_paid"] = 0.0
hh.loc[hh["ten1r8_i"]==4, "ann_rent_paid"] = hh.loc[hh["ten1r8_i"]==4, "gross_income_bhc"] * RENT_RATIO_PRIVATE
hh.loc[hh["ten1r8_i"]==5, "ann_rent_paid"] = hh.loc[hh["ten1r8_i"]==5, "gross_income_bhc"] * RENT_RATIO_SOCIAL

hh["ann_housing_cost"] = np.where(
    hh["is_owner"]==1, hh["ann_mort_payment"], hh["ann_rent_paid"]
)

# ── Consumption (LCF 2025 prices, no uplift; income used for decile lookup) ──
hh["cons_cost"] = hh.apply(
    lambda r: lookup_consumption(r["hh_net_income"], r["is_owner"]==1), axis=1
)

# ── Demographics ──────────────────────────────────────────────────────────────
hh["degree_plus"] = (hh["HRPEdLevelR8"] == 1).astype(int)
hh["has_gift"]    = hh["HGiftR8"].isin([1, 2, 3]).astype(int)
hh["region_name"] = hh["GORR8"].map(REGION_MAP)

n_floor = needs_floor.sum()
print(f"  Income variable : DVTotInc_BHCR8 (total net HH income, not equivalised)")
print(f"  Uplifted to 2026 (base 2021): income ×{MULT_INC:.3f}  |  house prices ×{MULT_HP:.3f}  |  wealth ×{MULT_WEALTH:.3f}")
print(f"  ONS floor applied to {n_floor:,} mortgage payments")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 – PENSION WEALTH FROM PERSON FILE (uplifted)
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 6 – Aggregating and uplifting pension wealth from person file")
print("="*65)

pp["pen_wealth_indiv"] = pd.to_numeric(pp["totpen_oldr8"], errors="coerce").fillna(0) * MULT_WEALTH

pen_agg = (pp.groupby("CASER8")
             .agg(pen_wealth_person_sum=("pen_wealth_indiv","sum"),
                  n_with_pension=("PenFlagR8","sum"))
             .reset_index())
hh = hh.merge(pen_agg, on="CASER8", how="left")
print(f"  Mean pension wealth (uplifted to 2026): £{hh['pen_wealth_person_sum'].mean():,.0f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 – SELECT FTB COHORT
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 7 – Selecting FTB cohort (DVAge17R8 = 7 or 8, age 30–39 in 2021)")
print("="*65)

ftb = hh[hh["HRP_DVAge17R8"].isin([7, 8])].copy()
ftb["tenure_binary"]        = np.where(ftb["is_owner"]==1, "owner", "renter")
ftb["hrp_age_mid"]          = ftb["HRP_DVAge17R8"].map(AGE_BAND_MIDPOINTS_17)
ftb["years_to_retirement"]  = RETIREMENT_AGE - ftb["hrp_age_mid"]

wt = "R8xshhwgt"

def wmean(series, weights):
    mask = series.notna() & weights.notna() & (weights > 0)
    if mask.sum() == 0: return np.nan
    return float(np.average(series[mask], weights=weights[mask]))

def wmedian(series, weights):
    s = series.dropna()
    w = weights.loc[s.index].fillna(0)
    valid = w > 0
    s, w = s[valid].values, w[valid].values
    if len(s) == 0: return np.nan
    idx = np.argsort(s)
    s, w = s[idx], w[idx]
    cumw = np.cumsum(w)
    return float(s[np.searchsorted(cumw, cumw[-1] / 2.0)])

n_own  = (ftb["tenure_binary"]=="owner").sum()
n_rent = (ftb["tenure_binary"]=="renter").sum()

print(f"  Cohort size : {len(ftb):,}  (owners: {n_own:,}, renters: {n_rent:,})")
print(f"  Ages at survey midpoint: band 7 → ~32yrs, band 8 → ~37yrs")
print(f"  Years to retirement: band 7 → {RETIREMENT_AGE-32}, band 8 → {RETIREMENT_AGE-37}")

owners_d  = ftb[ftb["tenure_binary"]=="owner"]
renters_d = ftb[ftb["tenure_binary"]=="renter"]

print("\n  ── Pre-projection diagnostics (2026 £, weighted means) ──────")
for grp, sub in [("Owners", owners_d), ("Renters", renters_d)]:
    surplus = (sub["hh_net_income"] - sub["cons_cost"] - sub["ann_housing_cost"]).clip(lower=0)
    print(f"  {grp}:")
    print(f"    Total net HH income (2026)  : £{wmean(sub['hh_net_income'],     sub[wt]):>10,.0f}")
    print(f"    Consumption cost (LCF, 2026): £{wmean(sub['cons_cost'],         sub[wt]):>10,.0f}")
    print(f"    Housing cost                : £{wmean(sub['ann_housing_cost'],  sub[wt]):>10,.0f}")
    print(f"    Investable surplus          : £{wmean(surplus,                  sub[wt]):>10,.0f}")
    print(f"    Gross property value (2026) : £{wmean(sub['gross_prop_value'],  sub[wt]):>10,.0f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 – PROJECTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 8 – Projecting wealth from 2026 to retirement (age 67)")
print("="*65)

def fv_lumpsum(value, rate, n_years):
    return np.asarray(value, dtype=float) * (1 + rate)**np.asarray(n_years, dtype=float)

def fv_annuity(payment, rate, n_years):
    if n_years <= 0 or payment <= 0: return 0.0
    if rate == 0: return payment * n_years
    return float(payment * ((1 + rate)**n_years - 1) / rate)

def avg_growing_cost(c0, g, n_yrs):
    """Average value of a cost that grows at g% p.a. over n_yrs."""
    if g == 0 or n_yrs == 0: return c0
    return c0 * ((1 + g)**n_yrs - 1) / (g * n_yrs)

def project_wealth(df,
                   real_hpi      = REAL_HPI_GROWTH,
                   real_fin_ret  = REAL_FINANCIAL_RETURN,
                   real_pen_ret  = REAL_PENSION_GROWTH,
                   real_inc_grw  = REAL_INCOME_GROWTH,
                   real_wlt_grw  = REAL_WEALTH_GROWTH,
                   real_rent_grw = 0.01,
                   cons_infl     = CONSUMPTION_INFL,
                   pen_cont_rate = PENSION_CONT_RATE,
                   zero_gifts    = False):
    """
    Project wealth year-by-year from 2026 to retirement for each household.

    ANNUAL TIME-SERIES ENGINE
    ─────────────────────────
    For each household h and each year t = 1 … n_h:

      income(t)      = income_2026 × (1 + real_inc_grw)^t
      consumption(t) = cons_2026   × (1 + cons_infl)^t
      housing_cost(t):
          owner, t <= mort_term  → fixed mortgage annuity payment
          owner, t >  mort_term  → £0
          renter                 → rent_2026 × (1 + real_inc_grw)^t
                                   Rent grows proportionally with income, preserving
                                   the ONS-calibrated 34%/28% income share throughout
                                   the projection. Real income growth raises both
                                   rent and investable surplus in proportion.
      surplus(t) = max(income(t) - consumption(t) - housing_cost(t), 0)

    Each year's surplus is split pen_cont_rate / (1-pen_cont_rate) between
    pension and financial savings and compounded forward to retirement.

    FIXES vs previous version
    ─────────────────────────
    1. real_inc_grw (REAL_INCOME_GROWTH) now feeds into every year's income
       trajectory rather than being computed but unused.
    2. real_wlt_grw (REAL_WEALTH_GROWTH) now grows physical wealth instead of
       holding it flat.
    3. Rent is grown at real_inc_grw each year (same rate as income), so the
       ONS-calibrated 34%/28% income share is preserved throughout the projection.
       a single average-cost approximation, so different growth rates on
       income vs consumption vs housing costs are handled correctly.
    """
    d = df.copy()
    if zero_gifts:
        d["has_gift"] = 0

    N         = len(d)
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

    # Output arrays
    proj_prop  = np.zeros(N)
    proj_fin   = np.zeros(N)
    proj_pen   = np.zeros(N)
    proj_phys  = np.zeros(N)

    # Diagnostic accumulators (average over projection years for reporting)
    acc_surplus = np.zeros(N)
    acc_hcost   = np.zeros(N)
    acc_cons    = np.zeros(N)

    for i in range(N):
        n_i = int(round(n_arr[i]))
        if n_i <= 0:
            continue

        # A. Property: lump-sum HPI growth ────────────────────────────────────
        proj_prop[i] = gross_val[i] * (1 + real_hpi)**n_i if is_own[i] else 0.0

        # D. Physical wealth grows at real_wlt_grw ────────────────────────────
        proj_phys[i] = phys0[i] * (1 + real_wlt_grw)**n_i

        # Base stocks compounded to retirement ────────────────────────────────
        fin_pot = fin0[i] * (1 + real_fin_ret)**n_i
        pen_pot = pen0[i] * (1 + real_pen_ret)**n_i

        # Year-by-year surplus loop ────────────────────────────────────────────
        mort_cutoff = int(round(mort_yrs[i]))

        for t in range(1, n_i + 1):
            yrs_left = n_i - t

            # Income grows at real_inc_grw each year
            inc_t  = inc0[i]  * (1 + real_inc_grw)**t

            # Consumption grows at cons_infl each year
            cons_t = cons0[i] * (1 + cons_infl)**t

            # Housing cost for this year
            if is_own[i]:
                # Fixed mortgage annuity until paid off, then free
                hcost_t = ann_mort[i] if t <= mort_cutoff else 0.0
            else:
                # Rent is a fixed % of income (34% private, 28% social from ONS).
                # It grows in line with real income (real_inc_grw) — preserving the
                # ONS income-share calibration — plus any additional real rent growth
                # (real_rent_grw, default 0). In the central scenario real_rent_grw=0
                # so rent is purely income-linked. The +1% sensitivity scenario sets
                # real_rent_grw=0.01, making rent grow 1pp faster than income each year.
                hcost_t = ann_rent0[i] * (1 + real_inc_grw + real_rent_grw)**t

            surplus_t = max(inc_t - cons_t - hcost_t, 0.0)

            # Compound this year's surplus forward to retirement
            fin_pot += surplus_t * (1 - pen_cont_rate) * (1 + real_fin_ret)**yrs_left
            pen_pot += surplus_t * pen_cont_rate        * (1 + real_pen_ret)**yrs_left

            acc_surplus[i] += surplus_t
            acc_hcost[i]   += hcost_t
            acc_cons[i]    += cons_t

        proj_fin[i] = fin_pot
        proj_pen[i] = pen_pot

    # Average annual values for diagnostics
    n_safe = np.where(n_arr > 0, n_arr, 1.0)
    d["avg_surplus_during"] = acc_surplus / n_safe
    d["avg_housing_cost"]   = acc_hcost   / n_safe
    d["avg_cons"]           = acc_cons    / n_safe

    # Totals ───────────────────────────────────────────────────────────────────
    d["proj_prop_wealth"]  = proj_prop
    d["proj_fin_wealth"]   = proj_fin
    d["proj_pen_wealth"]   = proj_pen
    d["proj_phys_wealth"]  = proj_phys
    d["proj_total_wealth"] = proj_prop + proj_fin + proj_pen + proj_phys

    # Discounted values (HM Treasury Green Book, 3.5% p.a.) ───────────────────
    disc_factor = 1.0 / (1 + DISCOUNT_RATE)**n_arr
    d["disc_prop_wealth"]  = d["proj_prop_wealth"]  * disc_factor
    d["disc_fin_wealth"]   = d["proj_fin_wealth"]   * disc_factor
    d["disc_pen_wealth"]   = d["proj_pen_wealth"]   * disc_factor
    d["disc_phys_wealth"]  = d["proj_phys_wealth"]  * disc_factor
    d["disc_total_wealth"] = d["proj_total_wealth"] * disc_factor

    return d

# Run central projection
ftb = project_wealth(ftb,
                     real_hpi      = REAL_HPI_GROWTH,
                     real_fin_ret  = REAL_FINANCIAL_RETURN,
                     real_pen_ret  = REAL_PENSION_GROWTH,
                     real_inc_grw  = REAL_INCOME_GROWTH,
                     real_wlt_grw  = REAL_WEALTH_GROWTH,
                     real_rent_grw = 0.0)

owners  = ftb[ftb["tenure_binary"]=="owner"]
renters = ftb[ftb["tenure_binary"]=="renter"]

print(f"\n  Forward growth rates used in projection (from time series):")
print(f"    Real HPI growth    (CAGR {HP_FIRST}–{HP_LAST})  : {REAL_HPI_GROWTH*100:.2f}% p.a.")
print(f"    Real income growth (CAGR {INC_FIRST}–{INC_LAST}) : {REAL_INCOME_GROWTH*100:.2f}% p.a.  [feeds year-by-year surplus]")
print(f"    Real wealth growth (CAGR {WLT_FIRST}–{WLT_LAST})  : {REAL_WEALTH_GROWTH*100:.2f}% p.a.  [feeds physical wealth]")
print(f"    Financial return (fixed)              : {REAL_FINANCIAL_RETURN*100:.2f}% p.a.")
print(f"    Pension growth (fixed)                : {REAL_PENSION_GROWTH*100:.2f}% p.a.")

print("\n  ── Surplus diagnostics (2026 £, weighted means) ──────────────")
for grp, sub in [("Owners", owners), ("Renters", renters)]:
    print(f"  {grp}:")
    print(f"    Net HH income     : £{wmean(sub['hh_net_income'],       sub[wt]):>10,.0f}")
    print(f"    Avg consumption   : £{wmean(sub['avg_cons'],            sub[wt]):>10,.0f}")
    print(f"    Avg housing cost  : £{wmean(sub['avg_housing_cost'],    sub[wt]):>10,.0f}")
    print(f"    Investable surplus: £{wmean(sub['avg_surplus_during'],  sub[wt]):>10,.0f}")

print("\n  ── Projected Retirement Wealth – UNDISCOUNTED (2026 £) ───────")
rows_w = [("Property","proj_prop_wealth"),("Financial","proj_fin_wealth"),
          ("Pension","proj_pen_wealth"),("Physical","proj_phys_wealth"),("TOTAL","proj_total_wealth")]
for lbl, col in rows_w:
    om = wmean(owners[col],  owners[wt])
    rm = wmean(renters[col], renters[wt])
    print(f"  {lbl:<12}  Owners: £{om:>12,.0f}   Renters: £{rm:>12,.0f}   Gap: £{om-rm:>12,.0f}")

total_gap = (wmean(owners["proj_total_wealth"],owners[wt])
            -wmean(renters["proj_total_wealth"],renters[wt]))

print(f"\n  ── Projected Retirement Wealth – DISCOUNTED @ {DISCOUNT_RATE*100:.1f}% (2026 £) ──")
disc_rows = [("Property","disc_prop_wealth"),("Financial","disc_fin_wealth"),
             ("Pension","disc_pen_wealth"),("Physical","disc_phys_wealth"),("TOTAL","disc_total_wealth")]
for lbl, col in disc_rows:
    om = wmean(owners[col],  owners[wt])
    rm = wmean(renters[col], renters[wt])
    print(f"  {lbl:<12}  Owners: £{om:>12,.0f}   Renters: £{rm:>12,.0f}   Gap: £{om-rm:>12,.0f}")

total_gap_disc = (wmean(owners["disc_total_wealth"],owners[wt])
                 -wmean(renters["disc_total_wealth"],renters[wt]))

print(f"\n  ► GAP undiscounted (2026 £)          : £{total_gap:,.0f}")
print(f"  ► GAP discounted @ {DISCOUNT_RATE*100:.1f}% p.a. (2026 £) : £{total_gap_disc:,.0f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 – THREE-WAY DECOMPOSITION
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 9 – Three-way decomposition of the retirement wealth gap")
print("="*65)

# A. Property channel
gap_A = wmean(owners["proj_prop_wealth"], owners[wt])

# B. Housing cost savings channel
# ─────────────────────────────────────────────────────────────────────────
# Owners pay a mortgage for mort_term years, then £0 housing cost.
# Renters pay rent throughout the entire n years.
# Channel B = the additional savings accumulated by the owner because:
#   (i)  rent > mortgage during the mortgage years → the owner saves
#        the differential each year into financial assets
#   (ii) post mortgage: owner pays £0, renter still pays rent → the full
#        rent amount is extra savings for the owner in those years
# We use weighted mean representative values for each group.
owner_hcost_mean   = wmean(owners["avg_housing_cost"],     owners[wt])
renter_hcost_mean  = wmean(renters["avg_housing_cost"],    renters[wt])
n_owner_ret        = wmean(owners["years_to_retirement"],  owners[wt])
n_renter_ret       = wmean(renters["years_to_retirement"], renters[wt])
mort_term_mean     = wmean(owners["mort_years_remaining"],  owners[wt])

# Years owner has mortgage vs post-mortgage
mort_active_mean   = min(mort_term_mean, n_owner_ret)
post_mort_mean     = max(n_owner_ret - mort_active_mean, 0)

# During mortgage years: owner saves (rent - mortgage) if positive
hcost_diff_during  = max(renter_hcost_mean - owner_hcost_mean, 0)
fv_during          = fv_annuity(hcost_diff_during, REAL_FINANCIAL_RETURN, mort_active_mean)
# Bring that FV forward through the post-mortgage period
fv_during_to_ret   = fv_lumpsum(fv_during, REAL_FINANCIAL_RETURN, post_mort_mean)

# Post-mortgage years: owner pays £0, renter pays rent → full rent is the gap
fv_post            = fv_annuity(renter_hcost_mean, REAL_FINANCIAL_RETURN, post_mort_mean)

gap_B = float(np.sum(fv_during_to_ret) + np.sum(fv_post))

# C. Income channel (residual)
gap_C = total_gap - gap_A - gap_B

pct_A = gap_A/total_gap*100
pct_B = gap_B/total_gap*100
pct_C = gap_C/total_gap*100

# Discounted versions (same proportions applied to discounted total)
gap_A_disc = total_gap_disc * pct_A / 100
gap_B_disc = total_gap_disc * pct_B / 100
gap_C_disc = total_gap_disc * pct_C / 100

print(f"\n  Undiscounted (2026 £):")
print(f"  A. Property capital gain       : £{gap_A:>12,.0f}  ({pct_A:5.1f}%)")
print(f"  B. Housing cost savings channel: £{gap_B:>12,.0f}  ({pct_B:5.1f}%)")
print(f"  C. Income & endowment channel  : £{gap_C:>12,.0f}  ({pct_C:5.1f}%)")
print(f"  TOTAL                          : £{total_gap:>12,.0f}  (100.0%)")
print(f"\n  Discounted @ {DISCOUNT_RATE*100:.1f}% p.a. (2026 £):")
print(f"  A. Property capital gain       : £{gap_A_disc:>12,.0f}  ({pct_A:5.1f}%)")
print(f"  B. Housing cost savings channel: £{gap_B_disc:>12,.0f}  ({pct_B:5.1f}%)")
print(f"  C. Income & endowment channel  : £{gap_C_disc:>12,.0f}  ({pct_C:5.1f}%)")
print(f"  TOTAL                          : £{total_gap_disc:>12,.0f}  (100.0%)")

# Oaxaca-Blinder
print("\n  ── Oaxaca-Blinder (supplementary) ──────────────────────────────")
covars = ["hh_net_income","degree_plus","has_gift","n_with_pension",
          "HRP_DVAge17R8","HRPSexR8","GORR8","HRPNSSEC3R8"]

ob = ftb[covars+["proj_total_wealth","tenure_binary",wt]].copy().dropna(subset=covars)
for c in ["HRPNSSEC3R8","GORR8","HRPSexR8"]:
    ob[c] = ob[c].fillna(ob[c].median())
ob["log_wealth"] = np.log1p(ob["proj_total_wealth"].clip(lower=0))
ob = ob[np.isfinite(ob["log_wealth"])]

X_own  = ob.loc[ob["tenure_binary"]=="owner",  covars].values
X_rent = ob.loc[ob["tenure_binary"]=="renter", covars].values
y_own  = ob.loc[ob["tenure_binary"]=="owner",  "log_wealth"].values
y_rent = ob.loc[ob["tenure_binary"]=="renter", "log_wealth"].values
w_own  = ob.loc[ob["tenure_binary"]=="owner",  wt].values
w_rent = ob.loc[ob["tenure_binary"]=="renter", wt].values

reg_own  = LinearRegression().fit(X_own,  y_own,  sample_weight=w_own)
reg_rent = LinearRegression().fit(X_rent, y_rent, sample_weight=w_rent)
X_own_mn  = np.average(X_own,  weights=w_own,  axis=0)
X_rent_mn = np.average(X_rent, weights=w_rent, axis=0)
tot_log_gap   = np.average(y_own,weights=w_own) - np.average(y_rent,weights=w_rent)
explained     = reg_own.coef_ @ (X_own_mn - X_rent_mn)
unexplained   = X_rent_mn     @ (reg_own.coef_ - reg_rent.coef_)
ob_explained  = total_gap * explained   / tot_log_gap
ob_unexplained= total_gap * unexplained / tot_log_gap

print(f"  Explained (underlying advantages): £{ob_explained:>12,.0f}  ({explained/tot_log_gap*100:.1f}%)")
print(f"  Unexplained (ownership effect)   : £{ob_unexplained:>12,.0f}  ({unexplained/tot_log_gap*100:.1f}%)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 – SENSITIVITY ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 10 – Sensitivity analysis")
print("="*65)

sens_results = {}       # undiscounted
sens_results_disc = {}  # discounted
for scenario, overrides in SCENARIO_OVERRIDES.items():
    zg  = overrides.pop("zero_gifts", False) if isinstance(overrides, dict) else False
    kw  = {"real_hpi": REAL_HPI_GROWTH, "real_fin_ret": REAL_FINANCIAL_RETURN,
           "real_pen_ret": REAL_PENSION_GROWTH, "real_inc_grw": REAL_INCOME_GROWTH,
           "real_wlt_grw": REAL_WEALTH_GROWTH, "real_rent_grw": 0.0,
           **(overrides or {})}
    proj = project_wealth(ftb.copy(), zero_gifts=zg, **kw)
    o    = proj[proj["tenure_binary"]=="owner"]
    r    = proj[proj["tenure_binary"]=="renter"]
    g         = wmean(o["proj_total_wealth"],o[wt]) - wmean(r["proj_total_wealth"],r[wt])
    g_disc    = wmean(o["disc_total_wealth"],o[wt]) - wmean(r["disc_total_wealth"],r[wt])
    sens_results[scenario]      = g
    sens_results_disc[scenario] = g_disc
    print(f"  {scenario:<30s}  undiscounted: £{g:>12,.0f}   discounted: £{g_disc:>12,.0f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 – BREAKDOWNS
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 11 – Breakdowns by quintile, region, education")
print("="*65)

def gap_by_group(df, group_col, wt_col="R8xshhwgt", min_n=10):
    rows=[]
    for grp, sub in df.groupby(group_col, observed=True):
        o = sub[sub["tenure_binary"]=="owner"]
        r = sub[sub["tenure_binary"]=="renter"]
        if len(o)<min_n or len(r)<min_n: continue
        ow      = wmean(o["proj_total_wealth"],  o[wt_col])
        rw      = wmean(r["proj_total_wealth"],  r[wt_col])
        ow_med  = wmedian(o["proj_total_wealth"], o[wt_col])
        rw_med  = wmedian(r["proj_total_wealth"], r[wt_col])
        ow_d    = wmean(o["disc_total_wealth"],  o[wt_col])
        rw_d    = wmean(r["disc_total_wealth"],  r[wt_col])
        rows.append({"group":grp,
                     "owner_wealth":ow,        "renter_wealth":rw,      "gap":ow-rw,
                     "owner_wealth_med":ow_med, "renter_wealth_med":rw_med, "gap_med":ow_med-rw_med,
                     "owner_wealth_disc":ow_d,  "renter_wealth_disc":rw_d,  "gap_disc":ow_d-rw_d,
                     "n_owners":len(o),         "n_renters":len(r)})
    return pd.DataFrame(rows)

ftb["income_quintile_lbl"] = pd.qcut(
    ftb["hh_net_income"].rank(method="first"), 5,
    labels=["Q1 (lowest)","Q2","Q3","Q4","Q5 (highest)"])

# ── Income decile brackets: compute actual £ thresholds from data ─────────────
decile_edges = np.nanpercentile(ftb["hh_net_income"].dropna(), np.arange(0, 101, 10))
def decile_label(i):
    """Return 'D1 (£X – £Y)' label for decile i (1-based)."""
    lo = decile_edges[i-1]
    hi = decile_edges[i]
    return f"D{i} (£{lo:,.0f}–£{hi:,.0f})"

ftb["income_decile_lbl"] = pd.qcut(
    ftb["hh_net_income"].rank(method="first"), 10,
    labels=[decile_label(i) for i in range(1, 11)])

gap_income  = gap_by_group(ftb, "income_quintile_lbl")
gap_decile  = gap_by_group(ftb, "income_decile_lbl", min_n=5)
gap_region  = gap_by_group(ftb, "region_name")
gap_educ    = gap_by_group(ftb, "degree_plus")
gap_educ["group"] = gap_educ["group"].map({0:"No degree",1:"Degree+"})

print("\n  By income quintile:")
print(gap_income[["group","gap","gap_disc"]].rename(
    columns={"gap":"Gap (undiscounted)","gap_disc":"Gap (discounted)"}).to_string(index=False))

print("\n  By income decile (with income brackets, D1=lowest, D10=highest):")
print(f"  {'Decile':<28} {'n_own':>5} {'n_rent':>6}  "
      f"{'Owner mean':>12} {'Owner med':>11} {'Renter mean':>12} {'Renter med':>11}  "
      f"{'Gap (mean)':>12} {'Gap (med)':>11}")
print("  " + "-"*118)
for _, row in gap_decile.iterrows():
    print(f"  {str(row['group']):<28} {row['n_owners']:>5} {row['n_renters']:>6}  "
          f"£{row['owner_wealth']:>10,.0f} £{row['owner_wealth_med']:>9,.0f} "
          f"£{row['renter_wealth']:>10,.0f} £{row['renter_wealth_med']:>9,.0f}  "
          f"£{row['gap']:>10,.0f} £{row['gap_med']:>9,.0f}")

print("\n  By region (sorted by undiscounted gap):")
reg_print = gap_region.sort_values("gap", ascending=False)[["group","gap","gap_disc"]].copy()
reg_print.columns = ["Region","Gap (undiscounted)","Gap (discounted)"]
for col in ["Gap (undiscounted)","Gap (discounted)"]:
    reg_print[col] = reg_print[col].map(lambda v: f"£{v:,.0f}")
print(reg_print.to_string(index=False))

print("\n  By education:")
edu_print = gap_educ[["group","gap","gap_disc"]].copy()
edu_print.columns = ["Education","Gap (undiscounted)","Gap (discounted)"]
for col in ["Gap (undiscounted)","Gap (discounted)"]:
    edu_print[col] = edu_print[col].map(lambda v: f"£{v:,.0f}")
print(edu_print.to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 12 – CHARTS
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 12 – Generating charts")
print("="*65)

plt.rcParams.update({"font.family":"sans-serif","axes.spines.top":False,
                     "axes.spines.right":False,"figure.dpi":150})
BLUE,GREEN,PINK,ORANGE = "#2166ac","#4dac26","#d01c8b","#e66101"
def fmt_k(v,_): return f"£{v/1e3:,.0f}k"

# ── Chart helper: stacked bar for one pair of groups ─────────────────────────
def stacked_wealth_chart(owners_df, renters_df, prop_col, fin_col, pen_col, phys_col,
                          title, ylabel, ax_obj, wt_col="R8xshhwgt"):
    cols   = [prop_col, fin_col, pen_col, phys_col]
    labels = ["Property","Financial","Pension","Physical"]
    x      = np.array([0, 0.65])
    bottom = np.zeros(2)
    for c, lbl, col in zip(cols, labels, [BLUE,GREEN,PINK,ORANGE]):
        vals = [wmean(owners_df[c], owners_df[wt_col])/1e3,
                wmean(renters_df[c],renters_df[wt_col])/1e3]
        ax_obj.bar(x, vals, bottom=bottom, width=0.45, label=lbl, color=col, alpha=0.88)
        for xi, vi, bi in zip(x, vals, bottom):
            if vi > 15:
                ax_obj.text(xi, bi+vi/2, f"£{vi:,.0f}k", ha="center", va="center",
                            fontsize=7, color="white", fontweight="bold")
        bottom += np.array(vals)
    ax_obj.set_xticks(x)
    ax_obj.set_xticklabels(["Homeowners","Lifetime renters"], fontsize=10)
    ax_obj.set_ylabel(ylabel)
    ax_obj.set_title(title, fontsize=10)
    ax_obj.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_k))

# Chart 1: Undiscounted vs discounted stacked wealth bars (side by side subplots)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
stacked_wealth_chart(owners, renters,
    "proj_prop_wealth","proj_fin_wealth","proj_pen_wealth","proj_phys_wealth",
    f"Undiscounted (2026 £)\nTotal gap: £{total_gap/1e3:,.0f}k",
    "Projected wealth at retirement (2026 £ thousands)", ax1)
stacked_wealth_chart(owners, renters,
    "disc_prop_wealth","disc_fin_wealth","disc_pen_wealth","disc_phys_wealth",
    f"Discounted @ {DISCOUNT_RATE*100:.1f}% p.a. (2026 £)\nTotal gap: £{total_gap_disc/1e3:,.0f}k",
    "Discounted wealth (2026 £ thousands)", ax2)
handles, labels_leg = ax1.get_legend_handles_labels()
fig.legend(handles, labels_leg, title="Component", bbox_to_anchor=(1.01,0.85), loc="upper left")
fig.suptitle("Projected retirement wealth by tenure group\n(WAS R8, age 30–39 cohort, central scenario)",
             fontsize=11, y=1.01)
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart1_wealth_stacked.png", bbox_inches="tight")
plt.close()

# Chart 2: Three-way decomposition — undiscounted vs discounted grouped bars
fig, ax = plt.subplots(figsize=(10, 5))
cats   = ["A. Property\ncapital gain","B. Housing cost\nsavings channel","C. Income &\nendowment channel"]
vals_u = [gap_A/1e3,      gap_B/1e3,      gap_C/1e3]
vals_d = [gap_A_disc/1e3, gap_B_disc/1e3, gap_C_disc/1e3]
x_pos  = np.arange(len(cats))
w      = 0.35
bu = ax.bar(x_pos - w/2, vals_u, width=w, color=[BLUE,GREEN,ORANGE], alpha=0.88, label="Undiscounted")
bd = ax.bar(x_pos + w/2, vals_d, width=w, color=[BLUE,GREEN,ORANGE], alpha=0.45,
            label=f"Discounted @ {DISCOUNT_RATE*100:.1f}%", hatch="//")
for bar, v in zip(bu, vals_u):
    ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+5,
            f"£{v:,.0f}k", ha="center", va="bottom", fontsize=8)
for bar, v in zip(bd, vals_d):
    ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+5,
            f"£{v:,.0f}k", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x_pos)
ax.set_xticklabels(cats)
ax.set_ylabel("Contribution to wealth gap (2026 £ thousands)")
ax.set_title(f"Three-way decomposition  |  Undiscounted gap: £{total_gap/1e3:,.0f}k"
             f"   Discounted: £{total_gap_disc/1e3:,.0f}k")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_k))
ax.legend()
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart2_threeway_decomposition.png", bbox_inches="tight")
plt.close()

# Chart 3: Time series (nominal + CPI-deflated overlay)
fig, axes = plt.subplots(1, 3, figsize=(14, 4))
series_info = [
    (hp_series_nom,  HP_FIRST,  HP_LAST,  "UK Average House Price (£)", MULT_HP,    BLUE),
    (wlt_series_nom, WLT_FIRST, WLT_LAST, "Median Household Wealth (£000s)", MULT_WEALTH, GREEN),
    (inc_series_nom, INC_FIRST, INC_LAST, "Disposable Income per Head (£)", MULT_INC,   PINK),
]
for ax, (s_nom, f_yr, l_yr, title, mult, col) in zip(axes, series_info):
    obs_nom  = s_nom[(s_nom.index >= f_yr) & (s_nom.index <= l_yr)]
    obs_real = deflate_series_to_base(obs_nom, l_yr)
    ax.plot(obs_nom.index,  obs_nom.values,  "o-",  color=col,   linewidth=2, markersize=4, label="Nominal")
    ax.plot(obs_real.index, obs_real.values, "s--", color=col,   linewidth=1.5, markersize=4,
            alpha=0.6, label=f"Real ({l_yr} £)")
    ax.axvline(SURVEY_YEAR,      color="grey",  linestyle=":", linewidth=1,   label=f"Survey {SURVEY_YEAR}")
    ax.axvline(MODEL_START_YEAR, color="black", linestyle="--",linewidth=1.2, label=f"Model {MODEL_START_YEAR}")
    ax.set_title(f"{title}\nMultiplier ×{mult:.3f}  |  Real CAGR: see Step 1", fontsize=8)
    ax.set_xlabel("Year")
    ax.legend(fontsize=7)
plt.suptitle(f"Time series: nominal vs CPI-deflated  ({SURVEY_YEAR}→{MODEL_START_YEAR} uplift)", fontsize=11, y=1.02)
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart3_time_series_uplift.png", bbox_inches="tight")
plt.close()

# Chart 4: Sensitivity tornado — undiscounted and discounted side by side
fig, (ax_u, ax_d) = plt.subplots(1, 2, figsize=(14, 5))
central_u = sens_results["Central"]
central_d = sens_results_disc["Central"]
names     = list(sens_results.keys())
for ax_s, results, central, label in [
    (ax_u, sens_results,      central_u, "Undiscounted"),
    (ax_d, sens_results_disc, central_d, f"Discounted @ {DISCOUNT_RATE*100:.1f}%"),
]:
    devs = [(v - central)/1e3 for v in results.values()]
    ax_s.barh(names, devs, color=[PINK if d>0 else BLUE for d in devs], alpha=0.85)
    ax_s.axvline(0, color="black", linewidth=0.8)
    for i, (d, v) in enumerate(zip(devs, results.values())):
        ax_s.text(d + (0.3 if d>=0 else -0.3), i, f"£{v/1e3:,.0f}k",
                  va="center", ha="left" if d>=0 else "right", fontsize=8)
    ax_s.set_xlabel("Difference from central (£ thousands)")
    ax_s.set_title(f"Sensitivity – {label}\nCentral gap: £{central/1e3:,.0f}k")
plt.suptitle("Sensitivity analysis: retirement wealth gap", fontsize=11)
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart4_sensitivity.png", bbox_inches="tight")
plt.close()

# Chart 5: Income waterfall (unchanged — no discounting applies to annual flows)
fig, ax = plt.subplots(figsize=(9,5))
for grp,col,lbl,offset in [("owner",BLUE,"Owners",-0.18),("renter",PINK,"Renters",0.18)]:
    sub=ftb[ftb["tenure_binary"]==grp]
    surplus=(sub["hh_net_income"]-sub["cons_cost"]-sub["ann_housing_cost"]).clip(lower=0)
    vals=[wmean(sub["gross_income_bhc"],sub[wt])/1e3,
          wmean(sub["hh_net_income"],sub[wt])/1e3,
          wmean(sub["hh_net_income"]-sub["cons_cost"],sub[wt])/1e3,
          wmean(surplus,sub[wt])/1e3]
    xp=np.arange(4)+offset
    ax.bar(xp,vals,width=0.33,color=col,alpha=0.85,label=lbl)
ax.set_xticks(np.arange(4))
ax.set_xticklabels(["Gross income\n(BHC)","Net HH\nincome","After\nconsumption","Investable\nsurplus"])
ax.set_ylabel("Annual 2026 £ (thousands)")
ax.set_title("Income waterfall to investable surplus\n(2026 £, weighted means, age 30–39 cohort)")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"£{v:,.0f}k"))
ax.legend()
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart5_income_waterfall.png",bbox_inches="tight")
plt.close()

# Chart 6: Wealth distribution KDE — undiscounted and discounted
fig, (ax_u, ax_d) = plt.subplots(1, 2, figsize=(14, 4))
cap_u = 4_000_000
cap_d = 2_000_000
for ax_s, wcol, cap, lbl_ax in [
    (ax_u, "proj_total_wealth", cap_u, "Undiscounted (2026 £)"),
    (ax_d, "disc_total_wealth", cap_d, f"Discounted @ {DISCOUNT_RATE*100:.1f}% (2026 £)"),
]:
    for grp, col, lbl in [("owner",BLUE,"Homeowners"),("renter",PINK,"Lifetime renters")]:
        sub = ftb[ftb["tenure_binary"]==grp][wcol].clip(upper=cap)
        sub = sub[sub>0]
        kde = stats.gaussian_kde(sub, bw_method=0.2)
        xr  = np.linspace(0, cap, 500)
        ax_s.plot(xr, kde(xr), label=lbl, color=col, linewidth=2)
        ax_s.fill_between(xr, kde(xr), alpha=0.15, color=col)
    ax_s.set_xlabel("Wealth at retirement (£)")
    ax_s.set_ylabel("Density")
    ax_s.set_title(lbl_ax)
    ax_s.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_:f"£{v/1e3:,.0f}k"))
    ax_s.legend()
fig.suptitle("Distribution of projected retirement wealth\n(WAS R8, age 30–39 cohort, central scenario)",
             fontsize=11)
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart6_wealth_distribution.png", bbox_inches="tight")
plt.close()

# Chart 7: Gap by income quintile — undiscounted and discounted grouped bars
fig, ax = plt.subplots(figsize=(9, 4))
x_q   = np.arange(len(gap_income))
w_q   = 0.35
ax.bar(x_q - w_q/2, gap_income["gap"]/1e3,      width=w_q, color=BLUE,  alpha=0.88, label="Undiscounted")
ax.bar(x_q + w_q/2, gap_income["gap_disc"]/1e3, width=w_q, color=BLUE,  alpha=0.45,
       label=f"Discounted @ {DISCOUNT_RATE*100:.1f}%", hatch="//")
ax.set_xticks(x_q)
ax.set_xticklabels(gap_income["group"], fontsize=9)
ax.set_ylabel("Wealth gap at retirement (2026 £ thousands)")
ax.set_xlabel("Total net HH income quintile")
ax.set_title("Retirement wealth gap by income quintile\n(undiscounted vs discounted)")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_k))
ax.legend()
plt.tight_layout()
fig.savefig(f"{OUTPUT_DIR}/chart7_gap_by_income.png", bbox_inches="tight")
plt.close()

print("  All charts saved.")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 13 – SUMMARY TABLE
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("STEP 13 – Summary table")
print("="*65)

surplus_o = (owners["hh_net_income"]-owners["cons_cost"]-owners["ann_housing_cost"]).clip(lower=0)
surplus_r = (renters["hh_net_income"]-renters["cons_cost"]-renters["ann_housing_cost"]).clip(lower=0)

rows=[
    ("── MODEL PARAMETERS ──","",""),
    ("Survey year",                                     SURVEY_YEAR,                      "y"),
    ("Model start year (inflated to)",                 MODEL_START_YEAR,                 "y"),
    ("House price multiplier (2021→2026)",             MULT_HP,                          "x"),
    ("Wealth multiplier (2021→2026)",                  MULT_WEALTH,                      "x"),
    ("Income multiplier (2021→2026)",                  MULT_INC,                         "x"),
    (f"Real HPI growth (CAGR {HP_FIRST}–{HP_LAST}, CPI-deflated)",   REAL_HPI_GROWTH*100,  "%"),
    (f"Real income growth (CAGR {INC_FIRST}–{INC_LAST}, CPI-deflated)", REAL_INCOME_GROWTH*100, "%"),
    (f"Real wealth growth (CAGR {WLT_FIRST}–{WLT_LAST}, CPI-deflated)", REAL_WEALTH_GROWTH*100, "%"),
    ("Discount rate (HM Treasury Green Book)",         DISCOUNT_RATE*100,                "%"),
    ("","",""),
    ("── COHORT ──","",""),
    ("Homeowners (n)",                                 n_own,                            "n"),
    ("Renters (n)",                                    n_rent,                           "n"),
    ("","",""),
    ("── PROJECTED RETIREMENT WEALTH – UNDISCOUNTED (2026 £) ──","",""),
    ("Owners – total wealth",                          wmean(owners["proj_total_wealth"],owners[wt]),   "£"),
    ("Renters – total wealth",                         wmean(renters["proj_total_wealth"],renters[wt]), "£"),
    ("Raw wealth gap (undiscounted)",                  total_gap,                        "£"),
    ("","",""),
    ("── PROJECTED RETIREMENT WEALTH – DISCOUNTED @ 3.5% (2026 £) ──","",""),
    ("Owners – total wealth (discounted)",             wmean(owners["disc_total_wealth"],owners[wt]),   "£"),
    ("Renters – total wealth (discounted)",            wmean(renters["disc_total_wealth"],renters[wt]), "£"),
    ("Raw wealth gap (discounted)",                    total_gap_disc,                   "£"),
    ("","",""),
    ("── THREE-WAY DECOMPOSITION ──","",""),
    ("A. Property capital gain  (undiscounted)",       gap_A,                            "£"),
    ("A. Property capital gain  (discounted)",         gap_A_disc,                       "£"),
    ("B. Housing cost savings   (undiscounted)",       gap_B,                            "£"),
    ("B. Housing cost savings   (discounted)",         gap_B_disc,                       "£"),
    ("C. Income & endowment     (undiscounted)",       gap_C,                            "£"),
    ("C. Income & endowment     (discounted)",         gap_C_disc,                       "£"),
    ("","",""),
    ("── OAXACA-BLINDER ──","",""),
    ("Explained – underlying advantages",              ob_explained,                     "£"),
    ("Unexplained – ownership effect",                 ob_unexplained,                   "£"),
    ("","",""),
    ("── ANNUAL BUDGET (2026 £, weighted means) ──","",""),
    ("Net HH income – owners",                         wmean(owners["hh_net_income"],    owners[wt]),   "£"),
    ("Net HH income – renters",                        wmean(renters["hh_net_income"],   renters[wt]),  "£"),
    ("Consumption – owners",                           wmean(owners["cons_cost"],        owners[wt]),   "£"),
    ("Consumption – renters",                          wmean(renters["cons_cost"],        renters[wt]), "£"),
    ("Housing cost – owners (mortgage)",               wmean(owners["ann_housing_cost"], owners[wt]),   "£"),
    ("Housing cost – renters (rent)",                  wmean(renters["ann_housing_cost"],renters[wt]),  "£"),
    ("Investable surplus – owners",                    wmean(surplus_o,                  owners[wt]),   "£"),
    ("Investable surplus – renters",                   wmean(surplus_r,                  renters[wt]),  "£"),
    ("","",""),
    ("── SENSITIVITY ANALYSIS ──","",""),
    ("Central – gap (undiscounted)",                   sens_results["Central"],                         "£"),
    ("Central – gap (discounted)",                     sens_results_disc["Central"],                    "£"),
    ("High HPI (+3% real) – gap (undiscounted)",       sens_results["High HPI (real +3%)"],             "£"),
    ("High HPI (+3% real) – gap (discounted)",         sens_results_disc["High HPI (real +3%)"],        "£"),
    ("High HPI vs Central – extra gap (undiscounted)", sens_results["High HPI (real +3%)"] - sens_results["Central"], "£"),
    ("High HPI vs Central – extra gap (discounted)",   sens_results_disc["High HPI (real +3%)"] - sens_results_disc["Central"], "£"),
    ("Rent escalation (+1%) – gap (undiscounted)",     sens_results["Rent escalation +1%"],             "£"),
    ("Rent escalation (+1%) – gap (discounted)",       sens_results_disc["Rent escalation +1%"],        "£"),
    ("Rent escalation vs Central – extra gap (undiscounted)", sens_results["Rent escalation +1%"] - sens_results["Central"], "£"),
    ("Rent escalation vs Central – extra gap (discounted)",   sens_results_disc["Rent escalation +1%"] - sens_results_disc["Central"], "£"),
    ("  [Rent grows at income growth + 1pp; central scenario has rent_grw=0]","",""),
    ("","",""),
    ("── WEALTH GAP BY INCOME DECILE (undiscounted, 2026 £) ──","",""),
    ("  [mean = survey-weighted mean; med = survey-weighted median]","",""),
]

# Append decile rows dynamically
for _, row in gap_decile.iterrows():
    g = str(row['group'])
    rows.append((f"  {g} – n owners",           row["n_owners"],        "n"))
    rows.append((f"  {g} – n renters",          row["n_renters"],       "n"))
    rows.append((f"  {g} – owner mean wealth",  row["owner_wealth"],    "£"))
    rows.append((f"  {g} – owner median wealth",row["owner_wealth_med"],"£"))
    rows.append((f"  {g} – renter mean wealth", row["renter_wealth"],   "£"))
    rows.append((f"  {g} – renter median wealth",row["renter_wealth_med"],"£"))
    rows.append((f"  {g} – gap (mean)",         row["gap"],             "£"))
    rows.append((f"  {g} – gap (median)",       row["gap_med"],         "£"))
    rows.append((f"  {g} – gap discounted",     row["gap_disc"],        "£"))


summary_rows = []
for metric, val, pfx in rows:
    if not metric:
        summary_rows.append({"Metric":"","Value":""})
        continue
    if pfx=="£":   fmt=f"£{val:,.0f}"
    elif pfx=="%": fmt=f"{val:+.2f}% p.a." if val < 0 else f"{val:.2f}% p.a."
    elif pfx=="pct": fmt=f"{val:.1f}%"
    elif pfx=="x": fmt=f"×{val:.4f}"
    elif pfx=="n": fmt=f"{int(val):,}"
    elif pfx=="y": fmt=f"{int(val)}"
    else:          fmt=""
    summary_rows.append({"Metric":metric,"Value":fmt})

summary_df = pd.DataFrame(summary_rows)
print(summary_df.to_string(index=False))

# ── Print sensitivity and decile sections separately for readability ──────────
print("\n  ── Sensitivity results (selected scenarios) ──────────────────")
print(f"  {'Scenario':<40} {'Undiscounted':>14} {'Discounted':>12} {'Δ vs Central':>14}")
print("  " + "-"*82)
central_u = sens_results["Central"]
central_d = sens_results_disc["Central"]
for scen in ["Central", "High HPI (real +3%)", "Rent escalation +1%"]:
    gu    = sens_results[scen]
    gd    = sens_results_disc[scen]
    delta = f"£{gu-central_u:+,.0f}" if scen != "Central" else "—"
    print(f"  {scen:<40} £{gu:>12,.0f} £{gd:>11,.0f} {delta:>14}")
print(f"  Note: Rent escalation — rent grows at income growth + 1pp (central: +0pp).")

print("\n  ── Wealth gap by income decile ────────────────────────────────")
print(f"  {'Decile':<28} {'n_own':>5} {'n_rent':>6}  "
      f"{'Owner mean':>12} {'Owner med':>11} {'Renter mean':>12} {'Renter med':>11}  "
      f"{'Gap mean':>12} {'Gap med':>11}")
print("  " + "-"*118)
for _, row in gap_decile.iterrows():
    print(f"  {str(row['group']):<28} {row['n_owners']:>5} {row['n_renters']:>6}  "
          f"£{row['owner_wealth']:>10,.0f} £{row['owner_wealth_med']:>9,.0f} "
          f"£{row['renter_wealth']:>10,.0f} £{row['renter_wealth_med']:>9,.0f}  "
          f"£{row['gap']:>10,.0f} £{row['gap_med']:>9,.0f}")

summary_df.to_csv(f"{OUTPUT_DIR}/summary_table_v4.csv", index=False)

print(f"\n  All outputs → {os.path.abspath(OUTPUT_DIR)}/")
print("\n" + "="*65)
print("ANALYSIS COMPLETE")
print("="*65)
