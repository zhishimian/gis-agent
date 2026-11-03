---
name: gis-verification
description: Test consequential GIS claims with small counterexamples, allocation balances and coverage checks. Use when formulas, assignments, routing assumptions or approximations affect downstream results. Reuse established evidence; styling belongs to gis-cartography.
compatibility: Measurement scripts require GeoPandas/Shapely in a GIS Python interpreter; the precision example requires NumPy. Host tools are optional. Measurement helpers accept a JSON settings file and GIS_AGENT_RESULT_PATH.
---

# GIS verification

Choose the smallest evidence that can expose a consequential error. Check a new assumption before dependent ranking, selection or plotting; widen coverage when observations disagree. Reuse evidence when inputs and methods are unchanged.

- Metadata, fields, key duplicates and known foreign-key relations: reuse host inspection tools; exact examples and limitations are in [checks](references/checks.md).
- Cross-version key coverage or multiplicity: [identity_audit.py](scripts/identity_audit.py).
- Population/quantity coverage and residuals: [allocation_balance.py](scripts/allocation_balance.py), with the [balance pattern](references/checks.md#allocation-and-delivery).
- Network access, direction and unreachable evidence: [shared network reference](../gis-spatial-analysis/references/network-access.md).
- Multipart/hole facts and selected planar distances: [geometry_facts.py](scripts/geometry_facts.py).
- Numerical precision and claim-specific counterexamples: [checks](references/checks.md#numerical-precision), with [precision_example.py](scripts/precision_example.py).
- Held-out prediction and terrain/registration evidence: [checks](references/checks.md#prediction-and-terrain-evidence), including a [split counterexample](scripts/validation_split.py).
- Business formulas, ambiguous matches and network assumptions still need semantic reasoning; a script cannot choose the intended policy.
- Necessary evidence remains unavailable: [evidence gaps and handoff](references/checks.md#evidence-gaps-and-handoff) distinguishes recoverable errors, missing input and consequential business choices.

Record the checked objects, observation, scope and PASS/FAIL/UNKNOWN briefly. A zero exit code proves execution, not the business claim; null measurements leave a gap. Apply task-defined precision at its specified stage, preserve execution errors, and keep sample claims within their coverage.
Stop when the requirement has sufficient evidence. Extra reports, evidence registration and cross-engine reimplementation are optional. For a necessary custom Processing check, reuse the [shared execution reference](../../integrations/qgis/execution.md).
Carry already-discovered unmatched quantities, unreachable objects and consequential assumptions into delivery notes. Reuse existing statistics; no extra report or rerun is required.
