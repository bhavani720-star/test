"""Run model management's LSEG reported input test (scope 1-3), unchanged, on local files.

On StarMine the script is not run on its own. The job hands it four things, and the script calls six functions from
model management's shared utils:

    metadata            the test's settings (start year, % limits, max outliers); written in the script's own docstring
    get_df_for_slice()  the ADC extract stored at reference_datetime: the "previous" extract
    get_all_inputs()    this run's inputs: lseg_reported (the current extract), marketcap, icb_info, univ_inactive
    current_date        the date of this run; it names the Excel file
    utils_lib.utils     get_change, prepaire_year_column_input_test, prioritize_list_of_suspicious_datapoints,
                        two include_value_in_summary_report_... functions, write_to_excel

This runner supplies them from a folder of files and runs script/input_test_lseg_reported_task.py exactly as it is.

    python run_script.py --input sample_data
    python run_script.py --input sample_data --set diff_in_abs_value=50000
    python run_script.py --input sample_data --shuffle-rows      (shows the unsorted-input trap)

--input         folder with current_extract, previous_extract, marketcap, icb_info, univ_inactive (.csv/.xlsx/.parquet)
--mapping       column_mapping.csv: renames source field names to the names the script uses
--set           KEY=VALUE changes one metadata setting for this run, e.g. --set max_number_of_outliers=100
--current-date  YYYY-MM-DD; default: the latest as_of_date in the current extract
--utils-dir     folder that holds the real utils_lib package; default: the local stand-in in utils_lib/
--shuffle-rows  hand the current extract over in random row order, to show what the script does with unsorted data
"""
import argparse
import importlib.util
import json
import os
import sys
import traceback
import types
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "script" / "input_test_lseg_reported_task.py"

INPUTS = ["current_extract", "previous_extract", "marketcap", "icb_info", "univ_inactive"]
DIRECT = ["co2_emiss_scope1", "co2_emiss_scope2", "co2_emiss_scope2_marketbased", "co2_emiss_scope2_locbased"]
MEASURES = DIRECT + ["total_upstream_scope3", "total_downstream_scope3"]
# Every column the script (or the stand-in utils) reads from each input. If one is missing, the script stops with a KeyError.
REQUIRED = {
    "current_extract": ["organization_perm_id", *DIRECT, "as_of_date"],
    "previous_extract": ["organization_perm_id", *DIRECT, "as_of_date"],
    "marketcap": ["organization_perm_id", "company_market_cap"],
    "icb_info": ["organization_perm_id", "name", "ric", "industry_name"],
    "univ_inactive": ["organizationid", "name", "ric", "status"],
}
YEAR_SOURCES = ["year", "fiscal_year", "period_end_date"]   # what the stand-in prepaire_year_column_input_test accepts
ID_COLUMNS = {"organization_perm_id": str, "organizationid": str}
SHOW = ["organization_perm_id", "name", "year", "measure", "reason_for_inclusion"]

LOG = []


def log(text=""):
    print(text)
    LOG.append(text)


def read_table(path):
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=ID_COLUMNS)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype=ID_COLUMNS)


def load_inputs(folder):
    tables, missing = {}, []
    for name in INPUTS:
        files = [f for f in folder.glob(f"{name}.*") if f.suffix.lower() in (".csv", ".xlsx", ".xls", ".parquet")]
        if files:
            tables[name] = read_table(files[0])
            log(f"  {files[0].name:<22} {len(tables[name]):>5} rows")
        else:
            missing.append(name)
    if missing:
        raise SystemExit(f"\nNOT RUN: no file for {', '.join(missing)} in {folder} (.csv, .xlsx or .parquet)")
    return tables


def apply_mapping(tables, mapping_path):
    mapping = pd.read_csv(mapping_path)
    for name, table in tables.items():
        rows = mapping[mapping["input"].isin([name, "both extracts"] if "extract" in name else [name])]
        renames = {s: t for s, t in zip(rows["source_column"], rows["script_column"]) if s in table.columns and s != t}
        if renames:
            log(f"  mapping: {name}: renamed {len(renames)} columns")
            for source, target in renames.items():
                log(f"    {source:<32} -> {target}")
            tables[name] = table.rename(columns=renames)
    return tables


