import argparse
import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def find_project_root(start_dir: Path) -> Path:
    """Find the nearest parent folder containing the shared source_data folder."""
    for path in (start_dir, *start_dir.parents):
        if (path / "source_data").is_dir():
            return path
    return start_dir


PROJECT_ROOT = find_project_root(SCRIPT_DIR)
SOURCE_DATA_DIR = PROJECT_ROOT / "source_data"
DEFAULT_DATA_DIR = SOURCE_DATA_DIR / "WAS_data"
DEFAULT_CPI_PATH = SOURCE_DATA_DIR / "CPI_Inflation.csv"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR

os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".matplotlib-cache"))

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde


BLUE = "#2166ac"
PINK = "#d01c8b"
GREEN = "#4dac26"
ORANGE = "#e66101"
GREY = "#636363"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 150,
    }
)

AGE_BANDS_65_74 = {14, 15}
OWNER_CODES = {1, 2, 3}
RENTER_CODES = {4, 5}
NEAR_ZERO_PRIVATE_WEALTH = 1_000
TARGET_PRICE_YEAR = 2022
ROUND_END_MONTH = {
    5: "2016-03",
    6: "2018-03",
    7: "2020-03",
    8: "2022-03",
}
ROUND_END_CPIH = {
    5: 100.4,
    6: 105.1,
    7: 108.6,
    8: 116.5,
}
MEASURE_SPECS = [
    ("total_wealth", "Total wealth"),
    ("wealth_excl_private_pension", "Total wealth excl private pension"),
    ("property_wealth", "Property wealth"),
    ("financial_wealth", "Financial wealth"),
    ("pension_wealth", "Private pension wealth"),
    ("physical_wealth", "Physical wealth"),
]

ROUND_CONFIG = {
    5: {
        "hh_file": "was_round_5_hhold.tab",
        "person_file": "was_round_5_person.tab",
        "caser": ["CASER5"],
        "weight": ["r5xshhwgt", "R5xshhwgt"],
        "tenure": ["Ten1R5_i", "Ten1R5", "ten1r5_i", "ten1r5"],
        "total_wealth": ["TotWlthR5"],
        "property_wealth": ["HPropWR5", "HpropWR5"],
        "financial_wealth": ["HFINWR5_Sum", "HFINWR5_SUM"],
        "physical_wealth": ["HphysWR5"],
        "pension_wealth_hh": ["TOTPENR5_aggr"],
        "income": ["NetEquincAnnR5", "NetEquIncAnnR5"],
        "hrp_flag": ["HRP_RespW5", "IsHRPW5"],
        "age17": ["DVAge17R5"],
        "person_pension": ["TOTPENR5"],
    },
    6: {
        "hh_file": "was_round_6_hhold.tab",
        "person_file": "was_round_6_person.tab",
        "caser": ["CASER6"],
        "weight": ["R6xshhwgt", "r6xshhwgt"],
        "tenure": ["Ten1R6_i", "Ten1R6", "ten1r6_i", "ten1r6"],
        "total_wealth": ["TotWlthR6"],
        "property_wealth": ["HpropWR6", "HPropWR6"],
        "financial_wealth": ["HFINWR6_Sum", "HFINWR6_SUM"],
        "physical_wealth": ["HphysWR6"],
        "pension_wealth_hh": ["TotpenR6_aggr", "TOTPENR6_aggr"],
        "income": ["NetEquIncAnn_R6", "netequincann_BHCW6"],
        "hrp_flag": ["HRP_RespW6", "IsHRPW6"],
        "age17": ["DVAge17R6"],
        "person_pension": ["TotpenR6", "TOTPENR6"],
    },
    7: {
        "hh_file": "was_round_7_hhold.tab",
        "person_file": "was_round_7_person.tab",
        "caser": ["CASER7"],
        "weight": ["R7xshhwgt", "r7xshhwgt"],
        "tenure": ["ten1r7_i", "ten1r7", "Ten1R7_i", "Ten1R7"],
        "total_wealth": ["TotWlthR7"],
        "property_wealth": ["HPropWR7"],
        "financial_wealth": ["HFINWR7_SUM"],
        "physical_wealth": ["HphysWR7"],
        "pension_wealth_hh": ["TOTPENR7_aggr"],
        "income": ["Inequiv_BHCR7", "netequincann_BHCR7", "DVTotinc_bhcR7"],
        "hrp_flag": ["hrp_respr7", "IsHRPR7"],
        "age17": ["DVAge17R7"],
        "person_pension": ["TOTPENR7"],
    },
    8: {
        "hh_file": "was_round_8_hhold.tab",
        "person_file": "was_round_8_person.tab",
        "caser": ["CASER8"],
        "weight": ["R8xshhwgt", "r8xshhwgt"],
        "tenure": ["ten1r8_i", "Ten1R8_i", "ten1r8", "Ten1R8"],
        "total_wealth": ["TotWlth_oldR8", "TotWlthR8"],
        "property_wealth": ["HPropWR8"],
        "financial_wealth": ["HFINWR8_SUM"],
        "physical_wealth": ["HphysWR8"],
        "pension_wealth_hh": ["TOTPEN_oldR8_aggr", "TOTPENR8_aggr"],
        "pension_wealth_updated_hh": ["totalpenr8_aggr"],
        "income": ["NetEquIncAnn_BHCR8", "Inequiv_BHCR8", "DVTotInc_BHCR8"],
        "hrp_flag": ["hrp_respr8", "IsHRPR8"],
        "age17": ["DVAge17R8"],
        "person_pension": ["totpen_oldr8", "TOTPEN_oldR8", "TOTPENR8"],
    },
}


