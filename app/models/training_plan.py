"""SQLAlchemy 2.0 async-compatible models for the Training Plans module."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Generic, Optional, TypeVar

from app.schemas.training_plan import PlanArchetype, PlanStatus, SessionBlockType, SessionStatus

T = TypeVar("T")

try:
    from sqlalchemy import Boolean, Date, ForeignKey, Integer, JSON, String, Text, Uuid
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

    SQLALCHEMY_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - lightweight fallback when SQLAlchemy is absent locally
    SQLALCHEMY_AVAILABLE = False

    class Mapped(Generic[T]):  # type: ignore[no-redef]
        pass

    class _ColumnSpec:
        def __init__(self, default: Any = None, nullable: bool = True, primary_key: bool = False):
            self.default = default
            self.nullable = nullable
            self.primary_key = primary_key

    class _RelationshipSpec:
        def __init__(self, target: str, back_populates: Optional[str] = None, **kwargs: Any):
            self.target = target
            self.back_populates = back_populates
            self.kwargs = kwargs

    def mapped_column(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        return _ColumnSpec(
            default=kwargs.get("default"),
            nullable=kwargs.get("nullable", True),
            primary_key=kwargs.get("primary_key", False),
        )

    def relationship(target: str, **kwargs: Any) -> Any:  # type: ignore[misc]
        return _RelationshipSpec(target, **kwargs)

    def ForeignKey(target: str, **kwargs: Any) -> str:  # noqa: N802
        return target

    def String(length: int = 255) -> type:  # noqa: N802
        return str

    def Integer() -> type:  # noqa: N802
        return int

    def Boolean() -> type:  # noqa: N802
        return bool

    def Text() -> type:  # noqa: N802
        return str

    def Date() -> type:  # noqa: N802
        return date

    def JSON() -> type:  # noqa: N802
        return dict

    def Uuid(as_uuid: bool = True) -> type:  # noqa: N802
        return uuid.UUID

    class _Metadata:
        def __init__(self) -> None:
            self.tables: dict[str, Any] = {}

    class _DeclarativeMeta(type):
        def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
            col_specs: dict[str, _ColumnSpec] = {}
            rel_specs: dict[str, _RelationshipSpec] = {}
            for k, v in list(namespace.items()):
                if isinstance(v, _ColumnSpec):
                    col_specs[k] = v
                elif isinstance(v, _RelationshipSpec):
                    rel_specs[k] = v
            namespace["_col_specs"] = col_specs
            namespace["_rel_specs"] = rel_specs
            cls = super().__new__(mcls, name, bases, namespace)
            tablename = namespace.get("__tablename__")
            if tablename and hasattr(cls, "metadata"):
                cls.metadata.tables[tablename] = cls
            return cls

    class DeclarativeBase(metaclass=_DeclarativeMeta):  # type: ignore[no-redef]
        metadata = _Metadata()

        def __init__(self, **kwargs: Any) -> None:
            annotations = {}
            for base in reversed(self.__class__.__mro__):
                annotations.update(getattr(base, "__annotations__", {}))
            for attr, spec in getattr(self.__class__, "_col_specs", {}).items():
                if attr in kwargs:
                    setattr(self, attr, kwargs.pop(attr))
                elif spec.default is not None:
                    val = spec.default() if callable(spec.default) else spec.default
                    setattr(self, attr, val)
                else:
                    setattr(self, attr, None)
            for attr, rspec in getattr(self.__class__, "_rel_specs", {}).items():
                if attr in kwargs:
                    setattr(self, attr, kwargs.pop(attr))
                else:
                    ann = str(annotations.get(attr, ""))
                    if "list[" in ann:
                        setattr(self, attr, [])
                    else:
                        setattr(self, attr, None)
            for k, v in kwargs.items():
                setattr(self, k, v)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy 2.0 Training Plans models."""

    pass


