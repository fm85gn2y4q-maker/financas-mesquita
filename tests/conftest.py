import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    """Sem isto o anyio roda cada teste também em trio, que não está instalado."""
    return "asyncio"
