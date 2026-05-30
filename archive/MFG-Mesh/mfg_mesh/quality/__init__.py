"""Phase 3: Data-quality / SLA enforcement primitives."""

from .contracts import ContractResult, enforce_silver_contract, build_gold_aggregates

__all__ = ["ContractResult", "enforce_silver_contract", "build_gold_aggregates"]
