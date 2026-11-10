import pytest


@pytest.mark.fast
def test_always_fails() -> None:
    assert False, "intentional failure"
