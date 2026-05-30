"""dbt-style data contracts enforced at the Silver / Gold table boundary.

The contracts here are intentionally Python-native so the same validation can
run in *any* environment (dbt isn't required to enforce them). In production
the same definitions would be expressed in ``schema.yml`` and enforced by
``dbt build --select state:modified+ --warn-error``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pyarrow as pa

from robomesh.catalog.iceberg import read_table_arrow
from robomesh.logging_setup import get_logger

log = get_logger(__name__)


class ContractViolation(RuntimeError):
    """Raised when a table's actual schema diverges from its contract."""


@dataclass(frozen=True)
class ColumnContract:
    name: str
    arrow_type: str         # serialized pyarrow type name e.g. "int64"
    nullable: bool = True
    not_null_in_silver: bool = False


@dataclass(frozen=True)
class TableContract:
    full_name: str
    columns: tuple[ColumnContract, ...]
    primary_key: tuple[str, ...] = ()


# ---------- Contract definitions ------------------------------------------- #

SILVER_CONTRACT = TableContract(
    full_name="silver.synchronized_trajectories",
    primary_key=("episode_id", "camera_id", "frame_index"),
    columns=(
        ColumnContract("episode_id",       "string",  nullable=False),
        ColumnContract("robot_model_id",   "string",  nullable=False),
        ColumnContract("camera_id",        "string",  nullable=False),
        ColumnContract("frame_index",      "int64",   nullable=False),
        ColumnContract("camera_ts_us",     "int64",   nullable=False),
        ColumnContract("video_uri",        "string",  nullable=False),
        ColumnContract("max_joint_torque_nm", "double", nullable=True),
        ColumnContract("failure_type_tag", "string",  nullable=True),
        ColumnContract("success_flag",     "bool",    nullable=True),
    ),
)

GOLD_CONTRACT = TableContract(
    full_name="gold.vla_episodes",
    primary_key=("episode_id",),
    columns=(
        ColumnContract("episode_id",              "string", nullable=False),
        ColumnContract("robot_model_id",          "string", nullable=False),
        ColumnContract("failure_type_tag",        "string", nullable=True),
        ColumnContract("success_flag",            "bool",   nullable=True),
        ColumnContract("peak_torque_nm",          "double", nullable=True),
        ColumnContract("mean_policy_confidence",  "double", nullable=True),
        ColumnContract("vla_feature_vector",      "list<item: double>", nullable=True),
    ),
)

ALL_CONTRACTS: tuple[TableContract, ...] = (SILVER_CONTRACT, GOLD_CONTRACT)


def _arrow_type_name(t: pa.DataType) -> str:
    return str(t)


def _check(contract: TableContract) -> list[str]:
    """Return a list of violations (empty == passing)."""
    table = read_table_arrow(contract.full_name)
    schema = table.schema
    violations: list[str] = []

    actual_cols = {f.name: f for f in schema}
    for col in contract.columns:
        if col.name not in actual_cols:
            violations.append(f"missing column `{col.name}`")
            continue
        actual_type = _arrow_type_name(actual_cols[col.name].type)
        if actual_type != col.arrow_type:
            violations.append(
                f"column `{col.name}` type mismatch: "
                f"expected `{col.arrow_type}` got `{actual_type}`"
            )
        if not col.nullable:
            # Check no nulls actually present.
            null_count = table.column(col.name).null_count
            if null_count > 0:
                violations.append(
                    f"column `{col.name}` declared NOT NULL but has "
                    f"{null_count} null rows"
                )

    if contract.primary_key:
        # Cheap PK uniqueness audit using Arrow.
        keys = table.select(list(contract.primary_key)).to_pandas()
        dup = int(keys.duplicated().sum())
        if dup > 0:
            violations.append(
                f"primary key {contract.primary_key} has {dup} duplicate rows"
            )

    return violations


def enforce_all_contracts(
    contracts: Iterable[TableContract] = ALL_CONTRACTS,
    *,
    raise_on_violation: bool = True,
) -> dict[str, list[str]]:
    """Validate every supplied contract; optionally raise on the first failure."""
    report: dict[str, list[str]] = {}
    for c in contracts:
        violations = _check(c)
        report[c.full_name] = violations
        if violations:
            # Logging rule: log only counts, not the data itself.
            log.warning(
                "contract.fail table=%s n_violations=%d",
                c.full_name, len(violations),
            )
        else:
            log.info("contract.pass table=%s", c.full_name)

    if raise_on_violation and any(v for v in report.values()):
        bad = {k: v for k, v in report.items() if v}
        raise ContractViolation(f"Data contracts failed: {bad}")
    return report
