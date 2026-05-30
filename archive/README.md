# Archived projects

These three projects have been **consolidated into and superseded by
[`OMNI-Mesh`](../OMNI-Mesh)**, a single polymorphic data-mesh codebase that runs each domain
via the `OMNI_MESH_PROFILE` environment variable. They are retained read-only for history,
provenance, and reference — **new work should happen in `OMNI-Mesh`.**

| Archived project | Superseded by OMNI-Mesh profile(s) |
| --- | --- |
| `heal-mesh/` | `HEALTH_TECH`, `COMMERCIAL`, `CLINICAL` |
| `RoboMesh/` | `ROBOTICS` |
| `MFG-Mesh/` | `MANUFACTURING` |

## Not yet ported to OMNI-Mesh

Consult the original repos if you need any of the following, which were not carried over:

- **RoboMesh** — Ray Data loader / `torch.IterableDataset` training I/O, the Streamlit RAG
  explorer, and the walkthrough notebook.
- **heal-mesh** — Terraform infra stubs (AWS/GCP), `docker-compose` stack, OpenTelemetry
  observability, and the Grafana FinOps dashboard.

Each project still contains its own git history (`.git/`) intact.
