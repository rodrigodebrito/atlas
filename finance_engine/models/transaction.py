import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, func, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from finance_engine.database import Base


class TransactionType(str, enum.Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"


class PaymentMethod(str, enum.Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    PIX = "PIX"
    CASH = "CASH"
    TED = "TED"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="BRL")
    category: Mapped[str] = mapped_column(String(50), index=True)
    category_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    merchant: Mapped[str | None] = mapped_column(String(100))
    payment_method: Mapped[PaymentMethod | None] = mapped_column(SAEnum(PaymentMethod))
    notes: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="transactions")
