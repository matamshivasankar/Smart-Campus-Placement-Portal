"""SQLAlchemy models for the Smart Campus Placement Portal.

Everything the application shows is derived from these tables: there are no
hard-coded statistics or mock records anywhere in the code base.
"""
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    """Naive UTC timestamp for portable SQLite/PostgreSQL DATETIME storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Enumerated values
# --------------------------------------------------------------------------
ROLE_STUDENT = "student"
ROLE_RECRUITER = "recruiter"
ROLE_ADMIN = "admin"
USER_ROLES = (ROLE_STUDENT, ROLE_RECRUITER, ROLE_ADMIN)

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_STATES = (APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED)

JOB_DRAFT = "draft"
JOB_PENDING = "pending"
JOB_APPROVED = "approved"
JOB_REJECTED = "rejected"
JOB_CLOSED = "closed"
JOB_STATES = (JOB_DRAFT, JOB_PENDING, JOB_APPROVED, JOB_REJECTED, JOB_CLOSED)

# Application statuses -------------------------------------------------------
APP_APPLIED = "Applied"
APP_SHORTLISTED = "Shortlisted"
APP_INTERVIEW = "Interview Scheduled"
APP_SELECTED = "Selected"
APP_REJECTED = "Rejected"
APP_WITHDRAWN = "Withdrawn"

APPLICATION_STATUSES = (
    APP_APPLIED,
    APP_SHORTLISTED,
    APP_INTERVIEW,
    APP_SELECTED,
    APP_REJECTED,
    APP_WITHDRAWN,
)
ACTIVE_APPLICATION_STATUSES = (APP_APPLIED, APP_SHORTLISTED, APP_INTERVIEW)
FINAL_APPLICATION_STATUSES = (APP_SELECTED, APP_REJECTED, APP_WITHDRAWN)

# Recruiter driven transitions.  Student withdrawal is handled separately.
APPLICATION_TRANSITIONS = {
    APP_APPLIED: (APP_SHORTLISTED, APP_REJECTED),
    APP_SHORTLISTED: (APP_INTERVIEW, APP_REJECTED),
    APP_INTERVIEW: (APP_SELECTED, APP_REJECTED),
    APP_SELECTED: (),
    APP_REJECTED: (),
    APP_WITHDRAWN: (),
}
WITHDRAWABLE_STATUSES = (APP_APPLIED, APP_SHORTLISTED, APP_INTERVIEW)

# Interview states -----------------------------------------------------------
INTERVIEW_SCHEDULED = "Scheduled"
INTERVIEW_COMPLETED = "Completed"
INTERVIEW_CANCELLED = "Cancelled"
INTERVIEW_STATUSES = (INTERVIEW_SCHEDULED, INTERVIEW_COMPLETED, INTERVIEW_CANCELLED)

INTERVIEW_ONLINE = "Online"
INTERVIEW_OFFLINE = "In person"
INTERVIEW_MODES = (INTERVIEW_ONLINE, INTERVIEW_OFFLINE)

INTERVIEW_RESULT_PENDING = "Pending"
INTERVIEW_RESULT_PASS = "Pass"
INTERVIEW_RESULT_FAIL = "Fail"
INTERVIEW_RESULTS = (INTERVIEW_RESULT_PENDING, INTERVIEW_RESULT_PASS, INTERVIEW_RESULT_FAIL)


def enum_col(*values: str, name: str, default: str | None = None):
    """VARCHAR + CHECK backed enum so the same DDL shape works on SQLite/PostgreSQL."""
    return db.Column(
        db.Enum(*values, name=name, native_enum=False, validate_strings=True),
        nullable=False,
        default=default or values[0],
    )


# --------------------------------------------------------------------------
# Core tables
# --------------------------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = enum_col(*USER_ROLES, name="user_role")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    student_profile = db.relationship(
        "StudentProfile", back_populates="user", uselist=False,
        cascade="all, delete-orphan",
    )
    recruiter_profile = db.relationship(
        "RecruiterProfile", back_populates="user", uselist=False,
        cascade="all, delete-orphan", foreign_keys="RecruiterProfile.user_id",
    )
    notifications = db.relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan",
        order_by="Notification.created_at.desc()",
    )

    # -- password helpers -------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    # -- convenience ------------------------------------------------------
    @property
    def display_name(self) -> str:
        if self.role == ROLE_STUDENT and self.student_profile:
            return self.student_profile.full_name
        if self.role == ROLE_RECRUITER and self.recruiter_profile:
            return self.recruiter_profile.full_name
        return self.email

    @property
    def is_student(self) -> bool:
        return self.role == ROLE_STUDENT

    @property
    def is_recruiter(self) -> bool:
        return self.role == ROLE_RECRUITER

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.id} {self.email} {self.role}>"


class StudentProfile(db.Model):
    __tablename__ = "student_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    full_name = db.Column(db.String(150), nullable=False)
    roll_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    department = db.Column(db.String(120), nullable=False)
    degree = db.Column(db.String(120), nullable=False)
    cgpa = db.Column(db.Numeric(4, 2), nullable=True)
    graduation_year = db.Column(db.Integer, nullable=True, index=True)
    phone = db.Column(db.String(20), nullable=True)
    active_backlogs = db.Column(db.Integer, nullable=False, default=0)
    about = db.Column(db.Text, nullable=True)
    linkedin_url = db.Column(db.String(255), nullable=True)
    github_url = db.Column(db.String(255), nullable=True)
    resume_filename = db.Column(db.String(255), nullable=True)
    resume_storage = db.Column(db.String(20), nullable=False, default="local")
    resume_original_name = db.Column(db.String(255), nullable=True)
    resume_uploaded_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="student_profile")
    skills = db.relationship(
        "StudentSkill", back_populates="student", cascade="all, delete-orphan",
        order_by="StudentSkill.skill",
    )
    applications = db.relationship(
        "Application", back_populates="student", cascade="all, delete-orphan",
    )

    @property
    def skill_names(self) -> list[str]:
        return [s.skill for s in self.skills]

    @property
    def has_resume(self) -> bool:
        return bool(self.resume_filename)

    @property
    def is_complete(self) -> bool:
        return all([
            self.full_name, self.roll_number, self.department,
            self.degree, self.cgpa is not None, self.graduation_year,
        ])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StudentProfile {self.id} {self.roll_number}>"


class StudentSkill(db.Model):
    __tablename__ = "student_skills"
    __table_args__ = (
        db.UniqueConstraint("student_id", "skill", name="uq_student_skill"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    skill = db.Column(db.String(80), nullable=False)

    student = db.relationship("StudentProfile", back_populates="skills")


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True, index=True)
    website = db.Column(db.String(255), nullable=True)
    industry = db.Column(db.String(120), nullable=True)
    location = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    jobs = db.relationship("Job", back_populates="company", cascade="all, delete-orphan")
    recruiters = db.relationship("RecruiterProfile", back_populates="company")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company {self.id} {self.name}>"


class RecruiterProfile(db.Model):
    __tablename__ = "recruiter_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    full_name = db.Column(db.String(150), nullable=False)
    designation = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    company_id = db.Column(
        db.Integer, db.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True,
    )
    approval_status = enum_col(
        *APPROVAL_STATES, name="approval_status", default=APPROVAL_PENDING,
    )
    rejection_reason = db.Column(db.String(500), nullable=True)
    approved_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship("User", back_populates="recruiter_profile", foreign_keys=[user_id])
    company = db.relationship("Company", back_populates="recruiters")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    jobs = db.relationship("Job", back_populates="recruiter", cascade="all, delete-orphan")

    @property
    def is_approved(self) -> bool:
        return self.approval_status == APPROVAL_APPROVED

    @property
    def can_post_jobs(self) -> bool:
        return self.is_approved and self.company_id is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RecruiterProfile {self.id} {self.approval_status}>"


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(
        db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    recruiter_id = db.Column(
        db.Integer, db.ForeignKey("recruiter_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    responsibilities = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(150), nullable=False)
    employment_type = db.Column(db.String(50), nullable=False, default="Full time")
    salary_min = db.Column(db.Numeric(12, 2), nullable=True)
    salary_max = db.Column(db.Numeric(12, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=False, default="INR")
    openings = db.Column(db.Integer, nullable=False, default=1)

    # Eligibility criteria -------------------------------------------------
    min_cgpa = db.Column(db.Numeric(4, 2), nullable=True)
    eligible_graduation_year = db.Column(db.Integer, nullable=True, index=True)
    required_departments = db.Column(db.String(500), nullable=True)
    max_backlogs = db.Column(db.Integer, nullable=True)

    deadline = db.Column(db.Date, nullable=False, index=True)
    status = enum_col(*JOB_STATES, name="job_status", default=JOB_PENDING)
    approval_status = enum_col(*APPROVAL_STATES, name="job_approval_status")
    approved_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    approved_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.String(500), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    company = db.relationship("Company", back_populates="jobs")
    recruiter = db.relationship("RecruiterProfile", back_populates="jobs")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    required_skills = db.relationship(
        "JobRequiredSkill", back_populates="job", cascade="all, delete-orphan",
        order_by="JobRequiredSkill.skill",
    )
    applications = db.relationship(
        "Application", back_populates="job", cascade="all, delete-orphan",
    )

    # -- helpers ----------------------------------------------------------
    @property
    def skill_names(self) -> list[str]:
        return [s.skill for s in self.required_skills]

    @property
    def department_list(self) -> list[str]:
        if not self.required_departments:
            return []
        return [d.strip() for d in self.required_departments.split(",") if d.strip()]

    @property
    def is_open(self) -> bool:
        from datetime import date
        return (
            self.status == JOB_APPROVED
            and self.approval_status == APPROVAL_APPROVED
            and self.deadline >= date.today()
        )

    @property
    def is_expired(self) -> bool:
        from datetime import date
        return self.deadline < date.today()

    @property
    def salary_display(self) -> str:
        if self.salary_min is None and self.salary_max is None:
            return "Not disclosed"
        lo = f"{self.salary_min:,.0f}" if self.salary_min is not None else "?"
        hi = f"{self.salary_max:,.0f}" if self.salary_max is not None else "?"
        return f"{self.currency} {lo} - {hi} per annum"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job {self.id} {self.title}>"


class JobRequiredSkill(db.Model):
    __tablename__ = "job_required_skills"
    __table_args__ = (
        db.UniqueConstraint("job_id", "skill", name="uq_job_skill"),
    )

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    skill = db.Column(db.String(80), nullable=False)

    job = db.relationship("Job", back_populates="required_skills")


class Application(db.Model):
    __tablename__ = "applications"
    __table_args__ = (
        db.UniqueConstraint("job_id", "student_id", name="uq_application_job_student"),
    )

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status = enum_col(*APPLICATION_STATUSES, name="application_status", default=APP_APPLIED)
    cover_letter = db.Column(db.Text, nullable=True)
    status_updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    applied_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    job = db.relationship("Job", back_populates="applications")
    student = db.relationship("StudentProfile", back_populates="applications")
    interviews = db.relationship(
        "Interview", back_populates="application", cascade="all, delete-orphan",
        order_by="Interview.scheduled_at",
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_APPLICATION_STATUSES

    @property
    def next_interview(self):
        upcoming = [i for i in self.interviews if i.status == INTERVIEW_SCHEDULED]
        return upcoming[0] if upcoming else None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application {self.id} job={self.job_id} student={self.student_id} {self.status}>"


class Interview(db.Model):
    __tablename__ = "interviews"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer, db.ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    round_number = db.Column(db.Integer, nullable=False, default=1)
    round_name = db.Column(db.String(120), nullable=False, default="Technical Round")
    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=45)
    mode = enum_col(*INTERVIEW_MODES, name="interview_mode", default=INTERVIEW_ONLINE)
    venue = db.Column(db.String(255), nullable=True)
    meeting_link = db.Column(db.String(500), nullable=True)
    interviewer_name = db.Column(db.String(150), nullable=True)
    status = enum_col(*INTERVIEW_STATUSES, name="interview_status", default=INTERVIEW_SCHEDULED)
    result = enum_col(*INTERVIEW_RESULTS, name="interview_result", default=INTERVIEW_RESULT_PENDING)
    feedback = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    application = db.relationship("Application", back_populates="interviews")
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    @property
    def location_display(self) -> str:
        if self.mode == INTERVIEW_ONLINE:
            return self.meeting_link or "Online - link to be shared"
        return self.venue or "Venue to be confirmed"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Interview {self.id} app={self.application_id} round={self.round_number}>"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    user = db.relationship("User", back_populates="notifications")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Notification {self.id} user={self.user_id}>"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    actor_role = db.Column(db.String(20), nullable=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=True, index=True)
    details = db.Column(db.String(1000), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    actor = db.relationship("User", foreign_keys=[actor_user_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.id} {self.action} {self.entity_type}:{self.entity_id}>"