def check_columns(tables):
    problems = []
    for name, columns in REQUIRED.items():
        problems += [f"{name}: {c}" for c in columns if c not in tables[name].columns]
    for name in ("current_extract", "previous_extract"):
        table = tables[name]
        if not any(c in table.columns for c in YEAR_SOURCES):
            problems.append(f"{name}: a year column ({' / '.join(YEAR_SOURCES)})")
        for part in ("up_scope3", "down_scope3"):
            if not any(part in c for c in table.columns):
                log(f"  warning: {name} has no '{part}' columns. The script adds them up, so that total will be empty.")
    # The script finds the 'verification' columns in the current extract and drops them from both extracts.
    verification = [c for c in tables["current_extract"].columns if "verification" in c]
    problems += [f"previous_extract: {c} (the script drops it from both extracts)"
                 for c in verification if c not in tables["previous_extract"].columns]
    if not problems:
        log("  every column the script reads is present")
        return
    log(f"\nNOT RUN: the script reads {len(problems)} column(s) that are not in the input:")
    for problem in problems:
        log(f"  missing  {problem}")
    log("Add --mapping column_mapping.csv, or fix the mapping file, and run again.")
    raise SystemExit(2)


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def read_metadata(code):
    """The settings StarMine hands over as `metadata` are written in the script's docstring: one 'key: value' a line."""
    block = code.split("Metadata information for the current test:", 1)[1].split('"""', 1)[0]
    pairs = [line.strip().partition(":") for line in block.splitlines() if ":" in line]
    return {key.strip(): parse_value(value.strip()) for key, _, value in pairs}


def stub_unused_imports():
    """The script imports boto3 but never uses it. If it isn't installed, give the import an empty module."""
    if importlib.util.find_spec("boto3") is None:
        sys.modules["boto3"] = types.ModuleType("boto3")
        log("  note: boto3 is not installed. The script imports it but never calls it, so an empty stand-in is used.")


def change(current, previous):
    nominal = current - previous
    return nominal, nominal / previous * 100


