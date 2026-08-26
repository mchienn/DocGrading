import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    metadata = sa.MetaData(naming_convention={"pk": "pk_%(table_name)s"})
