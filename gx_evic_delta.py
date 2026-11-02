"""The EVIC delta step in Great Expectations: what moves to GX, and what doesn't.

Part 1  Input contract. GX checks the table before the delta runs, so a wrong file stops with a clear reason
        instead of a KeyError or a silently empty report.
Part 2  The delta itself. GX validates one table at a time; it has no rule for "flagged in an earlier week".
        So pandas first adds a column, flagged_before, by matching each row of this week against every earlier
        week on organization_perm_id + year + measure. One GX rule then lists the rows where it is False.
        Those rows are the delta.

    python gx_evic_delta.py --input sample_data/input_tests_evic_history.csv
    python gx_evic_delta.py --input sample_data/input_tests_evic_history.csv \
        --script-report output/qa_report_input_test_evic_delta_261026.xlsx
"""
import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")

import great_expectations as gx  # noqa: E402
import pandas as pd  # noqa: E402
from great_expectations.data_context.types.base import ProgressBarsConfig  # noqa: E402

from run_script import KEY, REQUIRED, apply_mapping, load_history  # noqa: E402

HERE = Path(__file__).resolve().parent
E = gx.expectations

# Part 1 rules: (id, severity, what it protects, expectation). "fatal" means the delta must not run.
CONTRACT = [
    ("C01", "fatal", "every column the script reads is there",
     E.ExpectTableColumnsToMatchSet(column_set=REQUIRED, exact_match=False)),
    ("C02", "fatal", "as_of_date is a real date (YYYY-MM-DD)",
     E.ExpectColumnValuesToMatchStrftimeFormat(column="as_of_date", strftime_format="%Y-%m-%d")),
    ("C03", "fatal", "merge key organization_perm_id is filled",
     E.ExpectColumnValuesToNotBeNull(column="organization_perm_id")),
    ("C04", "fatal", "merge key year is filled", E.ExpectColumnValuesToNotBeNull(column="year")),
    ("C05", "fatal", "merge key measure is filled", E.ExpectColumnValuesToNotBeNull(column="measure")),
    ("C06", "warning", "one row per data point per week (else the merge multiplies rows)",
     E.ExpectCompoundColumnsToBeUnique(column_list=KEY + ["as_of_date"])),
    ("C07", "warning", "fiscal years within the EVIC test's 2024-2026 window",
     E.ExpectColumnValuesToBeBetween(column="year", min_value=2024, max_value=2026)),
]


def new_context():
    context = gx.get_context(mode="ephemeral")
    context.variables.progress_bars = ProgressBarsConfig(globally=False)
    return context


def validate(context, name, table, rules, index_column=None):
    batch_definition = (context.data_sources.add_pandas(name=f"{name}_source")
                        .add_dataframe_asset(name=f"{name}_asset")
                        .add_batch_definition_whole_dataframe(f"{name}_batch"))
    suite = context.suites.add(gx.ExpectationSuite(name=name))
    for rule_id, severity, description, expectation in rules:
        expectation.meta = {"rule_id": rule_id, "severity": severity, "description": description}
        suite.add_expectation(expectation)
    result_format = {"result_format": "COMPLETE"}
    if index_column:
        result_format["unexpected_index_column_names"] = [index_column]
    batch = batch_definition.get_batch(batch_parameters={"dataframe": table})
    return batch.validate(suite, result_format=result_format)


def print_results(title, result):
    print(f"\n{title}")
    for r in sorted(result.results, key=lambda r: r.expectation_config.meta["rule_id"]):
        meta = r.expectation_config.meta
        count = r.result.get("unexpected_count")
        missing = (r.result.get("details") or {}).get("mismatched", {}).get("missing")
        if missing:
            detail = f"  (missing: {', '.join(missing)})"
        elif not r.success and not r.result:
            detail = "  (could not run: column not in the input)"
        else:
            detail = f"  ({count} rows)" if count else ""
        print(f"  {meta['rule_id']}  {'PASS' if r.success else 'FAIL':<4}  {meta['severity']:<7}  "
              f"{meta['description']}{detail}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mapping", type=Path, help="column_mapping.csv, as in run_script.py")
    parser.add_argument("--current-date")
    parser.add_argument("--script-report", type=Path, help="the delta Excel the original script wrote, to compare")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    args = parser.parse_args()

    raw = load_history(args.input)
    if args.mapping:
        raw = apply_mapping(raw, args.mapping)
    if "as_of_date" in raw.columns:
        raw["as_of_date"] = raw["as_of_date"].astype(str)
    context = new_context()

    # Part 1: input contract, on the table as it arrives.
    contract = validate(context, "evic_delta_input_contract", raw, CONTRACT)
    print_results(f"Part 1  Input contract on {args.input.name} ({len(raw)} rows)", contract)
    fatal = [r for r in contract.results if not r.success and r.expectation_config.meta["severity"] == "fatal"]
    if fatal:
        raise SystemExit("Stopped: a fatal contract rule failed, so the delta would not be reliable.")

    # Part 2: derive flagged_before with pandas, then one GX rule lists the new rows.
    df = raw.copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    df["organization_perm_id"] = df["organization_perm_id"].astype(str)
    current_date = pd.Timestamp(args.current_date) if args.current_date else df["as_of_date"].max()
    current = df[df["as_of_date"] == current_date].copy()
    earlier_keys = df.loc[df["as_of_date"] < current_date, KEY].drop_duplicates()
    current = current.merge(earlier_keys.assign(flagged_before=True), on=KEY, how="left")
    current["flagged_before"] = current["flagged_before"].fillna(False).astype(bool)
    current["record_key"] = current["organization_perm_id"] + "|" + current["year"].astype(str) + "|" + current["measure"]

    delta_rule = [("D01", "report", "flagged in an earlier week (False = new this week = delta)",
                   E.ExpectColumnValuesToBeInSet(column="flagged_before", value_set=[True]))]
    delta = validate(context, "evic_delta_new_rows", current, delta_rule, index_column="record_key")
    print_results(f"Part 2  Delta on {current_date:%Y-%m-%d} ({len(current)} rows flagged this week)", delta)
    new_keys = [i["record_key"] for i in delta.results[0].result.get("unexpected_index_list") or []]
    for key in new_keys:
        row = current.set_index("record_key").loc[key]
        print(f"     new  {row['name']:<20} {row['year']}  {row['measure']}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"gx_evic_delta_{current_date:%y%m%d}.json"
    out.write_text(json.dumps({"input_contract": contract.to_json_dict(), "delta": delta.to_json_dict()},
                              indent=2, default=str), encoding="utf-8")
    print(f"\nGX results: {out}")

    if args.script_report:
        script = pd.read_excel(args.script_report, sheet_name="summary_report", dtype={"organization_perm_id": str})
        script_keys = set(script["organization_perm_id"] + "|" + script["year"].astype(str) + "|" + script["measure"])
        print(f"\nCompared with the original script's report ({args.script_report.name}): "
              f"GX {len(new_keys)} rows, script {len(script_keys)} rows")
        script_company_years = {k.rsplit("|", 1)[0] for k in script_keys}
        for key in sorted(set(new_keys) - script_keys):
            reason = ("same company and year is in the script's report: its drop_duplicates leaves out 'measure'"
                      if key.rsplit("|", 1)[0] in script_company_years else "not in the script's report")
            print(f"  only in GX      {key}   ({reason})")
        for key in sorted(script_keys - set(new_keys)):
            print(f"  only in script  {key}")


if __name__ == "__main__":
    main()
