"""STAND-IN for the model owner's year-on-year volatility notebook (scope 1-3). Replace it with the real notebook.

Year on year means within the same run: the same company and measure, one fiscal year against the year before.
It needs the current run only. The outlier rule and the reasons here are made up so the pipeline can be tested.

The runner sets RUN_DIR and reads the table this script leaves in `outliers`.
"""
import numpy as np
import pandas as pd

PCT_LIMIT, ABS_LIMIT = 100, 10_000   # stand-in outlier rule: a change above +/-100% and above 10,000 t
REVENUE_LIMIT, INTENSITY_LIMIT = 0.25, 0.25
KEYS = ["organization_perm_id", "year", "measure"]
IDS = {"organization_perm_id": str}


def relative_change(current, previous):
    return abs(current - previous) / abs(previous) if previous else np.inf


def find_reason(row):
    if row.method_current != row.method_previous:
        return "Method changed between years"
    if relative_change(row.revenue_musd_current, row.revenue_musd_previous) > REVENUE_LIMIT:
        return "Revenue change"
    if relative_change(row.intensity_current, row.intensity_previous) > INTENSITY_LIMIT:
        return "Scope 3 intensity change" if row.measure.startswith("scope3") else "Intensity change"
    return "Not covered yet"


output = pd.read_csv(RUN_DIR / "model_output" / "model_output_scope123.csv.gz", dtype=IDS)
steps = pd.concat([pd.read_csv(RUN_DIR / "intermediate_scope12" / "s12_model_steps.csv.gz", dtype=IDS),
                   pd.read_csv(RUN_DIR / "intermediate_scope3" / "s3_model_steps.csv.gz", dtype=IDS)])
data = output.merge(steps[KEYS + ["revenue_musd", "intensity"]], on=KEYS, how="left").sort_values(KEYS)
year_before = data.assign(year=data["year"] + 1)
pairs = data.merge(year_before, on=KEYS, suffixes=("_current", "_previous"))
pairs["change_abs"] = pairs["value_current"] - pairs["value_previous"]
pairs["change_pct"] = pairs["change_abs"] / pairs["value_previous"] * 100
outliers = pairs[(pairs["change_pct"].abs() > PCT_LIMIT) & (pairs["change_abs"].abs() > ABS_LIMIT)].copy()
outliers["reason"] = outliers.apply(find_reason, axis=1)
outliers = outliers.sort_values(KEYS).reset_index(drop=True)
print(f"year on year: {len(pairs)} consecutive-year pairs, {len(outliers)} outliers")
