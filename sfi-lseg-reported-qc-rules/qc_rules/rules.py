"""The QC rules for the LSEG reported input test, built from the script's own settings.

One suite holds two kinds of rule for the same four checks:

    gx_custom   the custom GX expectations in custom_expectations.py, run by GX on pandas (or Spark on the platform)
    sql         the SQL rules in sql/, saved in the suite as GX UnexpectedRowsExpectation, so a SQL or Spark data
                source on the QC platform can run them as they are; locally they run on SQLite

L01 is one rule. L02, L03 and L04 are one rule per measure, like "apply on multiple columns" in the authoring notebook.
L04 (Isolation Forest) is a model, not a query, so it has no SQL rule.
"""
import json
import sqlite3
from pathlib import Path

import great_expectations as gx
import pandas as pd

from qc_rules import custom_expectations as cx

SQL_DIR = Path(__file__).resolve().parent / "sql"
DOMAIN, STAGE = "SFI", "lseg_reported_input"
SUITE_NAME = "sfi.lseg_reported.input_checks"
COMPANY_YEAR = ["organization_perm_id", "year", "snapshot"]
SQL_TABLE = "lseg_extracts"

CHECKS = {
    "L01": {"check": "Datapoints previous only", "dimension": "Completeness", "script_lines": "110-111",
            "expectation": cx.ExpectCompanyYearToBeInCurrentExtract, "sql": "L01_company_year_missing_in_current.sql"},
    "L02": {"check": "Variance current vs previous", "dimension": "Consistency", "script_lines": "114-136",
            "expectation": cx.ExpectChangeVsPreviousExtractToBeWithinLimits, "sql": "L02_change_vs_previous_extract.sql"},
    "L03": {"check": "YoY Outliers", "dimension": "Accuracy", "script_lines": "146-169",
            "expectation": cx.ExpectYearOnYearChangeToBeWithinLimits, "sql": "L03_year_on_year_change.sql"},
    "L04": {"check": "Iso F YoY current", "dimension": "Accuracy", "script_lines": "202-279",
            "expectation": cx.ExpectYearOnYearChangeToNotBeIsolationForestOutlier, "sql": None},
}


def limits(md):
    """The script's docstring settings, as the parameters each rule takes."""
    variance = {"min_pct_change": md["change_diference_for_variance_test_down"],
                "max_pct_change": md["change_diference_for_variance_test_up"],
                "min_abs_change": md["diff_in_abs_value"]}
    yoy = {"min_pct_change": md["per_of_change_in_time_threshold_min"],
           "max_pct_change": md["per_of_change_in_time_threshold_max"],
           "min_abs_change": md["diff_in_abs_value"]}
    return {"L01": {}, "L02": variance, "L03": yoy,
            "L04": {"min_pct_change": yoy["min_pct_change"], "max_pct_change": yoy["max_pct_change"],
                    "percentile": 99.9, "test_size": 0.2, "random_state": 42}}


def render_sql(file_name, measure, params):
    """Fill in the measure and limits; {batch} stays, as GX and the local runner put the table there."""
    template = (SQL_DIR / file_name).read_text(encoding="utf-8")
    return template.format(batch="{batch}", measure=measure or "", **params)


def meta(rule_id, measure, engine):
    check = CHECKS[rule_id]
    return {"rule_id": rule_id, "check": check["check"], "measure": measure or "N/A", "engine": engine,
            "data_quality_dimension": check["dimension"], "domain": DOMAIN, "stage": STAGE,
            "source": f"input_test_lseg_reported_task.py lines {check['script_lines']}"}


def build_suite(context, md, measures):
    """Authoring: every rule, with the metadata the QC platform keeps (rule id, check, dimension, domain, stage)."""
    suite = context.suites.add(gx.ExpectationSuite(name=SUITE_NAME, meta={
        "domain": DOMAIN, "stage": STAGE, "built_from": "input_test_lseg_reported_task.py"}))
    params = limits(md)
    for rule_id, check in CHECKS.items():
        for measure in ([None] if rule_id == "L01" else measures):
            columns = COMPANY_YEAR + ([measure] if measure else [])
            # severity "warning": a flag is a data point for Content Ops to review, not a reason to stop the run
            suite.add_expectation(check["expectation"](column_list=columns, severity="warning",
                                                       meta=meta(rule_id, measure, "gx_custom"), **params[rule_id]))
            if check["sql"]:
                suite.add_expectation(gx.expectations.UnexpectedRowsExpectation(
                    unexpected_rows_query=render_sql(check["sql"], measure, params[rule_id]), severity="warning",
                    description=f"{rule_id} {check['check']}{f' ({measure})' if measure else ''}, as SQL",
                    meta=meta(rule_id, measure, "sql")))
    return suite


def rule_key(rule):
    return rule["meta"]["rule_id"], rule["meta"]["measure"]


def load_suite(path):
    """Execution: read the saved suite. Returns it with its GX rules and SQL rules apart, as they run on different
    engines. The custom types resolve because importing this module imports custom_expectations."""
    saved = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = [{k: v for k, v in e.items() if k != "id"} for e in saved["expectations"]]
    return (saved, [r for r in rules if r["meta"]["engine"] == "gx_custom"],
            [r for r in rules if r["meta"]["engine"] == "sql"])


def extracts_table(current, previous):
    """Both prepared extracts in one table, so a rule can compare a row with the matching previous or prior-year row."""
    table = pd.concat([current.assign(snapshot=cx.CURRENT), previous.assign(snapshot=cx.PREVIOUS)], ignore_index=True)
    table.insert(0, "record_key", table["organization_perm_id"].astype(str) + "|" + table["year"].astype(str)
                 + "|" + table["snapshot"])
    return table


def run_sql_rules(sql_rules, table):
    """Run each SQL rule on SQLite (part of Python, nothing to install). Returns (rule id, measure) -> unexpected rows."""
    connection = sqlite3.connect(":memory:")
    try:
        table.to_sql(SQL_TABLE, connection, index=False)
        return {rule_key(rule): pd.read_sql_query(
                    rule["kwargs"]["unexpected_rows_query"].replace("{batch}", SQL_TABLE), connection)
                for rule in sql_rules}
    finally:
        connection.close()
