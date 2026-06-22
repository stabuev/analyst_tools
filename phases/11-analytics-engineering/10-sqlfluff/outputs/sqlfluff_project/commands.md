# SQLFluff project commands

Run from this dbt project root:

```bash
python -m sqlfluff lint models tests snapshots --format json
python -m sqlfluff fix models tests snapshots --check
dbt test --select "test_type:data" --project-dir . --profiles-dir .
```

The committed `.sqlfluff` uses `dialect = duckdb` and `templater = dbt`. The dbt
templater is the accurate CI gate because it resolves `ref()`, `source()`,
`is_incremental()` and project macros, but it is slower and needs a safe local
`profiles.yml`.

For fast editor feedback on plain SQL snippets, use the raw templater explicitly:

```bash
python -m sqlfluff lint ../../bad_style_example.sql --dialect duckdb --templater raw --format json
```

Generated artifacts are excluded in `.sqlfluffignore`: `target/`, `logs/`,
`dbt_packages/` and local `*.duckdb` files. SQLFluff is a style and parseability gate;
it does not replace `dbt test`, source freshness or the business reconciliation tests
from previous lessons.

The lesson auditor runs SQLFluff on a temporary copy and writes a compact report:

```bash
python ../sqlfluff_quality_gate.py --project . --output ../sqlfluff_lint_report.json --run-sqlfluff
```
