# SFI model output checks (scope 1-3): the model owner's process, end to end

The third thin thread, after `sfi-evic-delta-thin-thread` and `sfi-lseg-reported-thin-thread`. This one is about the
**model output** checks, as the model owner explained them in a walkthrough: where the files come from, how a run is laid out, which checks run on it, and what goes to Content Ops.
It is the "day one" set-up agreed in that call: the files are hooked up by hand from the model platform, in the same
folder structure the model owner uses, and their notebooks run on them.

```
model platform file store  ──►  runs/<run date>/          ──►  run_checks.py              ──►  output/<run date>/
(staging or live, 1 per run)    4 folders, file_manifest.csv    runs each check unchanged:       exception records (CSV, JSON)
                                (setup_run_folders.py)          coverage, YoY, d2d               + summarised / full / detailed
                                                                reason -> status -> next step      Excel reports
                                                                linked to the input checks
```

**Not real yet:** we don't have the model owner's notebooks or the list of files on the input documentation page. The three checks in
`checks/` are **stand-ins** that follow the steps the model owner described, and the file names in `file_manifest.csv` and the
sample data are made up. Swap in the real ones as described in step 6.

## The model owner's process, in short

| Step | What the model owner does | Here |
|---|---|---|
| 1 | The model runs on the model platform, staging first, then production (live). Each run has a file store with 4 folders: model output, input data (from ADC / EVIC), scope 1-2 intermediate files, scope 3 intermediate files (compressed CSVs). | `file_manifest.csv` |
| 2 | They download the files they need (about 10 for scope 1-3) into a folder in their OneDrive with the same structure, one folder per run date. For a new run they create the same empty folders. | `setup_run_folders.py` |
| 3 | They edit the path and date in each notebook and run it. Coverage and year on year need the current run; delivery versus delivery also needs the previous production run (e.g. 13 Oct vs 13 Jul). | `run_checks.py` hands each check the run folders (or replaces the path text with `--replace`) |
| 4 | Each notebook finds the outliers (`compute_outliers_volatility`, option 3) and a reason function of if-conditions gives each outlier a reason. Some reasons are final; some need the input check results (e.g. potential loss in reported data); none should stay "not covered yet". | `reason_catalogue.csv`, input check link |
| 5 | One cell writes 3 Excel reports: summarised (sent to Content Ops), full and detailed (audit, tracking). | the 3 reports + exception records for the QC tool |

| Check | Compares | Needs |
|---|---|---|
| `coverage` | company-years the model worked on but has no output value for, and why | current run |
| `yoy` (volatility year on year) | same company and measure, one fiscal year against the year before, within one run | current run |
| `d2d` (volatility delivery versus delivery) | same company-year, this run against the previous production run | current and previous run |

## Steps

### 1. Set up (once)

