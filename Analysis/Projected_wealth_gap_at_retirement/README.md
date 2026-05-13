# Projected Wealth Gap at Retirement

This analysis script resolves input files from the repository-level `source_data` folder, so it can be moved or cloned without editing machine-specific paths.

Expected layout:

```text
YBS_WAS_modelling/
  source_data/
    CPI_Inflation.csv
    Consumption_deciles_split_owners_renters_weekly.csv
    Disposable income per head .xlsx
    Median household wealth.xlsx
    UK average house price data.xlsx
    WAS_data/
      was_round_8_hhold.tab
      was_round_8_person.tab
  Analysis/
    Projected_wealth_gap_at_retirement/
      was_wealth_gap_analysis_v4.py
      requirements.txt
```

Set up the Python environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Run the analysis:

```powershell
python .\was_wealth_gap_analysis_v4.py
```

Outputs are written to `outputs_v4` in this folder.

The WAS `.tab` files are large. Standard GitHub repositories reject individual files over 100 MB, so share the source data using Git LFS, release assets, or separate download instructions if collaborators need to reproduce the analysis.
