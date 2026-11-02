"""Make a small, made-up history of EVIC input-test results to run the delta script on.

On StarMine the delta script gets `input_tests_evic_df`: every row the EVIC input test (init) flagged, saved
each Monday with an `as_of_date`. We don't have that data, so this builds three Mondays of it by hand, with
cases planted to show how the delta behaves:

    2026-10-12   5 flagged rows
    2026-10-19   5 flagged rows: 3 seen the week before, 2 new
    2026-10-26   8 flagged rows (the "current" week):
                   3 seen in earlier weeks       -> not in the delta
                     (one of them only on 10-12, not 10-19: the script checks every earlier week)
                   1 new year for a known company -> in the delta
                   2 new companies                -> in the delta
                   2 new rows for one company and year, different measures
                                                 -> both new, but only one reaches the report

Companies, IDs and values are invented. Which values `measure` can take is not known yet; here it is the
EVIC column that was flagged.

Writes to sample_data/:
    input_tests_evic_history.csv            one file, script column names, as_of_date column
    weekly/input_tests_evic_YYYY-MM-DD.csv  one file per Monday, no as_of_date column (date is in the name)
    input_tests_evic_history_tr_names.xlsx  same data with TR. field names as headers, like a client extract
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "sample_data"

COMPANIES = {
    # key: (organization_perm_id, org_id, ric, name, market cap in USD)
    "C01": ("5000000101", "ORG101", "ALDR.X", "Alder Test Holdings", 41_000e6),
    "C02": ("5000000102", "ORG102", "BRCH.X", "Birch Test Bank", 28_500e6),
    "C03": ("5000000103", "ORG103", "CEDR.X", "Cedar Test Insurance", 9_200e6),
    "C04": ("5000000104", "ORG104", "DOGW.X", "Dogwood Test Capital", 3_400e6),
    "C05": ("5000000105", "ORG105", "ELMT.X", "Elm Test Finance", 1_150e6),
    "C06": ("5000000106", "ORG106", "FIRT.X", "Fir Test Asset Mgmt", 17_800e6),
    "C07": ("5000000107", "ORG107", "GNKG.X", "Ginkgo Test Lending", 6_600e6),
    "C08": ("5000000108", "ORG108", "HAZL.X", "Hazel Test Bancorp", 52_300e6),
    "C09": ("5000000109", "ORG109", "IVYT.X", "Ivy Test Re", 2_900e6),
    "C10": ("5000000110", "ORG110", "JUNI.X", "Juniper Test Trust", 12_400e6),
}

EVIC = "tr_f_evexclceadjust"
MCAP = "market_capitalization"

# (company, year, measure, reason_for_inclusion, possible_reason_of_evic_change_yoy, comment)
WEEKS = {
    "2026-10-12": [
        ("C01", 2025, EVIC, "Variance current vs previous", "Change in market cap", "No reply yet"),
        ("C02", 2024, EVIC, "YoY Outliers", "Change in debt", "No reply yet"),
        ("C03", 2025, EVIC, "EVIC Gaps", "", "No reply yet"),
        ("C04", 2025, EVIC, "Top 20 with invalid", "", "No reply yet"),
        ("C05", 2024, EVIC, "Datapoints previous only", "", "delisted"),
    ],
    "2026-10-19": [
        ("C01", 2025, EVIC, "Variance current vs previous", "Change in market cap", "No reply yet"),
        ("C02", 2024, EVIC, "YoY Outliers", "Change in debt", "No reply yet"),
        ("C03", 2025, EVIC, "EVIC Gaps", "", "No reply yet"),
        ("C06", 2025, EVIC, "YoY Outliers", "No reason found in EVIC components", "No reply yet"),
        ("C07", 2024, EVIC, "Iso F YoY current", "Change in debt", "No reply yet"),
    ],
    "2026-10-26": [
        ("C01", 2025, EVIC, "Variance current vs previous", "Change in market cap", "No reply yet"),  # seen
        ("C06", 2025, EVIC, "YoY Outliers", "No reason found in EVIC components", "No reply yet"),  # seen
        ("C04", 2025, EVIC, "Top 20 with invalid", "", "No reply yet"),  # seen on 10-12 only
        ("C02", 2025, EVIC, "YoY Outliers", "Change in debt", "No reply yet"),  # new year
        ("C08", 2025, EVIC, "Variance current vs previous", "Change in market cap", "No reply yet"),  # new
        ("C09", 2024, EVIC, "EVIC Gaps", "", "No reply yet"),  # new
        ("C10", 2025, EVIC, "YoY Outliers", "Change in market cap", "No reply yet"),  # new
        ("C10", 2025, MCAP, "YoY Outliers", "Change in market cap", "No reply yet"),  # new, same company-year
    ],
}

SCRIPT_TO_TR = {
    "org_id": "TR.Orgidcode",
    "ric": "TR.PrimaryQuote",
    "name": "TR.OrganizationName",
    "year": "fiscal_year",
    "tr_f_evexclceadjust": "TR.F.EVexclCEAdjust",
    "market_cap_os": "TR.F.MktCapOutstShr",
    "debt_incl_equity_and_min_interest_total": "TR.F.DebtInclPrefEqMinIntrTot",
    "debt_total": "TR.F.DebtTot",
    "minority_interest_total": "TR.F.MinIntrTot",
    "preferred_shareholders_equity": "TR.F.PrefShHoldEq",
    "market_capitalization": "TR.F.MktCap",
}


def evic_parts(mcap, year, week_no):
    """Consistent made-up EVIC components, in USD. EVIC = market cap + debt incl. preferred equity and minorities."""
    drift = 1 + 0.01 * week_no + 0.03 * (year - 2024)
    market_cap_os = round(mcap * drift, -5)
    debt_total = round(mcap * 0.35 * drift, -5)
    minority = round(mcap * 0.02, -5)
    preferred = round(mcap * 0.01, -5)
    debt_incl = debt_total + minority + preferred
    return {
        "tr_f_evexclceadjust": market_cap_os + debt_incl,
        "market_cap_os": market_cap_os,
        "debt_incl_equity_and_min_interest_total": debt_incl,
        "debt_total": debt_total,
        "minority_interest_total": minority,
        "preferred_shareholders_equity": preferred,
        "market_capitalization": round(market_cap_os * 1.002, -5),
    }


def build():
    rows = []
    for week_no, (as_of, flagged) in enumerate(WEEKS.items()):
        for key, year, measure, reason, possible, comment in flagged:
            perm_id, org_id, ric, name, mcap = COMPANIES[key]
            rows.append({
                "organization_perm_id": perm_id, "org_id": org_id, "ric": ric, "name": name,
                "year": year, "measure": measure,
                **evic_parts(mcap, year, week_no),
                "possible_reason_of_evic_change_yoy": possible,
                "reason_for_inclusion": reason,
                "comment": comment,
                "as_of_date": as_of,
            })
    return pd.DataFrame(rows)


def main():
    history = build()
    (OUT / "weekly").mkdir(parents=True, exist_ok=True)
    history.to_csv(OUT / "input_tests_evic_history.csv", index=False)
    for as_of, week in history.groupby("as_of_date"):
        week.drop(columns="as_of_date").to_csv(OUT / "weekly" / f"input_tests_evic_{as_of}.csv", index=False)
    history.rename(columns=SCRIPT_TO_TR).to_excel(OUT / "input_tests_evic_history_tr_names.xlsx", index=False)
    print(f"{len(history)} rows over {history['as_of_date'].nunique()} Mondays -> {OUT}")
    print(history.groupby("as_of_date").size().to_string())


if __name__ == "__main__":
    main()
