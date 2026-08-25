import uuid
from datetime import datetime
from typing import Any

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


class NestedMutableDict(Mutable, dict):
    @classmethod
    def coerce(cls, key: str, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(value)
        return super().coerce(key, value)

    def __init__(
        self,
        *args: Any,
        _root: Mutable | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._root: Mutable | None = _root if _root is not None else self
        dict_data = dict(*args, **kwargs)
        for k, v in dict_data.items():
            super().__setitem__(k, self._wrap(v))

    def _wrap(self, value: Any) -> Any:
        root = self._root if self._root is not None else self
        if isinstance(value, dict) and not isinstance(value, NestedMutableDict):
            return NestedMutableDict(value, _root=root)
        if isinstance(value, list) and not isinstance(value, NestedMutableList):
            return NestedMutableList(value, _root=root)
        if isinstance(value, (NestedMutableDict, NestedMutableList)):
            value._root = root
            return value
        return value

    def _notify(self) -> None:
        if self._root is not None:
            self._root.changed()
        else:
            self.changed()

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, self._wrap(value))
        self._notify()

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self._notify()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        dict_data = dict(*args, **kwargs)
        for k, v in dict_data.items():
            self[k] = v

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


class NestedMutableList(Mutable, list):
    @classmethod
    def coerce(cls, key: str, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, list):
            return cls(value)
        return super().coerce(key, value)

    def __init__(self, *args: Any, _root: Mutable | None = None) -> None:
        super().__init__()
        self._root: Mutable | None = _root if _root is not None else self
        if args and args[0]:
            for item in args[0]:
                super().append(self._wrap(item))

    def _wrap(self, value: Any) -> Any:
        root = self._root if self._root is not None else self
        if isinstance(value, dict) and not isinstance(value, NestedMutableDict):
            return NestedMutableDict(value, _root=root)
        if isinstance(value, list) and not isinstance(value, NestedMutableList):
            return NestedMutableList(value, _root=root)
        if isinstance(value, (NestedMutableDict, NestedMutableList)):
            value._root = root
            return value
        return value

    def _notify(self) -> None:
        if self._root is not None:
            self._root.changed()
        else:
            self.changed()

    def __setitem__(self, index: Any, value: Any) -> None:
        super().__setitem__(index, self._wrap(value))
        self._notify()

    def __delitem__(self, index: Any) -> None:
        super().__delitem__(index)
        self._notify()

    def append(self, value: Any) -> None:
        super().append(self._wrap(value))
        self._notify()

    def extend(self, values: Any) -> None:
        for v in values:
            self.append(v)

    def insert(self, index: int, value: Any) -> None:
        super().insert(index, self._wrap(value))
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
