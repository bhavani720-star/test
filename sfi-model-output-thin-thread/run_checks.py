"""Run the model output checks (scope 1-3) on one model run laid out the way the model owner keeps it, and turn the outliers
and their reasons into exception records for the QC tool.

The model owner's process:
    1. The model runs on the model platform, in staging and then in production. Each run has a file store with four
       folders: model output, input data, scope 1-2 intermediate files, scope 3 intermediate files.
    2. They download the files they need into the same folder structure, one folder per run date.
    3. They point each notebook at that folder (they edit the path and date by hand) and run it. Coverage and year on
       year need the current run; delivery versus delivery also needs the previous production run.
    4. Each notebook finds the outliers and gives each one a reason. A reason is final, needs a look at the input
       checks, or is not covered yet (something to investigate by hand).
    5. One cell writes three Excel reports: summarised (sent to Content Ops), full and detailed.

This runner does steps 3-5 the same way every time. It checks the run folders against file_manifest.csv, runs each
check unchanged (it hands the check RUN_DIR and PREVIOUS_RUN_DIR, or edits the path text for you with --replace),
gives every reason a status from reason_catalogue.csv, links the reasons to the input checks, and writes exception
records (CSV and JSON, for the QC tool's database) plus the three reports.

    python run_checks.py --run-date 2026-10-13 --previous-run-date 2026-07-13
    python run_checks.py --run-date 2026-10-13 --checks coverage,yoy
    python run_checks.py --run-date 2026-10-13 --previous-run-date 2026-07-13 ^
        --check d2d=notebooks/<the model owner's notebook>.ipynb --result-var d2d=<table with the reasons> ^
        --replace "<path in the notebook>=<path to this run>"

--run-date            YYYY-MM-DD: the run to check (a folder under --runs-root)
--previous-run-date   YYYY-MM-DD: the previous production run; needed for delivery versus delivery (d2d)
--checks              comma-separated: coverage, yoy, d2d (default: all of them; d2d only with a previous run)
--check NAME=PATH     run this script or notebook (.py or .ipynb) for one check instead of the stand-in in checks/
--result-var NAME=VAR the variable that holds the outliers and reasons when that check ends (default: outliers)
--replace OLD=NEW     replace text in every check's code before running it, e.g. the run date in a path cell
--input-checks        the input test's report (.csv or .xlsx); default: the file in input_checks/ of the run, if any
--environment         live or staging; written on every record
--runs-root           folder with one sub-folder per run date; default: runs/
"""
import argparse
import contextlib
import io
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CHECKS = {
    "coverage": {"script": HERE / "checks" / "stand_in_coverage.py", "previous_run": False, "compared_with": "",
                 "sheet": "Coverage"},
    "yoy": {"script": HERE / "checks" / "stand_in_volatility_yoy.py", "previous_run": False,
            "compared_with": "previous year", "sheet": "Volatility YoY"},
    "d2d": {"script": HERE / "checks" / "stand_in_volatility_d2d.py", "previous_run": True,
            "compared_with": "previous run", "sheet": "Volatility d2d"},
}
RESULT_COLUMNS = ["organization_perm_id", "year", "measure", "reason"]   # every check's result must have these
VALUE_COLUMNS = ["value_current", "value_previous", "change_pct"]
KEYS = ["organization_perm_id", "year", "measure"]
# The input test reports its measures under the ADC names.
MEASURE_ALIASES = {"co2_emiss_scope1": "scope1", "co2_emiss_scope2": "scope2",
                   "total_upstream_scope3": "scope3_upstream", "total_downstream_scope3": "scope3_downstream"}
# What the model owner said Content Ops need: the company-year, upstream or downstream, financial or not, and the reason.
SUMMARISED = ["organization_perm_id", "name", "year", "measure", "upstream_downstream", "company_type", "reason"]
FULL = ["check", "organization_perm_id", "name", "year", "measure", "scope", "upstream_downstream", "company_type",
        "value_current", "value_previous", "compared_with", "change_pct", "reason", "reason_status", "next_step",
        "input_check", "content_ops_comment", "run_date", "previous_run_date", "environment"]