```powershell
cd sfi-model-output-thin-thread
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

On the Cloud PC, the Anaconda prompt already has both packages: use `python` there directly.

### 2. Make the sample data

```
python make_sample_data.py
```

Two made-up runs in the model owner's layout: `runs/2026-07-13` (previous production run, fiscal years 2021-2024) and
`runs/2026-10-13` (current run, 2021-2025), 20 companies, plus two rows of the input test's report in
`runs/2026-10-13/input_checks/`. The planted cases are listed at the top of `make_sample_data.py`.

### 3. Run the checks

```
python run_checks.py --run-date 2026-10-13 --previous-run-date 2026-07-13
```

Expected: **11 exceptions**: 2 coverage, 2 year on year, 7 delivery versus delivery. 8 have a final reason, 1 needs the
input checks (M01 2024 scope 1, potential loss in reported data: the input test flagged it, but there is no Content Ops
comment yet, so the next step is *Ask Content Ops for a comment*), and 2 are *not covered yet* (M06, M08).

Written to `output/2026-10-13/`:

| File | What it is |
|---|---|
| `exceptions_261013.csv` / `.json` | one record per exception, for the QC tool's database and UI: check, company, year, measure, scope, upstream / downstream, financial / non-financial, values, change, reason, status, next step, input check flag, Content Ops comment, run dates |
| `model_output_checks_summarised_261013.xlsx` | what Content Ops need: company, year, measure, upstream / downstream, financial / non-financial, reason. One sheet per check |
| `model_output_checks_full_261013.xlsx` | plus values, change, status, next step, input check link |
| `model_output_checks_detailed_261013.xlsx` | plus every other column the check produced (method, revenue, intensity, current and previous) |
| `run_log_261013.txt` | the run log |

Without `--previous-run-date`, delivery versus delivery is left out and only coverage and year on year run.

### 4. A new run

```
python setup_run_folders.py --run-date 2026-11-05
```

Creates `runs/2026-11-05/` with the 4 empty folders and lists each file to download, and where from on the platform.
Then run step 3 with the new dates.

### 5. Status and next step of each reason

`reason_catalogue.csv` gives every reason a status:

| Status | Meaning | Next step |
|---|---|---|
| `final` | explains the volatility; can go to the client | Send to Content Ops |
| `needs_input_check` | first-layer reason: check it against the input checks | Explained by the Content Ops comment / Ask Content Ops for a comment / No input check flag: investigate |
| `not_covered` | the reason function could not explain it | Investigate manually |
| `unmapped` | the check gave a reason that is not in the catalogue yet | Add this reason to reason_catalogue.csv |

### 6. With the model owner's real notebooks and files

1. Put the real file names, folders and platform locations from the input documentation page in `file_manifest.csv`
   (the model owner is adding the local path column there too).
2. Download one real run (and the previous production run) into `runs/<date>/` (step 4).
3. Run a notebook in place of a stand-in, unchanged:

```
python run_checks.py --run-date 2026-10-13 --previous-run-date 2026-07-13 ^
    --check d2d="<the model owner's delivery versus delivery notebook>.ipynb" ^
    --result-var d2d=<the table with the reason column> ^
    --replace "<the path in their path cell>=<full path to runs/2026-10-13>" ^
    --replace "<the previous run's path>=<full path to runs/2026-07-13>"
```

The runner runs the notebook's code cells in order (IPython lines such as `%matplotlib` are left out, `display()` does
nothing), so the notebook file itself is not edited. `--replace` does what the model owner does by hand in their path cell. The
table named in `--result-var` must have `organization_perm_id`, `year`, `measure` and `reason` columns. Add any new
reasons to `reason_catalogue.csv`.

4. Compare the three reports with the model owner's for the same run: same rows, same reasons.

## Files

```
file_manifest.csv              every file the checks read: folder, name, type, which checks need it, where on the platform
reason_catalogue.csv           every reason: status (final / needs_input_check / not_covered) and next step
setup_run_folders.py           creates the empty folders for a new run and lists what to download
make_sample_data.py            makes the two sample runs and the input check rows
run_checks.py                  checks the files, runs each check unchanged, builds exception records and the 3 reports
checks/stand_in_coverage.py         stand-in for the model owner's coverage notebook
checks/stand_in_volatility_yoy.py   stand-in for the model owner's year-on-year volatility notebook
checks/stand_in_volatility_d2d.py   stand-in for the model owner's delivery-versus-delivery volatility notebook
runs/                          one folder per model run (sample data)
output/                        exception records, reports and logs, one folder per run
```

## Open points from the call

| Point | Who |
|---|---|
| The ~10 files for scope 1-3, with a local path column, on the Confluence page | the model owner |
| One shared OneDrive run folder (after checking with their team) | the model owner |
| Which columns Content Ops need (the model owner thinks: company-year, upstream / downstream, financial / non-financial, reason) | Content Ops |
| A connector from the model platform (e.g. a Fabric instance) to replace the manual download | platform team |
| Whether Great Expectations rules sit on top of these checks | QC tool team |
