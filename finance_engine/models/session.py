import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
import enum

from finance_engine.database import Base


class SessionState(str, enum.Enum):
    IDLE = "idle"
    AWAITING_CATEGORY = "awaiting_category"
    AWAITING_AMOUNT = "awaiting_amount"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ONBOARDING = "onboarding"


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    state: Mapped[SessionState] = mapped_column(SAEnum(SessionState), default=SessionState.IDLE)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
