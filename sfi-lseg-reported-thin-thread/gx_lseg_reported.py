"""The LSEG reported input test in Great Expectations: what moves to GX, and what doesn't.

Part 1  Input contract. GX checks the five inputs before the test runs, so a wrong file stops with a clear reason
        instead of a KeyError deep in the script.
Part 2  The four checks. GX validates one table at a time; it has no rule for "compare with the previous extract" or
        "compare with the year before". So pandas first adds those comparisons as columns (the same way the script
        works them out), and ordinary GX rules then flag the rows:

            L01  Datapoints previous only   in the previous extract, not in the current one
            L02  Variance                   current vs previous extract, same company and year
            L03  YoY outliers               this fiscal year vs the year before, current extract
            L04  Isolation Forest YoY       anomaly score above the 99.9th percentile, and beyond the YoY % limits

        The script's prioritisation (more than 50 flags: fiscal years from `start`, top companies by market cap)
        is applied afterwards, then the result is compared with the report the original script wrote.

    python gx_lseg_reported.py --input sample_data
    python gx_lseg_reported.py --input sample_data --script-report output/qa_report_input_test_lseg_scope123_init_261026.xlsx
"""
import argparse
import json
import os
import warnings
from pathlib import Path

os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")

import great_expectations as gx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from great_expectations.data_context.types.base import ProgressBarsConfig  # noqa: E402
from sklearn.ensemble import IsolationForest  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from run_script import DIRECT, MEASURES, REQUIRED, SCRIPT, YEAR_SOURCES, apply_mapping, load_inputs, read_metadata  # noqa: E402

HERE = Path(__file__).resolve().parent
E = gx.expectations
KEY = ["organization_perm_id", "year"]
REASONS = {"L01": "Datapoints previous only", "L02": "Variance current vs previous", "L03": "YoY Outliers",
           "L04": "Iso F YoY current"}


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


# Part 2: derive the comparison columns the way the script does -----------------------------------------------------

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


def change(current, previous):
    nominal = current - previous
    with np.errstate(divide="ignore", invalid="ignore"):
        return nominal, nominal / previous * 100


def company_years(current, previous):
    table = current[KEY].merge(previous[KEY], on=KEY, how="outer", indicator=True)
    table["in_current"] = table["_merge"] != "right_only"
    table["in_previous"] = table["_merge"] != "left_only"
    table.insert(0, "record_key", table["organization_perm_id"] + "|" + table["year"].astype(str))
    return table.drop(columns="_merge")


def iforest_scores(values, settings):
    """Script lines 227-246 for one group of YoY changes: train on 80%, score all, threshold = 99.9th percentile."""
    if len(values) < 2:   # train_test_split needs two rows; the script would stop here
        return np.full(len(values), np.nan), np.inf
    train, _ = train_test_split(values, test_size=0.2, random_state=42)
    scores = np.abs(IsolationForest(random_state=42).fit(train).decision_function(values))
    threshold = np.percentile(scores, settings["percentile"]) if len(np.unique(scores)) > 1 else np.inf
    return scores, threshold


