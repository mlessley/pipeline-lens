import os

from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = os.environ.get("SCIE_DATABASE_URL", "sqlite:///./scie.db")
engine = create_engine(DATABASE_URL, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
