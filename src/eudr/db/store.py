"""Case persistence: one JSON document per case plus indexed columns. SQLite by default, Postgres via EUDR_DB_URL."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session

from eudr.config import settings
from eudr.models import Case


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"
    id = Column(String, primary_key=True)
    operator = Column(String, nullable=False)
    status = Column(String, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=False)
    body = Column(Text, nullable=False)


class CaseStore:
    def __init__(self, url: str | None = None):
        url = url or settings.sqlalchemy_url
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, future=True, **kw)
        Base.metadata.create_all(self.engine)

    def save(self, case: Case) -> Case:
        case.updated_at = datetime.now(timezone.utc)
        with Session(self.engine) as s:
            row = s.get(CaseRow, case.id) or CaseRow(id=case.id)
            row.operator, row.status, row.updated_at = case.operator, case.status.value, case.updated_at
            row.body = case.model_dump_json()
            s.add(row); s.commit()
        return case

    def get(self, case_id: str) -> Case:
        with Session(self.engine) as s:
            row = s.get(CaseRow, case_id)
            if not row:
                raise KeyError(case_id)
            return Case.model_validate_json(row.body)

    def list(self, status: str | None = None) -> list[dict]:
        with Session(self.engine) as s:
            q = select(CaseRow.id, CaseRow.operator, CaseRow.status, CaseRow.updated_at).order_by(CaseRow.updated_at.desc())
            if status:
                q = q.where(CaseRow.status == status)
            return [dict(id=r[0], operator=r[1], status=r[2], updated_at=r[3].isoformat()) for r in s.execute(q)]
