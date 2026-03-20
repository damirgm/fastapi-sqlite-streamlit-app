"""
FastAPI backend for admissions monitoring dashboard (university).
- SQLite file DB (database.db) is created automatically.
- SQLModel gives us SQLAlchemy ORM + Pydantic validation with minimal code.
- Full CRUD for Applicants, Programs, Applications
- Filtering endpoint /applications + KPI metrics
- Status change log (traceability)
- Simple synthetic seed data (>=100 applications)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Mapped
from sqlmodel import SQLModel, Field, Relationship, Session, create_engine, select

from sqlalchemy.orm import Mapped


# ----------------------------
# Constants / "white lists"
# ----------------------------

DB_URL = "sqlite:///./database.db"

ALLOWED_SOURCES = {"site", "olymp", "aggregator", "other"}


class ApplicationStatus(str, Enum):
    new = "new"
    review = "review"
    enrolled = "enrolled"
    rejected = "rejected"


# ----------------------------
# DB Models (SQLModel)
# ----------------------------

class Applicant(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    fio: str
    birth_year: int
    region: str

    applications: Mapped[List["Application"]] = Relationship(back_populates="applicant")


class Program(SQLModel, table=True):
    program_code: str = Field(primary_key=True)  # e.g. "CS-01"
    program_name: str
    faculty: str

    applications: Mapped[List["Application"]] = Relationship(back_populates="program")


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    applicant_id: int = Field(foreign_key="applicant.id", index=True)
    program_code: str = Field(foreign_key="program.program_code", index=True)

    wave: int = Field(default=1, ge=1)
    source: str = Field(index=True)
    status: ApplicationStatus = Field(default=ApplicationStatus.new, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    status_changed_at: datetime = Field(default_factory=datetime.utcnow)

    # relationships
    applicant: Mapped[Optional["Applicant"]] = Relationship(back_populates="applications")
    program: Mapped[Optional["Program"]] = Relationship(back_populates="applications")


class StatusLog(SQLModel, table=True):
    """
    Traceability: log each status change:
    - when it happened
    - who did it (in this учебный прототип: username is just a string from request body)
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="application.id", index=True)
    old_status: str
    new_status: str
    changed_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    username: str = Field(default="system")


# ----------------------------
# Pydantic/SQLModel Schemas
# (separate input/output models)
# ----------------------------

class ApplicantCreate(SQLModel):
    fio: str
    birth_year: int
    region: str


class ApplicantRead(SQLModel):
    id: int
    fio: str
    birth_year: int
    region: str


class ProgramCreate(SQLModel):
    program_code: str
    program_name: str
    faculty: str


class ProgramRead(SQLModel):
    program_code: str
    program_name: str
    faculty: str


class ApplicationCreate(SQLModel):
    applicant_id: int
    program_code: str
    wave: int = 1
    source: str
    status: ApplicationStatus = ApplicationStatus.new
    created_at: Optional[datetime] = None
    status_changed_at: Optional[datetime] = None


class ApplicationUpdate(SQLModel):
    # optional fields for PATCH-like update
    applicant_id: Optional[int] = None
    program_code: Optional[str] = None
    wave: Optional[int] = None
    source: Optional[str] = None
    status: Optional[ApplicationStatus] = None
    created_at: Optional[datetime] = None
    status_changed_at: Optional[datetime] = None
    username: Optional[str] = "ui_user"  # who changes status (traceability)


class ApplicationRead(SQLModel):
    id: int
    applicant_id: int
    program_code: str
    wave: int
    source: str
    status: ApplicationStatus
    created_at: datetime
    status_changed_at: datetime


class ApplicationReadExpanded(ApplicationRead):
    applicant: Optional[ApplicantRead] = None
    program: Optional[ProgramRead] = None


class Metrics(SQLModel):
    applications: int
    enrolled: int
    conversion: float


# ----------------------------
# Engine + session dependency
# ----------------------------

engine = create_engine(DB_URL, echo=False)


def get_session():
    """
    FastAPI dependency.
    Why Depends(Session)?
    - It ensures a DB session per request.
    - Session is closed automatically after response.
    """
    with Session(engine) as session:
        yield session


# ----------------------------
# Validation helpers (>= 5 validations)
# ----------------------------

