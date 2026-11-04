-- L03 YoY Outliers (script lines 146-169), for one measure
-- In the current extract, the change from the same company's row before (by year) is above max_pct_change % or
-- below min_pct_change %, and bigger than min_abs_change. LAG works in SQLite, Spark SQL and SQL Server.
WITH ordered AS (
    SELECT record_key,
           organization_perm_id,
           year,
           {measure}                                                                 AS value,
           LAG({measure}) OVER (PARTITION BY organization_perm_id ORDER BY year)     AS value_year_before
    FROM {batch}
    WHERE snapshot = 'current'
),
changes AS (
    SELECT record_key,
           organization_perm_id,
           year,
           value,
           value_year_before,
           value - value_year_before                                       AS nominal_change,
           (value - value_year_before) * 100.0 / NULLIF(value_year_before, 0) AS pct_change
    FROM ordered
)
SELECT record_key, organization_perm_id, year, value, value_year_before, nominal_change, pct_change
FROM changes
WHERE ABS(nominal_change) > {min_abs_change}
  AND (pct_change > {max_pct_change} OR pct_change < {min_pct_change})
  AND pct_change <> -100
