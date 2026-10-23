"""Deterministic eligibility engine.

Every result is recalculated from the stored student profile and the stored job
record using plain Python conditionals and database data.  No machine learning,
scoring heuristics or external services are involved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

CRITERION_PROFILE = "Profile completeness"
CRITERION_JOB_OPEN = "Job availability"
CRITERION_CGPA = "Minimum CGPA"
CRITERION_SKILLS = "Required skills"
CRITERION_GRADUATION = "Graduation year"
CRITERION_DEPARTMENT = "Department / degree"
CRITERION_BACKLOGS = "Backlog limit"
CRITERION_DEADLINE = "Application deadline"
CRITERION_RESUME = "Resume on file"


@dataclass
class EligibilityCheck:
    criterion: str
    passed: bool
    detail: str


@dataclass
class EligibilityResult:
    eligible: bool
    checks: list[EligibilityCheck] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    applied: bool = False

    @property
    def failed_checks(self) -> list[EligibilityCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def passed_checks(self) -> list[EligibilityCheck]:
        return [c for c in self.checks if c.passed]

    @property
    def summary(self) -> str:
        if self.eligible:
            return "You meet every criterion configured for this job."
        return "; ".join(c.detail for c in self.failed_checks) or "Not eligible."


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise(text: str) -> str:
    return " ".join(str(text).lower().replace(".", " ").replace("-", " ").split())


def evaluate_eligibility(student, job, *, already_applied: bool = False) -> EligibilityResult:
    """Check one student profile against one job posting.

    ``student`` is a StudentProfile (or ``None`` for a user without a profile).
    ``job`` is a Job record.  The returned result lists one entry per evaluated
    criterion so the UI can explain exactly why a student is or is not eligible.
    """
    checks: list[EligibilityCheck] = []
    missing_skills: list[str] = []

    # 1. Student profile completeness ------------------------------------
    if student is None:
        checks.append(EligibilityCheck(
            CRITERION_PROFILE, False,
            "Create your student profile before applying.",
        ))
    else:
        missing_bits = []
        if student.cgpa is None:
            missing_bits.append("CGPA")
        if not student.graduation_year:
            missing_bits.append("graduation year")
        if not student.department:
            missing_bits.append("department")
        if not student.roll_number:
            missing_bits.append("roll number")
        if missing_bits:
            checks.append(EligibilityCheck(
                CRITERION_PROFILE, False,
                "Complete your profile: missing " + ", ".join(missing_bits) + ".",
            ))
        else:
            checks.append(EligibilityCheck(
                CRITERION_PROFILE, True, "Your profile is complete."
            ))

    # 2. Job availability -------------------------------------------------
    if job.status != "approved" or job.approval_status != "approved":
        checks.append(EligibilityCheck(
            CRITERION_JOB_OPEN, False,
            "This job posting is not open for applications yet.",
        ))
    elif job.status == "closed":
        checks.append(EligibilityCheck(
            CRITERION_JOB_OPEN, False, "This job posting has been closed."
        ))
    else:
        checks.append(EligibilityCheck(CRITERION_JOB_OPEN, True, "Job posting is approved and open."))

    # 3. Deadline ---------------------------------------------------------
    if job.deadline < date.today():
        checks.append(EligibilityCheck(
            CRITERION_DEADLINE, False,
            f"The application deadline was {job.deadline.isoformat()}.",
        ))
    else:
        checks.append(EligibilityCheck(
            CRITERION_DEADLINE, True,
            f"Applications close on {job.deadline.isoformat()}.",
        ))

    # 4. Minimum CGPA -----------------------------------------------------
    if job.min_cgpa is None:
        checks.append(EligibilityCheck(CRITERION_CGPA, True, "No minimum CGPA is required."))
    elif student is None or student.cgpa is None:
        checks.append(EligibilityCheck(
            CRITERION_CGPA, False,
            f"Required minimum CGPA is {_as_float(job.min_cgpa):.2f}; your CGPA is not recorded.",
        ))
    else:
        student_cgpa = _as_float(student.cgpa)
        required_cgpa = _as_float(job.min_cgpa)
        passed = student_cgpa >= required_cgpa
        checks.append(EligibilityCheck(
            CRITERION_CGPA, passed,
            f"Required minimum CGPA is {required_cgpa:.2f}. "
            f"Your CGPA is {student_cgpa:.2f}."
            + ("" if passed else " This is below the requirement."),
        ))

    # 5. Required skills --------------------------------------------------
    required_skills = [s for s in (job.skill_names or []) if s]
    if not required_skills:
        checks.append(EligibilityCheck(CRITERION_SKILLS, True, "No specific skills are required."))
    else:
        student_skills = set()
        if student is not None:
            student_skills = {_normalise(s.skill) for s in student.skills}
        missing_skills = [s for s in required_skills if _normalise(s) not in student_skills]
        passed = not missing_skills
        if passed:
            detail = "You list all required skills: " + ", ".join(required_skills) + "."
        else:
            detail = ("Missing required skill(s): " + ", ".join(missing_skills)
                      + ". Required: " + ", ".join(required_skills) + ".")
        checks.append(EligibilityCheck(CRITERION_SKILLS, passed, detail))

    # 6. Graduation year --------------------------------------------------
    if not job.eligible_graduation_year:
        checks.append(EligibilityCheck(
            CRITERION_GRADUATION, True, "Any graduation year is accepted."
        ))
    elif student is None or not student.graduation_year:
        checks.append(EligibilityCheck(
            CRITERION_GRADUATION, False,
            f"Only the {job.eligible_graduation_year} graduating batch is eligible; "
            "your graduation year is not recorded.",
        ))
    else:
        passed = int(student.graduation_year) == int(job.eligible_graduation_year)
        checks.append(EligibilityCheck(
            CRITERION_GRADUATION, passed,
            f"Eligible batch: {job.eligible_graduation_year}. "
            f"Your graduation year: {student.graduation_year}.",
        ))

    # 7. Department / degree ---------------------------------------------
    allowed = job.department_list
    if not allowed:
        checks.append(EligibilityCheck(
            CRITERION_DEPARTMENT, True, "Open to all departments and degrees."
        ))
    elif student is None or not student.department:
        checks.append(EligibilityCheck(
            CRITERION_DEPARTMENT, False,
            "Eligible departments: " + ", ".join(allowed) + "; your department is not recorded.",
        ))
    else:
        student_values = {
            _normalise(student.department),
            _normalise(student.degree or ""),
        }
        allowed_values = {_normalise(d) for d in allowed}
        passed = bool(student_values & allowed_values)
        checks.append(EligibilityCheck(
            CRITERION_DEPARTMENT, passed,
            "Eligible departments / degrees: " + ", ".join(allowed) + ". "
            f"Yours: {student.department}.",
        ))

    # 8. Backlogs ---------------------------------------------------------
    if job.max_backlogs is None:
        checks.append(EligibilityCheck(
            CRITERION_BACKLOGS, True, "No backlog restriction is configured."
        ))
    else:
        backlogs = int(student.active_backlogs or 0) if student is not None else 0
        passed = backlogs <= int(job.max_backlogs)
        checks.append(EligibilityCheck(
            CRITERION_BACKLOGS, passed,
            f"Maximum {job.max_backlogs} active backlog(s) allowed; you have {backlogs}.",
        ))

    # 9. Resume -----------------------------------------------------------
    if student is not None and student.has_resume:
        checks.append(EligibilityCheck(
            CRITERION_RESUME, True, "A resume is on file and will be shared with the recruiter."
        ))
    else:
        checks.append(EligibilityCheck(
            CRITERION_RESUME, False, "Upload a resume before applying to this job."
        ))

    eligible = all(c.passed for c in checks)
    return EligibilityResult(
        eligible=eligible,
        checks=checks,
        missing_skills=missing_skills,
        applied=already_applied,
    )
