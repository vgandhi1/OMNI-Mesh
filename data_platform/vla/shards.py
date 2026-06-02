"""Pre-shuffled WebDataset shard writer for VLA training.

Reads ``gold.vla_episodes``, globally shuffles, and writes ``.tar`` shards each
holding ``<key>.npy`` (feature tensor) + ``<key>.json`` (metadata). Uses stdlib
``tarfile`` so it works without the optional ``webdataset`` package; the WebDataset
format is consumable by both ``webdataset`` and plain tar readers.
"""

from __future__ import annotations

import io
import json
import logging
import random
import tarfile

import numpy as np

from config.settings import get_settings
from data_platform import catalog

logger = logging.getLogger("omni_mesh.vla.shards")

try:
    import webdataset  # noqa: F401

    HAS_WEBDATASET = True
except Exception:
    HAS_WEBDATASET = False

DEFAULT_SAMPLES_PER_SHARD = 64


def _npy_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def _add_member(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))


def write_training_shards(
    *, samples_per_shard: int = DEFAULT_SAMPLES_PER_SHARD, shuffle_seed: int = 42
) -> list[str]:
    gold = catalog.read_table_arrow("gold.vla_episodes")
    rows = gold.to_pylist()
    if not rows:
        return []

    random.Random(shuffle_seed).shuffle(rows)  # global shuffle before sharding

    out_dir = get_settings().duckdb_path.parent / "training_shards"
    out_dir.mkdir(parents=True, exist_ok=True)

    shards: list[str] = []
    for shard_index, start in enumerate(range(0, len(rows), samples_per_shard)):
        chunk = rows[start : start + samples_per_shard]
        shard_path = out_dir / f"shard-{shard_index:05d}.tar"
        with tarfile.open(shard_path, "w") as tar:
            for row in chunk:
                key = row["episode_id"]
                vector = np.asarray(row["vla_feature_vector"], dtype=np.float32)
                _add_member(tar, f"{key}.npy", _npy_bytes(vector))
                meta = {
                    k: row[k]
                    for k in ("robot_model_id", "failure_type_tag", "success_flag", "backbone")
                }
                _add_member(tar, f"{key}.json", json.dumps(meta).encode("utf-8"))
        shards.append(str(shard_path))

    logger.info("wrote %d training shards to %s (webdataset=%s)", len(shards), out_dir, HAS_WEBDATASET)
    return shards
