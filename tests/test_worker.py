from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Transaction


def test_worker_claims_once(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        db.add(Transaction(id="t1", idempotency_key="key", amount_cents=100))
    import app.worker as worker
    monkeypatch.setattr(worker, "SessionLocal", Session)
    assert worker.process("t1") is True
    assert worker.process("t1") is False
    with Session() as db:
        assert db.get(Transaction, "t1").status == "completed"


class Channel:
    def __init__(self): self.acks, self.nacks, self.published = [], [], []
    def basic_ack(self, tag): self.acks.append(tag)
    def basic_nack(self, tag, requeue): self.nacks.append((tag, requeue))
    def basic_publish(self, **kwargs): self.published.append(kwargs)


def test_failed_delivery_enters_retry(monkeypatch):
    import app.worker as worker
    monkeypatch.setattr(worker, "process", lambda _: (_ for _ in ()).throw(RuntimeError("fail")))
    channel = Channel()
    worker.handle_delivery(channel, SimpleNamespace(delivery_tag=1), SimpleNamespace(headers={}), b'{"transaction_id":"t1"}')
    assert channel.nacks == [(1, False)]
    assert channel.acks == []


def test_exhausted_delivery_goes_to_dlq(monkeypatch):
    import app.worker as worker
    monkeypatch.setattr(worker, "process", lambda _: (_ for _ in ()).throw(RuntimeError("fail")))
    monkeypatch.setattr(worker, "MAX_RETRIES", 3)
    channel = Channel()
    headers = {"x-death": [{"queue": "cloudpulse.transactions", "reason": "rejected", "count": 3}]}
    worker.handle_delivery(channel, SimpleNamespace(delivery_tag=2), SimpleNamespace(headers=headers), b'bad')
    assert channel.acks == [2]
    assert channel.nacks == []
    assert channel.published[0]["routing_key"] == "cloudpulse.transactions.dlq"


def test_retry_count_reads_primary_rejections():
    from app.queue import retry_count
    assert retry_count({"x-death": [{"queue": "other", "reason": "rejected", "count": 9}, {"queue": "cloudpulse.transactions", "reason": "rejected", "count": 2}]}) == 2
