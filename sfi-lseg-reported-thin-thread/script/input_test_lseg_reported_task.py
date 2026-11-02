import os
import sys
import pandas as pd
import numpy as np
import boto3
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from datetime import date, datetime, timedelta
from utils_lib import utils as utils



import warnings
warnings.filterwarnings("ignore")

ISO_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

"""====================================================================================================
Metadata information for the current test:

 start: 2024
  end: 2026
  reference_datetime: "2026-07-13T06:00:00"
  change_diference_for_variance_test_up: 200
  change_diference_for_variance_test_down: -66
  per_of_change_in_time_threshold_max: 500
  per_of_change_in_time_threshold_min: -83
  diff_in_abs_value: 100000
  max_number_of_outliers: 50
  number_of_companies: 30

"""

print("""Get constant variables defined in dataset""")
start = metadata["start"]
reference_datetime = datetime.fromisoformat(metadata["reference_datetime"])
print(f"Reference datetime: {reference_datetime}")
change_diference_for_variance_test_up = metadata["change_diference_for_variance_test_up"]
change_diference_for_variance_test_down = metadata["change_diference_for_variance_test_down"]
per_of_change_in_time_threshold_max = metadata["per_of_change_in_time_threshold_max"]
per_of_change_in_time_threshold_min = metadata["per_of_change_in_time_threshold_min"]
diff_in_abs_value = metadata["diff_in_abs_value"]
max_number_of_outliers = metadata["max_number_of_outliers"]
number_of_companies = metadata["number_of_companies"]

previous_extract = get_df_for_slice('sfi_model_management/ingest_data_from_adc/extract_lseg_reported_scope123_adc', reference_datetime)

print("""Get input data used in the current test""")
input_dfs = get_all_inputs()

lseg_reported_latest = input_dfs['lseg_reported']
df_org_market_cap = input_dfs['marketcap']
df_icb_info = input_dfs['icb_info']
univ_inactive_status = input_dfs['univ_inactive']

df_icb_info = df_icb_info.merge(univ_inactive_status, left_on=["organization_perm_id"], right_on=["organizationid"],  how="left", suffixes=("_icb", "inactive_univ"))
df_icb_info = df_icb_info.rename(columns = {"name_icb": "name", "ric_icb": "ric"})

# ########################################################################### Read and process lseg reported ###########################################################################

df_previous_lseg = previous_extract.drop(['as_of_date'], axis=1)
df_current_lseg = lseg_reported_latest.drop(['as_of_date'], axis=1)

########################################################################### Process input data and keep only mandatory columns ###########################################################################

exclude_columns = [col for col in df_current_lseg.columns.to_list() if 'verification' in col]

df_current_lseg = df_current_lseg.drop(columns=exclude_columns)
df_previous_lseg = df_previous_lseg.drop(columns=exclude_columns)

upstream_comco_scope3_cols = [col for col in df_current_lseg.columns.to_list() if 'up_scope3' in col]
downstream_comco_scope3_cols = [col for col in df_current_lseg.columns.to_list() if 'down_scope3' in col]

df_previous_lseg = utils.prepaire_year_column_input_test(df_previous_lseg)
df_current_lseg = utils.prepaire_year_column_input_test(df_current_lseg)


df_current_lseg['total_upstream_scope3'] = df_current_lseg[upstream_comco_scope3_cols].sum(axis = 1)
df_current_lseg['total_downstream_scope3'] = df_current_lseg[downstream_comco_scope3_cols].sum(axis = 1)

df_previous_lseg['total_upstream_scope3'] = df_previous_lseg[upstream_comco_scope3_cols].sum(axis = 1)
df_previous_lseg['total_downstream_scope3'] = df_previous_lseg[downstream_comco_scope3_cols].sum(axis = 1)


columns_of_interest = ["co2_emiss_scope1", "co2_emiss_scope2", "co2_emiss_scope2_marketbased", "co2_emiss_scope2_locbased",  \
                        "total_upstream_scope3", "total_downstream_scope3"]

columns_to_join_on = [
        "organization_perm_id", \
        "year"
        ]

cols = columns_to_join_on + columns_of_interest

