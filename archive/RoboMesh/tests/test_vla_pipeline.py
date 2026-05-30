"""End-to-end integration: VLA flywheel + closed-loop.

Builds Phase 0 → 2.5 → shards → closed loop in a tmp warehouse, then asserts
every artifact is present and well-formed.
"""
from __future__ import annotations

import tarfile

from robomesh.catalog.iceberg import list_tables, read_table_arrow
from robomesh.closed_loop import simulate_live_inference
from robomesh.closed_loop.inference_logger import closed_loop_summary
from robomesh.config import get_settings
from robomesh.generators import (
    generate_simulation_drops,
    generate_telemetry_drops,
    generate_teleop_drops,
)
from robomesh.ingestion import ingest_all_domains
from robomesh.training import write_training_shards
from robomesh.transformations import (
    build_gold_layer,
    build_silver_layer,
    build_vla_layer,
)


def _build_all() -> None:
    s = get_settings()
    generate_teleop_drops(s.raw_root, s.demo_episodes, s.seed)
    generate_telemetry_drops(s.raw_root, s.demo_episodes, s.seed)
    generate_simulation_drops(s.raw_root, s.demo_episodes, s.seed)
    ingest_all_domains()
    build_silver_layer()
    build_gold_layer()
    build_vla_layer()


def test_vla_phase_materializes_silver_and_gold_v2() -> None:
    _build_all()
    tables = list_tables()
    assert "silver.frame_embeddings" in tables
    assert "gold.vla_episodes_v2" in tables

    fe = read_table_arrow("silver.frame_embeddings")
    # One row per (episode, camera, frame). Each row holds only a URI string —
    # heavy tensors must live on disk per Pitfall #1.
    assert fe.num_rows > 0
    assert "embedding_uri" in fe.schema.names
    for uri in fe["embedding_uri"].to_pylist()[:5]:
        assert uri.startswith("tensors://")

    gv2 = read_table_arrow("gold.vla_episodes_v2")
    assert "mean_embedding_uri" in gv2.schema.names
    assert "embedding_dim" in gv2.schema.names


def test_webdataset_shards_are_prebatched_and_valid() -> None:
    _build_all()
    paths = write_training_shards(samples_per_shard=4)
    assert paths, "expected at least one shard"

    for p in paths:
        with tarfile.open(p, mode="r") as tar:
            names = tar.getnames()
        # Each sample contributes two members: features.npy + metadata.json.
        assert len(names) % 2 == 0
        suffixes = {n.split(".", 1)[1] for n in names if "." in n}
        assert "vla_features.npy" in suffixes
        assert "vla_metadata.json" in suffixes


def test_closed_loop_writes_back_to_bronze() -> None:
    _build_all()
    n = simulate_live_inference(n_steps_per_episode=2)
    assert n > 0
    summary = closed_loop_summary()
    assert summary["n_events"] == n
    assert 0.0 <= float(summary["mean_confidence"]) <= 1.0
    table = read_table_arrow("simulation.bronze_live_inference")
    assert {"policy_confidence", "model_version", "is_failure",
            "deployment_env"}.issubset(set(table.schema.names))
