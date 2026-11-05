# Rule by Rule GX Mapping

## Mandatory rules
1. Only input: the application source code repository is the only evidence. Do not rely on external or assumed context.
2. Evidence first: for every finding, cite the file path and the narrowest locator (function, line range, SQL file or rule id).
3. Label every claim as Fact, Inference or Unknown. Never invent thresholds, columns or results.
4. A rule counts as migrated only if the repository holds its Great Expectations version: a built-in expectation, a custom expectation in qc_rules/custom_expectations.py, or a SQL rule in qc_rules/sql/. Otherwise mark it Not migrated.
5. Describe what the code does. Do not fix or rewrite it.

## What to produce
1. Rule mapping: one table with a row per rule of the original script and these columns, left to right:
   Rule id | Script rule: name, file and lines, logic, thresholds | Great Expectations version: expectation type or SQL file, parameters | Built-in, custom or SQL | Migration: Fully, Partially or Not | Reason
2. Input contract: the rules that exist only in the Great Expectations version, and what the script does today when that input problem happens.
3. Differences: every place where the Great Expectations version behaves differently from the script (order of steps, sorting, a check that flags nothing), with file and lines for both.
4. Evidence of equal results: what the repository shows, for example the sample data and the comparison step in gx_lseg_reported.py. Do not claim a result the code does not show.
