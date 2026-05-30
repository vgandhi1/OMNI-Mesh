"""Phase 2.5 — VLA-ready feature store (Silver → Gold visual embeddings).

This stage runs the frozen CV backbone over the camera-frame manifest and
produces:

  • ``silver.frame_embeddings`` — one row per (episode, camera, frame) carrying
    only the **URI** to a .npy tensor (Pitfall #1: heavy tensors live on blob,
    Iceberg holds plain strings).
  • ``gold.vla_episodes_v2``    — joins the Phase-2 ``gold.vla_episodes`` to
    per-episode embedding summary statistics (mean / std / peak L2 / URIs).
"""
from __future__ import annotations

from dataclasses import asdict

import duckdb
import numpy as np
import pyarrow as pa

from robomesh.catalog.iceberg import read_table_arrow, write_managed_table
from robomesh.cv import extract_episode_embeddings, get_backbone_name
from robomesh.cv.tensor_store import get_tensor_store
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


def _build_frame_embedding_table() -> pa.Table:
    """Run CV extraction over every camera frame in the Silver layer."""
    cameras = read_table_arrow("teleop.bronze_camera_manifest")
    log.info("vla.frame_embeddings.start n_frames=%d", cameras.num_rows)
    rows = cameras.to_pylist()
    embeddings = extract_episode_embeddings(rows, batch_size=64)
    arrow = pa.Table.from_pylist([asdict(e) for e in embeddings])
    log.info("vla.frame_embeddings.done rows=%d backbone=%s",
             arrow.num_rows, get_backbone_name())
    return arrow


def build_frame_embeddings() -> str:
    arrow = _build_frame_embedding_table()
    return write_managed_table("silver", "frame_embeddings", arrow)


def _episode_embedding_stats(frame_table: pa.Table) -> pa.Table:
    """Aggregate per-episode statistics + write episode-level mean tensor URIs.

    Per-episode mean embedding is a compact way to power coarse similarity
    search at the Gold tier. Per-frame URIs remain available for VLA training.
    """
    store = get_tensor_store()
    pdf = frame_table.to_pandas()
    out_rows: list[dict] = []

    for ep_id, group in pdf.groupby("episode_id"):
        # Lazily load each per-frame .npy, average, then write back as one URI.
        vectors = []
        for uri in group["embedding_uri"].tolist():
            vectors.append(store.read(uri))
        stacked = np.stack(vectors)
        mean_vec = stacked.mean(axis=0).astype(np.float32)
        std_vec = stacked.std(axis=0).astype(np.float32)
        mean_uri = store.write(ep_id, "episode_mean", mean_vec)
        std_uri = store.write(ep_id, "episode_std", std_vec)
        out_rows.append(
            {
                "episode_id": ep_id,
                "n_frames_embedded": int(len(group)),
                "embedding_dim": int(stacked.shape[1]),
                "backbone": get_backbone_name(),
                "mean_embedding_uri": mean_uri,
                "std_embedding_uri": std_uri,
                "mean_embedding_l2": float(np.linalg.norm(mean_vec)),
                "max_frame_embedding_l2": float(
                    np.linalg.norm(stacked, axis=1).max()
                ),
            }
        )

    return pa.Table.from_pylist(out_rows)


def build_gold_vla_v2() -> str:
    """Join Phase-2 Gold table with CV embedding statistics."""
    frame_table = read_table_arrow("silver.frame_embeddings")
    gold_v1 = read_table_arrow("gold.vla_episodes")
    stats = _episode_embedding_stats(frame_table)
    log.info("vla.gold_v2.join n_episodes=%d", stats.num_rows)

    con = duckdb.connect()
    con.register("g", gold_v1)
    con.register("s", stats)
    out = con.execute(
        """
        SELECT
            g.*,
            s.n_frames_embedded,
            s.embedding_dim,
            s.backbone               AS embedding_backbone,
            s.mean_embedding_uri,
            s.std_embedding_uri,
            s.mean_embedding_l2,
            s.max_frame_embedding_l2
        FROM g
        LEFT JOIN s USING (episode_id)
        ORDER BY g.robot_model_id, g.failure_type_tag, g.episode_id
        """
    ).arrow()
    con.close()

    full = write_managed_table("gold", "vla_episodes_v2", out)
    log.info("vla.gold_v2.done table=%s rows=%d", full, out.num_rows)
    return full


def build_vla_layer() -> tuple[str, str]:
    """Run Phase 2.5 end-to-end: frame embeddings + Gold v2."""
    silver = build_frame_embeddings()
    gold = build_gold_vla_v2()
    return silver, gold
