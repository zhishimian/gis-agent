---
name: gis-verification
description: Check consequential GIS claims before downstream use, including formulas/precision, source identity, spatial assignments, shortest routes, interpolation evaluation, georeferencing and terrain/hydrology. Use when a wrong assumption could propagate or evidence conflicts. Reuse unchanged established evidence; visual styling belongs to gis-cartography and analytical execution to gis-spatial-analysis.
compatibility: Measurement scripts require GeoPandas/Shapely in a GIS Python interpreter; the precision example requires NumPy. Host tools are optional. Measurement helpers accept a JSON settings file and GIS_AGENT_RESULT_PATH.
---

# GIS verification

Choose the smallest evidence that can expose a consequential error. Check a new assumption before dependent ranking, selection or plotting; widen coverage when observations disagree. Reuse evidence when inputs and methods are unchanged.

- Metadata, fields, key duplicates and known foreign-key relations: reuse host inspection tools; exact examples and limitations are in [checks](references/checks.md).
- Cross-version key coverage or multiplicity: [identity_audit.py](scripts/identity_audit.py).
- Multipart/hole facts and selected planar distances: [geometry_facts.py](scripts/geometry_facts.py).
- Numerical precision and claim-specific counterexamples: [checks](references/checks.md#numerical-precision), with [precision_example.py](scripts/precision_example.py).
- Held-out prediction and terrain/registration evidence: [checks](references/checks.md#prediction-and-terrain-evidence), including a [split counterexample](scripts/validation_split.py).
- Business formulas, ambiguous matches and network assumptions still need semantic reasoning; a script cannot choose the intended policy.

Record the checked objects, observation, scope and PASS/FAIL/UNKNOWN briefly. A zero exit code proves execution, not the business claim; null measurements leave a gap. Apply task-defined precision at its specified stage, preserve execution errors, and keep sample claims within their coverage.
Stop when the requirement has sufficient evidence. Extra reports, evidence registration and cross-engine reimplementation are optional. For a necessary custom Processing check, reuse the [shared execution reference](../../integrations/qgis/execution.md).
