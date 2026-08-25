from __future__ import annotations

import pickle
import uuid
import weakref

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.mixins import (
    NestedMutableDict,
    NestedMutableList,
    UUIDPrimaryKeyMixin,
)


class LocalBase(DeclarativeBase):
    pass


class SampleModel(UUIDPrimaryKeyMixin, LocalBase):
    __tablename__ = "sample_models"
    data: Mapped[dict] = mapped_column(
        NestedMutableDict.as_mutable(JSONB),
        default=dict,
    )
    items: Mapped[list] = mapped_column(
        NestedMutableList.as_mutable(JSONB),
        default=list,
    )


class SecondModel(UUIDPrimaryKeyMixin, LocalBase):
    __tablename__ = "second_models"
    data: Mapped[dict] = mapped_column(
        NestedMutableDict.as_mutable(JSONB),
        default=dict,
    )


def test_list_sort_reverse_iadd_imul_mark_dirty() -> None:
    m = SampleModel(items=[{"val": 2}, {"val": 1}])
    state = inspect(m)
    state._commit_all(state.dict)
    assert not state.modified

    # sort
    m.items.sort(key=lambda x: x["val"])
    assert state.modified
    assert m.items[0]["val"] == 1
    assert m.items[1]["val"] == 2

    # reset and reverse
    state._commit_all(state.dict)
    assert not state.modified
    m.items.reverse()
    assert state.modified
    assert m.items[0]["val"] == 2

    # reset and __iadd__
    state._commit_all(state.dict)
    assert not state.modified
    m.items += [{"val": 3}]
    assert state.modified
    assert len(m.items) == 3

    # check newly added element via += is wrapped and notifies
    state._commit_all(state.dict)
    assert not state.modified
    m.items[2]["val"] = 99
    assert state.modified

    # reset and __imul__
    state._commit_all(state.dict)
    assert not state.modified
    m.items *= 2
    assert state.modified
    assert len(m.items) == 6


def test_list_imul_invalid_multiplier_and_identity_preservation() -> None:
    m = SampleModel(items=[{"val": 10}])
    child = m.items[0]

    # Invalid multiplier raises TypeError without mutating contents
    with pytest.raises(TypeError):
        m.items *= "invalid"  # type: ignore[operator]
    assert len(m.items) == 1
    assert m.items[0]["val"] == 10

    # *= 1 preserves existing child identity
    m.items *= 1
    assert m.items[0] is child


def test_dict_ior_marks_dirty_and_wraps_nested() -> None:
    m = SampleModel(data={"a": 1})
    state = inspect(m)
    state._commit_all(state.dict)
    assert not state.modified

    m.data |= {"nested": {"b": 2}}
    assert state.modified

    state._commit_all(state.dict)
    assert not state.modified
    m.data["nested"]["b"] = 3
    assert state.modified


def test_list_extend_with_self_terminates_and_duplicates_once() -> None:
    m = SampleModel(items=[{"x": 1}, {"x": 2}])
    state = inspect(m)
    state._commit_all(state.dict)
    assert not state.modified

    m.items.extend(m.items)
    assert state.modified
    assert len(m.items) == 4
    assert [item["x"] for item in m.items] == [1, 2, 1, 2]

    # Verify each element is wrapped and tracks mutation
    state._commit_all(state.dict)
    assert not state.modified
    m.items[2]["x"] = 100
    assert state.modified


def test_slice_assignment_wraps_each_element_and_tracks_dirty() -> None:
    m = SampleModel(items=[{"k": 1}, {"k": 2}, {"k": 3}])
    state = inspect(m)
    state._commit_all(state.dict)
    assert not state.modified

    m.items[1:3] = [{"k": 20, "sub": {"sub_k": 200}}, {"k": 30}]
    assert state.modified

    state._commit_all(state.dict)
    assert not state.modified
    m.items[1]["sub"]["sub_k"] = 999
    assert state.modified


def test_moving_wrapped_subtree_reparents_descendants() -> None:
    m1 = SampleModel(data={"subtree": {"nested": {"count": 1}}})
    m2 = SecondModel(data={})

    state1 = inspect(m1)
    state2 = inspect(m2)
    state1._commit_all(state1.dict)
    state2._commit_all(state2.dict)
    assert not state1.modified
    assert not state2.modified

    # Move subtree from m1 into m2
    m2.data["imported"] = m1.data["subtree"]
    assert state2.modified
    assert not state1.modified

    state1._commit_all(state1.dict)
    state2._commit_all(state2.dict)

    # Mutating nested within m2's imported subtree should only mark m2 dirty
    m2.data["imported"]["nested"]["count"] = 42
    assert state2.modified
    assert not state1.modified


def test_pickle_roundtrip_and_post_unpickle_mutation() -> None:
    m1 = SampleModel(data={"config": {"retries": 3, "tags": ["a", "b"]}})
    state1 = inspect(m1)
    # Ensure _parents exists on m1.data by accessing / using it in ORM
    assert hasattr(m1.data, "_parents")

    # Pickle and unpickle the NestedMutableDict
    raw_data = pickle.dumps(m1.data)
    restored_data = pickle.loads(raw_data)

    m2 = SampleModel(data=restored_data)
    state2 = inspect(m2)
    state2._commit_all(state2.dict)
    assert not state2.modified

    # Nested mutations on unpickled data attached to ORM instance must track dirty
    m2.data["config"]["retries"] = 5
    assert state2.modified

    state2._commit_all(state2.dict)
    assert not state2.modified
    m2.data["config"]["tags"].append("c")
    assert state2.modified


def test_direct_unpickle_root_hierarchy_and_weakkeydict() -> None:
    d = NestedMutableDict({"config": {"retries": 3, "tags": ["a", "b"]}})
    raw = pickle.dumps(d)
    restored = pickle.loads(raw)

    assert restored["config"]._root is restored
    assert restored["config"]["tags"]._root is restored
    assert isinstance(restored._parents, weakref.WeakKeyDictionary)
    assert type(restored._parents) is weakref.WeakKeyDictionary


def test_cyclic_structure_raises_error() -> None:
    cyclic_dict: dict = {}
    cyclic_dict["self"] = cyclic_dict
    with pytest.raises(ValueError, match="Cyclic structure"):
        SampleModel(data=cyclic_dict)
