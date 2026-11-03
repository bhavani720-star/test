"""STAND-IN for the model owner's coverage notebook (scope 1-3). Replace it with the real notebook.

Coverage looks at every company-year the model worked on that has no output value, finds the root cause and
explains it. It needs the current run only. The reasons here are made up so the pipeline can be tested.

The runner sets RUN_DIR and reads the table this script leaves in `outliers`.
"""
import pandas as pd

KEYS = ["organization_perm_id", "year", "measure"]
IDS = {"organization_perm_id": str}


def find_reason(row):
    if pd.isna(row.reported_value) and pd.isna(row.revenue_musd):
        return "No reported data and no revenue"
    return "Not covered yet"


output = pd.read_csv(RUN_DIR / "model_output" / "model_output_scope123.csv.gz", dtype=IDS)
steps = pd.concat([pd.read_csv(RUN_DIR / "intermediate_scope12" / "s12_model_steps.csv.gz", dtype=IDS),
                   pd.read_csv(RUN_DIR / "intermediate_scope3" / "s3_model_steps.csv.gz", dtype=IDS)])
reported = pd.read_csv(RUN_DIR / "input_data" / "lseg_reported_scope123.csv.gz", dtype=IDS)
worked_on = steps.merge(output, on=KEYS, how="left").merge(reported, on=KEYS, how="left")
outliers = worked_on[worked_on["value"].isna()].copy()
outliers["reason"] = outliers.apply(find_reason, axis=1)
outliers = outliers.sort_values(KEYS).reset_index(drop=True)
print(f"coverage: {len(worked_on)} company-year-measures the model worked on, {len(outliers)} without an output value")