def read_header(path: Path) -> list[str]:
    return list(pd.read_csv(path, sep="\t", nrows=0).columns)


def first_match(header: list[str], candidates: list[str], required: bool = True) -> str | None:
    for candidate in candidates:
        if candidate in header:
            return candidate
    if required:
        raise KeyError(f"Could not find any of {candidates}")
    return None


def resolve_round_columns(round_no: int, data_dir: Path) -> dict:
    config = ROUND_CONFIG[round_no]
    hh_path = data_dir / config["hh_file"]
    person_path = data_dir / config["person_file"]
    hh_header = read_header(hh_path)
    person_header = read_header(person_path)

    resolved = {
        "round": round_no,
        "hh_path": hh_path,
        "person_path": person_path,
        "hh_columns": len(hh_header),
        "person_columns": len(person_header),
        "caser": first_match(hh_header, config["caser"]),
        "weight": first_match(hh_header, config["weight"]),
        "tenure": first_match(hh_header, config["tenure"]),
        "total_wealth": first_match(hh_header, config["total_wealth"]),
        "property_wealth": first_match(hh_header, config["property_wealth"]),
        "financial_wealth": first_match(hh_header, config["financial_wealth"]),
        "physical_wealth": first_match(hh_header, config["physical_wealth"]),
        "income": first_match(hh_header, config["income"], required=False),
        "pension_wealth_hh": first_match(hh_header, config["pension_wealth_hh"], required=False),
        "pension_wealth_updated_hh": first_match(
            hh_header, config.get("pension_wealth_updated_hh", []), required=False
        )
        if config.get("pension_wealth_updated_hh")
        else None,
        "person_caser": first_match(person_header, config["caser"]),
        "hrp_flag": first_match(person_header, config["hrp_flag"]),
        "age17": first_match(person_header, config["age17"]),
        "person_pension": first_match(person_header, config["person_pension"], required=False),
    }
    return resolved


def load_inflation_factors(cpi_path: Path) -> dict[int, float]:
    cpi = pd.read_csv(cpi_path)
    year_col = cpi.columns[0]
    index_col = cpi.columns[1]
    cpi[year_col] = pd.to_numeric(cpi[year_col], errors="coerce")
    cpi[index_col] = pd.to_numeric(cpi[index_col], errors="coerce")
    cpi = cpi.dropna(subset=[year_col, index_col])
    # The attached CPI file is annual, which is useful for cross-checks but not precise enough
    # for end-of-round rebasing. We therefore use March end-of-round CPIH values from the ONS
    # monthly L522 series, base 2015=100.
    target_index = ROUND_END_CPIH[8]
    return {round_no: target_index / ROUND_END_CPIH[round_no] for round_no in ROUND_END_CPIH}


def resolve_path(path_arg: str) -> Path:
    path = Path(path_arg).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def validate_inputs(parser: argparse.ArgumentParser, data_dir: Path, cpi_path: Path) -> None:
    expected_layout = (
        "Expected layout: <repo>/source_data/WAS_data/*.tab and "
        "<repo>/source_data/CPI_Inflation.csv. Use --data-dir or --cpi-path "
        "if your files are somewhere else."
    )
    if not data_dir.is_dir():
        parser.error(f"WAS data directory not found: {data_dir}\n{expected_layout}")
    if not cpi_path.is_file():
        parser.error(f"CPI file not found: {cpi_path}\n{expected_layout}")


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return np.nan
    return float(np.average(values[mask], weights=weights[mask]))


def weighted_quantile(values: pd.Series, weights: pd.Series, quantile: float) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return np.nan
    v = values[mask].to_numpy(dtype=float)
    w = weights[mask].to_numpy(dtype=float)
    order = np.argsort(v)
    v = v[order]
    w = w[order]
    cum_w = np.cumsum(w)
    cutoff = quantile * cum_w[-1]
    return float(v[np.searchsorted(cum_w, cutoff, side="left")])


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    return weighted_quantile(values, weights, 0.5)


def weighted_group_stats(df: pd.DataFrame, value_col: str, weight_col: str) -> dict:
    return {
        "weighted_mean": weighted_mean(df[value_col], df[weight_col]),
        "weighted_median": weighted_median(df[value_col], df[weight_col]),
    }


