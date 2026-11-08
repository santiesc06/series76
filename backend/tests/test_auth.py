"""Login and per-user conversations (US-21), through the real API and database. No LLM calls."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent.llm import get_chat_model
from app.auth.seed import SEED_FILE, seed_users
from app.auth.service import hash_password, verify_password
from app.db.models import AuthToken, User
from app.db.session import get_db
from app.main import app
from tests.fakes import ScriptedModel, final, tool_call

PN = "763B00-11300000/A"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def ask(client, token, session_id=None):
    """One scripted turn (lookup + answer) as the user who owns `token`."""
    model = ScriptedModel(
        script=[
            tool_call("lookup_part", part_number=PN),
            final("It delivers 500 Nm.", status="answered", product_refs=[PN]),
        ]
    )
    app.dependency_overrides[get_chat_model] = lambda: model
    body = {"query": f"Torque of {PN}?"} | ({"session_id": session_id} if session_id else {})
    return client.post("/api/conversation", json=body, headers=bearer(token))


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_returns_a_token_that_works(client, make_user):  # US-21 AC1
    make_user("ana@series76.test", "right-password")
    r = login(client, "  Ana@Series76.test ", "right-password")  # email is trimmed, any case
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["email"] == "ana@series76.test"
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC) + timedelta(days=6)
    me = client.get("/api/auth/me", headers=bearer(body["token"]))
    assert me.status_code == 200 and me.json()["email"] == "ana@series76.test"


def test_wrong_password_and_unknown_email_look_the_same(client, make_user):  # US-21 AC1
    make_user("ana@series76.test", "right-password")
    wrong = login(client, "ana@series76.test", "wrong-password")
    unknown = login(client, "nobody@series76.test", "right-password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "invalid_credentials"


def test_passwords_are_stored_as_argon2id_hashes(db, make_user):  # US-21 AC2
    user, _ = make_user("ana@series76.test", "right-password")
    assert user.password_hash.startswith("$argon2id$")
    assert "right-password" not in user.password_hash
    assert verify_password(user.password_hash, "right-password")
    assert not verify_password(user.password_hash, "wrong-password")
    assert not verify_password("not-a-hash", "right-password")


def test_login_response_never_contains_the_password_hash(client, make_user):  # US-21 AC2
    make_user("ana@series76.test", "right-password")
    text = login(client, "ana@series76.test", "right-password").text
    assert "argon2" not in text and "password" not in text


def test_seeded_test_users_are_idempotent_and_hashed(db):  # US-21 AC3
    entries = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    assert len(entries) >= 2
    assert all(e["password_hash"].startswith("$argon2id$") for e in entries)
    assert all(set(e) == {"email", "name", "password_hash"} for e in entries)  # no passwords
    seed_users(db)
    seed_users(db)
    emails = db.scalars(select(User.email)).all()
    assert sorted(emails) == sorted(e["email"] for e in entries)


def test_seed_updates_an_existing_user(db, tmp_path):  # US-21 AC3
    path = tmp_path / "users.json"
    entry = {"email": "Ana@Series76.test", "name": "Ana", "password_hash": hash_password("one")}
    path.write_text(json.dumps([entry]), encoding="utf-8")
    seed_users(db, path)
    entry |= {"name": "Ana B.", "password_hash": hash_password("two")}
    path.write_text(json.dumps([entry]), encoding="utf-8")
    seed_users(db, path)
    user = db.scalar(select(User).where(User.email == "ana@series76.test"))
    assert user.name == "Ana B." and verify_password(user.password_hash, "two")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/conversation"),
        ("get", "/api/sessions"),
        ("get", "/api/sessions/00000000-0000-0000-0000-000000000000/messages"),
        ("get", "/api/messages/00000000-0000-0000-0000-000000000000/debug"),
        ("get", "/api/auth/me"),
        ("post", "/api/auth/logout"),
    ],
)
def test_every_api_route_needs_a_token(client, method, path):  # US-21 AC4
    kwargs = {"json": {"query": "hi"}} if method == "post" else {}
    for headers in ({}, bearer("not-a-real-token"), {"Authorization": "Basic abc"}):
        r = getattr(client, method)(path, headers=headers, **kwargs)
        assert r.status_code == 401, (path, headers)
        assert r.json()["error"]["code"] == "unauthorized"
        assert r.headers["WWW-Authenticate"] == "Bearer"


def test_health_and_docs_stay_open(client):  # US-21 AC4
    assert client.get("/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_expired_token_is_rejected(client, db, make_user):  # US-21 AC4
    _, token = make_user()
    row = db.scalar(select(AuthToken))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 401


def test_tokens_are_stored_only_as_hashes(db, make_user):  # US-21, design U1
    _, token = make_user()
    stored = db.scalars(select(AuthToken.token_hash)).all()
    assert token not in stored and len(stored[0]) == 64


def test_users_only_see_their_own_conversations(client, make_user):  # US-21 AC5, AC6
    _, alice = make_user("alice@x.test")
    _, bob = make_user("bob@x.test")
    first = ask(client, alice).json()
    sid, mid = first["session_id"], first["message_id"]

    assert [s["id"] for s in client.get("/api/sessions", headers=bearer(alice)).json()] == [sid]
    assert client.get("/api/sessions", headers=bearer(bob)).json() == []

    for path in (f"/api/sessions/{sid}/messages", f"/api/messages/{mid}/debug"):
        assert client.get(path, headers=bearer(alice)).status_code == 200
        r = client.get(path, headers=bearer(bob))
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"

    # Bob cannot continue Alice's conversation; Alice can.
    assert ask(client, bob, session_id=sid).status_code == 404
    assert ask(client, alice, session_id=sid).status_code == 200


def test_conversations_from_before_login_are_hidden(client, db, make_user):  # US-21, design U3
    from app.db.models import ChatSession

    db.add(ChatSession(title="old, no owner"))
    db.flush()
    _, token = make_user()
    assert client.get("/api/sessions", headers=bearer(token)).json() == []


def test_logout_revokes_the_token(client, make_user):  # US-21 AC8
    make_user("ana@series76.test", "right-password")
    token = login(client, "ana@series76.test", "right-password").json()["token"]
    other = login(client, "ana@series76.test", "right-password").json()["token"]
    assert client.post("/api/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 401
    assert client.get("/api/auth/me", headers=bearer(other)).status_code == 200  # other device


def test_swagger_has_the_authorize_button(client):  # US-21, design U4
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