df_previous_lseg = df_previous_lseg[cols]
df_current_lseg = df_current_lseg[cols]

for col in columns_of_interest:
    df_current_lseg[col] = df_current_lseg[col].replace(0, np.nan)
for col in columns_of_interest:
    df_previous_lseg[col] = df_previous_lseg[col].replace(0, np.nan)

df_current_lseg = df_current_lseg.dropna(subset = columns_of_interest, how="all")
df_previous_lseg = df_previous_lseg.dropna(subset = columns_of_interest, how="all")

########################################################################### Comco comparation files to be used ###########################################################################

compare = df_current_lseg.merge(df_previous_lseg, on = columns_to_join_on, how="outer", suffixes=("_current", "_previous"), indicator=True)
datapoints_only_in_previous = compare[compare["_merge"] == "right_only"]
datapoints_in_both_deliveries_raw = compare[compare["_merge"] == "both"]

########################################################################### Identify variances same year ###########################################################################

print("Check differences in reported values grater than specific percentage same year")
print("Create empty dict to store dataframes")
dataframe_dict = {}
datapoints_in_both_deliveries_var = datapoints_in_both_deliveries_raw.copy()
for col in columns_of_interest:
    datapoints_in_both_deliveries_var["Nominal diff"] = datapoints_in_both_deliveries_var[f"{col}_current"] - datapoints_in_both_deliveries_var[f"{col}_previous"]
    datapoints_in_both_deliveries_var["Perc diff"] = datapoints_in_both_deliveries_var.apply(lambda row: utils.get_change(row[f"{col}_current"], row[f"{col}_previous"]), \
                                                                                                axis=1)
    datapoints_in_both_deliveries_var[f"Abs Perc diff"] = abs(datapoints_in_both_deliveries_var[f"Perc diff"])
    datapoints_in_both_deliveries_outliers = datapoints_in_both_deliveries_var[((datapoints_in_both_deliveries_var["Perc diff"] > change_diference_for_variance_test_up) | (datapoints_in_both_deliveries_var['Perc diff'] < change_diference_for_variance_test_down)) & \
                                                                            (abs(datapoints_in_both_deliveries_var["Nominal diff"]) > diff_in_abs_value)]
    datapoints_in_both_deliveries_outliers = datapoints_in_both_deliveries_outliers.sort_values(by = "Abs Perc diff", ascending = False)
    datapoints_in_both_deliveries_outliers = datapoints_in_both_deliveries_outliers.drop(columns = ['_merge'])
    datapoints_in_both_deliveries_outliers = datapoints_in_both_deliveries_outliers[datapoints_in_both_deliveries_outliers["Perc diff"]!= np.inf]
    if len(datapoints_in_both_deliveries_outliers) > max_number_of_outliers:
        print(f" Variance check  - Number of max outliers have been reached for col: {col}")
        datapoints_in_both_deliveries_outliers = datapoints_in_both_deliveries_outliers[datapoints_in_both_deliveries_outliers["year"] >= start]
        datapoints_in_both_deliveries_outliers = utils.prioritize_list_of_suspicious_datapoints(datapoints_in_both_deliveries_outliers, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)
        datapoints_in_both_deliveries_outliers = datapoints_in_both_deliveries_outliers.drop(columns = ['company_market_cap'])
    datapoints_in_both_deliveries_outliers["Outlier_for_data_field"] = col
    dataframe_dict[col] = datapoints_in_both_deliveries_outliers

df_var = pd.DataFrame()

for value in dataframe_dict.values():
    df_var = pd.concat([df_var, value])


# ########################################################################### Identify outliers on current extraction for each ISIN ###########################################################################

