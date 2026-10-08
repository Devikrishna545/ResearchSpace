import pytest

from app.core.auth import _active_user_id


@pytest.fixture(autouse=True)
def authenticated_service_context():
    token = _active_user_id.set("test-owner")
    yield
    _active_user_id.reset(token)
