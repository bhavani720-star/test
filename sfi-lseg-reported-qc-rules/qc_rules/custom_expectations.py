"""Custom Great Expectations rules for the LSEG reported (scope 1-3) input test.

The standard GX rules look at one row at a time. The four checks in input_test_lseg_reported_task.py compare a row
with another row: the same company-year in the previous extract, or the same company's year before. These custom
rules make that comparison inside GX, on one table that holds both extracts:

    record_key | organization_perm_id | year | snapshot ('current' or 'previous') | the six measures

Every rule takes column_list in this order: company, year, snapshot and, except L01, the measure it checks. A row is
unexpected when the script would have flagged it, so GX's unexpected rows are the script's flags.

    L01  ExpectCompanyYearToBeInCurrentExtract                 script lines 110-111
    L02  ExpectChangeVsPreviousExtractToBeWithinLimits         script lines 114-136
    L03  ExpectYearOnYearChangeToBeWithinLimits                script lines 146-169
    L04  ExpectYearOnYearChangeToNotBeIsolationForestOutlier   script lines 202-279

Importing this module registers the four rules with GX, so a suite saved as JSON can name them by type.
"""
from __future__ import annotations

from typing import ClassVar, Literal, Tuple

import numpy as np
import pandas as pd
from great_expectations.execution_engine import PandasExecutionEngine
from great_expectations.expectations.expectation import MulticolumnMapExpectation
from great_expectations.expectations.metrics.map_metric_provider import MulticolumnMapMetricProvider
from great_expectations.expectations.metrics.map_metric_provider.multicolumn_condition_partial import (
    multicolumn_condition_partial,
)
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split

CURRENT, PREVIOUS = "current", "previous"
DOMAIN_KEYS = ("batch_id", "table", "column_list", "row_condition", "condition_parser", "ignore_row_if")
IgnoreRowIf = Literal["all_values_are_missing", "any_value_is_missing", "never"]


def _roles(column_list, with_measure=True):
    names = list(column_list.columns)
    if len(names) != (4 if with_measure else 3):
        raise ValueError(f"column_list must be [company, year, snapshot{', measure' if with_measure else ''}], "
                         f"got {names}")
    return names


def _company_year(frame, company, year):
    return frame[company].astype(str) + "|" + frame[year].astype(str)


def _year_on_year(rows, company, year, measure):
    """Change from the same company's row before, with rows sorted by company and year (script lines 147-153).
    The script's Isolation Forest part (lines 206-210) does not sort; sorting here makes it independent of row order."""
    ordered = rows.sort_values([company, year], kind="mergesort")
    grouped = ordered.groupby(company)[measure]
    nominal = grouped.diff()
    return ordered, nominal, nominal / grouped.shift() * 100


def _outside(pct, low, high):
    return np.isfinite(pct) & ((pct > high) | (pct < low))


# Metrics: one row-level condition each. True means the row meets the rule. ----------------------------------------

class CompanyYearInCurrentExtract(MulticolumnMapMetricProvider):
    condition_metric_name = "lseg_reported.company_year_in_current_extract"
    condition_domain_keys = DOMAIN_KEYS

    @multicolumn_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column_list, **kwargs):
        company, year, snapshot = _roles(column_list, with_measure=False)
        key = _company_year(column_list, company, year)
        in_current = key.isin(set(key[column_list[snapshot] == CURRENT]))
        return (column_list[snapshot] != PREVIOUS) | in_current


class ChangeVsPreviousExtractWithinLimits(MulticolumnMapMetricProvider):
    condition_metric_name = "lseg_reported.change_vs_previous_extract_within_limits"
    condition_domain_keys = DOMAIN_KEYS
    condition_value_keys = ("min_pct_change", "max_pct_change", "min_abs_change")

    @multicolumn_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column_list, **kwargs):
        company, year, snapshot, measure = _roles(column_list)
        key = _company_year(column_list, company, year)
        is_previous = column_list[snapshot] == PREVIOUS
        previous = pd.Series(column_list.loc[is_previous, measure].to_numpy(), index=key[is_previous].to_numpy())
        previous_value = key.map(previous[~previous.index.duplicated()])
        nominal = column_list[measure] - previous_value
        flagged = ((column_list[snapshot] == CURRENT)
                   & _outside(nominal / previous_value * 100, kwargs["min_pct_change"], kwargs["max_pct_change"])
                   & (nominal.abs() > kwargs["min_abs_change"]))
        return ~flagged


class YearOnYearChangeWithinLimits(MulticolumnMapMetricProvider):
    condition_metric_name = "lseg_reported.year_on_year_change_within_limits"
    condition_domain_keys = DOMAIN_KEYS
    condition_value_keys = ("min_pct_change", "max_pct_change", "min_abs_change")

    @multicolumn_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column_list, **kwargs):
        company, year, snapshot, measure = _roles(column_list)
        ordered, nominal, pct = _year_on_year(column_list[column_list[snapshot] == CURRENT], company, year, measure)
        flagged = ((nominal.abs() > kwargs["min_abs_change"])
                   & _outside(pct, kwargs["min_pct_change"], kwargs["max_pct_change"])
                   & ordered[measure].notna() & (pct != -100))
        return ~flagged.reindex(column_list.index, fill_value=False)