def datapoints(current, previous):
    """One row per company, fiscal year and measure, with the variance, YoY and Isolation Forest columns."""
    both = current.merge(previous, on=KEY, how="inner", suffixes=("_current", "_previous"))
    ordered = current.sort_values(KEY)   # the script's YoY check sorts; its Isolation Forest part does not (lines 206-210)
    frames = []
    for col in MEASURES:
        var = both[KEY].assign(measure=col)
        var["extract_nominal_change"], var["extract_pct_change"] = change(both[f"{col}_current"], both[f"{col}_previous"])

        yoy = ordered[KEY + [col]].rename(columns={col: "value"}).assign(measure=col)
        grouped = ordered.groupby("organization_perm_id")[col]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yoy["yoy_nominal_change"], yoy["yoy_pct_change"] = grouped.diff(), grouped.pct_change() * 100
        excluded = yoy["value"].isna() | ~np.isfinite(yoy["yoy_pct_change"]) | (yoy["yoy_pct_change"] == -100)
        yoy.loc[excluded, ["yoy_nominal_change", "yoy_pct_change"]] = np.nan

        iso = ordered[KEY + [col]].dropna()
        grouped = iso.groupby("organization_perm_id")[col]
        iso = iso[KEY].assign(measure=col, iso_nominal_change=grouped.diff(), iso_pct_change=grouped.pct_change() * 100)
        iso["iforest_score"], iso["iforest_threshold"] = np.nan, np.nan
        for side in (iso["iso_pct_change"] <= 0, iso["iso_pct_change"] > 0):
            group = iso[side]
            if len(group):
                scores, threshold = iforest_scores(group[["iso_pct_change", "iso_nominal_change"]].to_numpy(),
                                                   {"percentile": 99.9})
                iso.loc[group.index, "iforest_score"] = scores
                iso.loc[group.index, "iforest_threshold"] = threshold

        merged = yoy.merge(var, on=KEY + ["measure"], how="left").merge(iso, on=KEY + ["measure"], how="left")
        frames.append(merged)
    table = pd.concat(frames, ignore_index=True)
    table = table.replace([np.inf, -np.inf], np.nan).assign(iforest_threshold=lambda t: t["iforest_threshold"].fillna(np.inf))
    table.insert(0, "record_key", table["organization_perm_id"] + "|" + table["year"].astype(str) + "|" + table["measure"])
    return table


def check_rules(md):
    up, down = md["change_diference_for_variance_test_up"], md["change_diference_for_variance_test_down"]
    low, high = md["per_of_change_in_time_threshold_min"], md["per_of_change_in_time_threshold_max"]
    big = f"abs({{}}) > {md['diff_in_abs_value']}"
    company_year = [
        ("L01", "report", "company-year in the previous extract is in the current one",
         E.ExpectColumnValuesToBeInSet(column="in_current", value_set=[True], row_condition="in_previous == True",
                                       condition_parser="pandas")),
    ]
    datapoint = [
        ("L02", "report", f"variance vs previous extract within {down}%..{up}% (when the change is over "
                          f"{md['diff_in_abs_value']:,})",
         E.ExpectColumnValuesToBeBetween(column="extract_pct_change", min_value=down, max_value=up,
                                         row_condition=big.format("extract_nominal_change"), condition_parser="pandas")),
        ("L03", "report", f"YoY change within {low}%..{high}% (when the change is over {md['diff_in_abs_value']:,})",
         E.ExpectColumnValuesToBeBetween(column="yoy_pct_change", min_value=low, max_value=high,
                                         row_condition=big.format("yoy_nominal_change"), condition_parser="pandas")),
        ("L04", "report", f"Isolation Forest score below its group's 99.9th percentile (YoY beyond {low}%..{high}%)",
         E.ExpectColumnPairValuesAToBeGreaterThanB(
             column_A="iforest_threshold", column_B="iforest_score", ignore_row_if="either_value_is_missing",
             row_condition=f"(iso_nominal_change != 0) & ((iso_pct_change > {high}) | (iso_pct_change < {low}))",
             condition_parser="pandas")),
    ]
    return company_year, datapoint


def prioritise(flags, md, market_cap):
    """The script's rule when a check flags too many: fiscal years from `start`, then the top companies by market cap."""
    if len(flags) <= md["max_number_of_outliers"]:
        return flags
    flags = flags[flags["year"] >= md["start"]].merge(market_cap, on="organization_perm_id", how="left")
    top = flags.sort_values("company_market_cap", ascending=False)["organization_perm_id"].drop_duplicates()
    return flags[flags["organization_perm_id"].isin(top.head(md["number_of_companies"]))].drop(columns="company_market_cap")