def make_weighted_quantile_groups(df: pd.DataFrame, value_col: str, weight_col: str, n: int) -> pd.Series:
    values = df[value_col]
    weights = df[weight_col]
    mask = values.notna() & weights.notna() & (weights > 0)
    out = pd.Series(index=df.index, dtype="float64")
    if not mask.any():
        return out
    temp = (
        pd.DataFrame({"value": values[mask], "weight": weights[mask]}, index=df.index[mask])
        .sort_values("value")
        .copy()
    )
    cum_weight = temp["weight"].cumsum()
    total_weight = temp["weight"].sum()
    temp["quantile_group"] = np.ceil((cum_weight / total_weight) * n).clip(1, n).astype(int)
    out.loc[temp.index] = temp["quantile_group"]
    return out


def make_weighted_deciles(df: pd.DataFrame, value_col: str, weight_col: str) -> pd.Series:
    return make_weighted_quantile_groups(df, value_col, weight_col, 10)


def format_money(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:,.0f}"


def prepare_round_dataset(resolved: dict) -> tuple[pd.DataFrame, dict]:
    hh_usecols = [
        resolved["caser"],
        resolved["weight"],
        resolved["tenure"],
        resolved["total_wealth"],
        resolved["property_wealth"],
        resolved["financial_wealth"],
        resolved["physical_wealth"],
    ]
    if resolved["income"]:
        hh_usecols.append(resolved["income"])
    if resolved["pension_wealth_hh"]:
        hh_usecols.append(resolved["pension_wealth_hh"])
    if resolved["pension_wealth_updated_hh"]:
        hh_usecols.append(resolved["pension_wealth_updated_hh"])
    hh = pd.read_csv(resolved["hh_path"], sep="\t", usecols=list(dict.fromkeys(hh_usecols)), low_memory=False)

    person_usecols = [resolved["person_caser"], resolved["hrp_flag"], resolved["age17"]]
    if resolved["person_pension"]:
        person_usecols.append(resolved["person_pension"])
    person = pd.read_csv(
        resolved["person_path"],
        sep="\t",
        usecols=list(dict.fromkeys(person_usecols)),
        low_memory=False,
    )

    person[resolved["hrp_flag"]] = pd.to_numeric(person[resolved["hrp_flag"]], errors="coerce")
    hrp = person[person[resolved["hrp_flag"]] == 1][[resolved["person_caser"], resolved["age17"]]].copy()
    hrp = hrp.rename(
        columns={
            resolved["person_caser"]: "case_id",
            resolved["age17"]: "hrp_age17_band",
        }
    )

    hh = hh.rename(
        columns={
            resolved["caser"]: "case_id",
            resolved["weight"]: "weight",
            resolved["tenure"]: "tenure_code",
            resolved["total_wealth"]: "total_wealth",
            resolved["property_wealth"]: "property_wealth",
            resolved["financial_wealth"]: "financial_wealth",
            resolved["physical_wealth"]: "physical_wealth",
        }
    )
    if resolved["income"]:
        hh = hh.rename(columns={resolved["income"]: "equivalised_income"})
    if resolved["pension_wealth_hh"]:
        hh = hh.rename(columns={resolved["pension_wealth_hh"]: "pension_wealth_hh"})
    if resolved["pension_wealth_updated_hh"]:
        hh = hh.rename(columns={resolved["pension_wealth_updated_hh"]: "pension_wealth_updated_hh"})

    hh = hh.merge(hrp, on="case_id", how="left")

    if resolved["person_pension"]:
        pension_by_case = (
            person[[resolved["person_caser"], resolved["person_pension"]]]
            .rename(columns={resolved["person_caser"]: "case_id", resolved["person_pension"]: "person_pension"})
            .copy()
        )
        pension_by_case["person_pension"] = pd.to_numeric(pension_by_case["person_pension"], errors="coerce").fillna(0)
        pension_by_case = pension_by_case.groupby("case_id", as_index=False)["person_pension"].sum()
        hh = hh.merge(pension_by_case, on="case_id", how="left")
    else:
        hh["person_pension"] = np.nan

    for column in [
        "weight",
        "tenure_code",
        "total_wealth",
        "property_wealth",
        "financial_wealth",
        "physical_wealth",
        "hrp_age17_band",
        "equivalised_income",
        "pension_wealth_hh",
        "pension_wealth_updated_hh",
        "person_pension",
    ]:
        if column in hh.columns:
            hh[column] = pd.to_numeric(hh[column], errors="coerce")

    hh["pension_wealth"] = hh["pension_wealth_hh"] if "pension_wealth_hh" in hh.columns else np.nan
    if hh["pension_wealth"].isna().all() and hh["person_pension"].notna().any():
        hh["pension_wealth"] = hh["person_pension"]

    if resolved["round"] == 8 and "pension_wealth_updated_hh" in hh.columns:
        hh["wealth_excl_private_pension"] = hh["total_wealth"] - hh["pension_wealth"]
        hh["pension_wealth"] = hh["pension_wealth_updated_hh"]
        hh["total_wealth"] = hh["wealth_excl_private_pension"] + hh["pension_wealth"]
    else:
        hh["wealth_excl_private_pension"] = hh["total_wealth"] - hh["pension_wealth"]

    hh["private_wealth_combined"] = hh["financial_wealth"] + hh["pension_wealth"]
    hh["owner_group"] = pd.Series(pd.NA, index=hh.index, dtype="object")
    hh.loc[hh["tenure_code"].isin(OWNER_CODES), "owner_group"] = "Owner"
    hh.loc[hh["tenure_code"].isin(RENTER_CODES), "owner_group"] = "Renter"

    return hh, resolved


