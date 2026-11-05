# Introduction and Goals

## Mandatory rules
1. Only input: the application source code repository is the only evidence. Do not rely on external or assumed context.
2. Evidence first: for every finding, cite the file path and the narrowest locator (function, line range, SQL file or rule id).
3. Label every claim as Fact, Inference or Unknown. Never invent thresholds, columns or results.
4. Keep the original script (script/input_test_lseg_reported_task.py) and its Great Expectations version (qc_rules/, gx_lseg_reported.py, author_suite.py, expectations/) apart, and say which one each finding is about.
5. Describe what the code does. Do not fix or rewrite it.

## What to produce
1. Summary, 5 lines at most: what the input test checks, on which inputs, and who uses the result.
2. Inputs: one table with a row per input: name, the file or function that supplies it, the columns used.
3. Rules overview: one table with a row per rule the script applies (each check, the data preparation steps, the prioritisation and the report): rule id, name, where it is implemented (file and lines), the logic in one sentence, thresholds and where they come from, the output (report sheet).
4. Settings: one table with every setting in the script's metadata and its value.
5. Outputs: the report sheets and their columns.
6. Open questions: what the code does not answer, as a numbered list.
