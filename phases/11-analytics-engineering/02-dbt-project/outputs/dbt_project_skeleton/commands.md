# Reproducible dbt commands

Run these commands from the lesson root after creating a temporary profiles directory.

```bash
mkdir -p /tmp/analytics-dbt-profiles
cp outputs/dbt_project_skeleton/profiles.yml.example /tmp/analytics-dbt-profiles/profiles.yml
uv run --locked dbt debug --project-dir outputs/dbt_project_skeleton --profiles-dir /tmp/analytics-dbt-profiles
uv run --locked dbt parse --project-dir outputs/dbt_project_skeleton --profiles-dir /tmp/analytics-dbt-profiles
uv run --locked dbt compile --project-dir outputs/dbt_project_skeleton --profiles-dir /tmp/analytics-dbt-profiles
```

The example profile uses local DuckDB. Set `DBT_DUCKDB_PATH` when you want the database
file outside the temporary profiles directory.