class DrillCatalog(Base):
    """Master catalog of technical, SPT, scored distance, and match-play archery drills."""

    __tablename__ = "drill_catalog"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    block_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    bow_divisions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    faults_addressed: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    min_distance_m: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    default_arrows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spt_hold_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spt_rest_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    requires_cv_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session_blocks: Mapped[list["SessionBlock"]] = relationship(
        "SessionBlock",
        back_populates="drill",
    )


class TrainingPlan(Base):
    """Macrocycle training plan for an athlete with baseline, goals, and recalibration state."""

    __tablename__ = "training_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    coach_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    primary_archetype: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=PlanArchetype.COMPETITION_PEAK.value,
    )
    secondary_archetype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=PlanStatus.ACTIVE.value,
        index=True,
    )
    baseline_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    goal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    recalibration_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recalibration_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    mesocycles: Mapped[list["TrainingMesocycle"]] = relationship(
        "TrainingMesocycle",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TrainingMesocycle.start_week",
        lazy="selectin",
    )
    microcycles: Mapped[list["TrainingMicrocycle"]] = relationship(
        "TrainingMicrocycle",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="TrainingMicrocycle.week_number",
        lazy="selectin",
    )


class TrainingMesocycle(Base):
    """Multi-week periodized training phase (e.g., Foundation, Specific Prep, Pre-Comp, Taper)."""

    __tablename__ = "training_mesocycles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase_name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_week: Mapped[int] = mapped_column(Integer, nullable=False)
    end_week: Mapped[int] = mapped_column(Integer, nullable=False)
    pillar_ratios_json: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)

    plan: Mapped["TrainingPlan"] = relationship("TrainingPlan", back_populates="mesocycles")
    microcycles: Mapped[list["TrainingMicrocycle"]] = relationship(
        "TrainingMicrocycle",
        back_populates="mesocycle",
        cascade="all, delete-orphan",
        order_by="TrainingMicrocycle.week_number",
        lazy="selectin",
    )


class TrainingMicrocycle(Base):
    """Single training week within a mesocycle adhering to the 15% cap and 3:1 deload laws."""

    __tablename__ = "training_microcycles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mesocycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_mesocycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    target_arrows: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_arrows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deload_week: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coach_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    plan: Mapped["TrainingPlan"] = relationship("TrainingPlan", back_populates="microcycles")
    mesocycle: Mapped["TrainingMesocycle"] = relationship(
        "TrainingMesocycle",
        back_populates="microcycles",
    )
    sessions: Mapped[list["TrainingSession"]] = relationship(
        "TrainingSession",
        back_populates="microcycle",
        cascade="all, delete-orphan",
        order_by="TrainingSession.scheduled_date",
        lazy="selectin",
    )


class TrainingSession(Base):
    """Single scheduled training day with RPE, anatomical pain flags, and ordered drill blocks."""

    __tablename__ = "training_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    microcycle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_microcycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    max_distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_mins: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=SessionStatus.SCHEDULED.value,
    )
    rpe_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pain_flags_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    microcycle: Mapped["TrainingMicrocycle"] = relationship(
        "TrainingMicrocycle",
        back_populates="sessions",
    )
    blocks: Mapped[list["SessionBlock"]] = relationship(
        "SessionBlock",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionBlock.block_order",
        lazy="selectin",
    )


class SessionBlock(Base):
    """Individual drill prescription inside a TrainingSession linked to scorecards and CV jobs."""

    __tablename__ = "session_blocks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drill_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("drill_catalog.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    block_order: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=SessionBlockType.TECHNICAL_BLANK_BALE.value,
    )
    prescribed_arrows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_arrows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    target_face_cm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    linked_scorecard_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True)
    linked_cv_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session: Mapped["TrainingSession"] = relationship("TrainingSession", back_populates="blocks")
    drill: Mapped["DrillCatalog"] = relationship(
        "DrillCatalog",
        back_populates="session_blocks",
        lazy="selectin",
    )
