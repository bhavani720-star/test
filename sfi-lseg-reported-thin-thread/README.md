# SFI LSEG reported (scope 1-3): one script, end to end

The same approach as `sfi-evic-delta-thin-thread`, for the second model management script:
`input_test_lseg_reported_task.py` (SFI MM PoC scripts > Model input related), transcribed from a screen recording
(404 lines, not edited). The script runs **unchanged** on local files and writes the same
`qa_report_input_test_lseg_scope123_init_YYMMDD.xlsx` it writes on StarMine.

The answers for the meeting (what the script needs, issues found, Great Expectations, questions for model
management) are in [docs/FINDINGS.md](docs/FINDINGS.md).

```
5 input files ───────────► column_mapping.csv ─► run_script.py supplies 4 things ─► original script ─► QA report Excel
(2 ADC extracts            (source -> script     metadata, get_df_for_slice(),      (not edited)       output/
 + 3 reference tables)      column names)        get_all_inputs(), current_date
                                                 + utils_lib stand-ins (6 functions)
```

## What the script does, in one line

It compares this run's ADC extract of LSEG reported scope 1-3 emissions with the previous extract, flags four kinds
of suspicious data points, and writes them to one Excel QA report for Content Ops.

| Report sheet | What it flags | Settings (from the script's docstring) |
|---|---|---|
| `datapoints_only_previous` | Company-years in the previous extract that are missing from the current one | |
| `variance current vs previous` | Same company and year, a big change between the two extracts | above +200% or below -66%, and a change over 100,000 |
| `YoY Outliers` | A big change from the fiscal year before (current extract) | above +500% or below -83%, and a change over 100,000 |
| `ISO F YoY current` | The most unusual year-on-year change per measure (Isolation Forest), if it is also beyond the YoY % limits | 99.9th percentile of the anomaly score |

The six measures: scope 1, scope 2, scope 2 market-based, scope 2 location-based, and upstream and downstream scope 3
(each a sum of the category columns). If a check flags more than 50, it keeps only fiscal years from 2024 and the
30 largest companies by market cap.

## Steps

### 1. Set up (once)

The `.venv` in this folder is already set up. To make it again, Windows PowerShell:

```powershell
cd sfi-lseg-reported-thin-thread
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Run every command below from this folder (the prompt ends in `\sfi-lseg-reported-thin-thread>`).
On Windows, use `.venv\Scripts\python` wherever the steps say `python`.

### 2. Make the sample data

```
python make_sample_data.py
```

Two made-up ADC extracts and three reference tables, with a fixed random seed:

| File | Content |
|---|---|
| `sample_data/current_extract.csv` | as of 2026-10-26, fiscal years 2021-2025, 40 companies |
| `sample_data/previous_extract.csv` | as of 2026-07-13 (the script's `reference_datetime`), fiscal years 2021-2024, 40 companies |
| `sample_data/marketcap.csv`, `icb_info.csv`, `univ_inactive.csv` | market cap, name / RIC / industry, and one delisted company |

Planted cases (details at the top of `make_sample_data.py`):

| Case | Check | Expected |
|---|---|---|
| C39 left the extract (delisted); C05 2023 emptied | Datapoints previous only | 5 rows, comment "Delisted" for C39 |
| C01 2023 scope 1 +700%, C02 2022 scope 2 -90% | Variance | flagged |
| C30 2023 scope 1 +400% but a change under 100,000 | Variance | not flagged |
| 60 company-years of downstream scope 3 restated | Variance | 60 flagged, prioritised to 12 |
| C03 2024 scope 1 +600%, C04 2025 upstream scope 3 -92% | YoY | flagged |
| C31 2025 scope 2 location-based +1,900% but a change under 100,000 | YoY / Isolation Forest | YoY: no; Isolation Forest: yes |
| C41 is a new company, only in the current extract | none | never compared with a previous extract |

### 3. Run the script on the sample data

```
python run_script.py --input sample_data
```

Expected: a summary report of **24 rows** (5 previous only, 14 variance, 2 YoY, 3 Isolation Forest) in
`output/qa_report_input_test_lseg_scope123_init_261026.xlsx`, and the log in `output/run_log_261026.txt`.
The runner also counts the flags per measure on its own, so you can see the prioritisation: downstream scope 3 has
60 variance flags and 12 reported.

### 4. Change a setting for one run

```
python run_script.py --input sample_data --set max_number_of_outliers=100
```

Any setting from the script's docstring can be changed this way. The script itself is not edited.

### 5. Show the unsorted-input trap

```
python run_script.py --input sample_data --shuffle-rows
```

The same data in a different row order. The Isolation Forest check now reports **5** rows instead of 3 (written to
`output/shuffled/`). See findings, issue 2.

### 6. Great Expectations version

```
python gx_lseg_reported.py --input sample_data --script-report output/qa_report_input_test_lseg_scope123_init_261026.xlsx
```

Part 1: the input contract on all five files, all pass. Part 2: the four checks as GX rules, then the script's
prioritisation, then a comparison with the script's report: **same rows for all four checks**.
Compare with the shuffled report instead (`output/shuffled/...`) and GX lists the 2 extra Isolation Forest rows
as "only in script". Results go to `output/gx_lseg_reported_261026.json`.

### 7. With the real data and the real utils

```
python run_script.py --input <folder with the 5 files> --mapping column_mapping.csv --utils-dir <folder that contains utils_lib>
```

## Files

```
script/input_test_lseg_reported_task.py   the shared script, transcribed from the screen recording, not edited
run_script.py                             loads the 5 inputs, maps columns, supplies the 4 things, runs the script, counts
utils_lib/utils.py                        stand-ins for the 6 utils functions the script calls
column_mapping.csv                        every column the script reads, per input: source name, DaaS target, status
gx_lseg_reported.py                       Great Expectations: input contract + the four checks as GX rules
make_sample_data.py                       makes the sample data
docs/FINDINGS.md                          answers for the meeting
output/                                   QA report Excel, run logs, GX results
```

## Compared with the EVIC delta project

| | EVIC delta (`sfi-evic-delta-thin-thread`) | LSEG reported (this project) |
|---|---|---|
| What the script does | Keeps the init test's flags that are new this week | Is an init test: runs four checks on the ADC extracts |
| Inputs StarMine supplies | `input_tests_evic_df`, `current_date` | `metadata`, `get_df_for_slice()`, `get_all_inputs()`, `current_date` |
| utils functions called | 1 (`write_to_excel`) | 6 |
| pandas 3 | fails (`drop(columns=..., axis=1)`) | runs, same result |
| Trap shown | `--no-date-fix`: empty report, no error | `--shuffle-rows`: wrong Isolation Forest flags, no error |
| GX | input contract + the delta as one rule | input contract + all four checks as rules |
