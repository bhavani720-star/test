-- L02 Variance current vs previous (script lines 114-136), for one measure
-- Same company and year in both extracts; the change is above max_pct_change % or below min_pct_change %,
-- and bigger than min_abs_change. Empty values (the script turns 0 into empty) never compare.
SELECT c.record_key,
       c.organization_perm_id,
       c.year,
       c.{measure}                                                  AS current_value,
       p.{measure}                                                  AS previous_value,
       c.{measure} - p.{measure}                                    AS nominal_change,
       (c.{measure} - p.{measure}) * 100.0 / NULLIF(p.{measure}, 0) AS pct_change
FROM {batch} AS c
JOIN {batch} AS p
  ON  p.organization_perm_id = c.organization_perm_id
  AND p.year = c.year
  AND p.snapshot = 'previous'
WHERE c.snapshot = 'current'
  AND ABS(c.{measure} - p.{measure}) > {min_abs_change}
  AND (   (c.{measure} - p.{measure}) * 100.0 / NULLIF(p.{measure}, 0) > {max_pct_change}
       OR (c.{measure} - p.{measure}) * 100.0 / NULLIF(p.{measure}, 0) < {min_pct_change})