def add_price_views(df: pd.DataFrame, round_no: int, inflation_factors: dict[int, float]) -> pd.DataFrame:
    factor = inflation_factors[round_no]
    df = df.copy()
    df["price_basis_nominal"] = "Nominal"
    if round_no == 8:
        df["price_basis_real"] = "March 2022 prices"
    else:
        df["price_basis_real"] = "Real terms (March 2022 prices)"
    for col, _ in MEASURE_SPECS:
        df[f"{col}_nominal"] = df[col]
        df[f"{col}_real"] = df[col] * factor
    df["private_wealth_combined_nominal"] = df["private_wealth_combined"]
    df["private_wealth_combined_real"] = df["private_wealth_combined"] * factor
    return df


def summary_rows_for_group(round_no: int, group_name: str, group_df: pd.DataFrame) -> list[dict]:
    rows = []
    for price_basis, suffix in [("Nominal", "nominal"), ("Real terms (March 2022 prices)", "real")]:
        actual_price_basis = price_basis if round_no != 8 or suffix != "real" else "March 2022 prices"
        for col, label in MEASURE_SPECS:
            stats = weighted_group_stats(group_df, f"{col}_{suffix}", "weight")
            rows.append(
                {
                    "round": round_no,
                    "price_basis": actual_price_basis,
                    "group": group_name,
                    "measure": label,
                    "weighted_mean": stats["weighted_mean"],
                    "weighted_median": stats["weighted_median"],
                }
            )
    return rows


def overall_round_rows(round_no: int, hh: pd.DataFrame) -> list[dict]:
    rows = []
    for price_basis, suffix in [("Nominal", "nominal"), ("Real terms (March 2022 prices)", "real")]:
        actual_price_basis = price_basis if round_no != 8 or suffix != "real" else "March 2022 prices"
        for col, label in [
            ("total_wealth", "Overall median household wealth"),
            ("wealth_excl_private_pension", "Overall median household wealth excl private pension"),
        ]:
            rows.append(
                {
                    "round": round_no,
                    "price_basis": actual_price_basis,
                    "measure": label,
                    "weighted_median": weighted_median(hh[f"{col}_{suffix}"], hh["weight"]),
                }
            )
    return rows


def gap_rows(round_no: int, cohort: pd.DataFrame) -> list[dict]:
    owner = cohort[cohort["owner_group"] == "Owner"]
    renter = cohort[cohort["owner_group"] == "Renter"]
    rows = []
    for price_basis, suffix in [("Nominal", "nominal"), ("Real terms (March 2022 prices)", "real")]:
        actual_price_basis = price_basis if round_no != 8 or suffix != "real" else "March 2022 prices"
        for col, label in MEASURE_SPECS:
            owner_mean = weighted_mean(owner[f"{col}_{suffix}"], owner["weight"])
            renter_mean = weighted_mean(renter[f"{col}_{suffix}"], renter["weight"])
            owner_median = weighted_median(owner[f"{col}_{suffix}"], owner["weight"])
            renter_median = weighted_median(renter[f"{col}_{suffix}"], renter["weight"])
            rows.append(
                {
                    "round": round_no,
                    "price_basis": actual_price_basis,
                    "measure": label,
                    "owner_mean": owner_mean,
                    "renter_mean": renter_mean,
                    "mean_gap": owner_mean - renter_mean if pd.notna(owner_mean) and pd.notna(renter_mean) else np.nan,
                    "mean_ratio": owner_mean / renter_mean if pd.notna(renter_mean) and renter_mean not in (0, np.nan) else np.nan,
                    "owner_median": owner_median,
                    "renter_median": renter_median,
                    "median_gap": owner_median - renter_median if pd.notna(owner_median) and pd.notna(renter_median) else np.nan,
                    "median_ratio": owner_median / renter_median if pd.notna(renter_median) and renter_median not in (0, np.nan) else np.nan,
                }
            )
    return rows


