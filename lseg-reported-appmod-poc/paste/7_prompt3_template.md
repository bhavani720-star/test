# GX Migration Feasibility

## Mandatory rules
1. Only input: the application source code repository is the only evidence. Do not rely on external or assumed context.
2. Evidence first: for every finding, cite the file path and the narrowest locator (function, line range, SQL file or rule id).
3. Label every claim as Fact, Inference or Unknown, and keep proposals apart from facts.
4. Feasible: the rule's logic maps cleanly onto a built-in Great Expectations expectation or a simple custom expectation, with no unresolved blocker. Partially feasible: part of the logic needs a step outside Great Expectations (pandas, a model) or a decision. Not feasible: it cannot be written as a Great Expectations rule.
5. Describe what the code does. Do not fix or rewrite it.

## What to produce
1. Feasibility matrix: one table with a row per rule: rule id, script file and lines, target Great Expectations state (expectation type or SQL rule), Feasible, Partially feasible or Not feasible, reason, blocker.
2. Steps that stay outside Great Expectations (data preparation, the Isolation Forest model, prioritisation, the Excel report) and why.
3. What the QC platform needs to run the rules: packages, the custom expectation classes to import, the data source type (pandas, SQL or Spark).
4. Blockers and open questions for model management, as a numbered list.
5. Recommended next steps, labelled as proposals.
