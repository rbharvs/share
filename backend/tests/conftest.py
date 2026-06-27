from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from share.api import create_app

DASHBOARD_HOST = "share.example.com"
PRIVATE_HOST = "private.usercontent.example"
PUBLIC_HOST = "public.usercontent.example"


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False so handler-mapped errors are observed as
    # real HTTP responses rather than re-raised exceptions.
    return TestClient(create_app(), raise_server_exceptions=False)
