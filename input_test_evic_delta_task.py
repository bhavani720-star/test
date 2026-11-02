import os
import sys
import pandas as pd
import numpy as np
import boto3
import openpyxl as xl
from datetime import date, datetime, timedelta
from utils_lib import utils as utils


import warnings
warnings.filterwarnings("ignore")

df_current = input_tests_evic_df[input_tests_evic_df["as_of_date"] == current_date]
df_all_previous = input_tests_evic_df[input_tests_evic_df["as_of_date"] != current_date]


sheets_dict = {}
extra_datapoints = df_current.merge(df_all_previous, on=['organization_perm_id', "year", "measure"], how="outer", suffixes=("_current", "_previous"),
indicator=True)
extra_datapoints = extra_datapoints[extra_datapoints["_merge"] == "left_only"]
extra_datapoints = extra_datapoints.drop(columns=["_merge", "tr_f_evexclceadjust_previous", "market_cap_os_previous",
"debt_incl_equity_and_min_interest_total_previous", "debt_total_previous", "minority_interest_total_previous", "preferred_shareholders_equity_previous",
"market_capitalization_previous", "possible_reason_of_evic_change_yoy_previous", \
                                                "comment_previous",  "as_of_date_previous", "as_of_date_current", "ric_previous", "org_id_previous",
"name_previous", "reason_for_inclusion_previous"], axis=1)
report = extra_datapoints.rename(columns = {"ric_current": "ric", "org_id_current": "org_id", "name_current": "name", "comment_current": "comment",
"tr_f_evexclceadjust_current": "tr_f_evexclceadjust", \
                                                    "minority_interest_total_current": "minority_interest_total", "preferred_shareholders_equity_current":
"preferred_shareholders_equity", "market_cap_os_current": "market_cap_os", "debt_incl_equity_and_min_interest_total_current":
"debt_incl_equity_and_min_interest_total", "debt_total_current": "debt_total", \
                                                        "market_capitalization_current": "market_capitalization",
"possible_reason_of_evic_change_yoy_current": "possible_reason_of_evic_change_yoy", "reason_for_inclusion_current": "reason_for_inclusion"})
report = report.drop_duplicates(subset=['organization_perm_id', "org_id", "ric", "name", 'year'])

summary_report = report.copy()
summary_report["correction_required"] = ""
sheets_dict["summary_report"] = summary_report

slice_date = current_date.strftime('%y%m%d')
utils.write_to_excel(sheets_dict, f"qa_report_input_test_evic_delta", slice_date)
