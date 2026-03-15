import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Float, func
from sqlalchemy.orm import Mapped, mapped_column

from finance_engine.database import Base


class MonthlySnapshot(Base):
    __tablename__ = "monthly_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # "2026-03"
    total_income_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_expense_cents: Mapped[int] = mapped_column(Integer, default=0)
    savings_rate: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_grade: Mapped[str] = mapped_column(String(2), default="C")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
