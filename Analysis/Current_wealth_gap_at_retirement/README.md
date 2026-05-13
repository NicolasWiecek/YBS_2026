# Current Wealth Gap at Retirement

This analysis script looks for input files relative to the repository, so it can be cloned or moved without editing hardcoded paths.

Expected layout:

```text
YBS_WAS_modelling/
  source_data/
    CPI_Inflation.csv
    WAS_data/
      was_round_5_hhold.tab
      was_round_5_person.tab
      was_round_6_hhold.tab
      was_round_6_person.tab
      was_round_7_hhold.tab
      was_round_7_person.tab
      was_round_8_hhold.tab
      was_round_8_person.tab
  Analysis/
    Current_wealth_gap_at_retirement/
      was_retirement_observational_rounds_5_8.py
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
python .\was_retirement_observational_rounds_5_8.py
```

If the data is stored somewhere else, pass the paths explicitly:

```powershell
python .\was_retirement_observational_rounds_5_8.py --data-dir "C:\path\to\WAS_data" --cpi-path "C:\path\to\CPI_Inflation.csv"
```

The WAS `.tab` files are large. Standard GitHub repositories reject individual files over 100 MB, so share the source data using Git LFS, a release asset, or separate download instructions if collaborators need to reproduce the analysis.
