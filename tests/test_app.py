import pytest
import json
from app.app import app, db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()


def test_health_check(client):
    """Health endpoint must return 200 when DB is reachable."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["status"] == "healthy"


def test_create_note(client):
    resp = client.post(
        "/notes",
        json={"title": "Test Note", "content": "Hello World"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    data = json.loads(resp.data)
    assert data["title"] == "Test Note"
    assert "id" in data


def test_get_notes(client):
    client.post("/notes", json={"title": "A", "content": "B"})
    resp = client.get("/notes")
    assert resp.status_code == 200
    notes = json.loads(resp.data)
    assert len(notes) >= 1


def test_update_note(client):
    r = client.post("/notes", json={"title": "Old", "content": "Old content"})
    note_id = json.loads(r.data)["id"]
    resp = client.put(f"/notes/{note_id}", json={"title": "New Title"})
    assert resp.status_code == 200
    assert json.loads(resp.data)["title"] == "New Title"


def test_delete_note(client):
    r = client.post("/notes", json={"title": "Del", "content": "Bye"})
    note_id = json.loads(r.data)["id"]
    resp = client.delete(f"/notes/{note_id}")
    assert resp.status_code == 200


def test_missing_fields(client):
    resp = client.post("/notes", json={"title": "only title"})
    assert resp.status_code == 400
