from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base


def test_idempotency_returns_same_transaction(monkeypatch):
    import app.api as api
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(api, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(api, "init_db", lambda: None)
    monkeypatch.setattr(api, "publish_transaction", lambda _: None)
    with TestClient(api.app) as client:
        one = client.post("/transactions", headers={"Idempotency-Key": "same-key"}, json={"amount_cents": 100})
        two = client.post("/transactions", headers={"Idempotency-Key": "same-key"}, json={"amount_cents": 100})
    assert one.status_code == 202
    assert two.status_code == 200
    assert one.json()["id"] == two.json()["id"]


def test_validation_and_missing_idempotency_key(monkeypatch):
    import app.api as api
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(api, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(api, "init_db", lambda: None)
    with TestClient(api.app) as client:
        assert client.post("/transactions", json={"amount_cents": 1}).status_code == 422
        assert client.post("/transactions", headers={"Idempotency-Key": "bad"}, json={"amount_cents": 0}).status_code == 422
        assert client.get("/transactions/not-a-real-id").status_code == 404


def test_publish_failure_is_503_and_row_is_retained(monkeypatch):
    import app.api as api
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(api, "SessionLocal", Session)
    monkeypatch.setattr(api, "init_db", lambda: None)
    monkeypatch.setattr(api, "publish_transaction", lambda _: (_ for _ in ()).throw(RuntimeError("broker down")))
    with TestClient(api.app) as client:
        response = client.post("/transactions", headers={"Idempotency-Key": "publish-failure"}, json={"amount_cents": 7})
    assert response.status_code == 503
    with Session() as db:
        assert db.query(__import__("app.models", fromlist=["Transaction"]).Transaction).one().status == "pending"
