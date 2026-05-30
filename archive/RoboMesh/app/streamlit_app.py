"""RoboMesh — Agentic RAG explorer (Streamlit).

Run with::

    streamlit run app/streamlit_app.py

The app gives ML researchers a natural-language interface over the Gold-tier
Iceberg table plus a Chroma-backed vector index of episode summaries.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from robomesh.catalog.iceberg import list_tables, read_table_arrow
from robomesh.config import get_settings
from robomesh.semantic.rag_agent import RoboMeshAgent
from robomesh.semantic.vector_store import index_size

st.set_page_config(
    page_title="RoboMesh — Agentic Data Mining",
    page_icon="🤖",
    layout="wide",
)


# ---------- Header -------------------------------------------------------- #

st.markdown(
    """
    <div style="display:flex;align-items:center;gap:0.75rem">
      <h1 style="margin:0">🤖 RoboMesh</h1>
      <span style="color:#888">— Federated Robotics Telemetry & Demonstration Data Mesh</span>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------- Sidebar — pipeline status ------------------------------------- #

with st.sidebar:
    st.header("Lakehouse status")
    s = get_settings()
    tables = list_tables()
    st.metric("Iceberg tables", len(tables))
    st.metric("Episodes in vector index", index_size())
    st.metric("Active role", s.active_role)
    with st.expander("Configured paths", expanded=False):
        st.code(
            f"warehouse  = {s.warehouse_root}\n"
            f"catalog    = {s.catalog_uri}\n"
            f"vector_idx = {s.chroma_path}\n"
            f"embedding  = {s.embedding_model}",
            language="text",
        )
    with st.expander("Registered tables", expanded=False):
        for t in tables:
            st.write(" • " + t)


# ---------- Tabs ---------------------------------------------------------- #

tab_ask, tab_gold, tab_vla, tab_loop, tab_pipeline = st.tabs(
    ["💬 Agentic RAG", "🏆 Gold lakehouse", "🧠 VLA flywheel",
     "🔁 Closed loop", "🛠️ Pipeline"]
)


# ---------- Tab 1: Agentic RAG ------------------------------------------- #

with tab_ask:
    st.subheader("Ask the lakehouse")
    examples = [
        "Find me grasp failures on Figure-01 with a 3-finger gripper",
        "Show me successful recoveries from joint over-torque",
        "Which episodes had the highest sim-to-real divergence?",
        "Vision occlusion failures at the Stuttgart factory",
    ]
    cols = st.columns(len(examples))
    chosen = None
    for i, ex in enumerate(examples):
        if cols[i].button(ex, key=f"ex_{i}"):
            chosen = ex
    query = st.text_input(
        "Natural-language question",
        value=chosen or "Find me grasp failures on Figure-01",
        help="The agent extracts filters from your question and runs them "
        "against both the vector index and the Gold Iceberg table.",
    )
    k = st.slider("Max hits", min_value=1, max_value=20, value=8)

    if st.button("Search", type="primary"):
        with st.spinner("Querying vector index + Iceberg..."):
            answer = RoboMeshAgent(k=k).answer(query)

        st.success(answer.natural_language)

        if answer.filters:
            st.markdown("**Parsed filters**")
            st.json(answer.filters)

        if answer.iceberg_rows:
            df = pd.DataFrame(answer.iceberg_rows)
            st.markdown("**Iceberg rows (`gold.vla_episodes`)**")
            st.dataframe(df, use_container_width=True, hide_index=True)

        if answer.matches:
            st.markdown("**Vector-store hits**")
            for m in answer.matches:
                sim = m.get("similarity")
                sim_str = f"{sim:.3f}" if isinstance(sim, float) else "—"
                with st.expander(f"{m['episode_id']} (sim={sim_str})", expanded=False):
                    st.write(m["text"])
                    st.json(m["metadata"])


# ---------- Tab 2: Gold lakehouse ---------------------------------------- #

with tab_gold:
    st.subheader("Gold layer — `gold.vla_episodes`")
    try:
        gold = read_table_arrow("gold.vla_episodes").to_pandas()
    except Exception as exc:  # noqa: BLE001
        st.warning(
            "Gold table not built yet. Run `make demo` from a terminal to "
            f"materialize the pipeline. ({exc.__class__.__name__})"
        )
        gold = pd.DataFrame()

    if not gold.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Episodes", len(gold))
        c2.metric("Successes", int(gold["success_flag"].sum()))
        c3.metric("Failures", int((~gold["success_flag"].astype(bool)).sum()))
        c4.metric("Robot models", gold["robot_model_id"].nunique())

        st.markdown("**Failure taxonomy distribution**")
        st.bar_chart(gold["failure_type_tag"].value_counts())

        st.markdown("**Peak torque vs. mean policy confidence (per episode)**")
        chart_df = gold[
            ["peak_torque_nm", "mean_policy_confidence",
             "failure_type_tag", "robot_model_id"]
        ].dropna()
        st.scatter_chart(
            chart_df,
            x="peak_torque_nm",
            y="mean_policy_confidence",
            color="failure_type_tag",
        )

        with st.expander("Full Gold table", expanded=False):
            st.dataframe(gold, use_container_width=True, hide_index=True)


