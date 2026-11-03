"""Make two small, made-up model runs (scope 1-3), laid out the way the model owner keeps them, to run the output checks on.

The model owner downloads each run from the model platform's file store into one folder per run date, with the same four
sub-folders as the platform (see file_manifest.csv). We don't have those files, so this builds two such runs with a
fixed random seed:

    runs/2026-07-13   previous production run, fiscal years 2021-2024, companies M01-M20
    runs/2026-10-13   current production run,  fiscal years 2021-2025, companies M01-M20

Planted cases (current run unless said otherwise):

    Delivery vs delivery (same company-year, current vs previous run; flagged above +/-50% and 10,000 t)
      M01 2024 scope 1             reported last run, modelled this run, -67%           -> Potential loss in reported data
      M02 2024 scope 2             modelled last run, reported this run, +75%           -> New reported data point
      M03 2023 scope 1             reported both runs, the company restated it, +60%    -> Reported value restated
      M04 2024 scope 3 up and down modelled both runs, revenue 1.8x (2 rows)            -> Revenue change
      M05 2024 scope 3 upstream    modelled both runs, scope 3 intensity 1.8x           -> Scope 3 intensity change
      M06 2023 scope 3 downstream  modelled both runs, 1.7x with no change in the inputs -> Not covered yet
    Coverage (the model worked on the company-year, but there is no output value)
      M07 2025 scope 1             no reported value and no revenue                     -> No reported data and no revenue
      M08 2025 scope 3 upstream    revenue and intensity are both there                 -> Not covered yet
    Volatility year on year (within the current run; flagged above +/-100% and 10,000 t)
      M09 2025 scope 2             modelled in 2024, reported in 2025, +250%            -> Method changed between years
      M10 2025 scope 1             modelled both years, revenue 2.5x                    -> Revenue change

    Input checks (runs/2026-10-13/input_checks/): two rows of the input test's report
      M01 2024 scope 1  "Datapoints previous only", no Content Ops comment yet
      M03 2023 scope 1  "Variance current vs previous", with a Content Ops comment

Companies, IDs, values, file names and columns are invented. Replace them with the real files listed on the input
documentation page (file_manifest.csv says which file goes where).
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
SEED = 11

CURRENT_RUN, PREVIOUS_RUN = "2026-10-13", "2026-07-13"
YEARS = [2021, 2022, 2023, 2024, 2025]
MEASURES = ["scope1", "scope2", "scope3_upstream", "scope3_downstream"]
INTENSITY = {"scope1": (100, 600), "scope2": (50, 300), "scope3_upstream": (150, 800), "scope3_downstream": (200, 1200)}
NAMES = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hazel", "Ivy", "Juniper", "Larch", "Maple",
         "Oak", "Pine", "Rowan", "Spruce", "Teak", "Willow", "Yew", "Aspen"]
SECTORS = ["Oil & Gas", "Utilities", "Chemicals", "Banks", "Retail", "Technology", "Insurance", "Industrial Goods"]
FINANCIAL_SECTORS = {"Banks", "Insurance"}
# Scope 1-2 measures each company reports (scope 3 is always modelled here). Planted cases need these fixed.
FORCE_REPORTED = {("M01", "scope1"), ("M03", "scope1"), ("M04", "scope1"), ("M04", "scope2")}
FORCE_MODELLED = {("M02", "scope2"), ("M07", "scope1"), ("M09", "scope2"), ("M10", "scope1")}


def companies():
    rows = []
    for n in range(1, 21):
        sector = SECTORS[n % len(SECTORS)]
        rows.append({"key": f"M{n:02d}", "organization_perm_id": f"40000{n + 300:05d}",
                     "name": f"{NAMES[n - 1]} Model Test Co", "sector": sector,
                     "is_financial": sector in FINANCIAL_SECTORS})
    return pd.DataFrame(rows)


def base_run(rng, info):
    """Every company, year and measure as the model would produce it, before any of the planted changes."""
    rows = []
    for key in info["key"]:
        revenue = rng.uniform(500, 5000)
        intensity = {m: rng.uniform(*INTENSITY[m]) for m in MEASURES}
        reported = {m: rng.random() < 0.5 for m in MEASURES[:2]}
        reported.update({m: (key, m) in FORCE_REPORTED for m in MEASURES[:2] if (key, m) in FORCE_REPORTED | FORCE_MODELLED})
        for year in YEARS:
            for m in MEASURES:
                modelled = revenue * intensity[m]
                is_reported = reported.get(m, False)
                value = modelled * rng.uniform(0.9, 1.1) if is_reported else modelled
                rows.append({"key": key, "year": year, "measure": m, "revenue_musd": round(revenue, 1),
                             "intensity": round(intensity[m], 2), "method": "reported" if is_reported else "modelled",
                             "value": round(value)})
                intensity[m] *= 1 + rng.uniform(-0.03, 0.03)
            revenue *= 1 + rng.uniform(-0.05, 0.05)
    return pd.DataFrame(rows)


def plant(current, previous):
    def at(key, years, measures):
        return current["key"].eq(key) & current["year"].isin(years) & current["measure"].isin(measures)

    def previous_value(key, year, measure):
        return previous.loc[previous["key"].eq(key) & previous["year"].eq(year) & previous["measure"].eq(measure),
                            "value"].iloc[0]

    def remodel(rows):
        current.loc[rows, "value"] = (current.loc[rows, "revenue_musd"] * current.loc[rows, "intensity"]).round()

    rows = at("M01", [2024, 2025], ["scope1"])                       # reported value gone: modelled at a third
    current.loc[rows, "method"] = "modelled"
    current.loc[rows, "value"] = (current.loc[rows, "value"] * 0.33).round()
    current.loc[rows, "intensity"] = (current.loc[rows, "value"] / current.loc[rows, "revenue_musd"]).round(2)
    current.loc[at("M02", [2024], ["scope2"]), ["method", "value"]] = ["reported", round(previous_value("M02", 2024, "scope2") * 1.75)]
    current.loc[at("M03", [2023], ["scope1"]), "value"] = round(previous_value("M03", 2023, "scope1") * 1.6)
    rows = at("M04", [2024, 2025], ["scope3_upstream", "scope3_downstream"])
    current.loc[rows, "revenue_musd"] = (current.loc[rows, "revenue_musd"] * 1.8).round(1)
    remodel(rows)
    rows = at("M05", [2024, 2025], ["scope3_upstream"])
    current.loc[rows, "intensity"] = (current.loc[rows, "intensity"] * 1.8).round(2)
    remodel(rows)
    current.loc[at("M06", [2023], ["scope3_downstream"]), "value"] = round(previous_value("M06", 2023, "scope3_downstream") * 1.7)
    current.loc[at("M07", [2025], ["scope1"]), ["method", "revenue_musd", "value"]] = ["no_data", np.nan, np.nan]
    current.loc[at("M08", [2025], ["scope3_upstream"]), "value"] = np.nan
    value_2024 = current.loc[at("M09", [2024], ["scope2"]), "value"].iloc[0]
    current.loc[at("M09", [2025], ["scope2"]), ["method", "value"]] = ["reported", round(value_2024 * 3.5)]
    rows = at("M10", [2025], ["scope1"])
    current.loc[rows, "revenue_musd"] = (current.loc[rows, "revenue_musd"] * 2.5).round(1)
    remodel(rows)
    return current


def files(run, info):
    """One run's tables, named and placed as in file_manifest.csv."""
    run = run.merge(info[["key", "organization_perm_id"]], on="key").drop(columns="key")
    keys = ["organization_perm_id", "year", "measure"]
    steps = run[keys + ["method", "revenue_musd", "intensity"]].rename(columns={"method": "estimate_source"})
    return {
        "model_output/model_output_scope123.csv.gz": run.loc[run["value"].notna(), keys + ["value", "method"]],
        "input_data/lseg_reported_scope123.csv.gz":
            run.loc[run["method"].eq("reported"), keys + ["value"]].rename(columns={"value": "reported_value"}),
        "input_data/company_info.csv.gz": info[["organization_perm_id", "name", "sector", "is_financial"]],
        "intermediate_scope12/s12_model_steps.csv.gz": steps[steps["measure"].isin(MEASURES[:2])],
        "intermediate_scope3/s3_model_steps.csv.gz": steps[~steps["measure"].isin(MEASURES[:2])],
    }


