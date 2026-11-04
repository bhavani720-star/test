"""The LSEG reported input test as QC rules: custom Great Expectations rules and SQL rules.

Part 1  Input contract. GX checks the five inputs before the test runs, so a wrong file stops with a clear reason
        instead of a KeyError deep in the script.
Part 2  The four checks as QC rules, read from the suite that author_suite.py saved:

            L01  Datapoints previous only   in the previous extract, not in the current one
            L02  Variance                   current vs previous extract, same company and year
            L03  YoY outliers               this fiscal year vs the year before, current extract
            L04  Isolation Forest YoY       anomaly score at the 99.9th percentile, and beyond the YoY % limits

        Both extracts go into one table (a `snapshot` column says which), so the custom GX rules compare rows
        themselves; nothing is worked out in pandas first. The SQL rules (L01-L03) run on the same table on SQLite,
        and the two engines must flag the same rows. Then the script's prioritisation (more than 50 flags: fiscal
        years from `start`, top companies by market cap), the records, and a comparison with the script's report.

    python author_suite.py
    python gx_lseg_reported.py --input sample_data
    python gx_lseg_reported.py --input sample_data --script-report output/qa_report_input_test_lseg_scope123_init_261026.xlsx

Results, like the QC platform's two stores: output/validation_runs_YYMMDD.csv (every rule, passed or not) and
output/failed_events_YYMMDD.csv (one row per flagged data point), plus the GX results as JSON.
"""
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")

import great_expectations as gx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from great_expectations.data_context.types.base import ProgressBarsConfig  # noqa: E402

from qc_rules.rules import CHECKS, extracts_table, load_suite, rule_key, run_sql_rules  # noqa: E402
from run_script import DIRECT, MEASURES, REQUIRED, SCRIPT, YEAR_SOURCES, apply_mapping, load_inputs, read_metadata  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_SUITE = HERE / "expectations" / "sfi_lseg_reported_input_checks.json"
E = gx.expectations
KEY = ["organization_perm_id", "year"]
REASONS = {rule_id: check["check"] for rule_id, check in CHECKS.items()}


def new_context():
    context = gx.get_context(mode="ephemeral")
    context.variables.progress_bars = ProgressBarsConfig(globally=False)
    return context


def batch_for(context, name, table):
    return (context.data_sources.add_pandas(name=f"{name}_source")
            .add_dataframe_asset(name=f"{name}_asset")
            .add_batch_definition_whole_dataframe(f"{name}_batch")
            .get_batch(batch_parameters={"dataframe": table}))


def validate(context, name, table, rules, index_column=None):
    suite = context.suites.add(gx.ExpectationSuite(name=name))
    for rule_id, severity, description, expectation in rules:
        expectation.meta = {"rule_id": rule_id, "severity": severity, "description": description}
        suite.add_expectation(expectation)
    result_format = {"result_format": "COMPLETE"}
    if index_column:
        result_format["unexpected_index_column_names"] = [index_column]
    return batch_for(context, name, table).validate(suite, result_format=result_format)


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


# Part 1 ------------------------------------------------------------------------------------------------------------

def contract_rules(table, year, verification=()):
    rules = [
        ("C01", "fatal", "every column the script reads is there",
         E.ExpectTableColumnsToMatchSet(column_set=["organization_perm_id", year, *DIRECT, "as_of_date"],
                                        exact_match=False)),
        ("C02", "fatal", "as_of_date is a real date (YYYY-MM-DD)",
         E.ExpectColumnValuesToMatchStrftimeFormat(column="as_of_date", strftime_format="%Y-%m-%d")),
        ("C03", "fatal", "join key organization_perm_id is filled",
         E.ExpectColumnValuesToNotBeNull(column="organization_perm_id")),
        ("C04", "fatal", f"join key {year} is filled", E.ExpectColumnValuesToNotBeNull(column=year)),
        ("C05", "warning", "one row per company and year (else the merge multiplies rows)",
         E.ExpectCompoundColumnsToBeUnique(column_list=["organization_perm_id", year])),
    ]
    for n, column in enumerate(DIRECT, start=6):
        rules.append((f"C{n:02d}", "warning", f"{column} is not negative",
                      E.ExpectColumnValuesToBeBetween(column=column, min_value=0)))
    if verification:
        rules.append(("C10", "fatal", "has every 'verification' column of the current extract (the script drops them)",
                      E.ExpectTableColumnsToMatchSet(column_set=list(verification), exact_match=False)))
    return rules