def validate_application_payload(
    session: Session,
    applicant_id: int,
    program_code: str,
    source: str,
    created_at: datetime,
    status_changed_at: datetime,
):
    # (1) program_code not empty
    if not program_code or not program_code.strip():
        raise HTTPException(status_code=422, detail="program_code must not be empty")

    # (2) source must be in whitelist
    if source not in ALLOWED_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {sorted(ALLOWED_SOURCES)}"
        )

    # (3) created_at <= status_changed_at
    if created_at > status_changed_at:
        raise HTTPException(status_code=422, detail="created_at must be <= status_changed_at")

    # (4) FK applicant_id exists
    applicant = session.get(Applicant, applicant_id)
    if not applicant:
        raise HTTPException(status_code=422, detail="applicant_id does not exist")

    # (5) FK program_code exists
    program = session.get(Program, program_code)
    if not program:
        raise HTTPException(status_code=422, detail="program_code does not exist")


def auto_policy_on_enroll(session: Session, enrolled_app: Application):
    """
    Business rule (simplified demo):
    If an applicant becomes enrolled in one program,
    then all other their applications with status new/review become rejected (auto снятие).
    This is just a prototype policy (can be changed).
    """
    if enrolled_app.status != ApplicationStatus.enrolled:
        return

    q = select(Application).where(
        Application.applicant_id == enrolled_app.applicant_id,
        Application.id != enrolled_app.id,
        Application.status.in_([ApplicationStatus.new, ApplicationStatus.review]),
    )
    others = session.exec(q).all()
    now = datetime.utcnow()

    for app in others:
        old = app.status
        app.status = ApplicationStatus.rejected
        app.status_changed_at = now
        session.add(StatusLog(
            application_id=app.id,
            old_status=str(old),
            new_status=str(app.status),
            changed_at=now,
            username="policy:auto_on_enroll"
        ))


# ----------------------------
# App init + DB init/seed
# ----------------------------

app = FastAPI(title="Admissions Monitoring API (Demo)")


@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)


def seed_if_empty(session: Session):
    # Create minimal synthetic dataset only once
    any_applicant = session.exec(select(Applicant).limit(1)).first()
    if any_applicant:
        return

    # programs
    programs = [
        Program(program_code="CS-01", program_name="Computer Science", faculty="IT"),
        Program(program_code="DS-01", program_name="Data Science", faculty="IT"),
        Program(program_code="LAW-01", program_name="Law", faculty="Law"),
        Program(program_code="ECO-01", program_name="Economics", faculty="Business"),
    ]
    session.add_all(programs)

    # applicants (>= 20)
    regions = ["Moscow", "SPb", "Kazan", "Novosibirsk", "Other"]
    for i in range(1, 21):
        session.add(Applicant(
            fio=f"Абитуриент {i}",
            birth_year=2004 + (i % 4),
            region=regions[i % len(regions)]
        ))
    session.commit()

    applicants = session.exec(select(Applicant)).all()
    program_codes = [p.program_code for p in programs]
    sources = ["site", "olymp", "aggregator", "other"]
    statuses = [ApplicationStatus.new, ApplicationStatus.review, ApplicationStatus.enrolled, ApplicationStatus.rejected]

    # applications (>=100)
    base = datetime.utcnow() - timedelta(days=60)
    apps: List[Application] = []
    for i in range(1, 121):
        a = applicants[i % len(applicants)]
        program_code = program_codes[i % len(program_codes)]
        wave = 1 if i % 3 else 2
        source = sources[i % len(sources)]
        status = statuses[i % len(statuses)]
        created_at = base + timedelta(days=i % 50)
        status_changed_at = created_at + timedelta(hours=(i % 48))
        apps.append(Application(
            applicant_id=a.id,
            program_code=program_code,
            wave=wave,
            source=source,
            status=status,
            created_at=created_at,
            status_changed_at=status_changed_at,
        ))
    session.add_all(apps)
    session.commit()


# ----------------------------
# CRUD: Applicants
# ----------------------------

@app.post("/applicants", response_model=ApplicantRead)
def create_applicant(payload: ApplicantCreate, session: Session = Depends(get_session)):
    applicant = Applicant.model_validate(payload)
    session.add(applicant)
    session.commit()
    session.refresh(applicant)
    return applicant


@app.get("/applicants", response_model=List[ApplicantRead])
def list_applicants(session: Session = Depends(get_session)):
    return session.exec(select(Applicant).order_by(Applicant.id)).all()