print("Identify outliers in values reported  group by an ISIN on the current version")
comco_current = df_current_lseg.sort_values(by = ['organization_perm_id', 'year'])
outlier_dict = {}
for col in columns_of_interest:
    df_col = comco_current.copy()
    df_col['Nominal_diff'] = df_col.groupby('organization_perm_id')[col].diff()
    try:
        df_col['Percentage_diff'] = df_col.groupby('organization_perm_id')[col].pct_change()*100
    except ZeroDivisionError:
        df_col['Percentage_diff'] = np.inf
    df_yoy_outliers =  df_col[
        (df_col['Nominal_diff'].abs() > diff_in_abs_value) &
        (( df_col['Percentage_diff'] < per_of_change_in_time_threshold_min) | (df_col['Percentage_diff'] > per_of_change_in_time_threshold_max ))
    ]
    df_yoy_outliers = df_yoy_outliers[df_yoy_outliers["Percentage_diff"]!= np.inf]
    df_yoy_outliers = df_yoy_outliers.loc[(df_yoy_outliers[col].notna())]
    df_yoy_outliers = df_yoy_outliers.loc[(df_yoy_outliers["Percentage_diff"] != -100) ]
    if len(df_yoy_outliers) > max_number_of_outliers:
        df_yoy_outliers = df_yoy_outliers[df_yoy_outliers["year"] >= start]
        print(f" YoY check  - Number of max outliers havs been reached for col: {col}")
        df_yoy_outliers = utils.prioritize_list_of_suspicious_datapoints(df_yoy_outliers, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)
        df_yoy_outliers = df_yoy_outliers.drop(columns = ['company_market_cap'])
    df_yoy_outliers["Outlier_for_data_field"] = col
    outlier_dict[col] = df_yoy_outliers

df_yoy = pd.DataFrame()

for value in outlier_dict.values():
    df_yoy = pd.concat([df_yoy, value])

########################################################################### Compute new columns for Isolation Forest Outlier Detection on current vs previous runs ###########################################################################
df_merged_comco_both = datapoints_in_both_deliveries_raw.copy()
previous_cols = [col for col in df_merged_comco_both.columns if col.endswith('_previous')]
current_cols = [col for col in df_merged_comco_both.columns if col.endswith('_current')]

prev_values = df_merged_comco_both[previous_cols].to_numpy()
current_values = df_merged_comco_both[current_cols].to_numpy()

nominal_diff = current_values - prev_values

diff_results = np.zeros_like(prev_values, dtype = float)

diff_results[(prev_values == 0) & (current_values !=0 )] = float('inf')
diff_results[(prev_values == 0) & (current_values == 0)] = 0

mask = prev_values != 0
diff_results[mask] = (current_values[mask] - prev_values[mask]) / prev_values[mask]

diff_df = pd.DataFrame(diff_results, columns = [f"Perc_diff_in_col_{col.replace('_previous', '')}" for col in previous_cols])

diff_nominal_df = pd.DataFrame(nominal_diff, columns = [f"Nominal_diff_in_col_{col.replace('_previous', '')}" for col in previous_cols])
df_merged_comco_both = pd.concat([df_merged_comco_both, diff_df, diff_nominal_df], axis = 1)


# ########################################################################### Compute new columns for Isolation Forest Outlier Detection on current YoY ###########################################################################

df_red_comco_current = df_current_lseg.sort_values(by = ['organization_perm_id', 'year'])

numeric_cols_iso_f = df_red_comco_current.columns.difference(['organization_perm_id', 'year'])

for col in numeric_cols_iso_f:
    df_col = df_current_lseg[['organization_perm_id', 'year', col]]
    df_col = df_col.dropna()
    df_col[col + '_nominal_diff'] = df_col.groupby('organization_perm_id')[col].diff()
    df_col[col + '_percentage_diff'] = df_col.groupby('organization_perm_id')[col].pct_change()*100

    df_red_comco_current = pd.merge(df_red_comco_current, df_col, how = 'left', on = ['organization_perm_id', 'year'])
    df_red_comco_current = df_red_comco_current.rename(columns={col + "_x": col})

print(df_red_comco_current.columns)
print("**********************************")
########################################################################### Identify outliers on current extraction for each ISIN Isolation Forest ###########################################################################

outlier_dict_iso_f_YoY = {}

