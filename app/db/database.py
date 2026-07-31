# backend/app/db/database.py

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/anpr_db"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """
    Database session dependency.
    Used in FastAPI Depends().
    """
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()
