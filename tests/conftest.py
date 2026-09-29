import pytest
import app as server
from analyst.auth import require_owner


@pytest.fixture
def owner_session(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fixture.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-only")
    server.app.dependency_overrides[require_owner] = lambda: (
        "00000000-0000-0000-0000-000000000001"
    )
    yield
    server.app.dependency_overrides.pop(require_owner, None)
