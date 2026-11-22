from pydantic import BaseModel


class Page[T](BaseModel):
    """Envelope standar untuk semua endpoint daftar."""

    items: list[T]
    page: int
    limit: int
    total: int