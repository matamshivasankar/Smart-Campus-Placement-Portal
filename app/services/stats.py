"""Dashboard statistics.

Every number below is produced by a live SQL aggregate over the configured database;
nothing is hard-coded or simulated.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func

from ..extensions import db
from ..models import (
    ACTIVE_APPLICATION_STATUSES,
    APP_INTERVIEW,
    APP_REJECTED,
    APP_SELECTED,
    APP_SHORTLISTED,
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    Application,
    Company,
    Interview,
    Job,
    JobRequiredSkill,
    RecruiterProfile,
    StudentProfile,
    User,
)


def student_stats(student: StudentProfile) -> dict:
    total = Application.query.filter_by(student_id=student.id).count()
    in_progress = (
        Application.query
        .filter(Application.student_id == student.id,
                Application.status.in_(ACTIVE_APPLICATION_STATUSES))
        .count()
    )
    shortlisted = Application.query.filter_by(
        student_id=student.id, status=APP_SHORTLISTED
    ).count()
    interviews = (
        Application.query.filter_by(student_id=student.id, status=APP_INTERVIEW).count()
    )
    selected = Application.query.filter_by(student_id=student.id, status=APP_SELECTED).count()
    rejected = Application.query.filter_by(student_id=student.id, status=APP_REJECTED).count()

    upcoming = (
        Interview.query
        .join(Application, Interview.application_id == Application.id)
        .filter(Application.student_id == student.id,
                Interview.scheduled_at >= func.now())
        .order_by(Interview.scheduled_at)
        .limit(5)
        .all()
    )

    open_jobs = (
        Job.query
        .filter(Job.status == APPROVAL_APPROVED,
                Job.approval_status == APPROVAL_APPROVED,
                Job.deadline >= date.today())
        .count()
    )

    return {
        "total_applications": total,
        "in_progress": in_progress,
        "shortlisted": shortlisted,
        "interview_stage": interviews,
        "selected": selected,
        "rejected": rejected,
        "upcoming_interviews": upcoming,
        "open_jobs": open_jobs,
        "has_resume": student.has_resume,
        "profile_complete": student.is_complete,
        "skill_count": len(student.skills),
    }


def recruiter_stats(recruiter: RecruiterProfile) -> dict:
    job_ids = [j.id for j in Job.query.filter_by(recruiter_id=recruiter.id).all()]
    total_jobs = len(job_ids)
    open_jobs = (
        Job.query
        .filter(Job.recruiter_id == recruiter.id,
                Job.status == APPROVAL_APPROVED,
                Job.deadline >= date.today())
        .count()
    )
    if not job_ids:
        return {
            "total_jobs": total_jobs,
            "open_jobs": open_jobs,
            "total_applications": 0,
            "shortlisted": 0,
            "interview_stage": 0,
            "selected": 0,
            "rejected": 0,
            "interviews_scheduled": 0,
            "applications_by_job": [],
            "approval_status": recruiter.approval_status,
        }

    base = Application.query.filter(Application.job_id.in_(job_ids))

    def count_status(status: str) -> int:
        return base.filter(Application.status == status).count()

    interviews_scheduled = (
        Interview.query
        .join(Application, Interview.application_id == Application.id)
        .filter(Application.job_id.in_(job_ids))
        .count()
    )

    per_job = (
        db.session.query(
            Job.id, Job.title, Job.status, Job.deadline,
            func.count(Application.id).label("applications"),
        )
        .outerjoin(Application, Application.job_id == Job.id)
        .filter(Job.recruiter_id == recruiter.id)
        .group_by(Job.id, Job.title, Job.status, Job.deadline)
        .order_by(Job.created_at.desc())
        .all()
    )

    return {
        "total_jobs": total_jobs,
        "open_jobs": open_jobs,
        "total_applications": base.count(),
        "shortlisted": count_status(APP_SHORTLISTED),
        "interview_stage": count_status(APP_INTERVIEW),
        "selected": count_status(APP_SELECTED),
        "rejected": count_status(APP_REJECTED),
        "interviews_scheduled": interviews_scheduled,
        "applications_by_job": per_job,
        "approval_status": recruiter.approval_status,
    }


def admin_stats() -> dict:
    total_students = StudentProfile.query.count()
    total_recruiters = RecruiterProfile.query.count()
    pending_recruiters = RecruiterProfile.query.filter_by(
        approval_status=APPROVAL_PENDING
    ).count()
    total_companies = Company.query.count()
    total_jobs = Job.query.count()
    pending_jobs = Job.query.filter_by(approval_status=APPROVAL_PENDING).count()
    approved_jobs = Job.query.filter_by(status=APPROVAL_APPROVED).count()
    closed_jobs = Job.query.filter_by(status="closed").count()
    total_applications = Application.query.count()

    def app_count(status: str) -> int:
        return Application.query.filter_by(status=status).count()

    selected = app_count(APP_SELECTED)

    placement_rate = round((selected / total_students) * 100, 1) if total_students else 0.0
    placed_students = (
        db.session.query(func.count(func.distinct(Application.student_id)))
        .filter(Application.status == APP_SELECTED)
        .scalar()
    ) or 0
    student_placement_rate = (
        round((placed_students / total_students) * 100, 1) if total_students else 0.0
    )

    by_company = (
        db.session.query(
            Company.name,
            func.count(func.distinct(Job.id)).label("jobs"),
            func.count(Application.id).label("applications"),
        )
        .outerjoin(Job, Job.company_id == Company.id)
        .outerjoin(Application, Application.job_id == Job.id)
        .group_by(Company.name)
        .order_by(func.count(Application.id).desc())
        .limit(10)
        .all()
    )

    by_department = (
        db.session.query(
            StudentProfile.department,
            func.count(func.distinct(Application.student_id)).label("applicants"),
            func.count(Application.id).label("applications"),
        )
        .outerjoin(Application, Application.student_id == StudentProfile.id)
        .group_by(StudentProfile.department)
        .order_by(StudentProfile.department)
        .all()
    )

    by_graduation_year = (
        db.session.query(
            StudentProfile.graduation_year,
            func.count(func.distinct(StudentProfile.id)).label("students"),
        )
        .group_by(StudentProfile.graduation_year)
        .order_by(StudentProfile.graduation_year)
        .all()
    )

    top_skills = (
        db.session.query(JobRequiredSkill.skill, func.count(JobRequiredSkill.id).label("demand"))
        .group_by(JobRequiredSkill.skill)
        .order_by(func.count(JobRequiredSkill.id).desc())
        .limit(8)
        .all()
    )

    return {
        "total_students": total_students,
        "total_recruiters": total_recruiters,
        "pending_recruiters": pending_recruiters,
        "total_companies": total_companies,
        "total_jobs": total_jobs,
        "pending_jobs": pending_jobs,
        "approved_jobs": approved_jobs,
        "closed_jobs": closed_jobs,
        "total_applications": total_applications,
        "applied": app_count("Applied"),
        "shortlisted": app_count(APP_SHORTLISTED),
        "interview_stage": app_count(APP_INTERVIEW),
        "selected": selected,
        "rejected": app_count(APP_REJECTED),
        "withdrawn": app_count("Withdrawn"),
        "placed_students": placed_students,
        "placement_rate": placement_rate,
        "student_placement_rate": student_placement_rate,
        "by_company": by_company,
        "by_department": by_department,
        "by_graduation_year": by_graduation_year,
        "top_skills": top_skills,
        "active_users": User.query.filter_by(is_active=True).count(),
        "upcoming_interviews": (
            Interview.query
            .filter(Interview.scheduled_at >= func.now())
            .count()
        ),
        "interviews_this_week": (
            Interview.query
            .filter(Interview.scheduled_at >= datetime.now(timezone.utc).replace(tzinfo=None),
                    Interview.scheduled_at <= datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(days=7))
            .count()
        ),
    }