def unexpected_keys(result):
    return {r.expectation_config.meta["rule_id"]: [i["record_key"] for i in r.result.get("unexpected_index_list") or []]
            for r in result.results}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mapping", type=Path, help="column_mapping.csv, as in run_script.py")
    parser.add_argument("--script-report", type=Path, help="the QA report the original script wrote, to compare")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    args = parser.parse_args()

    tables = load_inputs(args.input)
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

    # Part 2: derive the comparison columns with pandas, then ordinary GX rules flag the rows.
    current, previous = prepare(current_raw, current_raw.columns, year), prepare(previous_raw, current_raw.columns, year)
    levels = {"company_year": company_years(current, previous), "datapoint": datapoints(current, previous)}
    company_year_rules, datapoint_rules = check_rules(md)
    checks = {"company_year": validate(context, "lseg_company_year", levels["company_year"], company_year_rules, "record_key"),
              "datapoint": validate(context, "lseg_datapoint", levels["datapoint"], datapoint_rules, "record_key")}
    print("\n\nPart 2  The four checks as GX rules")
    for level, result in checks.items():
        print_results(f"  {level} level ({len(levels[level])} rows)", result)

    market_cap = tables["marketcap"][["organization_perm_id", "company_market_cap"]]
    names = tables["icb_info"].assign(organization_perm_id=lambda t: t["organization_perm_id"].astype(str))
    names = names.drop_duplicates("organization_perm_id").set_index("organization_perm_id")["name"]
    flagged = {**unexpected_keys(checks["company_year"]), **unexpected_keys(checks["datapoint"])}
    reported = {}
    print("\n  After the script's prioritisation (per measure, then per check):")
    for rule_id in REASONS:
        level = "company_year" if rule_id == "L01" else "datapoint"
        rows = levels[level].set_index("record_key").loc[flagged.get(rule_id, [])].reset_index()
        if rule_id != "L01":
            rows = pd.concat([prioritise(group, md, market_cap) for _, group in rows.groupby("measure")] or [rows])
        rows = prioritise(rows, md, market_cap)
        reported[rule_id] = rows
        print(f"  {rule_id} {REASONS[rule_id]:<29} flagged {len(flagged.get(rule_id, [])):>3}   reported {len(rows):>3}")
        for _, row in rows.iterrows():
            print(f"       {names.get(row['organization_perm_id'], row['organization_perm_id']):<22} {row['year']}  "
                  f"{row.get('measure', 'N/A')}")
    empty = [REASONS[r] for r in ("L02", "L03", "L04") if reported[r].empty]
    if empty:
        print(f"  note: nothing reported by {', '.join(empty)}. The original script stops in that case "
              "(lines 325, 335 or 344).")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    as_of = pd.to_datetime(current_raw["as_of_date"]).max()
    out = args.output_dir / f"gx_lseg_reported_{as_of:%y%m%d}.json"
    out.write_text(json.dumps({"input_contract": {k: v.to_json_dict() for k, v in contract.items()},
                               "checks": {k: v.to_json_dict() for k, v in checks.items()}}, indent=2, default=str),
                   encoding="utf-8")
    print(f"\nGX results: {out}")

    if args.script_report:
        script = pd.read_excel(args.script_report, sheet_name="summary_report", dtype={"organization_perm_id": str})
        print(f"\nCompared with the original script's report ({args.script_report.name}):")
        for rule_id, reason in REASONS.items():
            rows = script[script["reason_for_inclusion"] == reason]
            script_keys = set(rows["organization_perm_id"] + "|" + rows["year"].astype(str)
                              + ("" if rule_id == "L01" else "|" + rows["measure"]))
            gx_keys = set(reported[rule_id]["record_key"])
            print(f"  {rule_id} {reason:<29} GX {len(gx_keys):>3}   script {len(script_keys):>3}   "
                  f"{'same rows' if gx_keys == script_keys else 'DIFFERENT'}")
            for key in sorted(gx_keys - script_keys):
                print(f"       only in GX      {key}")
            for key in sorted(script_keys - gx_keys):
                print(f"       only in script  {key}")


if __name__ == "__main__":
    main()
