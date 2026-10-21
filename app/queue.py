import json
import time

import pika

from app.settings import QUEUE_NAME, RABBITMQ_URL, RETRY_DELAY_MS

RETRY_QUEUE = f"{QUEUE_NAME}.retry"
DLQ_NAME = f"{QUEUE_NAME}.dlq"


def connection(retries: int = 30):
    for attempt in range(retries):
        try:
            return pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        except pika.exceptions.AMQPConnectionError:
            if attempt == retries - 1:
                raise
            time.sleep(1)


def declare(channel) -> None:
    channel.queue_declare(queue=DLQ_NAME, durable=True)
    channel.queue_declare(
        queue=RETRY_QUEUE, durable=True,
        arguments={"x-message-ttl": RETRY_DELAY_MS,
                   "x-dead-letter-exchange": "",
                   "x-dead-letter-routing-key": QUEUE_NAME},
    )
    channel.queue_declare(
        queue=QUEUE_NAME, durable=True,
        arguments={"x-dead-letter-exchange": "",
                   "x-dead-letter-routing-key": RETRY_QUEUE},
    )


def publish_transaction(transaction_id: str) -> None:
    conn = connection()
    try:
        channel = conn.channel()
        declare(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps({"transaction_id": transaction_id}),
            properties=pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent),
            mandatory=True,
        )
    finally:
        conn.close()


def retry_count(headers) -> int:
    """Count rejected dead-letter events from the primary queue."""
    for death in (headers or {}).get("x-death", []):
        if death.get("queue") == QUEUE_NAME and death.get("reason") == "rejected":
            return int(death.get("count", 0))
    return 0


def send_to_dlq(channel, body, properties) -> None:
    channel.basic_publish(
        exchange="", routing_key=DLQ_NAME, body=body,
        properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent,
            headers=(properties.headers if properties else None),
        ),
    )
