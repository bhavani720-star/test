# SFI LSEG reported (scope 1-3): QC rules with custom Great Expectations and SQL

Built on `sfi-lseg-reported-thin-thread`. The input file is the same script,
`script/input_test_lseg_reported_task.py` (not edited). The QC rules validation part is new:

- the four checks are **custom GX expectations**, not standard ones, so the comparisons with the previous extract and
  the year before happen inside the rules;
- the same checks are also **SQL rules**, saved in the suite as GX `UnexpectedRowsExpectation`;
- rules are authored into one suite JSON and executed from it, and results are written like the QC platform's
  `validation runs` and `failed events` tables.

Rule by rule, and why: [docs/QC_RULES.md](docs/QC_RULES.md). The thin thread's findings on the script are kept in
[docs/FINDINGS.md](docs/FINDINGS.md).

```
script docstring ─► author_suite.py ─► expectations/sfi_lseg_reported_input_checks.json   (authoring)
(settings)                             19 custom GX rules + 13 SQL rules

5 input files ─► gx_lseg_reported.py                                                         (execution)
                 Part 1 input contract (standard GX)
                 Part 2 both extracts in one table ─► custom GX rules ─┐
                                                   └► SQL rules (SQLite) ┴► must agree
                        ─► script's prioritisation ─► validation_runs / failed_events / compare with script
```

| Rule | Check | Custom GX rule | SQL rule |
|---|---|---|---|
| L01 | Datapoints previous only | `ExpectCompanyYearToBeInCurrentExtract` | yes |
| L02 | Variance current vs previous | `ExpectChangeVsPreviousExtractToBeWithinLimits` | yes, per measure |
| L03 | YoY Outliers | `ExpectYearOnYearChangeToBeWithinLimits` | yes, per measure |
| L04 | Iso F YoY current | `ExpectYearOnYearChangeToNotBeIsolationForestOutlier` | no: a model, not a query |

No new packages: the SQL rules run on SQLite, which is part of Python. `requirements-lock.txt` is the thin thread's.

## Steps

Run every command from this folder. On Windows, use `.venv\Scripts\python` wherever the steps say `python`.

### 1. Set up (once)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
```

On the Cloud PC, pip installs from LSEG Artifactory, as in the thin thread's `commonds.txt`.

### 2. Make the sample data (optional, it is already in `sample_data/`)

```
python make_sample_data.py
```

### 3. Run the original script

```
python run_script.py --input sample_data
```

Expected: `summary_report: 24 row(s)` in `output/qa_report_input_test_lseg_scope123_init_261026.xlsx`.
This is the report the QC rules are compared with.

### 4. Author the suite

```
python author_suite.py
```

Expected: `Suite sfi.lseg_reported.input_checks: 32 rules`, written to `expectations/`. The limits come from the
script's docstring; `--set diff_in_abs_value=50000` changes one before the rules are built.

### 5. Run the QC rules

```
python gx_lseg_reported.py --input sample_data --script-report output/qa_report_input_test_lseg_scope123_init_261026.xlsx
```

Expected:

- Part 1: the input contract, all pass.
- Part 2: `custom GX and SQL rules flag the same rows`.
- After prioritisation: 5 / 14 / 2 / 3.
- Compared with the script: `same rows` for L01 to L04.

Results in `output/`: `validation_runs_261026.csv` (32 rule runs), `failed_events_261026.csv` (one row per flagged
data point, per engine) and `gx_lseg_reported_261026.json`.

### 6. Two cases where the rules do better than the script

Unsorted input. The script's Isolation Forest then reports 5 rows instead of 3; the rules still give 3, and the
comparison names the script's 2 extra rows as "only in script":

```
python run_script.py --input sample_data --shuffle-rows
python gx_lseg_reported.py --input sample_data --shuffle-rows --script-report output/shuffled/qa_report_input_test_lseg_scope123_init_261026.xlsx
```

A check that flags nothing. The script stops with no report; the rules record the check as passed:

```
python author_suite.py --set diff_in_abs_value=1000000000000000 --output expectations/quiet_suite.json
python gx_lseg_reported.py --input sample_data --suite expectations/quiet_suite.json
```

### 7. With the real data

```
python gx_lseg_reported.py --input <folder with the 5 files> --mapping column_mapping.csv
```

## Files

```
script/input_test_lseg_reported_task.py   the input: the shared script, not edited
qc_rules/custom_expectations.py           the 4 custom GX expectations and their metrics
qc_rules/sql/                             the SQL rules: L01, L02, L03 ({batch} is the table)
qc_rules/rules.py                         the rule catalogue: builds the suite, loads it, runs the SQL rules
author_suite.py                           authoring: writes expectations/sfi_lseg_reported_input_checks.json
expectations/                             the suite JSON (custom GX + SQL rules, with rule metadata)
gx_lseg_reported.py                       execution: input contract, QC rules, records, compare with the script
run_script.py, utils_lib/                 run the original script unchanged (from the thin thread)
make_sample_data.py, sample_data/         the sample data with planted cases (from the thin thread)
column_mapping.csv                        source -> script column names (from the thin thread)
docs/QC_RULES.md                          the rules, the design and the results
docs/FINDINGS.md                          the thin thread's findings on the script
output/                                   the script's report, validation_runs, failed_events, GX results
```
