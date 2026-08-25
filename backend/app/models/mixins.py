from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.mutable import Mutable
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )


class RevisionMixin:
    revision: Mapped[int] = mapped_column(
        sa.Integer,
        default=1,
        server_default=sa.text("1"),
        nullable=False,
    )


def _reparent(
    value: Any,
    root: Mutable | None = None,
    seen: set[int] | None = None,
) -> Any:
    if seen is None:
        seen = set()
    if id(value) in seen:
        raise ValueError("Cyclic structure cannot be serialized to JSON")

    if isinstance(value, dict):
        curr_seen = set(seen)
        curr_seen.add(id(value))
        res = NestedMutableDict(_root=root)
        actual_root = root if root is not None else res
        res._root = actual_root
        for k, v in value.items():
            super(NestedMutableDict, res).__setitem__(
                k,
                _reparent(v, actual_root, curr_seen),
            )
        return res
    if isinstance(value, list):
        curr_seen = set(seen)
        curr_seen.add(id(value))
        res = NestedMutableList(_root=root)
        actual_root = root if root is not None else res
        res._root = actual_root
        for item in value:
            super(NestedMutableList, res).append(
                _reparent(item, actual_root, curr_seen),
            )
        return res
    return value


class NestedMutableDict(Mutable, dict):
    _root: Mutable | None = None

    @classmethod
    def coerce(cls, key: str, value: Any) -> Any:
        if isinstance(value, dict):
            return _reparent(value, None)
        return super().coerce(key, value)

    def __init__(
        self,
        *args: Any,
        _root: Mutable | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._root = _root if _root is not None else self
        if args or kwargs:
            raw = dict(*args, **kwargs)
            for k, v in raw.items():
                super().__setitem__(k, _reparent(v, self._root))

    def _notify(self) -> None:
        root = getattr(self, "_root", None)
        if root is not None and root is not self:
            root.changed()
        else:
            self.changed()

    def __setitem__(self, key: Any, value: Any) -> None:
        root = getattr(self, "_root", None) or self
        super().__setitem__(key, _reparent(value, root))
        self._notify()

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self._notify()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        raw = dict(*args, **kwargs)
        root = getattr(self, "_root", None) or self
        for k, v in raw.items():
            super().__setitem__(k, _reparent(v, root))
        self._notify()

    def __ior__(self, other: Any) -> NestedMutableDict:
        self.update(other)
        return self

    def pop(self, *args: Any) -> Any:
        res = super().pop(*args)
        self._notify()
        return res

    def popitem(self) -> Any:
        res = super().popitem()
        self._notify()
        return res

    def clear(self) -> None:
        super().clear()
        self._notify()

    def __getstate__(self) -> dict[str, Any]:
        return {"_data": {k: v for k, v in self.items()}}

    def __setstate__(self, state: dict[str, Any]) -> None:
        super().__init__()
        self._root = self
        self._parents = {}
        for k, v in state.get("_data", {}).items():
            super().__setitem__(k, _reparent(v, self))


class NestedMutableList(Mutable, list):
    _root: Mutable | None = None

    @classmethod
    def coerce(cls, key: str, value: Any) -> Any:
        if isinstance(value, list):
            return _reparent(value, None)
        return super().coerce(key, value)

    def __init__(self, *args: Any, _root: Mutable | None = None) -> None:
        super().__init__()
        self._root = _root if _root is not None else self
        if args and args[0]:
            for item in args[0]:
                super().append(_reparent(item, self._root))

    def _notify(self) -> None:
        root = getattr(self, "_root", None)
        if root is not None and root is not self:
            root.changed()
        else:
            self.changed()

    def __setitem__(self, index: Any, value: Any) -> None:
        root = getattr(self, "_root", None) or self
        if isinstance(index, slice):
            wrapped = [_reparent(v, root) for v in value]
            super().__setitem__(index, wrapped)
        else:
            super().__setitem__(index, _reparent(value, root))
        self._notify()

    def __delitem__(self, index: Any) -> None:
        super().__delitem__(index)
        self._notify()

    def append(self, value: Any) -> None:
        root = getattr(self, "_root", None) or self
        super().append(_reparent(value, root))
        self._notify()

    def extend(self, values: Any) -> None:
        root = getattr(self, "_root", None) or self
        items = list(values)
        for v in items:
            super().append(_reparent(v, root))
        self._notify()

    def insert(self, index: int, value: Any) -> None:
        root = getattr(self, "_root", None) or self
        super().insert(index, _reparent(value, root))
        self._notify()

    def pop(self, *args: Any) -> Any:
        res = super().pop(*args)
        self._notify()
        return res

    def remove(self, value: Any) -> None:
        super().remove(value)
        self._notify()

    def clear(self) -> None:
        super().clear()
        self._notify()

    def sort(self, *args: Any, **kwargs: Any) -> None:
        super().sort(*args, **kwargs)
        self._notify()

    def reverse(self) -> None:
        super().reverse()
        self._notify()

    def __iadd__(self, values: Any) -> NestedMutableList:
        self.extend(values)
        return self

    def __imul__(self, n: int) -> NestedMutableList:
        root = getattr(self, "_root", None) or self
        items = list(self)
        super().clear()
        for _ in range(n):
            for item in items:
                super().append(_reparent(item, root))
        self._notify()
        return self

    def __getstate__(self) -> dict[str, Any]:
        return {"_data": list(self)}

    def __setstate__(self, state: dict[str, Any]) -> None:
        super().__init__()
        self._root = self
        self._parents = {}
        for item in state.get("_data", []):
            super().append(_reparent(item, self))