def reference_rules():
    return {
        name: [(f"R{n}", "fatal", f"{name} has the columns the script reads",
                E.ExpectTableColumnsToMatchSet(column_set=REQUIRED[name], exact_match=False))]
        for n, name in enumerate(["marketcap", "icb_info", "univ_inactive"], start=1)
    }


# Part 2 ------------------------------------------------------------------------------------------------------------

def prepare(extract, current_columns, year):
    """Script lines 63-106: drop as_of_date and 'verification' columns, add the scope 3 totals, keep the six measures,
    treat 0 as empty and drop company-years with every measure empty."""
    df = extract.drop(columns=["as_of_date"] + [c for c in current_columns if "verification" in c])
    df = df.rename(columns={year: "year"}) if year != "period_end_date" else df.assign(
        year=pd.to_datetime(df.pop("period_end_date")).dt.year)
    df["year"] = pd.to_numeric(df["year"]).astype(int)
    df["total_upstream_scope3"] = df[[c for c in current_columns if "up_scope3" in c]].sum(axis=1)
    df["total_downstream_scope3"] = df[[c for c in current_columns if "down_scope3" in c]].sum(axis=1)
    df = df[KEY + MEASURES].replace(0, np.nan)
    return df.dropna(subset=MEASURES, how="all")


def run_gx_rules(context, saved, gx_rules, table):
    suite = context.suites.add(gx.ExpectationSuite(name=saved["name"], expectations=gx_rules, meta=saved.get("meta")))
    return batch_for(context, "qc_rules", table).validate(
        suite, result_format={"result_format": "COMPLETE", "unexpected_index_column_names": ["record_key"]})


def flagged_keys(gx_result):
    """(rule id, measure) -> the record keys GX found unexpected."""
    return {rule_key(r.expectation_config.to_json_dict()): {i["record_key"] for i in r.result.get("unexpected_index_list") or []}
            for r in gx_result.results}


def flagged_rows(keys, rule_id):
    """One row per flagged data point: company, year and, except L01, measure; with the report's record key."""
    rows = [{"organization_perm_id": k.split("|")[0], "year": int(k.split("|")[1]), "measure": measure}
            for (rid, measure), found in keys.items() if rid == rule_id for k in found]
    rows = pd.DataFrame(rows, columns=["organization_perm_id", "year", "measure"])
    rows["record_key"] = rows["organization_perm_id"] + "|" + rows["year"].astype(str) + (
        "" if rule_id == "L01" else "|" + rows["measure"])
    return rows.sort_values(["measure", "organization_perm_id", "year"]).reset_index(drop=True)


def prioritise(flags, md, market_cap):
    """The script's rule when a check flags too many: fiscal years from `start`, then the top companies by market cap."""
    if len(flags) <= md["max_number_of_outliers"]:
        return flags
    flags = flags[flags["year"] >= md["start"]].merge(market_cap, on="organization_perm_id", how="left")
    top = flags.sort_values("company_market_cap", ascending=False)["organization_perm_id"].drop_duplicates()
    return flags[flags["organization_perm_id"].isin(top.head(md["number_of_companies"]))].drop(columns="company_market_cap")


