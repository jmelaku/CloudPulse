import time

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.settings import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db(retries: int = 30) -> None:
    from app.models import Transaction  # register metadata
    for attempt in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1)
