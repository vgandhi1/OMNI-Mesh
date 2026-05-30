"""VLA flywheel tests (exercise the numpy/tarfile fallbacks when torchvision/
webdataset are absent)."""

import tarfile

import pytest

from config.profiles import MeshProfile
from data_platform import catalog, generators
from data_platform.vla import closed_loop, feature_extractor, shards


def _seed_robotics_bronze(n: int = 16) -> None:
    catalog.ensure_namespaces()
    batch = generators.make_bronze_batch(MeshProfile.ROBOTICS, n=n)
    catalog.write_data_product(
        catalog.NAMESPACE_BRONZE, "robot_signals", batch, expected_schema=batch.schema
    )


def test_build_vla_gold(monkeypatch):
    feature_extractor.reset_backbone_cache()
    _seed_robotics_bronze()
    count = feature_extractor.build_vla_gold(limit=16)
    assert count == 16

    gold = catalog.read_table_arrow("gold.vla_episodes")
    assert gold.num_rows == 16
    assert "vla_feature_vector" in gold.column_names
    row = gold.to_pylist()[0]
    assert row["feature_dim"] == len(row["vla_feature_vector"]) > 0
    assert row["backbone"] in {"torchvision/resnet18", "numpy/sha256-prng"}


def test_vla_rejects_non_robotics(monkeypatch):
    monkeypatch.setenv("OMNI_MESH_PROFILE", "HEALTH_TECH")
    from config import settings

    settings.get_settings.cache_clear()
    with pytest.raises(ValueError):
        feature_extractor.build_vla_gold()


def test_write_training_shards():
    _seed_robotics_bronze()
    feature_extractor.build_vla_gold(limit=16)
    written = shards.write_training_shards(samples_per_shard=8)
    assert len(written) == 2  # 16 samples / 8 per shard
    with tarfile.open(written[0]) as tar:
        names = tar.getnames()
    assert any(n.endswith(".npy") for n in names)
    assert any(n.endswith(".json") for n in names)


def test_closed_loop_logs_to_bronze():
    _seed_robotics_bronze()
    feature_extractor.build_vla_gold(limit=16)
    scored = closed_loop.run_closed_loop()
    assert scored == 16
    live = catalog.read_table_arrow("bronze.live_inference")
    assert live.num_rows == 16
    assert "policy_confidence" in live.column_names
