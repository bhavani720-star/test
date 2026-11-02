"""Local stand-in for model management's shared utils (the "toolbox" file).

The EVIC delta script calls only one function from it: utils.write_to_excel(sheets_dict, file_name, slice_date).
The real code is not shared with us yet, so this version does what the call implies: one workbook, one sheet per
entry in sheets_dict, saved as <file_name>_<slice_date>.xlsx (slice_date is YYMMDD).

Where the real one saves the file (local disk or S3, given the script imports boto3) is an open question.
Here it goes to the folder in the QC_OUTPUT_DIR environment variable, which run_script.py sets.
When you get the real utils_lib, pass its parent folder with: run_script.py --utils-dir <folder>
"""
import os
from pathlib import Path

import pandas as pd


def write_to_excel(sheets_dict, file_name, slice_date):
    out_dir = Path(os.environ.get("QC_OUTPUT_DIR", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{file_name}_{slice_date}.xlsx"
    with pd.ExcelWriter(path) as writer:
        for sheet_name, frame in sheets_dict.items():
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    sizes = ", ".join(f"{name}: {len(frame)} rows" for name, frame in sheets_dict.items())
    print(f"  [utils.write_to_excel] wrote {path} ({sizes})")
    return path
