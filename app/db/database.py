import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

_url = os.getenv("DATABASE_URL", "sqlite:///./bylaw_app.db")

# Railway provides postgres:// URLs; SQLAlchemy requires postgresql://
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql://", 1)

# check_same_thread is SQLite-only
connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