for col in columns_of_interest:
    df_col = df_red_comco_current[['organization_perm_id', 'year', col, col+'_percentage_diff', col + '_nominal_diff']]

    df_col_neg = df_col[df_col[col+'_percentage_diff'] <= 0]
    df_col_pos = df_col[df_col[col+'_percentage_diff'] > 0]

    if len(df_col_neg) > 0:
        X_neg = df_col_neg[[col+'_percentage_diff', col + '_nominal_diff']]
        X_train_neg, X_test_neg = train_test_split(X_neg, test_size=0.2, random_state=42)

        iso_forest = IsolationForest(random_state=42)
        iso_forest.fit(X_train_neg)

        y_pred_neg = iso_forest.decision_function(X_neg)

        df_YoY_neg_iso_f = df_col_neg.copy()
        df_YoY_neg_iso_f['Anomaly Score'] = abs(y_pred_neg)

        if len(df_YoY_neg_iso_f['Anomaly Score'].unique()) > 1:
            thr_YoY_outliers_iso_f = np.percentile(df_YoY_neg_iso_f['Anomaly Score'], 99.9)
            df_YoY_neg_iso_f['Outlier Indicator'] = df_YoY_neg_iso_f['Anomaly Score'].apply(lambda x: -1 if x >= thr_YoY_outliers_iso_f else 1)
        else:
            df_YoY_neg_iso_f['Outlier Indicator'] = 1

        df_YoY_neg_iso_f.drop('Anomaly Score', axis = 1)
        df_YoY_neg_iso_f = df_YoY_neg_iso_f[(df_YoY_neg_iso_f['Outlier Indicator'] == -1) & (df_YoY_neg_iso_f[col + '_nominal_diff'] != 0 )].drop('Outlier Indicator', axis = 1)
    else:
        df_YoY_neg_iso_f = pd.DataFrame(columns=['organization_perm_id', 'year', 'reason_for_inclusion'])

    if len(df_col_pos) > 0:
        X_pos = df_col_pos[[col+'_percentage_diff', col + '_nominal_diff']]
        X_train_pos, X_test_pos = train_test_split(X_pos, test_size=0.2, random_state=42)

        iso_forest = IsolationForest(random_state=42)
        iso_forest.fit(X_train_pos)

        y_pred_pos = iso_forest.decision_function(X_pos)

        df_YoY_pos_iso_f = df_col_pos.copy()
        df_YoY_pos_iso_f['Anomaly Score'] = abs(y_pred_pos)

        if len(df_YoY_pos_iso_f['Anomaly Score'].unique()) > 1:
            thr_YoY_outliers_iso_f = np.percentile(df_YoY_pos_iso_f['Anomaly Score'], 99.9)
            df_YoY_pos_iso_f['Outlier Indicator'] = df_YoY_pos_iso_f['Anomaly Score'].apply(lambda x: -1 if x >= thr_YoY_outliers_iso_f else 1)
        else:
            df_YoY_pos_iso_f['Outlier Indicator'] = 1

        df_YoY_pos_iso_f.drop('Anomaly Score', axis = 1)
        df_YoY_pos_iso_f = df_YoY_pos_iso_f[(df_YoY_pos_iso_f['Outlier Indicator'] == -1) & (df_YoY_pos_iso_f[col + '_nominal_diff'] != 0 )].drop('Outlier Indicator', axis = 1)
    else:
        df_YoY_pos_iso_f = pd.DataFrame(columns=['organization_perm_id', 'year', 'reason_for_inclusion'])
    df_YoY_iso_f = pd.concat([df_YoY_pos_iso_f, df_YoY_neg_iso_f])
    if len(df_YoY_iso_f) > max_number_of_outliers:
        df_YoY_iso_f = df_YoY_iso_f[df_YoY_iso_f["year"] >= start]
        df_YoY_iso_f = utils.prioritize_list_of_suspicious_datapoints(df_YoY_iso_f, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)
        df_YoY_iso_f = df_YoY_iso_f.drop(columns = ['company_market_cap'])
    df_YoY_iso_f["Outlier_for_data_field"] = col
    df_YoY_iso_f = df_YoY_iso_f[(df_YoY_iso_f[col + "_percentage_diff"] > per_of_change_in_time_threshold_max) | (df_YoY_iso_f[col + "_percentage_diff"] < per_of_change_in_time_threshold_min)]
    outlier_dict_iso_f_YoY[col] = df_YoY_iso_f


df_yoy_iso = pd.DataFrame()

for value in outlier_dict_iso_f_YoY.values():
    df_yoy_iso = pd.concat([df_yoy_iso, value])

