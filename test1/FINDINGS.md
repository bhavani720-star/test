# LSEG reported (scope 1-3) input test: findings

Script: `input_test_lseg_reported_task.py` (SFI MM PoC scripts > Model input related), transcribed from a screen
recording, 404 lines, not edited. Everything below was run on made-up sample data; commands are in the README.

## 1. "If I give you the files, can you run the script?" Yes.

```
python run_script.py --input sample_data
```

The script runs **unchanged** (pandas 2.3.3, and pandas 3.1.0 gives the same result) and writes
`qa_report_input_test_lseg_scope123_init_261026.xlsx` with five sheets. Every run writes a log to
`output/run_log_YYMMDD.txt`.

## 2. What the script needs that is not in the script

| Needed | On StarMine | Here |
|---|---|---|
| `metadata` | Given by the job: start year, % limits, max outliers, number of companies | Read from the script's own docstring; `--set KEY=VALUE` changes one for a run |
| `get_df_for_slice(path, reference_datetime)` | The ADC extract stored at `reference_datetime` (2026-07-13): the previous extract | Returns `previous_extract` |
| `get_all_inputs()` | `lseg_reported` (current extract), `marketcap`, `icb_info`, `univ_inactive` | Returns the four files |
| `current_date` | Given by the job; names the Excel file | Latest `as_of_date` of the current extract, or `--current-date` |
| `utils_lib.utils` | 6 functions: `get_change`, `prepaire_year_column_input_test`, `prioritize_list_of_suspicious_datapoints`, 2 x `include_value_in_summary_report_...`, `write_to_excel` | Stand-ins in `utils_lib/utils.py`, or `--utils-dir` for the real one |
| `import boto3`, `sklearn` | Installed | sklearn installed; boto3 imported but never used, an empty stand-in if missing |

## 3. Issues found in the script as shared

| # | Issue | Effect | Shown by |
|---|---|---|---|
| 1 | A check that flags nothing makes the script **stop** (lines 325, 335, 344: `apply(..., axis=1)` on an empty table) | A quiet run, with no variance, YoY or Isolation Forest flags, gives **no report at all** | `--set diff_in_abs_value=1000000000000000` |
| 2 | Isolation Forest works out year-on-year changes on the current extract **in the order it arrives** (lines 206-210; the YoY check sorts first, line 147) | Unsorted input gives **wrong flags, no error**. Sample: 5 rows instead of 3 | `--shuffle-rows`; GX names the 2 extra rows |
| 3 | The variance check only compares company-years found in both extracts | A company that is **new** in the current extract (C41) is never compared; only the YoY checks see it | Runner note |
| 4 | Isolation Forest results are kept only if the YoY % is also beyond -83%..500% (line 278) | It catches large % changes the YoY check leaves out because the change is under 100,000 (C31), but never an unusual change inside the % limits | Sample case C31 |
| 5 | If the previous extract lacks a `verification` column the current one has | Bare `KeyError` at line 71 | Runner and GX rule C10 check it first |
| 6 | Lines 176-197 build `df_merged_comco_both`, which is never used | No effect; dead code (its `concat` also mixes row indexes) | Reading the script |
| 7 | Lines 245 and 268: `drop('Anomaly Score', axis = 1)` is not saved back | No effect; harmless, as line 389 needs that column | Reading the script |
| 8 | Line 213 renames `<col>_x` but keeps `<col>_y` | Extra duplicate columns (visible in the script's printout) | Run output |

The runner guards 2, 3 and 5 without editing the script and explains 1 when it happens. 1, 2 and 4 need model
management's intent.

## 4. Columns

All columns are in `column_mapping.csv`, per input. The script needs, from both extracts: `organization_perm_id`, a
fiscal year (made into `year` by `prepaire_year_column_input_test`), scope 1, scope 2, scope 2 market-based, scope 2
location-based, the scope 3 category columns (found by `up_scope3` / `down_scope3` in the name and added up), and
`as_of_date`. The real TR. / DaaS names of the emission columns are **not known yet**, so the mapping is one-to-one
for now; `--mapping` is ready for when they are.

## 5. Great Expectations: can we migrate? Yes, all four checks, with one pandas step before.

`gx_lseg_reported.py` runs both parts.

**Input contract.** 10 GX rules on each extract (columns present, `as_of_date` a date, keys filled, one row per
company and year, no negative emissions, `verification` columns in both) and one on each reference table. This turns
issue 5 into a clear stop.

**The four checks.** GX validates one table at a time, so pandas first adds the comparison columns the same way the
script works them out (variance %, YoY %, Isolation Forest score and threshold). Then four ordinary GX rules flag the
rows, and the script's prioritisation is applied after. Result on the sample: **the same rows as the script for all
four checks** (5 / 14 / 2 / 3). Because the GX version sorts before working out year-on-year changes, it is not
affected by issue 2.

**Recommendation:** the checks move to GX well with the "derive columns first, then plain rules" pattern already used
for A01-A04 in `sfi-qc-poc`. Keep the Isolation Forest scoring and the prioritisation as small pandas steps around
the rules. Note that `sfi-qc-poc` A04 does not have the line 278 filter (issue 4), so its counts can differ from the
original script.

## 6. Questions for model management

1. Can we have the real `utils_lib`? Especially `prioritize_list_of_suspicious_datapoints` (which market cap column?),
   `get_change` and `prepaire_year_column_input_test` (which column does it read the year from?).
2. How is `metadata` built on StarMine: from the script's docstring, or from a dataset definition?
3. Is the current extract always sorted by `organization_perm_id` and year when it arrives? (Issue 2.)
4. Has a run ever had no variance, YoY or Isolation Forest flags? What happened? (Issue 1.)
5. Is the YoY % filter on the Isolation Forest results (line 278) intended? (Issue 4.)
6. Should companies that are new in the current extract be flagged for review? (Issue 3.)
7. What are the real column names (TR. / DaaS) for the six measures and the scope 3 categories?
8. Is there a delta script for this test, like the EVIC one, so Content Ops only gets new flags each run?