# ---------- Tab 3: VLA flywheel ------------------------------------------ #

with tab_vla:
    st.subheader("VLA feature flywheel")
    st.caption(
        "Phase 2.5 — PyTorch CV embeddings + pre-shuffled WebDataset shards. "
        "Heavy tensors live on blob storage; only URIs and summary stats land "
        "in Iceberg."
    )
    try:
        from robomesh.cv import HAS_TORCH, get_backbone_name
        from robomesh.training.iterable_dataset import iter_arrow_batches

        c1, c2, c3 = st.columns(3)
        c1.metric("Backbone", get_backbone_name())
        c2.metric("PyTorch loaded", "yes" if HAS_TORCH else "fallback")

        try:
            gold_v2 = read_table_arrow("gold.vla_episodes_v2").to_pandas()
            c3.metric("Gold-v2 episodes", len(gold_v2))
            if not gold_v2.empty:
                st.markdown("**Gold v2 — per-episode embedding stats**")
                st.dataframe(
                    gold_v2[
                        [
                            "episode_id", "robot_model_id", "failure_type_tag",
                            "success_flag", "embedding_dim", "embedding_backbone",
                            "mean_embedding_l2", "max_frame_embedding_l2",
                            "mean_embedding_uri",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as exc:  # noqa: BLE001
            st.info(
                f"Gold v2 not built yet — run `make vla`. "
                f"({exc.__class__.__name__})"
            )

        try:
            from robomesh.config import get_settings as _gs
            shard_dir = _gs().artifacts_root / "training_shards"
            shards = sorted(shard_dir.glob("robomesh-vla-*.tar"))
            if shards:
                st.markdown("**Pre-shuffled WebDataset shards**")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"shard": p.name, "size_bytes": p.stat().st_size}
                            for p in shards
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        st.warning(f"VLA module not available: {exc.__class__.__name__}: {exc}")


# ---------- Tab 4: Closed loop ------------------------------------------- #

with tab_loop:
    st.subheader("Closed-loop policy evaluation")
    st.caption(
        "Phase 6 — deployed VLA inference events stream back into "
        "`simulation.bronze_live_inference` and seed the next training run."
    )
    try:
        live = read_table_arrow("simulation.bronze_live_inference").to_pandas()
    except Exception:  # noqa: BLE001
        live = pd.DataFrame()

    if live.empty:
        st.info("No live-inference events yet — run `make closed-loop`.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Events", len(live))
        c2.metric("Failures", int(live["is_failure"].sum()))
        c3.metric("Models", live["model_version"].nunique())
        c4.metric(
            "Mean confidence",
            f"{float(live['policy_confidence'].mean()):.3f}",
        )
        st.markdown("**Confidence vs. failures**")
        st.bar_chart(live.groupby("failure_type_tag")["policy_confidence"].mean())
        with st.expander("Raw events", expanded=False):
            st.dataframe(live, use_container_width=True, hide_index=True)


# ---------- Tab 5: Pipeline ---------------------------------------------- #

with tab_pipeline:
    st.subheader("End-to-end pipeline")
    st.markdown(
        """
        ```text
        ┌───────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │ Phase 0       │   │ Phase 1          │   │ Phase 2          │
        │ Generators    │──►│ Bronze ingest    │──►│ Silver + Gold    │
        │ (3 domains)   │   │ (Iceberg v2)     │   │ (DuckDB / dbt)   │
        └───────────────┘   └──────────────────┘   └─────────┬────────┘
                                                             │
        ┌────────────────┐   ┌─────────────────┐   ┌─────────▼────────┐
        │ Phase 6        │   │ Phase 2.5       │   │ Phase 3          │
        │ Closed-loop    │◄──│ CV embeddings + │◄──│ Contracts + Mask │
        │ live inference │   │ WebDataset      │   │ (SHA-256 RBAC)   │
        │ → Bronze       │   │ shards (Ray/DDP)│   └──────────────────┘
        └────────────────┘   └────────┬────────┘
                                      │
        ┌───────────────┐   ┌─────────▼────────┐
        │ Phase 5       │   │ Phase 4          │
        │ FinOps audit  │◄──│ Semantic RAG     │
        │ + Dagster     │   │ (ChromaDB)       │
        └───────────────┘   └──────────────────┘
        ```
        """
    )
    st.info(
        "Run `make demo` to materialize every phase end-to-end. "
        "Run `make dagster` to inspect the same DAG in the Dagit UI."
    )