########################################################################### Extra prioritization in case max number  outliers has been reached ###########################################################################
if len(datapoints_only_in_previous) > max_number_of_outliers:
    datapoints_only_in_previous = datapoints_only_in_previous[datapoints_only_in_previous["year"] >= start]
    print(f"Datapoints only in previous  - Number of max outliers has been reached")
    datapoints_only_in_previous = utils.prioritize_list_of_suspicious_datapoints(datapoints_only_in_previous, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)

if len(df_var) > max_number_of_outliers:
    df_var = df_var[df_var["year"] >= start]
    print(f" Variance check  - Number of max outliers has been reached")
    df_var = utils.prioritize_list_of_suspicious_datapoints(df_var, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)

if len(df_yoy) > max_number_of_outliers:
    df_yoy = df_yoy[df_yoy["year"] >= start]
    print(f" YoY - Number of max outliers has been reached")
    df_yoy = utils.prioritize_list_of_suspicious_datapoints(df_yoy, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)


if len(df_yoy_iso) > max_number_of_outliers:
    df_yoy_iso = df_yoy_iso[df_yoy_iso["year"] >= start]
    print(f" YoY ISO - Number of max outliers has been reached")
    df_yoy_iso = utils.prioritize_list_of_suspicious_datapoints(df_yoy_iso, df_org_market_cap, cols_to_sort_by=["company_market_cap"], nr_of_companies = number_of_companies)

########################################################################### Create report for results ###########################################################################

datapoints_only_in_previous = datapoints_only_in_previous.merge(df_icb_info, on=["organization_perm_id"], how="left")

datapoints_only_in_previous_report = datapoints_only_in_previous.copy()
datapoints_only_in_previous_report["reason_for_inclusion"] = "Datapoints previous only"
datapoints_only_in_previous_report["measure"] = "N/A"
datapoints_only_in_previous_report["current_value"] = "N/A"
datapoints_only_in_previous_report["previous_value"] = "N/A"
datapoints_only_in_previous_report['comment_from_content_team'] = datapoints_only_in_previous["status"]


df_var_report = df_var.copy()
df_var_report = df_var_report.merge(df_icb_info, on=["organization_perm_id"], how="left")
df_var_report['reason_for_inclusion'] = 'Variance current vs previous'
df_var_report["measure"] = df_var_report["Outlier_for_data_field"]
df_var_report['values'] = df_var_report.apply(utils.include_value_in_summary_report_for_variance_check_lseg_reported, axis = 1)
df_var_report['current_value'] = df_var_report['values'].apply(lambda row: row["current"])
df_var_report['previous_value'] = df_var_report['values'].apply(lambda row: row["previous"])
df_var_report['comment_from_content_team'] = 'No reply yet'


df_yoy_report = df_yoy.copy()
df_yoy_report = df_yoy_report.merge(df_icb_info, on=["organization_perm_id"], how="left")
df_yoy_report['reason_for_inclusion'] = 'YoY Outliers'
df_yoy_report["measure"] = df_yoy_report["Outlier_for_data_field"]
df_yoy_report['current_value'] = df_yoy_report.apply(utils.include_value_in_summary_report_lseg_reported, axis = 1)
df_yoy_report["previous_value"] = "N/A"
df_yoy_report['comment_from_content_team'] = 'No reply yet'


df_yoy_iso_report = df_yoy_iso.copy()
df_yoy_iso_report = df_yoy_iso_report.merge(df_icb_info, on=["organization_perm_id"], how="left")
df_yoy_iso_report['reason_for_inclusion'] = 'Iso F YoY current'
df_yoy_iso_report["measure"] = df_yoy_iso_report["Outlier_for_data_field"]
df_yoy_iso_report["current_value"] = df_yoy_iso_report.apply(utils.include_value_in_summary_report_lseg_reported, axis = 1)
df_yoy_iso_report["previous_value"] = "N/A"
df_yoy_iso_report['comment_from_content_team'] = 'No reply yet'


