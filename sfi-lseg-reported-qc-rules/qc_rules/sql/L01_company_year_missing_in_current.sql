-- L01 Datapoints previous only (script lines 110-111)
-- A company-year in the previous extract that is not in the current extract.
-- Returns the unexpected rows. {batch} is the table that holds both extracts, one row per company, year and snapshot.
SELECT p.record_key,
       p.organization_perm_id,
       p.year
FROM {batch} AS p
WHERE p.snapshot = 'previous'
  AND NOT EXISTS (
        SELECT 1
        FROM {batch} AS c
        WHERE c.snapshot = 'current'
          AND c.organization_perm_id = p.organization_perm_id
          AND c.year = p.year
      )
