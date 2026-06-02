import pyarrow as pa
from pyiceberg.exceptions import NoSuchTableError

from config.profiles import REGISTRY, MeshProfile
from data_platform import catalog, generators


def test_create_and_append_roundtrip():
    batch = generators.make_bronze_batch(MeshProfile.ROBOTICS, n=10)
    written = catalog.write_data_product(
        "bronze", "robot_signals", batch, expected_schema=REGISTRY[MeshProfile.ROBOTICS].silver_schema
    )
    assert written == 10
    arrow = catalog.read_table_arrow("bronze.robot_signals")
    assert arrow.num_rows == 10


def test_align_batch_fills_missing_columns():
    target = pa.schema([("a", pa.int64()), ("b", pa.string())])
    batch = pa.table({"a": [1, 2, 3]})
    aligned = catalog._align_batch(batch, target)
    assert aligned.schema.equals(target)
    assert aligned.column("b").null_count == 3


def test_create_race_lost_reloads(monkeypatch):
    batch = generators.make_bronze_batch(MeshProfile.ROBOTICS, n=5)
    catalog.write_data_product("bronze", "robot_signals", batch)  # table now exists

    cat = catalog.get_catalog()
    original_load = cat.load_table
    state = {"first": True}

    def flaky_load(identifier):
        # Simulate a concurrent worker: first load sees the table as missing, so the
        # write goes down the create path, hits TableAlreadyExistsError, then reloads.
        if state["first"]:
            state["first"] = False
            raise NoSuchTableError(identifier)
        return original_load(identifier)

    monkeypatch.setattr(cat, "load_table", flaky_load)
    written = catalog.write_data_product("bronze", "robot_signals", batch)
    assert written == 5