report_columns = ['organization_perm_id', 'name', 'industry_name', 'year', 'measure', 'current_value', 'previous_value', 'reason_for_inclusion', 'comment_from_content_team']
report = pd.DataFrame()
report = pd.concat([report,datapoints_only_in_previous_report[["organization_perm_id", 'name', 'industry_name', 'year', 'measure', 'current_value', 'previous_value', "reason_for_inclusion", "comment_from_content_team"]]])
report = pd.concat([report,df_var_report[["organization_perm_id", 'name', 'industry_name', 'year', 'measure', 'current_value', 'previous_value', "reason_for_inclusion", "comment_from_content_team"]]])
report = pd.concat([report,df_yoy_report[["organization_perm_id", 'name', 'industry_name', 'year', 'measure', 'current_value', 'previous_value', "reason_for_inclusion", "comment_from_content_team"]]])
report = pd.concat([report, df_yoy_iso_report[["organization_perm_id", 'name', 'industry_name', 'year', 'measure', 'current_value', 'previous_value', "reason_for_inclusion", "comment_from_content_team"]]])

report = report[report_columns].drop_duplicates()
report['comment_from_content_team'] = np.where(report['comment_from_content_team'].isna(), 'No reply yet', report['comment_from_content_team'])
report["year"] = report["year"].fillna(0).astype(int)
report = report[report["year"] != 0]
########################################################################### Change column order ###########################################################################
datapoints_only_in_previous = datapoints_only_in_previous[["organization_perm_id", "year", "co2_emiss_scope1_current", "co2_emiss_scope1_previous", \
                    "co2_emiss_scope2_current", "co2_emiss_scope2_previous", "co2_emiss_scope2_marketbased_current", "co2_emiss_scope2_marketbased_previous", \
                    "co2_emiss_scope2_locbased_current", "co2_emiss_scope2_locbased_previous",
                    "total_upstream_scope3_current", "total_upstream_scope3_previous", \
                    "total_downstream_scope3_current", "total_downstream_scope3_previous", "status"]]

df_var = df_var[["organization_perm_id", "year", "co2_emiss_scope1_current", "co2_emiss_scope1_previous", \
                    "co2_emiss_scope2_current", "co2_emiss_scope2_previous",  "co2_emiss_scope2_marketbased_current", "co2_emiss_scope2_marketbased_previous", \
                    "co2_emiss_scope2_locbased_current", "co2_emiss_scope2_locbased_previous", \
                    "total_upstream_scope3_current", "total_upstream_scope3_previous", \
                    "total_downstream_scope3_current", "total_downstream_scope3_previous", \
                    "Nominal diff", "Perc diff", "Abs Perc diff", "Outlier_for_data_field"]]


df_yoy_iso = df_yoy_iso[[
        "organization_perm_id", "year", \
        "co2_emiss_scope1",  \
        "co2_emiss_scope2", \
        "co2_emiss_scope2_marketbased", \
        "co2_emiss_scope2_locbased", \
        "total_downstream_scope3", \
        "total_upstream_scope3", \
        "co2_emiss_scope1_percentage_diff", "co2_emiss_scope1_nominal_diff", \
        "co2_emiss_scope2_percentage_diff", "co2_emiss_scope2_nominal_diff", \
        "co2_emiss_scope2_marketbased_percentage_diff", "co2_emiss_scope2_marketbased_nominal_diff", \
        "co2_emiss_scope2_locbased_percentage_diff", "co2_emiss_scope2_locbased_nominal_diff", \
        "total_upstream_scope3_percentage_diff", "total_upstream_scope3_nominal_diff", \
        "total_downstream_scope3_percentage_diff", "total_downstream_scope3_nominal_diff", \
        "Anomaly Score", "Outlier_for_data_field"]]
########################################################################### Write all results in excel files ###########################################################################

summary_report = report.copy()
summary_report["correction_required"] = ""

excel_mapping = {
    "summary_report": summary_report,
    "datapoints_only_previous": datapoints_only_in_previous,
    "variance current vs previous" : df_var,
    "YoY Outliers": df_yoy,
    "ISO F YoY current": df_yoy_iso
}

slice_date = current_date.strftime('%y%m%d')
utils.write_to_excel(excel_mapping, "qa_report_input_test_lseg_scope123_init", slice_date)
