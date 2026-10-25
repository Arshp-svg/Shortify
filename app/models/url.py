"""SQLAlchemy URL entity model."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class URL(Base):
    """URL mapping entity representing a shortened link and its metadata."""

    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    short_code: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
    )
    original_url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    click_count: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    __table_args__ = (
        Index("ix_urls_active_expires_at", "active", "expires_at"),
    )

    @property
    def is_expired(self) -> bool:
        """Evaluate if the URL is expired relative to current UTC time."""
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry <= now
