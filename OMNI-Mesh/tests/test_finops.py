import json

from data_platform import finops


def test_run_audit_parses_run_results(tmp_path):
    results = tmp_path / "run_results.json"
    results.write_text(
        json.dumps(
            {
                "results": [
                    {"unique_id": "model.omni_mesh.gold_robot_health", "status": "success", "execution_time": 2.0},
                    {"unique_id": "model.omni_mesh.silver_robot_signals", "status": "success", "execution_time": 0.5},
                ]
            }
        )
    )
    rows = finops.run_audit(cost_per_second=0.1, results_path=results)
    assert len(rows) == 2
    # Sorted by execution time descending.
    assert rows[0].node.endswith("gold_robot_health")
    assert rows[0].estimated_cost_usd == 0.2
    assert finops.total_cost(rows) == 0.25


def test_run_audit_missing_file_returns_empty(tmp_path):
    assert finops.run_audit(results_path=tmp_path / "nope.json") == []