IDS = {"organization_perm_id": str}

LOG = []


def log(text=""):
    print(text)
    LOG.append(text)


def pairs(values, label):
    result = {}
    for text in values:
        key, sep, value = text.partition("=")
        if not sep:
            raise SystemExit(f"{label} {text}: expected NAME=VALUE")
        result[key] = value
    return result


def read_table(path):
    if path.suffix.lower() in (".xlsx", ".xls"):
        sheets = pd.read_excel(path, sheet_name=None, dtype=IDS)
        return sheets.get("summary_report", next(iter(sheets.values())))
    return pd.read_csv(path, dtype=IDS)


def check_files(manifest, run_dir, checks, label):
    needed = manifest[manifest["needed_for"].str.split(";").map(lambda used: bool(set(used) & set(checks)))]
    missing = [f"{row.folder}/{row.file_name}" for row in needed.itertuples()
               if not (run_dir / row.folder / row.file_name).exists()]
    if missing:
        log(f"\nNOT RUN: the {label} run folder {run_dir} is missing {len(missing)} file(s):")
        for name in missing:
            log(f"  missing  {name}")
        log("Download them (python setup_run_folders.py lists where from), or fix file_manifest.csv, and run again.")
        raise SystemExit(2)
    log(f"  {label:<8} run {run_dir.name}: all {len(needed)} files for {', '.join(checks)} are there")


def load_code(path, replacements):
    """A .py file as it is, or a notebook's code cells in order (IPython-only lines such as %magic are left out)."""
    if path.suffix.lower() == ".ipynb":
        cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
        code = "\n\n".join("".join(cell["source"]) for cell in cells if cell["cell_type"] == "code")
        code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith(("%", "!")))
    else:
        code = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old in code:
            log(f"    --replace: {code.count(old)} x '{old}' -> '{new}'")
            code = code.replace(old, new)
    return code


def run_check(name, path, result_var, replacements, inputs):
    code = load_code(path, replacements)
    scope = {"__name__": "__main__", "__file__": str(path), "display": lambda *a, **k: None, **inputs}
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(code, str(path), "exec"), scope)
    for line in printed.getvalue().splitlines():
        log(f"    | {line}")
    if not isinstance(scope.get(result_var), pd.DataFrame):
        raise SystemExit(f"\n{name}: {path.name} did not leave a table in '{result_var}'. "
                         f"Tell the runner which variable holds the outliers: --result-var {name}=<variable>")
    table = scope[result_var].reset_index(drop=True)
    missing = [c for c in RESULT_COLUMNS if c not in table.columns]
    if missing:
        raise SystemExit(f"\n{name}: the table in '{result_var}' has no {', '.join(missing)} column(s). "
                         f"Columns: {', '.join(map(str, table.columns))}")
    return table


def to_records(name, table, info, catalogue, args):
    records = table[RESULT_COLUMNS].copy()
    records["organization_perm_id"] = records["organization_perm_id"].astype(str)
    records["year"] = pd.to_numeric(records["year"]).astype(int)
    records["measure"] = records["measure"].replace(MEASURE_ALIASES)
    for column in VALUE_COLUMNS:
        records[column] = table[column] if column in table else np.nan
    records.insert(0, "check", name)
    records["compared_with"] = CHECKS[name]["compared_with"]
    records = records.merge(info, on="organization_perm_id", how="left")
    records["scope"] = records["measure"].str.extract(r"scope(\d)")[0]
    records["upstream_downstream"] = records["measure"].str.extract(r"scope3_(\w+)")[0].fillna("")
    records["company_type"] = records["is_financial"].map({True: "financial", False: "non-financial"}).fillna("")
    records = records.merge(catalogue, on="reason", how="left")
    records["reason_status"] = records["status"].fillna("unmapped")
    records["next_step"] = records["next_step"].fillna("Add this reason to reason_catalogue.csv")
    records["run_date"], records["previous_run_date"] = str(args.run_date), str(args.previous_run_date or "")
    records["environment"] = args.environment
    details = table.drop(columns=[c for c in table.columns if c in RESULT_COLUMNS + VALUE_COLUMNS])
    return records.drop(columns=["status", "is_financial"]), details