def input_checks(info):
    ids = info.set_index("key")["organization_perm_id"]
    return pd.DataFrame([
        {"organization_perm_id": ids["M01"], "year": 2024, "measure": "co2_emiss_scope1",
         "reason_for_inclusion": "Datapoints previous only", "content_ops_comment": ""},
        {"organization_perm_id": ids["M03"], "year": 2023, "measure": "co2_emiss_scope1",
         "reason_for_inclusion": "Variance current vs previous",
         "content_ops_comment": "Restated by the company in its 2025 report"},
    ])


def main():
    rng = np.random.default_rng(SEED)
    info = companies()
    base = base_run(rng, info)
    previous = base[base["year"] <= 2024].reset_index(drop=True)
    current = plant(base.copy(), previous)
    for run_date, run in ((PREVIOUS_RUN, previous), (CURRENT_RUN, current)):
        for name, table in files(run, info).items():
            path = RUNS / run_date / name
            path.parent.mkdir(parents=True, exist_ok=True)
            table.to_csv(path, index=False)
            print(f"  {run_date}/{name:<46} {len(table):>4} rows")
    path = RUNS / CURRENT_RUN / "input_checks" / "qa_report_input_test.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    input_checks(info).to_csv(path, index=False)
    print(f"  {CURRENT_RUN}/input_checks/{path.name:<33} {2:>4} rows\n-> {RUNS}")


if __name__ == "__main__":
    main()