def quantile_rows_for_group(round_no: int, group_name: str, group_df: pd.DataFrame) -> list[dict]:
    rows = []
    for price_basis, suffix in [("Nominal", "nominal"), ("Real terms (March 2022 prices)", "real")]:
        actual_price_basis = price_basis if round_no != 8 or suffix != "real" else "March 2022 prices"
        for col, label in MEASURE_SPECS:
            value_col = f"{col}_{suffix}"
            if value_col not in group_df.columns:
                continue
            for quantile_type, n in [("decile", 10), ("quintile", 5)]:
                q_col = make_weighted_quantile_groups(group_df, value_col, "weight", n)
                temp = group_df.copy()
                temp["_q"] = q_col.values
                for q in range(1, n + 1):
                    q_df = temp[temp["_q"] == q]
                    mean_val = weighted_mean(q_df[value_col], q_df["weight"]) if not q_df.empty else np.nan
                    rows.append({
                        "round": round_no,
                        "price_basis": actual_price_basis,
                        "group": group_name,
                        "measure": label,
                        "quantile_type": quantile_type,
                        "quantile_number": q,
                        "weighted_mean_wealth": mean_val,
                    })
    return rows


def renter_zero_rows(round_no: int, cohort: pd.DataFrame) -> dict:
    renters = cohort[cohort["owner_group"] == "Renter"].copy()
    if renters.empty:
        return [
            {
                "round": round_no,
                "price_basis": "Nominal",
                "renters_weighted_count": 0.0,
                "share_zero_private_wealth": np.nan,
                "share_near_zero_private_wealth": np.nan,
                "near_zero_threshold": NEAR_ZERO_PRIVATE_WEALTH,
            },
            {
                "round": round_no,
                "price_basis": "March 2022 prices" if round_no == 8 else "Real terms (March 2022 prices)",
                "renters_weighted_count": 0.0,
                "share_zero_private_wealth": np.nan,
                "share_near_zero_private_wealth": np.nan,
                "near_zero_threshold": NEAR_ZERO_PRIVATE_WEALTH,
            },
        ]
    rows = []
    for price_basis, suffix in [("Nominal", "nominal"), ("Real terms (March 2022 prices)", "real")]:
        actual_price_basis = price_basis if round_no != 8 or suffix != "real" else "March 2022 prices"
        zero = (renters[f"private_wealth_combined_{suffix}"] <= 0).astype(float)
        near_zero = (renters[f"private_wealth_combined_{suffix}"] <= NEAR_ZERO_PRIVATE_WEALTH).astype(float)
        rows.append(
            {
                "round": round_no,
                "price_basis": actual_price_basis,
                "renters_weighted_count": float(renters["weight"].fillna(0).sum()),
                "share_zero_private_wealth": weighted_mean(zero, renters["weight"]),
                "share_near_zero_private_wealth": weighted_mean(near_zero, renters["weight"]),
                "near_zero_threshold": NEAR_ZERO_PRIVATE_WEALTH,
            }
        )
    return rows


def plot_weighted_kde(ax, values: pd.Series, weights: pd.Series, color: str, label: str, cap: float) -> None:
    mask = values.notna() & weights.notna() & (weights > 0)
    if mask.sum() < 2:
        return
    clipped = values[mask].clip(lower=0, upper=cap)
    w = weights[mask]
    if clipped.nunique() < 2:
        return
    kde = gaussian_kde(clipped.to_numpy(dtype=float), weights=w.to_numpy(dtype=float), bw_method=0.2)
    x_grid = np.linspace(0, cap, 400)
    density = kde(x_grid)
    ax.plot(x_grid, density, color=color, linewidth=2, label=label)
    ax.fill_between(x_grid, density, color=color, alpha=0.12)


