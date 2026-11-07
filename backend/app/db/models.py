"""SQLAlchemy models (design §2).

Catalog, normalized the way the PDF is shaped:
  catalog_tables (7)  one row per source table: enclosure, power supply, certifications, markings
  parts (68)          one row per Base Part Number: electrical data (speed, current, power)
  ratings (111)       one row per part and service: torque, duty cycle, cycles/starts per hour

Conversations: sessions + messages (payload = what the user saw, debug = what the agent did).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CatalogTable(Base):
    __tablename__ = "catalog_tables"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    page: Mapped[int] = mapped_column(Integer)
    enclosure: Mapped[str] = mapped_column(String(20), index=True)  # weatherproof|explosionproof
    voltage: Mapped[int] = mapped_column(Integer)  # 24 | 110 | 220
    phase: Mapped[str | None] = mapped_column(String(10))  # single | three | None (24V)
    current_type: Mapped[str] = mapped_column(String(10))  # ac | dc | ac_dc
    frequency_dependent: Mapped[bool] = mapped_column(Boolean)
    service_split: Mapped[bool] = mapped_column(Boolean)  # False: 3-phase, one rating (D-1)
    layout: Mapped[str] = mapped_column(String(20))
    certifications: Mapped[list[str]] = mapped_column(ARRAY(String(10)))
    markings: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # Structured hazardous-area markings (D-2b), null for weatherproof. Small fixed shape, read
    # whole, never queried by key: JSONB keeps it in one place.
    hazardous: Mapped[dict | None] = mapped_column(JSONB)
    summary_claim: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    footnotes: Mapped[list[str]] = mapped_column(ARRAY(Text))

    parts: Mapped[list["Part"]] = relationship(back_populates="table")


class Part(Base):
    __tablename__ = "parts"

    part_number: Mapped[str] = mapped_column(String(32), primary_key=True)
    match_key: Mapped[str] = mapped_column(String(32), unique=True)  # for matching user input
    model_code: Mapped[str] = mapped_column(String(8), index=True)  # e.g. 763B
    size: Mapped[int] = mapped_column(Integer)
    table_code: Mapped[str] = mapped_column(ForeignKey("catalog_tables.code"), index=True)
    data_available: Mapped[bool] = mapped_column(Boolean)  # False for N/A rows (D-6)
    csa_certified: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer)  # row order in the PDF table
    motor_power_w: Mapped[float | None] = mapped_column(Float)
    speed_s_60hz: Mapped[float | None] = mapped_column(Float)
    speed_s_50hz: Mapped[float | None] = mapped_column(Float)
    fla_a_60hz: Mapped[float | None] = mapped_column(Float)
    fla_a_50hz: Mapped[float | None] = mapped_column(Float)
    lra_a_60hz: Mapped[float | None] = mapped_column(Float)
    lra_a_50hz: Mapped[float | None] = mapped_column(Float)

    table: Mapped[CatalogTable] = relationship(back_populates="parts")
    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="part", cascade="all, delete-orphan", order_by="Rating.id"
    )


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("part_number", "service"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_number: Mapped[str] = mapped_column(ForeignKey("parts.part_number", ondelete="CASCADE"))
    service: Mapped[str] = mapped_column(String(12))  # on_off | modulating | both
    torque_inlb: Mapped[float] = mapped_column(Float)
    torque_nm: Mapped[float] = mapped_column(Float)
    duty_cycle_pct: Mapped[float] = mapped_column(Float)
    cycles_per_hour: Mapped[float | None] = mapped_column(Float)
    starts_per_hour: Mapped[float | None] = mapped_column(Float)

    part: Mapped[Part] = relationship(back_populates="ratings")


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)  # login-ready (C6)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, index=True
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)  # status, view, products snapshot, ...
    debug: Mapped[dict | None] = mapped_column(JSONB)  # tool calls, tokens, model, checks
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
