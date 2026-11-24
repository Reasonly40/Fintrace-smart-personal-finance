from functools import cache
from zoneinfo import ZoneInfo, available_timezones

# Default untuk akun lokal awal (Decision Log, bagian 26 dokumen)
DEFAULT_TIMEZONE = "Asia/Makassar"


@cache
def _known() -> frozenset[str]:
    return frozenset(available_timezones())


def is_valid_timezone(name: str) -> bool:
    """True hanya untuk nama zona IANA yang dikenal, misalnya Asia/Makassar."""
    return name in _known()


def get_zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)