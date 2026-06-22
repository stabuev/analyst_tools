# Reproducible source/ref commands

The lesson auditor creates a temporary DuckDB database and loads `../data/tiny/*.csv`
into schema `raw`. To run dbt manually, create a working `profiles.yml` from the example
and preload the raw schema first.

```bash
mkdir -p /tmp/source-ref-profiles
cp outputs/source_ref_project/profiles.yml.example /tmp/source-ref-profiles/profiles.yml
uv run --locked dbt parse --project-dir outputs/source_ref_project --profiles-dir /tmp/source-ref-profiles
uv run --locked dbt compile --project-dir outputs/source_ref_project --profiles-dir /tmp/source-ref-profiles
uv run --locked dbt source freshness --project-dir outputs/source_ref_project --profiles-dir /tmp/source-ref-profiles
```

Use `python outputs/source_ref_lineage_auditor.py --run-dbt` for the reproducible path.
