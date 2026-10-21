import json
import logging
import time

from prometheus_client import Counter, start_http_server
from sqlalchemy import update

from app.database import SessionLocal, init_db
from app.models import Transaction
from app.queue import connection, declare, retry_count, send_to_dlq
from app.settings import MAX_RETRIES, PROCESSING_DELAY_MS, QUEUE_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
completed = Counter("cloudpulse_transactions_completed_total", "Completed transactions")


def process(transaction_id: str) -> bool:
    """Claim a pending transaction atomically; duplicates become no-ops."""
    with SessionLocal.begin() as db:
        claimed = db.execute(
            update(Transaction)
            .where(Transaction.id == transaction_id, Transaction.status == "pending")
            .values(status="processing")
        ).rowcount
    if not claimed:
        return False
    if PROCESSING_DELAY_MS:
        time.sleep(PROCESSING_DELAY_MS / 1000)
    with SessionLocal.begin() as db:
        db.execute(update(Transaction).where(Transaction.id == transaction_id,
                                             Transaction.status == "processing")
                   .values(status="completed", result="processed"))
    completed.inc()
    log.info("completed transaction_id=%s", transaction_id)
    return True


def handle_delivery(channel, method, properties, body) -> None:
    """Ack durable success; delay retry failures and finally preserve them in the DLQ."""
    try:
        process(json.loads(body)["transaction_id"])
        channel.basic_ack(method.delivery_tag)
    except Exception:
        attempts = retry_count(getattr(properties, "headers", None))
        log.exception("worker failed transaction; retry_count=%s", attempts)
        if attempts >= MAX_RETRIES:
            send_to_dlq(channel, body, properties)
            channel.basic_ack(method.delivery_tag)
        else:
            channel.basic_nack(method.delivery_tag, requeue=False)


def main() -> None:
    init_db()
    start_http_server(9100)
    conn = connection()
    channel = conn.channel()
    declare(channel)
    channel.basic_qos(prefetch_count=10)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=handle_delivery, auto_ack=False)
    log.info("worker consuming queue=%s", QUEUE_NAME)
    channel.start_consuming()


if __name__ == "__main__":
    main()
