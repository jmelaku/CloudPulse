import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, make_asgi_app
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, init_db
from app.models import Transaction
from app.queue import publish_transaction

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
requests = Counter("cloudpulse_transactions_submitted_total", "Transactions submitted")
submit_latency = Histogram("cloudpulse_submit_seconds", "Transaction submit duration")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="CloudPulse", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


class TransactionRequest(BaseModel):
    amount_cents: int = Field(gt=0, le=100_000_000)
    description: Optional[str] = Field(default=None, max_length=1000)


class TransactionResponse(BaseModel):
    id: str
    status: str
    amount_cents: int
    description: Optional[str]
    result: Optional[str]
    error: Optional[str]


def as_response(row: Transaction) -> TransactionResponse:
    return TransactionResponse(id=row.id, status=row.status, amount_cents=row.amount_cents,
                               description=row.description, result=row.result, error=row.error)


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "database unavailable") from exc
    return {"status": "ready"}


@app.post("/transactions", response_model=TransactionResponse, status_code=202)
def submit(payload: TransactionRequest, response: Response, idempotency_key: str = Header(...)):
    with submit_latency.time():
        db = SessionLocal()
        created = False
        try:
            row = Transaction(idempotency_key=idempotency_key, amount_cents=payload.amount_cents,
                              description=payload.description)
            db.add(row)
            db.commit()
            db.refresh(row)
            created = True
        except IntegrityError:
            db.rollback()
            row = db.query(Transaction).filter_by(idempotency_key=idempotency_key).one()
            response.status_code = 200
        finally:
            db.close()
        # Publishing on retries also repairs the small commit-to-publish failure window.
        if created or row.status == "pending":
            try:
                publish_transaction(row.id)
            except Exception as exc:
                log.exception("queue publish failed transaction_id=%s", row.id)
                raise HTTPException(503, "transaction recorded; queue temporarily unavailable") from exc
        requests.inc()
        return as_response(row)


@app.get("/transactions/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: str):
    with SessionLocal() as db:
        row = db.get(Transaction, transaction_id)
        if row is None:
            raise HTTPException(404, "transaction not found")
        return as_response(row)
