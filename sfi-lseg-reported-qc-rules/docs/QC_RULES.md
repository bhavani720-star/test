# LSEG reported input test as QC rules

How the four checks in `script/input_test_lseg_reported_task.py` became QC rules: **custom** Great Expectations rules
and SQL rules, in one expectation suite. Built on the QC platform walkthrough (authoring, suites, execution, results)
and on the thin thread in `sfi-lseg-reported-thin-thread`.

## Why custom rules

The standard GX rules check one row at a time, for example "this column is not null". Every check in this script
compares a row with another row: the same company-year in the previous extract, or the same company's year before.
The thin thread solved that by working out the comparisons in pandas first and then running standard rules on the
result. Here the comparison happens **inside** the rule:

- Both extracts go into one table, with a `snapshot` column (`current` or `previous`).
- Each custom rule is a GX `MulticolumnMapExpectation` with its own metric. The metric sees the whole table, so it
  can find the matching previous row or the year before, and marks each row as expected or not.
- A row GX marks as unexpected is a data point the script would flag. Its `record_key` is
  `organization_perm_id|year|snapshot`.

## The rules

| Rule | Script check (lines) | Custom GX rule | SQL rule | Dimension | Per measure |
|---|---|---|---|---|---|
| L01 | Datapoints previous only (110-111) | `ExpectCompanyYearToBeInCurrentExtract` | `L01_company_year_missing_in_current.sql` | Completeness | no, 1 rule |
| L02 | Variance current vs previous (114-136) | `ExpectChangeVsPreviousExtractToBeWithinLimits` | `L02_change_vs_previous_extract.sql` | Consistency | yes, 6 rules |
| L03 | YoY Outliers (146-169) | `ExpectYearOnYearChangeToBeWithinLimits` | `L03_year_on_year_change.sql` | Accuracy | yes, 6 rules |
| L04 | Iso F YoY current (202-279) | `ExpectYearOnYearChangeToNotBeIsolationForestOutlier` | none: a model, not a query | Accuracy | yes, 6 rules |

19 custom GX rules and 13 SQL rules, 32 in all. "Per measure" is the authoring notebook's "apply on multiple
columns": one rule for each of scope 1, scope 2, scope 2 market-based, scope 2 location-based, and upstream and
downstream scope 3.

Rule parameters, taken from the script's docstring when the suite is built:

| Rule | Parameters |
|---|---|
| L02 | `min_pct_change` -66, `max_pct_change` 200, `min_abs_change` 100,000 |
| L03 | `min_pct_change` -83, `max_pct_change` 500, `min_abs_change` 100,000 |
| L04 | `min_pct_change` -83, `max_pct_change` 500, `percentile` 99.9, `test_size` 0.2, `random_state` 42 |

Every rule carries metadata, as in the authoring notebook: `rule_id`, `check` (the script's reason for inclusion),
`measure`, `engine`, `data_quality_dimension`, `domain` (SFI), `stage` (lseg_reported_input) and `source` (the script
lines). Severity is GX's `warning`: a flag is a data point for Content Ops to review, not a reason to stop.

## Authoring and execution

| QC platform (walkthrough) | Here |
|---|---|
| Authoring notebook: create rules from expectation types, save the suite | `python author_suite.py` writes `expectations/sfi_lseg_reported_input_checks.json` |
| Consolidated expectations JSON in the central store | the same JSON; custom types are named by their snake_case type |
| Test the rules on sample data before the merge request | `python gx_lseg_reported.py --input sample_data` |
| Execution notebook: run a suite against a data frame | `gx_lseg_reported.py` reads the JSON and runs it |
| `validation runs` table: every rule, passed or not | `output/validation_runs_YYMMDD.csv` |
| `failed events` table: only failed outcomes | `output/failed_events_YYMMDD.csv` |

To move the rules to the platform, the custom rule classes in `qc_rules/custom_expectations.py` have to be importable
where the suite runs, as for any custom GX expectation. The SQL rules are standard GX `UnexpectedRowsExpectation`
rules, so a SQL or Spark data source can run them without custom code. `{batch}` in each query is the table.

## Results on the sample data

| | L01 | L02 | L03 | L04 |
|---|---|---|---|---|
| Custom GX rules flag | 5 | 62 | 2 | 3 |
| SQL rules flag | 5 | 62 | 2 | - |
| After the script's prioritisation | 5 | 14 | 2 | 3 |
| Original script reports | 5 | 14 | 2 | 3 |

Custom GX and SQL agree on every rule, and after prioritisation the rows are the same as the script's. Two cases
behave differently from the script, on purpose:

| Case | Original script | QC rules |
|---|---|---|
| Current extract arrives unsorted | Isolation Forest flags 5 rows instead of 3 (findings, issue 2) | Same 3 rows: the rules sort by company and year |
| A check flags nothing | Stops at line 325, 335 or 344, no report (findings, issue 1) | Records the rule as passed and carries on |

## What stays outside the rules

| Step | Why |
|---|---|
| Preparing the extracts (script lines 63-106): drop `verification`, add scope 3 totals, 0 as empty | Data shaping, not a rule. A pandas step before the suite runs |
| Prioritisation: more than 50 flags keeps fiscal years from `start` and the top 30 companies by market cap | It picks which flags to send, it does not decide what is wrong. A pandas step after |
| Isolation Forest as SQL | A trained model has no SQL form. L04 runs as a custom GX rule only |

## Notes for the real data

- Line 278 orders things differently: the script prioritises the Isolation Forest flags before the YoY % filter, the
  rules filter first. With more than 50 Isolation Forest flags for one measure the counts could differ. On the
  sample they are the same.
- The SQL uses `NULLIF`, `LAG ... OVER` and `NOT EXISTS`, which SQLite, Spark SQL and SQL Server all support.
- The column names are the script's. When the DaaS names are known, rename in `column_mapping.csv` as before; the
  rules do not change.
