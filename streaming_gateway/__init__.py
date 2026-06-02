"""Low-latency telemetry downsampling gateway (500Hz -> 30Hz).

Built on Starlette (FastAPI's ASGI core) to stay dependency-compatible with the
installed Dagster stack. Profile-aware: the downsample aggregation and metric label
change with OMNI_MESH_PROFILE (robotics=peak, manufacturing/health=mean).
"""
