from enum import StrEnum


def sql_in(column: str, enum_cls: type[StrEnum]) -> str:
    """Ekspresi CHECK: kolom hanya boleh berisi nilai-nilai enum."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"