"""Computer-vision feature extraction (Phase 2.5 — Silver → Gold boundary).

This subpackage embeds video frames using a frozen, pre-trained vision
backbone (ResNet18 / ViT-Tiny) so VLA training workers consume **pre-computed
tensor embeddings** instead of raw pixels — eliminating the GPU-idle-while-CPU-
decodes-MP4 bottleneck.
"""
from robomesh.cv.feature_extractor import (
    FrameEmbedding,
    HAS_TORCH,
    extract_episode_embeddings,
    get_backbone_name,
)
from robomesh.cv.tensor_store import (
    TensorStore,
    get_tensor_store,
    tensor_uri_to_path,
)

__all__ = [
    "FrameEmbedding",
    "HAS_TORCH",
    "extract_episode_embeddings",
    "get_backbone_name",
    "TensorStore",
    "get_tensor_store",
    "tensor_uri_to_path",
]
