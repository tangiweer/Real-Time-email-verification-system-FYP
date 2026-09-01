
import os
import pytest

# Unit and integration tests must never share the running application's Redis
# data.  Otherwise an SMTP result cached by one test can change a later test's
# verdict.  Production caching remains enabled outside pytest.
os.environ.pop("REDIS_URL", None)
os.environ["MOCK_SMTP"] = "0"

# Configure pytest-asyncio to use asyncio as the default event loop
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
