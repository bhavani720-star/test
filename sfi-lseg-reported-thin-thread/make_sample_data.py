"""Make a small, made-up pair of ADC extracts (LSEG reported scope 1-3 emissions) to run the input test on.

On StarMine the script reads this run's ADC extract (`lseg_reported`), the extract stored at `reference_datetime`
(`get_df_for_slice`) and three reference tables. We don't have that data, so this builds it with a fixed random
seed, with cases planted to show what each check does:

    previous extract  as of 2026-07-13, fiscal years 2021-2024, companies C01-C40
    current extract   as of 2026-10-26, fiscal years 2021-2025, companies C01-C38, C40, C41

    Datapoints previous only
      C39 2021-2024   company no longer in the current extract (delisted)        -> 4 rows
      C05 2023        every measure empty in the current extract                 -> 1 row
    Variance current vs previous (same company and year)
      C01 2023 scope 1       previous was 1/8 of current: +700%                  -> flagged
      C02 2022 scope 2       previous was 10x current: -90%                      -> flagged
      C30 2023 scope 1       +400%, but a change of under 100,000                -> not flagged (too small)
      60 company-years       downstream scope 3 restated (previous was 1/10)     -> 60 flagged: more than 50, so
                                                                                    prioritised to fiscal year 2024
                                                                                    and the top 30 by market cap
    YoY outliers (current extract, this year vs the year before)
      C03 2024 scope 1       7x 2023: +600% (and stays at that level in 2025)    -> flagged
      C04 2025 upstream s3   8% of 2024: -92%                                    -> flagged
      C31 2025 scope 2 loc.  +1,900%, but a change of under 100,000              -> not flagged (too small)
    Isolation Forest YoY
      the most unusual YoY change per measure and direction, kept only if it is also beyond the YoY % limits
      (expected: the three YoY cases above, including C31, which the YoY check leaves out)
    Not checked
      C41 2023-2025   new company, only in the current extract: the variance check never sees it

Companies, IDs and values are invented. The scope 3 category column names are made up too: the script finds them
by name ('up_scope3', 'down_scope3') and adds them up.

Writes to sample_data/:
    current_extract.csv  previous_extract.csv  marketcap.csv  icb_info.csv  univ_inactive.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "sample_data"
SEED = 7

CURRENT_AS_OF, PREVIOUS_AS_OF = "2026-10-26", "2026-07-13"
YEARS = [2021, 2022, 2023, 2024, 2025]
DIRECT = ["co2_emiss_scope1", "co2_emiss_scope2", "co2_emiss_scope2_marketbased", "co2_emiss_scope2_locbased"]
UP = [f"co2_emiss_up_scope3_cat{n}" for n in range(1, 9)]
DOWN = [f"co2_emiss_down_scope3_cat{n}" for n in range(9, 16)]
VERIFICATION = ["co2_emiss_scope1_verification", "co2_emiss_scope2_verification"]
MEASURES = DIRECT + UP + DOWN

TREES = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Ginkgo", "Hazel", "Ivy", "Juniper", "Larch", "Maple",
         "Oak", "Pine", "Rowan", "Spruce", "Teak", "Willow", "Yew", "Aspen", "Beech"]
KINDS = ["Energy", "Holdings", "Industries"]
INDUSTRIES = ["Oil & Gas", "Utilities", "Chemicals", "Industrial Goods", "Banks", "Retail", "Technology", "Insurance"]


def companies(rng):
    rows = []
    for n in range(1, 42):
        name = f"{TREES[(n - 1) % len(TREES)]} Test {KINDS[(n - 1) // len(TREES)]}"
        rows.append({
            "key": f"C{n:02d}",
            "organization_perm_id": f"50000{n + 200:05d}",
            "name": name,
            "ric": f"{name[:4].upper()}{n:02d}.X",
            "industry_name": INDUSTRIES[n % len(INDUSTRIES)],
            "company_market_cap": round(float(rng.lognormal(23, 1.1)), -5),
        })
    table = pd.DataFrame(rows)
    table.loc[table["key"].isin(["C30", "C31"]), "company_market_cap"] = [3.2e8, 4.1e8]  # two small companies
    return table


def history(rng, company):
    """Five fiscal years of every measure for one company: a starting level and small yearly drift."""
    start = {m: rng.uniform(200e3, 5e6) for m in ["co2_emiss_scope1", "co2_emiss_scope2"]}
    start["co2_emiss_scope2_marketbased"] = start["co2_emiss_scope2"] * rng.uniform(0.85, 0.95)
    start["co2_emiss_scope2_locbased"] = start["co2_emiss_scope2"] * rng.uniform(1.0, 1.1)
    start.update({m: rng.uniform(50e3, 1.5e6) for m in UP})
    start.update({m: rng.uniform(100e3, 2e6) for m in DOWN})
    if company == "C30":
        start = {m: v / 100 for m, v in start.items()}       # tiny emitter: every change stays under 100,000
    if company == "C31":
        start["co2_emiss_scope2_locbased"] = 5_000.0
    rows, level = [], dict(start)
    for year in YEARS:
        rows.append({"key": company, "fiscal_year": year, **{m: round(v) for m, v in level.items()}})
        level = {m: v * (1 + float(np.clip(rng.normal(0, 0.05), -0.12, 0.12))) for m, v in level.items()}
    return rows


def build():
    rng = np.random.default_rng(SEED)
    info = companies(rng)
    data = pd.DataFrame([row for key in info["key"] for row in history(rng, key)])
    for column in VERIFICATION:
        data[column] = rng.choice(["Verified", "Limited assurance", "Not verified"], len(data))

    def at(key, year=None):
        rows = data["key"] == key
        return rows if year is None else rows & (data["fiscal_year"] == year)

    # Real changes, reported the same way in both extracts.
    data.loc[at("C03") & (data["fiscal_year"] >= 2024), "co2_emiss_scope1"] *= 7          # YoY +600%
    data.loc[at("C04", 2025), UP] = (data.loc[at("C04", 2025), UP] * 0.08).round()        # YoY -92%
    data.loc[at("C31", 2025), "co2_emiss_scope2_locbased"] = 100_000                      # +1,900%, small change

    current = data[(data["key"] != "C39") & ~(data["key"].eq("C41") & (data["fiscal_year"] < 2023))].copy()
    current.loc[current["key"].eq("C05") & current["fiscal_year"].eq(2023), MEASURES] = np.nan
    current["as_of_date"] = CURRENT_AS_OF

    previous = data[(data["fiscal_year"] <= 2024) & (data["key"] != "C41")].copy()
    # Restatements: the previous extract had other values for the same company and year.
    previous.loc[at("C01", 2023), "co2_emiss_scope1"] = (previous.loc[at("C01", 2023), "co2_emiss_scope1"] / 8).round()
    previous.loc[at("C02", 2022), "co2_emiss_scope2"] *= 10
    previous.loc[at("C30", 2023), "co2_emiss_scope1"] = (previous.loc[at("C30", 2023), "co2_emiss_scope1"] / 5).round()
    pool = previous[~previous["key"].isin(["C01", "C02", "C03", "C04", "C05", "C30", "C31", "C39"])]
    wave = pool.sample(60, random_state=SEED).index
    previous.loc[wave, DOWN] = (previous.loc[wave, DOWN] / 10).round()
    previous["as_of_date"] = PREVIOUS_AS_OF

    ids = info.set_index("key")["organization_perm_id"]
    order = ["organization_perm_id", "fiscal_year"] + MEASURES + VERIFICATION + ["as_of_date"]
    extracts = {}
    for name, frame in (("current_extract", current), ("previous_extract", previous)):
        frame = frame.assign(organization_perm_id=frame["key"].map(ids))
        extracts[name] = frame.sort_values(["organization_perm_id", "fiscal_year"])[order]

    inactive = info[info["key"] == "C39"].rename(columns={"organization_perm_id": "organizationid"})
    return {
        **extracts,
        "marketcap": info[["organization_perm_id", "company_market_cap"]],
        "icb_info": info[["organization_perm_id", "name", "ric", "industry_name"]],
        "univ_inactive": inactive[["organizationid", "name", "ric"]].assign(status="Delisted"),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, table in build().items():
        table.to_csv(OUT / f"{name}.csv", index=False)
        print(f"  {name + '.csv':<22} {len(table):>4} rows")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
