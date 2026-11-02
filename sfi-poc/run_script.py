"""Run model management's EVIC delta script, unchanged, on a CSV / Excel / parquet file.


On StarMine the script is not run on its own. The job hands it two variables and a helper package:

    input_tests_evic_df   every row the EVIC input test (init) flagged, saved each week with an as_of_date
    current_date          the date of this week's run
    utils_lib.utils       model management's shared toolbox (the script only calls utils.write_to_excel)

This runner supplies those three things and runs script/input_test_evic_delta_task.py exactly as it is.

    python run_script.py --input sample_data/input_tests_evic_history.csv
    python run_script.py --input sample_data/weekly
    python run_script.py --input sample_data/input_tests_evic_history_tr_names.xlsx --mapping column_mapping.csv
    python run_script.py --input sample_data/input_tests_evic_history.csv --no-date-fix     (shows the silent-empty trap)

--input        one file with an as_of_date column, or a folder of weekly files named *_YYYY-MM-DD.csv/.xlsx/.parquet
--mapping      column_mapping.csv: renames TR. field names (or DaaS names) to the names the script uses
--current-date YYYY-MM-DD; default: the latest as_of_date in the input
--utils-dir    folder that holds the real utils_lib package; default: the local stand-in in utils_lib/
--no-date-fix  hand the data over as read (as_of_date stays text) to show what happens without the date step
--pandas3-fix  the script runs on pandas 2.x as written; this drops 'axis=1' from one drop() call, in memory only
"""
import argparse
import importlib.util
import os
import re
import sys
import types
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "script" / "input_test_evic_delta_task.py"

KEY = ["organization_perm_id", "year", "measure"]
# Every column the script merges on, drops or renames. If one is missing, the script stops with a KeyError.
REQUIRED = KEY + [
    "org_id", "ric", "name",
    "tr_f_evexclceadjust", "market_cap_os", "debt_incl_equity_and_min_interest_total", "debt_total",
    "minority_interest_total", "preferred_shareholders_equity", "market_capitalization",
    "possible_reason_of_evic_change_yoy", "reason_for_inclusion", "comment", "as_of_date",
]
SHOW = ["organization_perm_id", "name", "year", "measure", "reason_for_inclusion"]
DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")
PANDAS3_EDIT = ('"reason_for_inclusion_previous"], axis=1)', '"reason_for_inclusion_previous"])')

LOG = []


def log(text=""):
    print(text)
    LOG.append(text)


def read_table(path):
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype={"organization_perm_id": str})
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"organization_perm_id": str})


def load_history(path):
    """One file, or a folder of weekly files. For weekly files the as_of_date comes from the file name."""
    if path.is_file():
        return read_table(path)
    weeks = []
    for file in sorted(path.iterdir()):
        match = DATE_IN_NAME.search(file.stem)
        if not match or file.suffix.lower() not in (".csv", ".xlsx", ".xls", ".parquet"):
            continue
        week = read_table(file)
        if "as_of_date" not in week.columns:
            week["as_of_date"] = match.group(1)
        weeks.append(week)
    if not weeks:
        raise SystemExit(f"No weekly files named *_YYYY-MM-DD.* in {path}")
    return pd.concat(weeks, ignore_index=True)


def apply_mapping(df, mapping_path):
    mapping = pd.read_csv(mapping_path)
    renames = {s: t for s, t in zip(mapping["source_column"], mapping["script_column"]) if s in df.columns and s != t}
    if renames:
        log(f"  mapping: renamed {len(renames)} columns")
        for source, target in renames.items():
            log(f"    {source:<32} -> {target}")
    return df.rename(columns=renames)


def check_columns(df):
    missing = [c for c in REQUIRED if c not in df.columns]
    extra = [c for c in df.columns if c not in REQUIRED]
    if extra:
        log(f"  note: {len(extra)} extra column(s) not used by the script: {', '.join(extra)}. "
            "The script keeps them as <name>_current and <name>_previous in the report.")
    if not missing:
        log(f"  all {len(REQUIRED)} columns the script reads are present")
        return
    mapping = pd.read_csv(HERE / "column_mapping.csv")
    source_of = dict(zip(mapping["script_column"], mapping["source_column"]))
    log(f"\nNOT RUN: the script reads {len(missing)} column(s) that are not in the input:")
    for column in missing:
        hint = f"   (source field: {source_of[column]})" if source_of.get(column, column) != column else ""
        log(f"  missing  {column}{hint}")
    log("Add --mapping column_mapping.csv, or fix the mapping file, and run again.")
    raise SystemExit(2)


def load_script(pandas3_fix):
    code = SCRIPT.read_text(encoding="utf-8")
    if pandas3_fix:
        if code.count(PANDAS3_EDIT[0]) != 1:
            raise SystemExit("--pandas3-fix: the drop(..., axis=1) line was not found exactly once; script differs.")
        code = code.replace(*PANDAS3_EDIT)
        log("  pandas 3 fix applied in memory: drop(columns=[...], axis=1) -> drop(columns=[...])")
    return compile(code, str(SCRIPT), "exec")