def save_round_charts(round_no: int, cohort: pd.DataFrame, output_dir: Path) -> None:
    owner = cohort[cohort["owner_group"] == "Owner"].copy()
    renter = cohort[cohort["owner_group"] == "Renter"].copy()

    finite_total = cohort["total_wealth_nominal"].dropna()
    cap = float(finite_total.quantile(0.98)) if not finite_total.empty else 1.0
    cap = max(cap, 1.0)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    plot_weighted_kde(axes[0], owner["total_wealth_nominal"], owner["weight"], BLUE, "Owners", cap)
    plot_weighted_kde(axes[0], renter["total_wealth_nominal"], renter["weight"], PINK, "Renters", cap)
    axes[0].set_title(f"Round {round_no}: weighted KDE, total wealth")
    axes[0].set_xlabel("Wealth (£)")
    axes[0].set_ylabel("Density")
    axes[0].xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"£{v/1e3:.0f}k"))
    axes[0].legend()

    finite_ex_pension = cohort["wealth_excl_private_pension_nominal"].dropna()
    cap2 = float(finite_ex_pension.quantile(0.98)) if not finite_ex_pension.empty else 1.0
    cap2 = max(cap2, 1.0)
    plot_weighted_kde(axes[1], owner["wealth_excl_private_pension_nominal"], owner["weight"], BLUE, "Owners", cap2)
    plot_weighted_kde(axes[1], renter["wealth_excl_private_pension_nominal"], renter["weight"], PINK, "Renters", cap2)
    axes[1].set_title(f"Round {round_no}: weighted KDE, wealth excl private pension")
    axes[1].set_xlabel("Wealth (£)")
    axes[1].set_ylabel("Density")
    axes[1].xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"£{v/1e3:.0f}k"))
    axes[1].legend()
    plt.tight_layout()
    fig.savefig(output_dir / f"round_{round_no}_kde.png", bbox_inches="tight")
    plt.close(fig)

    owner["decile"] = make_weighted_deciles(owner, "total_wealth_nominal", "weight")
    renter["decile"] = make_weighted_deciles(renter, "total_wealth_nominal", "weight")
    owner_dec = owner.dropna(subset=["decile"]).groupby("decile").apply(
        lambda g: weighted_mean(g["total_wealth_nominal"], g["weight"])
    )
    renter_dec = renter.dropna(subset=["decile"]).groupby("decile").apply(
        lambda g: weighted_mean(g["total_wealth_nominal"], g["weight"])
    )

    fig, ax = plt.subplots(figsize=(9, 4.5))
    deciles = np.arange(1, 11)
    ax.plot(deciles, owner_dec.reindex(deciles), marker="o", color=BLUE, linewidth=2, label="Owners")
    ax.plot(deciles, renter_dec.reindex(deciles), marker="o", color=PINK, linewidth=2, label="Renters")
    ax.set_title(f"Round {round_no}: weighted mean total wealth by within-group decile")
    ax.set_xlabel("Within-group wealth decile")
    ax.set_ylabel("Wealth (£)")
    ax.set_xticks(deciles)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"£{v/1e3:.0f}k"))
    ax.legend()
    plt.tight_layout()
    fig.savefig(output_dir / f"round_{round_no}_wealth_deciles.png", bbox_inches="tight")
    plt.close(fig)


def save_comparison_charts(gaps_df: pd.DataFrame, output_dir: Path) -> None:
    compare = gaps_df[
        (gaps_df["measure"].isin(["Total wealth", "Total wealth excl private pension"]))
        & (gaps_df["price_basis"] == "Nominal")
    ].copy()
    if compare.empty:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for measure, color in [("Total wealth", BLUE), ("Total wealth excl private pension", GREEN)]:
        sub = compare[compare["measure"] == measure].sort_values("round")
        axes[0].plot(sub["round"], sub["mean_gap"], marker="o", linewidth=2, color=color, label=measure)
        axes[1].plot(sub["round"], sub["mean_ratio"], marker="o", linewidth=2, color=color, label=measure)

    axes[0].set_title("Owner-renter weighted mean wealth gap")
    axes[0].set_xlabel("WAS round")
    axes[0].set_ylabel("Gap (£)")
    axes[0].yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"£{v/1e3:.0f}k"))

    axes[1].set_title("Owner-renter weighted mean wealth ratio")
    axes[1].set_xlabel("WAS round")
    axes[1].set_ylabel("Ratio")
    axes[1].axhline(1.0, color=GREY, linewidth=1, linestyle="--")

    for ax in axes:
        ax.set_xticks(sorted(compare["round"].unique()))
        ax.legend()
    plt.tight_layout()
    fig.savefig(output_dir / "comparison_owner_renter_gaps.png", bbox_inches="tight")
    plt.close(fig)


def analyse_round(
    round_no: int, data_dir: Path, output_dir: Path, inflation_factors: dict[int, float], with_charts: bool
) -> dict:
    resolved = resolve_round_columns(round_no, data_dir)
    hh, _ = prepare_round_dataset(resolved)
    hh = add_price_views(hh, round_no, inflation_factors)

    cohort = hh[hh["hrp_age17_band"].isin(AGE_BANDS_65_74)].copy()
    cohort = cohort[cohort["owner_group"].isin(["Owner", "Renter"])].copy()

    if with_charts:
        save_round_charts(round_no, cohort, output_dir)

    result = {
        "structure": resolved,
        "overall_rows": overall_round_rows(round_no, hh),
        "group_rows": summary_rows_for_group(round_no, "Owner", cohort[cohort["owner_group"] == "Owner"])
        + summary_rows_for_group(round_no, "Renter", cohort[cohort["owner_group"] == "Renter"]),
        "gap_rows": gap_rows(round_no, cohort),
        "quantile_rows": quantile_rows_for_group(round_no, "Owner", cohort[cohort["owner_group"] == "Owner"])
        + quantile_rows_for_group(round_no, "Renter", cohort[cohort["owner_group"] == "Renter"]),
        "renter_private_wealth_rows": renter_zero_rows(round_no, cohort),
        "sample_rows": [
            {
                "round": round_no,
                "all_households": len(hh),
                "cohort_households": len(cohort),
                "cohort_owners": int((cohort["owner_group"] == "Owner").sum()),
                "cohort_renters": int((cohort["owner_group"] == "Renter").sum()),
                "weighted_households": float(hh["weight"].fillna(0).sum()),
                "weighted_cohort_households": float(cohort["weight"].fillna(0).sum()),
                "inflation_factor_to_2022_prices": inflation_factors[round_no],
                "round_end_month": ROUND_END_MONTH[round_no],
                "round_end_cpih_index_2015_100": ROUND_END_CPIH[round_no],
            }
        ],
    }
    return result


