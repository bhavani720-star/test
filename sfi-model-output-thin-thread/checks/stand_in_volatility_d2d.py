"""STAND-IN for the model owner's delivery-versus-delivery volatility notebook (scope 1-3). Replace it with the real notebook.

It follows the steps the model owner described: read the current and the previous production run, find the volatility
outliers (compute_outliers_volatility, option 3 by default), then a reason function, a set of if-conditions that
mirrors the model's logic in a simplified way, gives each outlier a reason. The outlier rule and the reasons here are
made up so the pipeline can be tested end to end.

The runner sets RUN_DIR and PREVIOUS_RUN_DIR (in the model owner's notebooks this is the path cell edited for each run) and
reads the table this script leaves in `outliers`.
"""
import numpy as np
import pandas as pd

PCT_LIMIT, ABS_LIMIT = 50, 10_000   # stand-in outlier rule: a change above +/-50% and above 10,000 t
REVENUE_LIMIT, INTENSITY_LIMIT = 0.25, 0.25
KEYS = ["organization_perm_id", "year", "measure"]
IDS = {"organization_perm_id": str}


def read_run(run_dir):
    output = pd.read_csv(run_dir / "model_output" / "model_output_scope123.csv.gz", dtype=IDS)
    steps = pd.concat([pd.read_csv(run_dir / "intermediate_scope12" / "s12_model_steps.csv.gz", dtype=IDS),
                       pd.read_csv(run_dir / "intermediate_scope3" / "s3_model_steps.csv.gz", dtype=IDS)])
    reported = pd.read_csv(run_dir / "input_data" / "lseg_reported_scope123.csv.gz", dtype=IDS)
    return (output.merge(steps[KEYS + ["revenue_musd", "intensity"]], on=KEYS, how="left")
                  .merge(reported, on=KEYS, how="left"))


def relative_change(current, previous):
    return abs(current - previous) / abs(previous) if previous else np.inf


def find_reason(row):
    if row.method_previous == "reported" and row.method_current == "modelled":
        return "Potential loss in reported data"
    if row.method_previous == "modelled" and row.method_current == "reported":
        return "New reported data point"
    if row.method_current == "reported":
        return "Reported value restated"
    if relative_change(row.revenue_musd_current, row.revenue_musd_previous) > REVENUE_LIMIT:
        return "Revenue change"
    if relative_change(row.intensity_current, row.intensity_previous) > INTENSITY_LIMIT:
        return "Scope 3 intensity change" if row.measure.startswith("scope3") else "Intensity change"
    return "Not covered yet"


both = read_run(RUN_DIR).merge(read_run(PREVIOUS_RUN_DIR), on=KEYS, suffixes=("_current", "_previous"))
both["change_abs"] = both["value_current"] - both["value_previous"]
both["change_pct"] = both["change_abs"] / both["value_previous"] * 100
outliers = both[(both["change_pct"].abs() > PCT_LIMIT) & (both["change_abs"].abs() > ABS_LIMIT)].copy()
outliers["reason"] = outliers.apply(find_reason, axis=1)
outliers = outliers.sort_values(KEYS).reset_index(drop=True)
print(f"delivery vs delivery: {len(both)} company-year-measures in both runs, {len(outliers)} outliers")
