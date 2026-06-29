from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "bad_control_selection_auditor.py"


def load_auditor():
    spec = importlib.util.spec_from_file_location("bad_control_selection_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.validate_specs(
        auditor.read_json(PHASE_ROOT / "02-causal-dags" / "outputs" / "causal_dag.json"),
        auditor.read_json(ROOT / "outputs" / "bad_control_policy.json"),
        auditor.read_json(ROOT / "outputs" / "candidate_control_actions.json"),
        auditor.read_json(PHASE_ROOT / "data" / "contract.json"),
    )
    candidates = {item["action_id"]: item for item in report["candidate_action_audits"]}
    payload = {
        "audit_valid": report["valid"],
        "blocking_checks": report["summary"]["blocking_checks"],
        "primary_action": report["summary"]["primary_recommendation"],
        "primary_open_unmeasured_paths": report["summary"][
            "primary_open_unmeasured_backdoor_paths"
        ],
        "allowed_actions": report["summary"]["allowed_candidate_actions"],
        "rejected_actions": report["summary"]["rejected_candidate_actions"],
        "mediator_blocks_directed_paths": candidates["mediator_adjusted_total_effect"][
            "blocked_directed_total_effect_paths"
        ],
        "collider_newly_opened_paths": candidates["support_chat_restricted_cohort"][
            "newly_opened_paths"
        ],
        "selection_newly_opened_paths": candidates["telemetry_complete_case_filter"][
            "newly_opened_paths"
        ],
        "bad_controls": report["summary"]["bad_control_variables"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
