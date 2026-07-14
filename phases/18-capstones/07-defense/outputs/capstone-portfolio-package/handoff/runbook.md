# Runbook

## Verify Package

```bash
uv run --locked python phases/18-capstones/07-defense/outputs/capstone_portfolio_builder.py --verify-package path/to/capstone-portfolio-package
```

A non-zero exit code means the package is stale, incomplete, restricted, 
or inconsistent with its reviewed provenance.

## Escalation

Return to the earliest affected stage, rebuild downstream packages, repeat 
independent verification and request re-review before another defense.
