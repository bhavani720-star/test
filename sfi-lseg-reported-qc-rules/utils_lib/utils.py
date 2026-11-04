"""Local stand-in for model management's shared utils (the "toolbox" file).

The LSEG reported script calls six functions from it. The real code is not shared with us yet, so each one here
does what the script's call implies. They are guesses: when you get the real utils_lib, pass its parent folder with
run_script.py --utils-dir <folder> and these are not used.

    prepaire_year_column_input_test(df)          adds the `year` column the script joins on
    get_change(current, previous)                % change, (current - previous) / previous * 100
    prioritize_list_of_suspicious_datapoints()   keeps the largest companies by market cap
    include_value_in_summary_report_...()        picks the flagged value(s) for the summary sheet
    write_to_excel(sheets_dict, name, date)      one workbook, one sheet per entry

Where the real write_to_excel saves the file (local disk or S3, given the script imports boto3) is an open question.
Here it goes to the folder in the QC_OUTPUT_DIR environment variable, which run_script.py sets.
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd


def prepaire_year_column_input_test(df):
    """Guess: the extract carries the fiscal year under another name, and this makes it `year` (a whole number)."""
    df = df.copy()
    if "year" not in df.columns:
        if "fiscal_year" in df.columns:
            df = df.rename(columns={"fiscal_year": "year"})
        elif "period_end_date" in df.columns:
            df["year"] = pd.to_datetime(df.pop("period_end_date")).dt.year
        else:
            raise KeyError("no year column: expected 'year', 'fiscal_year' or 'period_end_date'")
    df["year"] = pd.to_numeric(df["year"]).astype(int)
    return df


def get_change(current, previous):
    """% change from previous to current. Infinite when previous is 0 (the script then drops those rows)."""
    if pd.isna(current) or pd.isna(previous):
        return np.nan
    if previous == 0:
        return 0.0 if current == 0 else np.inf
    return (current - previous) / previous * 100


def prioritize_list_of_suspicious_datapoints(df, df_org_market_cap, cols_to_sort_by, nr_of_companies):
    """Keep the rows of the `nr_of_companies` largest companies. Returns them with a `company_market_cap` column,
    which the script drops afterwards. (The script itself first keeps only fiscal years from `start`.)"""
    market_cap = df_org_market_cap[["organization_perm_id", "company_market_cap"]].drop_duplicates("organization_perm_id")
    df = df.drop(columns=["company_market_cap"], errors="ignore").merge(market_cap, on="organization_perm_id", how="left")
    df = df.sort_values(cols_to_sort_by, ascending=False)
    top = df["organization_perm_id"].drop_duplicates().head(nr_of_companies)
    return df[df["organization_perm_id"].isin(top)]


def include_value_in_summary_report_for_variance_check_lseg_reported(row):
    """Variance check: the flagged measure's value in the current and in the previous extract."""
    measure = row["Outlier_for_data_field"]
    return {"current": row[f"{measure}_current"], "previous": row[f"{measure}_previous"]}


def include_value_in_summary_report_lseg_reported(row):
    """YoY checks: the flagged measure's current value."""
    return row[row["Outlier_for_data_field"]]


def write_to_excel(sheets_dict, file_name, slice_date):
    out_dir = Path(os.environ.get("QC_OUTPUT_DIR", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{file_name}_{slice_date}.xlsx"
    with pd.ExcelWriter(path) as writer:
        for sheet_name, frame in sheets_dict.items():
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    sizes = ", ".join(f"{name}: {len(frame)} rows" for name, frame in sheets_dict.items())
    print(f"  [utils.write_to_excel] wrote {path} ({sizes})")
    return path
