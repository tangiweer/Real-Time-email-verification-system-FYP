
import pytest

# Configure pytest-asyncio to use asyncio as the default event loop
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
