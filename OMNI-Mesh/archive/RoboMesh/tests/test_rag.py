"""Tests for the deterministic intent parser (no model download required)."""
from __future__ import annotations

from robomesh.semantic.rag_agent import _parse_intent, _to_chroma_where


def test_parse_failure_tag() -> None:
    out = _parse_intent("Find grasp failures on Figure-01")
    assert out["failure_type_tag"] == "GRASP_FAIL"
    assert out["robot_model_id"] == "Figure-01"


def test_parse_gripper_and_success() -> None:
    out = _parse_intent("show me successful 3-finger demonstrations")
    assert out["success_flag"] is True
    assert out["gripper_type"] == "3-finger"


def test_chroma_where_single_filter() -> None:
    where = _to_chroma_where({"failure_type_tag": "OVER_TORQUE"})
    assert where == {"failure_type_tag": "OVER_TORQUE"}


def test_chroma_where_multi_filter_uses_and() -> None:
    where = _to_chroma_where(
        {"failure_type_tag": "OVER_TORQUE", "robot_model_id": "Atlas-Next"}
    )
    assert where is not None
    assert "$and" in where
    assert {"failure_type_tag": "OVER_TORQUE"} in where["$and"]
