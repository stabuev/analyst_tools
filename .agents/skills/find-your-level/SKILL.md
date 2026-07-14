---
name: find-your-level
description: Diagnose Python, SQL, statistics, and workflow knowledge and recommend an entry phase and course route.
---

# Find Your Level

Use this skill when a learner asks where to start, which route to choose, or whether they
can skip part of the course.

## Source Of Truth

Read `curriculum.json`, `README.md`, and the README files for phases `00-07`. Do not invent
phase names, prerequisites, or durations.

## Procedure

Ask ten questions one at a time. Do not show all answers in advance and do not turn the
diagnostic into a tutorial while it is running.

Cover these dimensions:

1. Python data structures and functions.
2. Exceptions, files, and modules.
3. Git and reproducible environments.
4. Array shape, dtype, and vectorization.
5. DataFrame grain, missing values, and joins.
6. SQL aggregation, joins, and window functions.
7. Exploratory analysis and visualization choices.
8. Sampling, uncertainty, and experiments.
9. Data contracts, tests, and pipeline reliability.
10. The learner's target role and preferred deliverable.

Use short code or table fragments where practical. At least four questions must require an
explanation rather than selecting a term.

## Scoring

Score each technical answer:

- `0`: incorrect or unable to reason about the example;
- `1`: partially correct but misses an important failure mode;
- `2`: correct explanation and a safe practical decision.

The role question is not scored.

Map the weakest prerequisite, not the total score, to the entry point. The course does not
teach Python or SQL from zero; use `docs/pre-course-preparation.md` when the baseline is
not met:

- Weak Python functions or collections: preparation guide, then repeat Phase 00 diagnostic.
- Weak basic SQL (`SELECT`, `GROUP BY`, `JOIN`): preparation guide, then repeat Phase 00
  diagnostic.
- Python and SQL are sound but terminal or Git is weak: Phase 00.
- Workflow is sound but arrays are weak: Phase 02.
- Arrays are sound but DataFrame grain and joins are weak: Phase 03.
- pandas is sound but SQL is weak: Phase 04.
- Core skills are sound but tests and contracts are weak: Phase 07.
- Core is sound but sampling and uncertainty are weak: Phase 09.
- Core is complete: recommend a specialization using the routes in `README.md`.

Do not recommend skipping a phase when the learner cannot explain its central failure mode.

## Output

Return:

1. Recommended entry phase.
2. Recommended route.
3. Evidence from the diagnostic, including two strengths and up to three gaps.
4. Estimated hours from `curriculum.json`.
5. A compact ordered phase list.
6. When preparation is required, exact sections from `docs/pre-course-preparation.md` and
   the criterion for retrying the diagnostic.

State that the result is a placement recommendation, not a certification.