@app.get("/applicants/{applicant_id}", response_model=ApplicantRead)
def get_applicant(applicant_id: int, session: Session = Depends(get_session)):
    obj = session.get(Applicant, applicant_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Applicant not found")
    return obj


@app.delete("/applicants/{applicant_id}")
def delete_applicant(applicant_id: int, session: Session = Depends(get_session)):
    obj = session.get(Applicant, applicant_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Applicant not found")
    session.delete(obj)
    session.commit()
    return {"ok": True}


# ----------------------------
# CRUD: Programs
# ----------------------------

@app.post("/programs", response_model=ProgramRead)
def create_program(payload: ProgramCreate, session: Session = Depends(get_session)):
    if not payload.program_code or not payload.program_code.strip():
        raise HTTPException(status_code=422, detail="program_code must not be empty")

    existing = session.get(Program, payload.program_code)
    if existing:
        raise HTTPException(status_code=409, detail="Program with this code already exists")

    program = Program.model_validate(payload)
    session.add(program)
    session.commit()
    return program


@app.get("/programs", response_model=List[ProgramRead])
def list_programs(session: Session = Depends(get_session)):
    return session.exec(select(Program).order_by(Program.program_code)).all()


@app.get("/programs/{program_code}", response_model=ProgramRead)
def get_program(program_code: str, session: Session = Depends(get_session)):
    obj = session.get(Program, program_code)
    if not obj:
        raise HTTPException(status_code=404, detail="Program not found")
    return obj


@app.delete("/programs/{program_code}")
def delete_program(program_code: str, session: Session = Depends(get_session)):
    obj = session.get(Program, program_code)
    if not obj:
        raise HTTPException(status_code=404, detail="Program not found")
    session.delete(obj)
    session.commit()
    return {"ok": True}


# ----------------------------
# CRUD: Applications
# ----------------------------

@app.post("/applications", response_model=ApplicationRead)
def create_application(payload: ApplicationCreate, session: Session = Depends(get_session)):
    created_at = payload.created_at or datetime.utcnow()
    status_changed_at = payload.status_changed_at or created_at

    validate_application_payload(
        session=session,
        applicant_id=payload.applicant_id,
        program_code=payload.program_code,
        source=payload.source,
        created_at=created_at,
        status_changed_at=status_changed_at,
    )

    app_obj = Application(
        applicant_id=payload.applicant_id,
        program_code=payload.program_code,
        wave=payload.wave,
        source=payload.source,
        status=payload.status,
        created_at=created_at,
        status_changed_at=status_changed_at,
    )
    session.add(app_obj)
    session.commit()
    session.refresh(app_obj)

    # if created already enrolled -> apply policy
    auto_policy_on_enroll(session, app_obj)
    session.commit()

    return app_obj


@app.get("/applications", response_model=List[ApplicationReadExpanded])
def list_applications(
    session: Session = Depends(get_session),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    program: Optional[str] = None,
    source: Optional[str] = None,
    wave: Optional[int] = None,
    status: Optional[ApplicationStatus] = None,
    include_related: bool = True,
):
    """
    JSON-contract (mock endpoint requested in task):
    /applications?from=&to=&program=&source=
    + additional filters wave/status for convenience.
    """
    q = select(Application)

    if date_from:
        q = q.where(Application.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(Application.created_at <= datetime.combine(date_to, datetime.max.time()))
    if program:
        q = q.where(Application.program_code == program)
    if source:
        q = q.where(Application.source == source)
    if wave:
        q = q.where(Application.wave == wave)
    if status:
        q = q.where(Application.status == status)

    q = q.order_by(Application.created_at.desc())
    apps = session.exec(q).all()

    if not include_related:
        return apps  # type: ignore[return-value]

    # Expand related objects (simple & clear for beginners; ok for small datasets)
    result: List[ApplicationReadExpanded] = []
    for a in apps:
        applicant = session.get(Applicant, a.applicant_id)
        program_obj = session.get(Program, a.program_code)
        result.append(ApplicationReadExpanded(
            **a.model_dump(),
            applicant=ApplicantRead.model_validate(applicant) if applicant else None,
            program=ProgramRead.model_validate(program_obj) if program_obj else None,
        ))
    return result


@app.get("/applications/{application_id}", response_model=ApplicationReadExpanded)
def get_application(application_id: int, session: Session = Depends(get_session)):
    a = session.get(Application, application_id)
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")

    applicant = session.get(Applicant, a.applicant_id)
    program_obj = session.get(Program, a.program_code)
    return ApplicationReadExpanded(
        **a.model_dump(),
        applicant=ApplicantRead.model_validate(applicant) if applicant else None,
        program=ProgramRead.model_validate(program_obj) if program_obj else None,
    )


@app.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(application_id: int, payload: ApplicationUpdate, session: Session = Depends(get_session)):
    a = session.get(Application, application_id)
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")

    # Update fields if present
    data = payload.model_dump(exclude_unset=True)

    # Track status changes for logging
    old_status = a.status

    if "applicant_id" in data and data["applicant_id"] is not None:
        a.applicant_id = int(data["applicant_id"])
    if "program_code" in data and data["program_code"] is not None:
        a.program_code = str(data["program_code"])
    if "wave" in data and data["wave"] is not None:
        a.wave = int(data["wave"])
    if "source" in data and data["source"] is not None:
        a.source = str(data["source"])
    if "status" in data and data["status"] is not None:
        a.status = data["status"]
    if "created_at" in data and data["created_at"] is not None:
        a.created_at = data["created_at"]
    if "status_changed_at" in data and data["status_changed_at"] is not None:
        a.status_changed_at = data["status_changed_at"]

    # If status changed but status_changed_at not provided, update it automatically
    if a.status != old_status and "status_changed_at" not in data:
        a.status_changed_at = datetime.utcnow()

    validate_application_payload(
        session=session,
        applicant_id=a.applicant_id,
        program_code=a.program_code,
        source=a.source,
        created_at=a.created_at,
        status_changed_at=a.status_changed_at,
    )

    # Write status log if needed
    if a.status != old_status:
        session.add(StatusLog(
            application_id=a.id,
            old_status=str(old_status),
            new_status=str(a.status),
            changed_at=a.status_changed_at,
            username=(payload.username or "ui_user"),
        ))

    session.add(a)
    session.commit()
    session.refresh(a)

    # apply enroll policy if became enrolled
    auto_policy_on_enroll(session, a)
    session.commit()

    return a


@app.delete("/applications/{application_id}")
def delete_application(application_id: int, session: Session = Depends(get_session)):
    a = session.get(Application, application_id)
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")
    session.delete(a)
    session.commit()
    return {"ok": True}


# ----------------------------
# Metrics + CSV export
# ----------------------------

def _apply_filters_to_query(
    q,
    date_from: Optional[date],
    date_to: Optional[date],
    program: Optional[str],
    source: Optional[str],
    wave: Optional[int],
):
    if date_from:
        q = q.where(Application.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.where(Application.created_at <= datetime.combine(date_to, datetime.max.time()))
    if program:
        q = q.where(Application.program_code == program)
    if source:
        q = q.where(Application.source == source)
    if wave:
        q = q.where(Application.wave == wave)
    return q


@app.get("/metrics", response_model=Metrics)
def get_metrics(
    session: Session = Depends(get_session),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    program: Optional[str] = None,
    source: Optional[str] = None,
    wave: Optional[int] = None,
):
    q_all = _apply_filters_to_query(select(Application), date_from, date_to, program, source, wave)
    all_apps = session.exec(q_all).all()
    total = len(all_apps)

    q_enrolled = _apply_filters_to_query(
        select(Application).where(Application.status == ApplicationStatus.enrolled),
        date_from, date_to, program, source, wave
    )
    enrolled = len(session.exec(q_enrolled).all())

    conversion = (enrolled / total) if total else 0.0
    return Metrics(applications=total, enrolled=enrolled, conversion=round(conversion, 4))


@app.get("/report.csv", response_class=PlainTextResponse)
def export_csv_report(
    session: Session = Depends(get_session),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    program: Optional[str] = None,
    source: Optional[str] = None,
):
    """
    Export aggregated report:
    period, program, source, applications, enrolled, conversion

    period here is "from..to" string (demo). In real system you'd likely use day/week buckets.
    """
    q = select(Application)
    q = _apply_filters_to_query(q, date_from, date_to, program, source, wave=None)
    apps = session.exec(q).all()

    # group by (program_code, source)
    grouped: Dict[tuple, Dict[str, Any]] = {}
    for a in apps:
        key = (a.program_code, a.source)
        if key not in grouped:
            grouped[key] = {"applications": 0, "enrolled": 0}
        grouped[key]["applications"] += 1
        if a.status == ApplicationStatus.enrolled:
            grouped[key]["enrolled"] += 1

    period_str = f"{date_from or ''}..{date_to or ''}"

    lines = ["period,program,source,applications,enrolled,conversion"]
    for (p, s), vals in sorted(grouped.items()):
        total = vals["applications"]
        enrolled = vals["enrolled"]
        conv = (enrolled / total) if total else 0.0
        lines.append(f"{period_str},{p},{s},{total},{enrolled},{conv:.4f}")

    return "\n".join(lines)


@app.get("/status_logs", response_model=List[dict])
def list_status_logs(
    session: Session = Depends(get_session),
    application_id: Optional[int] = None,
):
    q = select(StatusLog)
    if application_id:
        q = q.where(StatusLog.application_id == application_id)
    q = q.order_by(StatusLog.changed_at.desc())
    logs = session.exec(q).all()
    # Keep it simple (return dicts)
    return [l.model_dump() for l in logs]
