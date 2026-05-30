"""Pre-shuffled, pre-batched WebDataset shard writer (Pitfall #2).

We never let downstream PyTorch workers shuffle a petabyte-scale Iceberg table
at training time. Instead, the **Gold-tier dbt model** is materialized once
into 100 MB-class tarball shards (``.tar``) that contain pre-shuffled, ready-
to-stream samples. The shard layout is fully compatible with the upstream
``webdataset`` library.

If ``webdataset`` is not installed we fall back to writing plain ``tar``
archives using Python's stdlib — the on-disk schema is byte-identical.
"""
from __future__ import annotations

import io
import json
import random
import tarfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.config import get_settings
from robomesh.cv.tensor_store import get_tensor_store
from robomesh.logging_setup import get_logger

log = get_logger(__name__)

# Target shard size: WebDataset recommends 50-250 MB; we pick 64 MB so the
# demo finishes quickly on a laptop.
DEFAULT_SHARD_BYTES = 64 * 1024 * 1024
DEFAULT_SAMPLES_PER_SHARD = 256


@dataclass(frozen=True)
class ShardingPlan:
    output_dir: Path
    samples_per_shard: int
    shuffle_seed: int


def _build_sample(row: dict, mean_embedding: np.ndarray) -> dict[str, bytes]:
    """One WebDataset sample (dict-of-bytes) per Gold-tier episode."""
    meta = {
        "episode_id": row["episode_id"],
        "robot_model_id": row.get("robot_model_id"),
        "factory_site": row.get("factory_site"),
        "failure_type_tag": row.get("failure_type_tag"),
        "success_flag": bool(row.get("success_flag")),
        "policy_family": row.get("policy_family"),
        "mean_policy_confidence": float(row.get("mean_policy_confidence") or 0.0),
        "peak_torque_nm": float(row.get("peak_torque_nm") or 0.0),
        "backbone": row.get("embedding_backbone"),
        "embedding_dim": int(row.get("embedding_dim") or 0),
    }

    npy_buf = io.BytesIO()
    np.save(npy_buf, mean_embedding.astype(np.float32), allow_pickle=False)

    return {
        "__key__": row["episode_id"],
        "vla_features.npy": npy_buf.getvalue(),
        "vla_metadata.json": json.dumps(meta).encode("utf-8"),
    }


def _write_tar_shard(samples: list[dict[str, bytes]], path: Path) -> int:
    """Write one ``.tar`` shard using stdlib ``tarfile`` (WebDataset-compatible)."""
    bytes_written = 0
    with tarfile.open(path, mode="w") as tar:
        for sample in samples:
            key = sample["__key__"]
            for fname, payload in sample.items():
                if fname == "__key__":
                    continue
                info = tarfile.TarInfo(name=f"{key}.{fname}")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
                bytes_written += len(payload)
    return bytes_written


def write_training_shards(
    *,
    samples_per_shard: int = DEFAULT_SAMPLES_PER_SHARD,
    shuffle_seed: int | None = None,
    output_subdir: str = "training_shards",
) -> list[Path]:
    """Materialize the Gold-tier into pre-shuffled WebDataset shards.

    Returns the list of shard paths actually written.
    """
    s = get_settings()
    seed = shuffle_seed if shuffle_seed is not None else s.seed

    gold = read_table_arrow("gold.vla_episodes_v2")
    rows = gold.to_pylist()
    if not rows:
        log.warning("training.shards.no_rows")
        return []

    rng = random.Random(seed)
    # Global random shuffle BEFORE shard assignment — this is what mitigates the
    # disk-read lag of sequentially-stored time-series during training.
    rng.shuffle(rows)
    log.info("training.shards.shuffle n=%d seed=%d", len(rows), seed)

    out_dir = (s.artifacts_root / output_subdir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    store = get_tensor_store()
    shard_paths: list[Path] = []
    buf: list[dict[str, bytes]] = []
    shard_idx = 0

    for row in rows:
        uri = row.get("mean_embedding_uri")
        if not uri:
            continue
        try:
            mean_emb = store.read(uri)
        except FileNotFoundError:
            log.warning("training.shards.missing_tensor episode=%s", row["episode_id"])
            continue
        buf.append(_build_sample(row, mean_emb))
        if len(buf) >= samples_per_shard:
            shard_path = out_dir / f"robomesh-vla-{shard_idx:05d}.tar"
            n_bytes = _write_tar_shard(buf, shard_path)
            log.info("training.shards.write path=%s n_samples=%d bytes=%d",
                     shard_path.name, len(buf), n_bytes)
            shard_paths.append(shard_path)
            shard_idx += 1
            buf.clear()

    if buf:
        shard_path = out_dir / f"robomesh-vla-{shard_idx:05d}.tar"
        n_bytes = _write_tar_shard(buf, shard_path)
        log.info("training.shards.write path=%s n_samples=%d bytes=%d",
                 shard_path.name, len(buf), n_bytes)
        shard_paths.append(shard_path)

    # Index file so Ray / WebDataset can enumerate shards quickly.
    index_path = out_dir / "shard_index.json"
    index_path.write_text(
        json.dumps(
            {
                "n_shards": len(shard_paths),
                "n_samples": len(rows),
                "samples_per_shard": samples_per_shard,
                "shuffle_seed": seed,
                "shards": [p.name for p in shard_paths],
            },
            indent=2,
        )
    )
    log.info("training.shards.done n_shards=%d index=%s",
             len(shard_paths), index_path.name)
    return shard_paths
