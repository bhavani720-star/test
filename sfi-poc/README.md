# SFI EVIC delta: one script, end to end

Devesh's question in the SFI work-progress meeting: *"If I give you a CSV right now, can you run that script?"*

This project answers it for the script model management shared after the meeting,
`input_test_evic_delta_task.py` (SFI MM PoC scripts > Model input related). The script runs **unchanged** on a
plain CSV, on a folder of weekly files, or on an Excel file with TR. field names. It writes the same
`qa_report_input_test_evic_delta_YYMMDD.xlsx` it writes on StarMine.

The answers for the meeting (what the script needs, mapping gaps, bugs found, Great Expectations, questions
for model management) are in [docs/FINDINGS_FOR_DEVESH.md](docs/FINDINGS_FOR_DEVESH.md).

```
CSV / Excel / weekly files ─► column_mapping.csv ─► run_script.py supplies 3 things ─► original script ─► delta Excel
 (script or TR. names)        (TR. -> script name)   input_tests_evic_df, current_date,    (not edited)       output/
                                                     utils_lib.utils.write_to_excel
```

## What the script does, in one line

Of the rows the EVIC input test flagged **this week**, keep only those never flagged in **any earlier week**
(matched on `organization_perm_id + year + measure`), and send that "new this week" list to Content Ops as Excel.

## Steps

### 1. Set up (once)

Windows PowerShell:

```powershell
cd sfi-evic-delta-thin-thread
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

macOS / Linux:

```bash
cd sfi-evic-delta-thin-thread
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` pins pandas 2.x: the script as written does not run on pandas 3 (see findings, issue 3).
On Windows, use `.venv\Scripts\python` wherever the steps below say `python`.

### 2. Make the sample data

```
python make_sample_data.py
```

Three Mondays (12, 19, 26 Oct 2026) of made-up EVIC init results, 18 rows, with planted cases. It writes the
same data three ways:

| File | Shape |
|---|---|
| `sample_data/input_tests_evic_history.csv` | one CSV, the script's column names, an `as_of_date` column |
| `sample_data/weekly/input_tests_evic_YYYY-MM-DD.csv` | one file per Monday, date in the file name |
| `sample_data/input_tests_evic_history_tr_names.xlsx` | Excel with TR. field names, like a client extract |

### 3. Run the script on the CSV 

```
python run_script.py --input sample_data/input_tests_evic_history.csv
```

Expected: `current_date = 2026-10-26: 8 rows this week, 10 rows from 2 earlier week(s)`, a delta report of
**4 rows**, and `output/qa_report_input_test_evic_delta_261026.xlsx`. The log is saved to `output/run_log_261026.txt`.

The runner also works out the expected delta on its own and compares: 5 rows are new, the script reports 4.
See findings, issue 1.

### 4. Same run, other input shapes

```
python run_script.py --input sample_data/weekly
python run_script.py --input sample_data/input_tests_evic_history_tr_names.xlsx
python run_script.py --input sample_data/input_tests_evic_history_tr_names.xlsx --mapping column_mapping.csv
```

The second one stops on purpose and lists the 11 missing columns with the TR. field each one comes from.
With `--mapping` it renames them and gives the same 4-row result.

### 5. Show the silent-empty trap

```
python run_script.py --input sample_data/input_tests_evic_history.csv --no-date-fix
```

The data goes in exactly as read from the CSV. The script runs without an error and writes an **empty** report
(to `output/no_date_fix/`). See findings, issue 2.

### 6. Great Expectations version

```
python gx_evic_delta.py --input sample_data/input_tests_evic_history.csv --script-report output/qa_report_input_test_evic_delta_261026.xlsx
```

Part 1: 7 input-contract rules, all pass. Part 2: the delta as one GX rule, 5 new rows.
It then compares with the script's report: GX has the one row the script drops. Results go to
`output/gx_evic_delta_261026.json`.

### 7. With the real data and the real utils

```
python run_script.py --input <real extract> --mapping column_mapping.csv --utils-dir <folder that contains utils_lib>
```

## Files

```
script/input_test_evic_delta_task.py   the shared script, transcribed from the screenshots, not edited
run_script.py                          loads data, maps columns, supplies the 3 inputs, runs the script, cross-checks
utils_lib/utils.py                     stand-in for model management's utils.write_to_excel
column_mapping.csv                     the 17 columns: script name, TR. field, source, DaaS target, status
gx_evic_delta.py                       Great Expectations: input contract + the delta as a GX rule
make_sample_data.py                    makes the sample data
docs/FINDINGS_FOR_DEVESH.md            answers for the meeting
output/                                Excel reports, run logs, GX results
```

Related earlier work: `../sfi-qc-poc` (local copy of the LMP QC tool flow with GX, and the Scope 1-3 ADC
checks A01-A04). Its `evic_delta/` folder is the first version of this project.
