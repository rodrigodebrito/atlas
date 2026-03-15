import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, SmallInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance_engine.database import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    notification_hour: Mapped[int] = mapped_column(SmallInteger, default=20)
    notification_timezone: Mapped[str] = mapped_column(String(50), default="America/Sao_Paulo")
    weekly_checkin_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    anomaly_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    budget_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(10), default="pt-BR")
    plan: Mapped[str] = mapped_column(String(20), default="free")  # free | pro | mei
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="preferences")