def write_outputs(all_results: list[dict], output_dir: Path, with_charts: bool) -> None:
    structure_df = pd.DataFrame([r["structure"] for r in all_results])
    overall_df = pd.DataFrame([row for r in all_results for row in r["overall_rows"]])
    group_df = pd.DataFrame([row for r in all_results for row in r["group_rows"]])
    gaps_df = pd.DataFrame([row for r in all_results for row in r["gap_rows"]])
    quantile_df = pd.DataFrame([row for r in all_results for row in r["quantile_rows"]])
    renter_df = pd.DataFrame([row for r in all_results for row in r["renter_private_wealth_rows"]])
    sample_df = pd.DataFrame([row for r in all_results for row in r["sample_rows"]])

    structure_df.to_csv(output_dir / "round_structure_summary.csv", index=False)
    overall_df.to_csv(output_dir / "overall_medians_by_round.csv", index=False)
    group_df.to_csv(output_dir / "cohort_owner_renter_stats_by_round.csv", index=False)
    gaps_df.to_csv(output_dir / "owner_renter_gaps_by_round.csv", index=False)
    quantile_df.to_csv(output_dir / "wealth_by_quantile_owner_renter.csv", index=False)
    renter_df.to_csv(output_dir / "renter_private_wealth_shares.csv", index=False)
    sample_df.to_csv(output_dir / "sample_sizes_by_round.csv", index=False)

    if with_charts:
        save_comparison_charts(gaps_df, output_dir)

    workbook_path = output_dir / "was_retirement_observational_summary.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        structure_df.to_excel(writer, sheet_name="structure", index=False)
        sample_df.to_excel(writer, sheet_name="sample_sizes", index=False)
        overall_df.to_excel(writer, sheet_name="overall_medians", index=False)
        group_df.to_excel(writer, sheet_name="group_stats", index=False)
        gaps_df.to_excel(writer, sheet_name="gaps", index=False)
        quantile_df.to_excel(writer, sheet_name="wealth_by_quantile", index=False)
        renter_df.to_excel(writer, sheet_name="renter_private_wealth", index=False)

    summary_lines = []
    for round_no in sorted(group_df["round"].unique()):
        total_gap = gaps_df[
            (gaps_df["round"] == round_no) & (gaps_df["measure"] == "Total wealth") & (gaps_df["price_basis"] == "Nominal")
        ].iloc[0]
        excl_gap = gaps_df[
            (gaps_df["round"] == round_no) & (gaps_df["measure"] == "Total wealth excl private pension")
            & (gaps_df["price_basis"] == "Nominal")
        ].iloc[0]
        total_gap_real = gaps_df[
            (gaps_df["round"] == round_no)
            & (gaps_df["measure"] == "Total wealth")
            & (gaps_df["price_basis"].isin(["Real terms (March 2022 prices)", "March 2022 prices"]))
        ].iloc[0]
        excl_gap_real = gaps_df[
            (gaps_df["round"] == round_no)
            & (gaps_df["measure"] == "Total wealth excl private pension")
            & (gaps_df["price_basis"].isin(["Real terms (March 2022 prices)", "March 2022 prices"]))
        ].iloc[0]
        renters = renter_df[(renter_df["round"] == round_no) & (renter_df["price_basis"] == "Nominal")].iloc[0]
        renters_real = renter_df[
            (renter_df["round"] == round_no)
            & (renter_df["price_basis"].isin(["Real terms (March 2022 prices)", "March 2022 prices"]))
        ].iloc[0]
        overall_total = overall_df[
            (overall_df["round"] == round_no)
            & (overall_df["measure"] == "Overall median household wealth")
            & (overall_df["price_basis"] == "Nominal")
        ].iloc[0]["weighted_median"]
        overall_excl = overall_df[
            (overall_df["round"] == round_no)
            & (overall_df["measure"] == "Overall median household wealth excl private pension")
            & (overall_df["price_basis"] == "Nominal")
        ].iloc[0]["weighted_median"]
        overall_total_real = overall_df[
            (overall_df["round"] == round_no)
            & (overall_df["measure"] == "Overall median household wealth")
            & (overall_df["price_basis"].isin(["Real terms (March 2022 prices)", "March 2022 prices"]))
        ].iloc[0]["weighted_median"]
        overall_excl_real = overall_df[
            (overall_df["round"] == round_no)
            & (overall_df["measure"] == "Overall median household wealth excl private pension")
            & (overall_df["price_basis"].isin(["Real terms (March 2022 prices)", "March 2022 prices"]))
        ].iloc[0]["weighted_median"]
        summary_lines.append(
            {
                "round": round_no,
                "overall_median_total_nominal": format_money(overall_total),
                "overall_median_excl_private_pension_nominal": format_money(overall_excl),
                "owner_mean_total_nominal": format_money(total_gap["owner_mean"]),
                "renter_mean_total_nominal": format_money(total_gap["renter_mean"]),
                "mean_gap_total_nominal": format_money(total_gap["mean_gap"]),
                "mean_ratio_total_nominal": round(total_gap["mean_ratio"], 2) if pd.notna(total_gap["mean_ratio"]) else np.nan,
                "owner_mean_excl_private_pension_nominal": format_money(excl_gap["owner_mean"]),
                "renter_mean_excl_private_pension_nominal": format_money(excl_gap["renter_mean"]),
                "mean_gap_excl_private_pension_nominal": format_money(excl_gap["mean_gap"]),
                "mean_ratio_excl_private_pension_nominal": round(excl_gap["mean_ratio"], 2)
                if pd.notna(excl_gap["mean_ratio"])
                else np.nan,
                "overall_median_total_real_2022_prices": format_money(overall_total_real),
                "overall_median_excl_private_pension_real_2022_prices": format_money(overall_excl_real),
                "owner_mean_total_real_2022_prices": format_money(total_gap_real["owner_mean"]),
                "renter_mean_total_real_2022_prices": format_money(total_gap_real["renter_mean"]),
                "mean_gap_total_real_2022_prices": format_money(total_gap_real["mean_gap"]),
                "mean_ratio_total_real_2022_prices": round(total_gap_real["mean_ratio"], 2)
                if pd.notna(total_gap_real["mean_ratio"])
                else np.nan,
                "owner_mean_excl_private_pension_real_2022_prices": format_money(excl_gap_real["owner_mean"]),
                "renter_mean_excl_private_pension_real_2022_prices": format_money(excl_gap_real["renter_mean"]),
                "mean_gap_excl_private_pension_real_2022_prices": format_money(excl_gap_real["mean_gap"]),
                "mean_ratio_excl_private_pension_real_2022_prices": round(excl_gap_real["mean_ratio"], 2)
                if pd.notna(excl_gap_real["mean_ratio"])
                else np.nan,
                "renter_share_zero_private_wealth_nominal": round(100 * renters["share_zero_private_wealth"], 1)
                if pd.notna(renters["share_zero_private_wealth"])
                else np.nan,
                "renter_share_near_zero_private_wealth_nominal": round(100 * renters["share_near_zero_private_wealth"], 1)
                if pd.notna(renters["share_near_zero_private_wealth"])
                else np.nan,
                "renter_share_zero_private_wealth_real_2022_prices": round(100 * renters_real["share_zero_private_wealth"], 1)
                if pd.notna(renters_real["share_zero_private_wealth"])
                else np.nan,
                "renter_share_near_zero_private_wealth_real_2022_prices": round(
                    100 * renters_real["share_near_zero_private_wealth"], 1
                )
                if pd.notna(renters_real["share_near_zero_private_wealth"])
                else np.nan,
            }
        )

    pd.DataFrame(summary_lines).to_csv(output_dir / "summary_table_for_reporting.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Directory containing the WAS round 5 to 8 .tab files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to write output tables and charts.",
    )
    parser.add_argument(
        "--cpi-path",
        default=str(DEFAULT_CPI_PATH),
        help="CSV file containing annual CPI/CPIH index values.",
    )
    parser.add_argument(
        "--with-charts",
        action="store_true",
        help="Also create the KDE and decile comparison charts.",
    )
    args = parser.parse_args()

    data_dir = resolve_path(args.data_dir)
    cpi_path = resolve_path(args.cpi_path)
    output_dir = resolve_path(args.output_dir)
    validate_inputs(parser, data_dir, cpi_path)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        output_dir = DEFAULT_OUTPUT_DIR

    inflation_factors = load_inflation_factors(cpi_path)
    all_results = []
    for round_no in [5, 6, 7, 8]:
        print(f"Analysing WAS round {round_no}...")
        all_results.append(analyse_round(round_no, data_dir, output_dir, inflation_factors, args.with_charts))

    write_outputs(all_results, output_dir, args.with_charts)

    metadata = {
        "age_bands_used_for_65_74": sorted(AGE_BANDS_65_74),
        "owner_codes": sorted(OWNER_CODES),
        "renter_codes": sorted(RENTER_CODES),
        "near_zero_private_wealth_threshold": NEAR_ZERO_PRIVATE_WEALTH,
        "target_price_year": TARGET_PRICE_YEAR,
        "round_end_month": ROUND_END_MONTH,
        "round_end_cpih_index_2015_100": ROUND_END_CPIH,
        "inflation_factors_to_2022_prices": inflation_factors,
        "round_8_total_wealth_method": "TotWlth_oldR8 - TOTPEN_oldR8_aggr + totalpenr8_aggr",
    }
    (output_dir / "analysis_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Done. Outputs written to: {output_dir}")


if __name__ == "__main__":
    main()
