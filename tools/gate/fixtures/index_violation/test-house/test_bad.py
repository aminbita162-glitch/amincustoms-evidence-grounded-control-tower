import pytest


@pytest.mark.fast
def test_bad_header():
    """id: T-STATE-0001
    title: Bad header test
    level: fast
    requirement: R1
    input: none
    expected: fail
    risk: low
    capability: test
    """
    assert True
