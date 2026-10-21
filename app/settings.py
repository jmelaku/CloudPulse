import os


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://postgres@postgres:5432/cloudpulse"
)
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F")
QUEUE_NAME = os.getenv("QUEUE_NAME", "cloudpulse.transactions")
PROCESSING_DELAY_MS = int(os.getenv("PROCESSING_DELAY_MS", "0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY_MS = int(os.getenv("RETRY_DELAY_MS", "1000"))
