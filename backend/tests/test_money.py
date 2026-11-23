import pytest
from pydantic import BaseModel, ValidationError

from app.core.money import MAX_RUPIAH, Rupiah


class Payload(BaseModel):
    amount: Rupiah


@pytest.mark.parametrize("value", [1, 1_000_000, MAX_RUPIAH])
def test_valid_rupiah_is_accepted(value):
    assert Payload(amount=value).amount == value


@pytest.mark.parametrize(
    "value", [0, -1, 100.5, 100.0, "100", True, None, MAX_RUPIAH + 1]
)
def test_invalid_rupiah_is_rejected(value):
    with pytest.raises(ValidationError):
        Payload(amount=value)