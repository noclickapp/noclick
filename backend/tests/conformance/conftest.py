"""Conformance tests must never open a socket, including during lazy imports."""
import pytest

from tests.conformance.harness import offline


@pytest.fixture(autouse=True)
def no_network():
    with offline():
        yield
