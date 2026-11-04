"""Authoring: build the QC rule suite for the LSEG reported input test and save it as JSON.

This is the authoring step from the QC platform walkthrough: rules are created from expectation types, collected in
an expectation suite, and saved as one consolidated expectations JSON. The execution step (gx_lseg_reported.py) reads
that JSON and runs it. The limits come from the script's docstring, so the rules match the script that is in use.

    python author_suite.py
    python author_suite.py --set diff_in_abs_value=50000

--set     KEY=VALUE changes one setting before the rules are built, as in run_script.py
--output  where to write the suite; default expectations/sfi_lseg_reported_input_checks.json
"""
import argparse
import json
import os
from collections import Counter
from pathlib import Path

os.environ.setdefault("GX_ANALYTICS_ENABLED", "False")

import great_expectations as gx  # noqa: E402

from qc_rules.rules import CHECKS, build_suite  # noqa: E402
from run_script import MEASURES, SCRIPT, parse_value, read_metadata  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "expectations" / "sfi_lseg_reported_input_checks.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    md = read_metadata(SCRIPT.read_text(encoding="utf-8"))
    for setting in args.set:
        key, _, value = setting.partition("=")
        if key not in md:
            raise SystemExit(f"--set {setting}: '{key}' is not a metadata setting. Settings: {', '.join(md)}")
        md[key] = parse_value(value)

    suite = build_suite(gx.get_context(mode="ephemeral"), md, MEASURES)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    saved = suite.to_json_dict()
    saved.pop("id", None)
    args.output.write_text(json.dumps(saved, indent=2), encoding="utf-8")

    counts = Counter((e.meta["rule_id"], e.meta["engine"]) for e in suite.expectations)
    print(f"Suite {suite.name}: {len(suite.expectations)} rules, written to {args.output}")
    for rule_id, check in CHECKS.items():
        print(f"  {rule_id}  {check['check']:<29} {counts[(rule_id, 'gx_custom')]:>2} custom GX   "
              f"{counts[(rule_id, 'sql')]:>2} SQL   {check['expectation'].__name__}")
    print(f"  limits from the script: variance {md['change_diference_for_variance_test_down']}%.."
          f"{md['change_diference_for_variance_test_up']}%, YoY {md['per_of_change_in_time_threshold_min']}%.."
          f"{md['per_of_change_in_time_threshold_max']}%, change over {md['diff_in_abs_value']:,}")


if __name__ == "__main__":
    main()
