from data_platform.ai_readiness import search


def _use_health(monkeypatch):
    monkeypatch.setenv("OMNI_MESH_PROFILE", "HEALTH_TECH")


def test_word_boundary_no_false_positive(monkeypatch):
    _use_health(monkeypatch)
    # 'EU' must NOT match inside 'revenue'.
    assert "region" not in search.extract_filters("what is our revenue trend this quarter")


def test_word_boundary_exact_match(monkeypatch):
    _use_health(monkeypatch)
    assert search.extract_filters("show me EU patients")["region"] == "EU"


def test_manufacturing_facility_extraction(monkeypatch):
    monkeypatch.setenv("OMNI_MESH_PROFILE", "MANUFACTURING")
    assert search.extract_filters("voltage faults at Texas_Giga_01")["facility_id"] == "Texas_Giga_01"


def test_robotics_failure_tag_extraction(monkeypatch):
    monkeypatch.setenv("OMNI_MESH_PROFILE", "ROBOTICS")
    filters = search.extract_filters("episodes with GRASP_FAIL on Optimus-Gen2")
    assert filters["failure_type_tag"] == "GRASP_FAIL"
    assert filters["robot_model_id"] == "Optimus-Gen2"
