import pytest
from fastapi.testclient import TestClient
from backend.main import app

def test_v2_redirects_to_root():
    client = TestClient(app)
    response = client.get("/v2.html", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/"

def test_root_serves_index_html():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "WFM" in response.text and ("Workforce Management" in response.text or "Vận Hành" in response.text)
    assert "tabAlertHanging" in response.text