def expected_counts(scope, md):
    """Work out, per measure, how many datapoints the variance and YoY checks should flag before prioritisation,
    and compare with how many the script reported."""
    both, current = scope["datapoints_in_both_deliveries_raw"], scope["comco_current"]
    rows = []
    for col in MEASURES:
        nominal, pct = change(both[f"{col}_current"], both[f"{col}_previous"])
        var = ((pct > md["change_diference_for_variance_test_up"]) | (pct < md["change_diference_for_variance_test_down"])) \
            & (nominal.abs() > md["diff_in_abs_value"]) & np.isfinite(pct)
        grouped = current.groupby("organization_perm_id")[col]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            nominal, pct = grouped.diff(), grouped.pct_change() * 100   # same call as the script, line 153
        yoy = ((pct < md["per_of_change_in_time_threshold_min"]) | (pct > md["per_of_change_in_time_threshold_max"])) \
            & (nominal.abs() > md["diff_in_abs_value"]) & np.isfinite(pct) & current[col].notna() & (pct != -100)
        reported = [(scope[name]["Outlier_for_data_field"] == col).sum() for name in ("df_var", "df_yoy", "df_yoy_iso")]
        rows.append({"measure": col, "variance: flagged": int(var.sum()), "reported": reported[0],
                     "YoY: flagged": int(yoy.sum()), "reported ": reported[1], "Iso F: reported": reported[2]})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--current-date")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    parser.add_argument("--utils-dir", type=Path)
    parser.add_argument("--shuffle-rows", action="store_true")
    args = parser.parse_args()
    if args.shuffle_rows and args.output_dir == HERE / "output":
        args.output_dir = HERE / "output" / "shuffled"  # keep the demo's report away from the real one

    log(f"LSEG reported thin-thread run  {datetime.now():%Y-%m-%d %H:%M:%S}  (pandas {pd.__version__})")

    log("\n[1/4] Load the inputs")
    tables = load_inputs(args.input)
    if args.mapping:
        tables = apply_mapping(tables, args.mapping)
    check_columns(tables)

    log("\n[2/4] Prepare what the script expects")
    code = SCRIPT.read_text(encoding="utf-8")
    metadata = read_metadata(code)
    for setting in args.set:
        key, _, value = setting.partition("=")
        if key not in metadata:
            raise SystemExit(f"--set {setting}: '{key}' is not a metadata setting. Settings: {', '.join(metadata)}")
        log(f"  --set: {key} = {parse_value(value)} (the script says {metadata[key]})")
        metadata[key] = parse_value(value)
    log(f"  metadata from the script's docstring: {len(metadata)} settings, start {metadata['start']}, "
        f"reference_datetime {metadata['reference_datetime']}")

    current, previous = tables["current_extract"], tables["previous_extract"]
    if args.shuffle_rows:
        current = current.sample(frac=1, random_state=1).reset_index(drop=True)
        log("  --shuffle-rows: the current extract is handed over in random row order")
    year = next(c for c in YEAR_SOURCES if c in current.columns)
    if not current.equals(current.sort_values(["organization_perm_id", year])):
        log("  warning: the current extract is not sorted by organization_perm_id and year. The Isolation Forest "
            "check works out year-on-year changes in the order the rows arrive (script lines 206-210).")
    for label, table in (("current ", current), ("previous", previous)):
        as_of = sorted(pd.to_datetime(table["as_of_date"]).dt.strftime("%Y-%m-%d").unique())
        years = pd.to_numeric(table[year])
        log(f"  {label} extract as of {', '.join(as_of)}: {len(table)} rows, {table['organization_perm_id'].nunique()} "
            f"companies, fiscal years {years.min()}-{years.max()}")
    reference = datetime.fromisoformat(str(metadata["reference_datetime"])).date()
    if reference not in set(pd.to_datetime(previous["as_of_date"]).dt.date):
        log(f"  note: the script asks for the extract stored at {reference}; the previous extract given is from "
            "another date. It is used as the previous extract anyway.")
    current_date = pd.Timestamp(args.current_date) if args.current_date else pd.to_datetime(current["as_of_date"]).max()
    log(f"  current_date = {current_date:%Y-%m-%d}")

    calls = []

    def get_df_for_slice(path, reference_datetime):
        calls.append((path, reference_datetime))
        return previous.copy()

    def get_all_inputs():
        return {"lseg_reported": current.copy(), "marketcap": tables["marketcap"].copy(),
                "icb_info": tables["icb_info"].copy(), "univ_inactive": tables["univ_inactive"].copy()}

    log(f"\n[3/4] Run {SCRIPT.name} (unchanged)")
    os.environ["QC_OUTPUT_DIR"] = str(args.output_dir)
    sys.path.insert(0, str(args.utils_dir or HERE))
    log(f"  utils_lib from: {'real package in ' + str(args.utils_dir) if args.utils_dir else 'local stand-in'}")
    stub_unused_imports()
    scope = {"__name__": "__main__", "__file__": str(SCRIPT), "metadata": metadata, "current_date": current_date,
             "get_df_for_slice": get_df_for_slice, "get_all_inputs": get_all_inputs}
    try:
        exec(compile(code, str(SCRIPT), "exec"), scope)
    except ValueError as error:
        if "Cannot set a DataFrame with multiple columns" not in str(error):
            raise
        line = next((f.lineno for f in reversed(traceback.extract_tb(error.__traceback__)) if f.filename == str(SCRIPT)), "?")
        raise SystemExit(f"\nThe script stopped at line {line}: {error}\nOne of the checks flagged nothing, so its table "
                         "is empty. On an empty table, apply(..., axis=1) returns a table instead of a column, and the "
                         "script cannot store it.\nAs written, the script needs at least one flag from each of the "
                         "variance, YoY and Isolation Forest checks.")
    log(f"  get_df_for_slice was asked for '{calls[0][0].rsplit('/', 1)[-1]}' at {calls[0][1]}")

    log("\n[4/4] Result")
    report = scope["summary_report"]
    log(f"  summary_report: {len(report)} row(s)")
    log(report.groupby("reason_for_inclusion", sort=False).size().to_string(header=False))
    log("")
    log(report[SHOW].to_string(index=False) if len(report) else "  (empty: nothing flagged)")

    log("\n  check: flagged datapoints per measure, worked out separately, and how many the script reported")
    log(expected_counts(scope, metadata).to_string(index=False))
    log(f"  (a check that flags more than {metadata['max_number_of_outliers']} keeps only fiscal years from "
        f"{metadata['start']} and the top {metadata['number_of_companies']} companies by market cap)")

    compare = scope["compare"]
    new = compare[compare["_merge"] == "left_only"]
    if len(new):
        by_year = new.groupby("year").size()
        log(f"\n  not checked by the variance check: {len(new)} company-year(s) are only in the current extract "
            f"({', '.join(f'{y}: {n}' for y, n in by_year.items())}). Only the YoY checks look at them.")
        brand_new = sorted(set(new["organization_perm_id"]) - set(compare.loc[compare["_merge"] != "left_only",
                                                                               "organization_perm_id"]))
        if brand_new:
            log(f"  companies that are new in the current extract: {', '.join(brand_new)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / f"run_log_{current_date:%y%m%d}{'_shuffled' if args.shuffle_rows else ''}.txt"
    log_path.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(f"\nlog saved to {log_path}")


if __name__ == "__main__":
    main()