def stub_unused_imports():
    """The script imports boto3 but never uses it. If it isn't installed, give the import an empty module."""
    if importlib.util.find_spec("boto3") is None:
        sys.modules["boto3"] = types.ModuleType("boto3")
        log("  note: boto3 is not installed. The script imports it but never calls it, so an empty stand-in is used.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--current-date")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    parser.add_argument("--utils-dir", type=Path)
    parser.add_argument("--no-date-fix", action="store_true")
    parser.add_argument("--pandas3-fix", action="store_true")
    args = parser.parse_args()
    if args.no_date_fix and args.output_dir == HERE / "output":
        args.output_dir = HERE / "output" / "no_date_fix"  # keep the demo's empty report away from the real one

    log(f"EVIC delta thin-thread run  {datetime.now():%Y-%m-%d %H:%M:%S}  (pandas {pd.__version__})")

    log("\n[1/4] Load the input")
    df = load_history(args.input)
    log(f"  {len(df)} rows from {args.input}")
    if args.mapping:
        df = apply_mapping(df, args.mapping)
    check_columns(df)

    log("\n[2/4] Prepare the two variables the script expects")
    if args.no_date_fix:
        # As read from the file: as_of_date is text, current_date is a date. The script compares them with ==.
        current_date = pd.Timestamp(args.current_date or df["as_of_date"].max())
        log(f"  --no-date-fix: as_of_date left as {df['as_of_date'].dtype} text, current_date = {current_date!r}")
    else:
        # The script compares as_of_date with current_date using ==, so both must be the same type.
        # Text from a CSV never equals a date: the script would find no rows and write an empty report.
        df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.normalize()
        df["organization_perm_id"] = df["organization_perm_id"].astype(str)
        df["year"] = pd.to_numeric(df["year"]).astype(int)
        current_date = pd.Timestamp(args.current_date) if args.current_date else df["as_of_date"].max()

        current = df[df["as_of_date"] == current_date]
        earlier = df[df["as_of_date"] < current_date]
        later = df[df["as_of_date"] > current_date]
        log(f"  current_date = {current_date:%Y-%m-%d}: {len(current)} rows this week, "
            f"{len(earlier)} rows from {earlier['as_of_date'].nunique()} earlier week(s)")
        if len(later):
            log(f"  warning: {len(later)} rows are dated after current_date; the script counts them as 'previous'.")
        if current.empty:
            raise SystemExit("NOT RUN: no rows have as_of_date equal to current_date.")

    log(f"\n[3/4] Run {SCRIPT.name}{'' if args.pandas3_fix else ' (unchanged)'}")
    os.environ["QC_OUTPUT_DIR"] = str(args.output_dir)
    sys.path.insert(0, str(args.utils_dir or HERE))
    log(f"  utils_lib from: {'real package in ' + str(args.utils_dir) if args.utils_dir else 'local stand-in'}")
    stub_unused_imports()
    scope = {"__name__": "__main__", "__file__": str(SCRIPT), "input_tests_evic_df": df, "current_date": current_date}
    try:
        exec(load_script(args.pandas3_fix), scope)
    except ValueError as error:
        if "Cannot specify both 'axis'" not in str(error):
            raise
        raise SystemExit(f"\nThe script stopped: {error}\nIt calls drop(columns=[...], axis=1), which pandas 2 "
                         f"accepts and pandas 3 refuses. This environment has pandas {pd.__version__}.\n"
                         "Install pandas 2.x (see requirements.txt), or add --pandas3-fix.")

    log("\n[4/4] Result")
    report = scope["summary_report"]
    log(f"  delta report: {len(report)} row(s)")
    log(report[SHOW].to_string(index=False) if len(report) else "  (empty: no new data points)")

    if args.no_date_fix:
        log("\n  The script ran without an error but found no rows for this week: as_of_date is text and "
            "current_date is a date, so == is never true. It wrote an empty report and gave no warning "
            "(the script turns warnings off). This is why run_script.py converts as_of_date first.")
    else:
        # Work out the expected delta independently and compare with what the script reported.
        seen = set(map(tuple, earlier[KEY].to_numpy()))
        new = current[[tuple(k) not in seen for k in current[KEY].to_numpy()]]
        log(f"\n  cross-check: {len(current)} flagged this week = {len(current) - len(new)} flagged before "
            f"+ {len(new)} new (key: organization_perm_id + year + measure)")
        later_keys = set(map(tuple, later[KEY].to_numpy()))
        in_later = new[[tuple(k) in later_keys for k in new[KEY].to_numpy()]]
        if len(in_later):
            log(f"  {len(in_later)} new row(s) left out because they appear again in a LATER week:")
            log(in_later[SHOW].to_string(index=False))
        lost = new.drop(in_later.index).merge(report[KEY], on=KEY, how="left", indicator=True)
        lost = lost[lost["_merge"] == "left_only"]
        if len(lost):
            log(f"  {len(lost)} new row(s) NOT in the report. The script's drop_duplicates key leaves out 'measure',"
                " so a second measure for the same company and year is dropped:")
            log(lost[SHOW].to_string(index=False))
        else:
            log("  the script's report matches the expected delta")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / f"run_log_{current_date:%y%m%d}{'_no_date_fix' if args.no_date_fix else ''}.txt"
    log_path.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(f"\nlog saved to {log_path}")


if __name__ == "__main__":
    main()