class YearOnYearChangeNotIsolationForestOutlier(MulticolumnMapMetricProvider):
    condition_metric_name = "lseg_reported.year_on_year_change_not_isolation_forest_outlier"
    condition_domain_keys = DOMAIN_KEYS
    condition_value_keys = ("min_pct_change", "max_pct_change", "percentile", "test_size", "random_state")

    @multicolumn_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column_list, **kwargs):
        company, year, snapshot, measure = _roles(column_list)
        current = column_list[(column_list[snapshot] == CURRENT) & column_list[measure].notna()]
        ordered, nominal, pct = _year_on_year(current, company, year, measure)
        outlier = pd.Series(False, index=ordered.index)
        for side in (pct <= 0, pct > 0):   # script lines 224-225: falls and rises get separate models
            values = np.column_stack([pct[side], nominal[side]])
            if len(values) < 2:            # train_test_split needs two rows; the script would stop here
                continue
            train, _ = train_test_split(values, test_size=kwargs["test_size"], random_state=kwargs["random_state"])
            model = IsolationForest(random_state=kwargs["random_state"]).fit(train)
            scores = np.abs(model.decision_function(values))
            if len(np.unique(scores)) > 1:
                outlier[side] = scores >= np.percentile(scores, kwargs["percentile"])
        flagged = outlier & (nominal != 0) & _outside(pct, kwargs["min_pct_change"], kwargs["max_pct_change"])
        return ~flagged.reindex(column_list.index, fill_value=False)


# Expectations: the rules a suite holds. -----------------------------------------------------------------------------

class ExpectCompanyYearToBeInCurrentExtract(MulticolumnMapExpectation):
    """L01 Datapoints previous only. Every company-year in the previous extract is still in the current extract.

    column_list: [company, year, snapshot]. Unexpected rows: previous-extract rows with no current row."""

    ignore_row_if: IgnoreRowIf = "never"
    map_metric: ClassVar[str] = CompanyYearInCurrentExtract.condition_metric_name
    success_keys: ClassVar[Tuple[str, ...]] = ("mostly",)


class ExpectChangeVsPreviousExtractToBeWithinLimits(MulticolumnMapExpectation):
    """L02 Variance current vs previous. For the same company-year, the change from the previous extract stays within
    min_pct_change..max_pct_change %, unless it is no bigger than min_abs_change.

    column_list: [company, year, snapshot, measure]. Unexpected rows: current-extract rows."""

    min_pct_change: float
    max_pct_change: float
    min_abs_change: float
    ignore_row_if: IgnoreRowIf = "never"
    map_metric: ClassVar[str] = ChangeVsPreviousExtractWithinLimits.condition_metric_name
    success_keys: ClassVar[Tuple[str, ...]] = ("mostly", "min_pct_change", "max_pct_change", "min_abs_change")


class ExpectYearOnYearChangeToBeWithinLimits(MulticolumnMapExpectation):
    """L03 YoY Outliers. In the current extract, the change from the company's year before stays within
    min_pct_change..max_pct_change %, unless it is no bigger than min_abs_change.

    column_list: [company, year, snapshot, measure]. Unexpected rows: current-extract rows."""

    min_pct_change: float
    max_pct_change: float
    min_abs_change: float
    ignore_row_if: IgnoreRowIf = "never"
    map_metric: ClassVar[str] = YearOnYearChangeWithinLimits.condition_metric_name
    success_keys: ClassVar[Tuple[str, ...]] = ("mostly", "min_pct_change", "max_pct_change", "min_abs_change")


class ExpectYearOnYearChangeToNotBeIsolationForestOutlier(MulticolumnMapExpectation):
    """L04 Iso F YoY current. Year-on-year changes in the current extract are scored with an Isolation Forest, falls and
    rises separately. A change is unexpected when its anomaly score reaches the group's `percentile`, it is not zero,
    and it is also outside min_pct_change..max_pct_change % (script line 278).

    column_list: [company, year, snapshot, measure]. Unexpected rows: current-extract rows."""

    min_pct_change: float
    max_pct_change: float
    percentile: float = 99.9
    test_size: float = 0.2
    random_state: int = 42
    ignore_row_if: IgnoreRowIf = "never"
    map_metric: ClassVar[str] = YearOnYearChangeNotIsolationForestOutlier.condition_metric_name
    success_keys: ClassVar[Tuple[str, ...]] = ("mostly", "min_pct_change", "max_pct_change", "percentile",
                                               "test_size", "random_state")
