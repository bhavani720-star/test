"""Create the empty folder structure for one model run, the way the model owner keeps it, and list what to download into it.

The model owner's step for a new run: "create the same type of folder structure, but empty folders", download the files from
the model platform's file store into them, then point the notebooks at the new date. The folders and files come from
file_manifest.csv, so the list stays in one place.

    python setup_run_folders.py --run-date 2026-11-05
    python setup_run_folders.py --run-date 2026-11-05 --environment staging --root D:/model_runs

--run-date     YYYY-MM-DD of the model run; it names the folder
--environment  live (production) or staging; only used in the "download from" text
--root         folder that holds one sub-folder per run date; default: runs/
--manifest     default: file_manifest.csv
"""
import argparse
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--environment", default="live", choices=["live", "staging"])
    parser.add_argument("--root", type=Path, default=HERE / "runs")
    parser.add_argument("--manifest", type=Path, default=HERE / "file_manifest.csv")
    args = parser.parse_args()

    manifest = pd.read_csv(args.manifest)
    run_dir = args.root / args.run_date.isoformat()
    for folder, files in manifest.groupby("folder", sort=False):
        (run_dir / folder).mkdir(parents=True, exist_ok=True)
        print(f"\n{run_dir / folder}")
        for row in files.itertuples():
            there = "  (already there)" if (run_dir / folder / row.file_name).exists() else ""
            where = row.platform_location.format(environment=args.environment, run_date=args.run_date)
            print(f"  {row.file_name:<34} from {where}{there}")
    print(f"\nDownload the files above into {run_dir}, then run:\n"
          f"  python run_checks.py --run-date {args.run_date} --previous-run-date <date of the previous production run>")


if __name__ == "__main__":
    main()
