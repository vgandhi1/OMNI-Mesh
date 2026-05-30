import pytest

from config.profiles import REGISTRY, MeshProfile
from data_platform import generators


@pytest.mark.parametrize("profile", list(MeshProfile))
def test_bronze_batch_matches_silver_schema(profile):
    batch = generators.make_bronze_batch(profile, n=8)
    assert batch.num_rows == 8
    assert batch.schema.equals(REGISTRY[profile].silver_schema)


@pytest.mark.parametrize("profile", list(MeshProfile))
def test_every_profile_has_rag_vocab(profile):
    spec = REGISTRY[profile]
    assert spec.rag_vocab
    for field_name in spec.rag_vocab:
        assert field_name in spec.silver_schema.names