def records(run, saved, gx_result, sql_found, table):
    """The two stores of the QC platform: every rule run (validation_runs) and every flagged data point (failed_events)."""
    values = table.drop_duplicates("record_key").set_index("record_key")
    runs, events = [], []
    found_by_engine = [("gx_custom", r.expectation_config.to_json_dict(),
                        {i["record_key"] for i in r.result.get("unexpected_index_list") or []}) for r in gx_result.results]
    found_by_engine += [("sql", rule, set(rows["record_key"])) for rule, rows in sql_found]
    for engine, rule, found in found_by_engine:
        meta = rule["meta"]
        runs.append({**run, "suite": saved["name"], "rule_id": meta["rule_id"], "check": meta["check"],
                     "measure": meta["measure"], "engine": engine, "expectation_type": rule["type"],
                     "data_quality_dimension": meta["data_quality_dimension"], "element_count": len(table),
                     "unexpected_count": len(found), "validation_succeeded": not found})
        for key in sorted(found):
            row = values.loc[key]
            events.append({**run, "rule_id": meta["rule_id"], "check": meta["check"], "measure": meta["measure"],
                           "engine": engine, "record_key": key, "organization_perm_id": row["organization_perm_id"],
                           "year": row["year"], "snapshot": row["snapshot"],
                           "value": row[meta["measure"]] if meta["measure"] in values.columns else None})
    return pd.DataFrame(runs), pd.DataFrame(events)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mapping", type=Path, help="column_mapping.csv, as in run_script.py")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE, help="the suite author_suite.py saved")
    parser.add_argument("--script-report", type=Path, help="the QA report the original script wrote, to compare")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    parser.add_argument("--shuffle-rows", action="store_true",
                        help="hand the current extract over in random row order, as run_script.py --shuffle-rows does")
    args = parser.parse_args()
    if not args.suite.exists():
        raise SystemExit(f"No suite at {args.suite}. Run `python author_suite.py` first.")
    if args.shuffle_rows and args.output_dir == HERE / "output":
        args.output_dir = HERE / "output" / "shuffled"

    tables = load_inputs(args.input)
    if args.shuffle_rows:
        tables["current_extract"] = tables["current_extract"].sample(frac=1, random_state=1).reset_index(drop=True)
        print("  --shuffle-rows: the current extract is handed over in random row order")
    if args.mapping:
        tables = apply_mapping(tables, args.mapping)
    for name, table in tables.items():
        for column in ("organization_perm_id", "organizationid"):
            if column in table:
                table[column] = table[column].astype(str)
        if "as_of_date" in table:
            table["as_of_date"] = table["as_of_date"].astype(str)
    md = read_metadata(SCRIPT.read_text(encoding="utf-8"))
    current_raw, previous_raw = tables["current_extract"], tables["previous_extract"]
    year = next((c for c in YEAR_SOURCES if c in current_raw.columns), "fiscal_year")
    verification = [c for c in current_raw.columns if "verification" in c]
    context = new_context()

    # Part 1: input contract, on the tables as they arrive.
    contract = {
        "current_extract": validate(context, "contract_current", current_raw, contract_rules(current_raw, year)),
        "previous_extract": validate(context, "contract_previous", previous_raw,
                                     contract_rules(previous_raw, year, verification)),
    }
    for name, rules in reference_rules().items():
        contract[name] = validate(context, f"contract_{name}", tables[name], rules)
    print("Part 1  Input contract")
    for name, result in contract.items():
        print_results(f"  {name} ({len(tables[name])} rows)", result)
    fatal = [r for result in contract.values() for r in result.results
             if not r.success and r.expectation_config.meta["severity"] == "fatal"]
    if fatal:
        raise SystemExit("\nStopped: a fatal contract rule failed, so the checks would not be reliable.")

    # Part 2: both extracts in one table; the custom GX rules and the SQL rules run on it.
    saved, gx_rules, sql_rules = load_suite(args.suite)
    table = extracts_table(prepare(current_raw, current_raw.columns, year), prepare(previous_raw, current_raw.columns, year))
    gx_result = run_gx_rules(context, saved, gx_rules, table)
    gx_found = flagged_keys(gx_result)
    sql_found = run_sql_rules(sql_rules, table)

    print(f"\n\nPart 2  The four checks as QC rules ({saved['name']}: {len(gx_rules)} custom GX, "
          f"{len(sql_rules)} SQL), on {len(table)} rows")
    print(f"  {'rule':<4}  {'measure':<29} {'custom GX':>9} {'SQL':>5}   engines")
    disagree = 0
    for rule_id, measure in gx_found:
        gx_keys, sql_rows = gx_found[(rule_id, measure)], sql_found.get((rule_id, measure))
        if sql_rows is None:
            print(f"  {rule_id:<4}  {measure:<29} {len(gx_keys):>9} {'-':>5}   (no SQL rule: a model, not a query)")
            continue
        sql_keys = set(sql_rows["record_key"])
        disagree += gx_keys != sql_keys
        print(f"  {rule_id:<4}  {measure:<29} {len(gx_keys):>9} {len(sql_keys):>5}   "
              f"{'agree' if gx_keys == sql_keys else 'DIFFERENT'}")
        for key in sorted(gx_keys ^ sql_keys):
            print(f"         only in {'custom GX' if key in gx_keys else 'SQL'}: {key}")
    print(f"  custom GX and SQL rules {'flag the same rows' if not disagree else f'differ on {disagree} rule(s)'}")

    market_cap = tables["marketcap"][["organization_perm_id", "company_market_cap"]]
    names = tables["icb_info"].assign(organization_perm_id=lambda t: t["organization_perm_id"].astype(str))
    names = names.drop_duplicates("organization_perm_id").set_index("organization_perm_id")["name"]
    reported = {}
    print("\n  After the script's prioritisation (per measure, then per check):")
    for rule_id in REASONS:
        rows = flagged_rows(gx_found, rule_id)
        flagged = len(rows)
        if rule_id != "L01":
            rows = pd.concat([prioritise(group, md, market_cap) for _, group in rows.groupby("measure")] or [rows])
        rows = prioritise(rows, md, market_cap)
        reported[rule_id] = rows
        print(f"  {rule_id} {REASONS[rule_id]:<29} flagged {flagged:>3}   reported {len(rows):>3}")
        for _, row in rows.iterrows():
            print(f"       {names.get(row['organization_perm_id'], row['organization_perm_id']):<22} {row['year']}  "
                  f"{row['measure'] if rule_id != 'L01' else 'N/A'}")
    empty = [REASONS[r] for r in ("L02", "L03", "L04") if reported[r].empty]
    if empty:
        print(f"  note: nothing reported by {', '.join(empty)}. The original script stops in that case "
              "(lines 325, 335 or 344); the QC rules do not.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    as_of = pd.to_datetime(current_raw["as_of_date"]).max()
    run = {"run_id": str(uuid.uuid4()), "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "domain": saved["meta"]["domain"], "stage": saved["meta"]["stage"], "as_of_date": f"{as_of:%Y-%m-%d}"}
    sql_pairs = [(rule, sql_found[rule_key(rule)]) for rule in sql_rules]
    runs, events = records(run, saved, gx_result, sql_pairs, table)
    paths = {"validation_runs": args.output_dir / f"validation_runs_{as_of:%y%m%d}.csv",
             "failed_events": args.output_dir / f"failed_events_{as_of:%y%m%d}.csv",
             "gx_results": args.output_dir / f"gx_lseg_reported_{as_of:%y%m%d}.json"}
    runs.to_csv(paths["validation_runs"], index=False)
    events.to_csv(paths["failed_events"], index=False)
    paths["gx_results"].write_text(json.dumps({"input_contract": {k: v.to_json_dict() for k, v in contract.items()},
                                               "qc_rules": gx_result.to_json_dict()}, indent=2, default=str),
                                   encoding="utf-8")
    print(f"\nvalidation_runs: {len(runs)} rule runs, {int((~runs['validation_succeeded']).sum())} with flags  "
          f"-> {paths['validation_runs'].name}")
    print(f"failed_events:   {len(events)} flagged data points (both engines)  -> {paths['failed_events'].name}")
    print(f"GX results: {paths['gx_results']}")

    if args.script_report:
        script = pd.read_excel(args.script_report, sheet_name="summary_report", dtype={"organization_perm_id": str})
        print(f"\nCompared with the original script's report ({args.script_report.name}):")
        for rule_id, reason in REASONS.items():
            rows = script[script["reason_for_inclusion"] == reason]
            script_keys = set(rows["organization_perm_id"] + "|" + rows["year"].astype(str)
                              + ("" if rule_id == "L01" else "|" + rows["measure"]))
            gx_keys = set(reported[rule_id]["record_key"])
            print(f"  {rule_id} {reason:<29} QC rules {len(gx_keys):>3}   script {len(script_keys):>3}   "
                  f"{'same rows' if gx_keys == script_keys else 'DIFFERENT'}")
            for key in sorted(gx_keys - script_keys):
                print(f"       only in QC rules  {key}")
            for key in sorted(script_keys - gx_keys):
                print(f"       only in script    {key}")


if __name__ == "__main__":
    main()