def link_input_checks(records, path):
    """Put the input test's flag (and any Content Ops comment) next to each exception for the same company-year."""
    checks = read_table(path)
    checks["year"] = pd.to_numeric(checks["year"], errors="coerce")
    checks = checks.dropna(subset=["year"]).astype({"year": int})
    checks["measure"] = checks["measure"].replace(MEASURE_ALIASES).replace("N/A", np.nan)
    if "content_ops_comment" not in checks:
        checks["content_ops_comment"] = ""
    checks["content_ops_comment"] = checks["content_ops_comment"].fillna("").astype(str)
    combine = {"reason_for_inclusion": lambda s: "; ".join(s.dropna().unique()),
               "content_ops_comment": lambda s: "; ".join(c for c in s.unique() if c)}
    exact = checks.dropna(subset=["measure"]).groupby(KEYS).agg(combine).reset_index()
    # 'Datapoints previous only' rows have no measure: they match every measure of that company-year.
    any_measure = checks[checks["measure"].isna()].groupby(KEYS[:2]).agg(combine).reset_index()
    linked = (records.merge(exact, on=KEYS, how="left")
                     .merge(any_measure, on=KEYS[:2], how="left", suffixes=("", "_any")))
    for column in ("reason_for_inclusion", "content_ops_comment"):
        any_measure_value = linked.pop(f"{column}_any").astype("string")
        linked[column] = linked[column].astype("string").fillna(any_measure_value).fillna("")
    linked = linked.rename(columns={"reason_for_inclusion": "input_check"})
    log(f"  input checks: {path.name}, {len(checks)} row(s); {(linked['input_check'] != '').sum()} exception(s) "
        "have an input check flag for the same company-year")
    return linked


def follow_up(row):
    if row.reason_status != "needs_input_check":
        return row.next_step
    if not row.input_check:
        return "No input check flag for this company-year: investigate"
    return "Explained by the Content Ops comment" if row.content_ops_comment else "Ask Content Ops for a comment"


