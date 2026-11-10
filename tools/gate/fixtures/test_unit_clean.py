import pytest


@pytest.mark.fast
def test_always_passes() -> None:
    assert True