def write_reports(records, details, folder, run):
    names = {}
    for level in ("summarised", "full", "detailed"):
        path = folder / f"model_output_checks_{level}_{run}.xlsx"
        with pd.ExcelWriter(path) as writer:
            for name, rows in records.groupby("check", sort=False):
                if level == "summarised":
                    table = rows[SUMMARISED]
                elif level == "full":
                    table = rows[FULL]
                else:
                    extra = details[name]
                    table = pd.concat([rows[FULL].reset_index(drop=True), extra.add_prefix("detail_")], axis=1)
                table.to_excel(writer, sheet_name=CHECKS[name]["sheet"], index=False)
        names[level] = path.name
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--previous-run-date", type=date.fromisoformat)
    parser.add_argument("--checks")
    parser.add_argument("--check", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--result-var", action="append", default=[], metavar="NAME=VAR")
    parser.add_argument("--replace", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument("--input-checks", type=Path)
    parser.add_argument("--environment", default="live", choices=["live", "staging"])
    parser.add_argument("--runs-root", type=Path, default=HERE / "runs")
    parser.add_argument("--manifest", type=Path, default=HERE / "file_manifest.csv")
    parser.add_argument("--catalogue", type=Path, default=HERE / "reason_catalogue.csv")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    args = parser.parse_args()

    log(f"Model output thin-thread run  {datetime.now():%Y-%m-%d %H:%M:%S}  (pandas {pd.__version__})")
    scripts = {name: Path(path) for name, path in pairs(args.check, "--check").items()}
    result_vars, replacements = pairs(args.result_var, "--result-var"), pairs(args.replace, "--replace")
    unknown = (set(scripts) | set(result_vars)) - set(CHECKS)
    if unknown:
        raise SystemExit(f"unknown check(s): {', '.join(sorted(unknown))}. Checks: {', '.join(CHECKS)}")
    checks = args.checks.split(",") if args.checks else list(CHECKS)
    if any(CHECKS[c]["previous_run"] for c in checks) and not args.previous_run_date:
        if args.checks:
            raise SystemExit("d2d (delivery versus delivery) compares two runs: add --previous-run-date")
        checks = [c for c in checks if not CHECKS[c]["previous_run"]]
        log("  note: no --previous-run-date, so delivery versus delivery (d2d) is left out")

    log("\n[1/5] Check the run folders against file_manifest.csv")
    manifest = pd.read_csv(args.manifest)
    run_dir = args.runs_root / str(args.run_date)
    previous_dir = args.runs_root / str(args.previous_run_date) if args.previous_run_date else None
    check_files(manifest, run_dir, checks, "current")
    if previous_dir:
        check_files(manifest, previous_dir, [c for c in checks if CHECKS[c]["previous_run"]], "previous")

    log("\n[2/5] Run the checks (each one unchanged)")
    inputs = {"RUN_DIR": run_dir, "PREVIOUS_RUN_DIR": previous_dir, "RUN_DATE": str(args.run_date),
              "PREVIOUS_RUN_DATE": str(args.previous_run_date or "")}
    results = {}
    for name in checks:
        path = scripts.get(name, CHECKS[name]["script"])
        log(f"  {name}: {path.relative_to(HERE) if path.is_relative_to(HERE) else path}"
            f"{'' if name in scripts else '  (stand-in)'}")
        results[name] = run_check(name, path, result_vars.get(name, "outliers"), replacements, inputs)

    log("\n[3/5] Exception records")
    company = manifest.set_index("file_key").loc["company_info"]
    info = pd.read_csv(run_dir / company["folder"] / company["file_name"], dtype=IDS)[["organization_perm_id", "name",
                                                                                          "is_financial"]]
    catalogue = pd.read_csv(args.catalogue)
    built = {name: to_records(name, table, info, catalogue, args) for name, table in results.items()}
    records = pd.concat([r for r, _ in built.values()], ignore_index=True)
    details = {name: d for name, (_, d) in built.items()}
    unmapped = sorted(records.loc[records["reason_status"] == "unmapped", "reason"].unique())
    if unmapped:
        log(f"  note: {len(unmapped)} reason(s) are not in reason_catalogue.csv: {'; '.join(unmapped)}")

    log("\n[4/5] Link to the input checks")
    input_checks = args.input_checks or next(iter(sorted((run_dir / "input_checks").glob("*.*"))), None)
    if input_checks:
        records = link_input_checks(records, input_checks)
    else:
        records["input_check"], records["content_ops_comment"] = "", ""
        log("  no input check report for this run: reasons that need one are marked for investigation")
    records["next_step"] = records.apply(follow_up, axis=1)

    log("\n[5/5] Result")
    log(f"  {len(records)} exception(s)")
    log(pd.crosstab(records["check"], records["reason_status"], margins=True, margins_name="total").to_string())
    log("")
    log(records[["check", "organization_perm_id", "name", "year", "measure", "change_pct", "reason", "next_step"]]
        .to_string(index=False, float_format=lambda v: f"{v:+.0f}%"))

    folder = args.output_dir / str(args.run_date)
    folder.mkdir(parents=True, exist_ok=True)
    run = f"{args.run_date:%y%m%d}"
    records[FULL].to_csv(folder / f"exceptions_{run}.csv", index=False)
    records[FULL].to_json(folder / f"exceptions_{run}.json", orient="records", indent=1)
    reports = write_reports(records, details, folder, run)
    log(f"\n  exception records: exceptions_{run}.csv and .json (one record per row, for the QC tool's database)")
    log(f"  reports: {', '.join(reports.values())}")
    log_path = folder / f"run_log_{run}.txt"
    log_path.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    print(f"\nwritten to {folder}")


if __name__ == "__main__":
    main()
