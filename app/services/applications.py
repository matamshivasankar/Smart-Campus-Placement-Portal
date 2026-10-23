"""Application workflow: applying, withdrawing, status transitions and interviews.

Every status change is validated on the server against an explicit transition
table, so an invalid or forged transition can never reach the database.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    APP_APPLIED,
    APP_INTERVIEW,
    APP_REJECTED,
    APP_SELECTED,
    APP_SHORTLISTED,
    APP_WITHDRAWN,
    APPLICATION_TRANSITIONS,
    INTERVIEW_SCHEDULED,
    WITHDRAWABLE_STATUSES,
    Application,
    Interview,
    Job,
    utcnow,
)
from ..utils import notify
from .audit import log_action
from .eligibility import evaluate_eligibility


class ApplicationError(Exception):
    """Raised when a workflow action violates a business rule."""


def current_application(student, job) -> Application | None:
    return Application.query.filter_by(student_id=student.id, job_id=job.id).first()


def apply_to_job(student, job: Job, cover_letter: str | None, actor) -> Application:
    """Create an application after re-checking every rule on the server."""
    if student is None:
        raise ApplicationError("Create your student profile before applying.")

    existing = current_application(student, job)
    if existing is not None:
        raise ApplicationError(
            f"You have already applied to this job (status: {existing.status})."
        )

    if job.deadline < date.today():
        raise ApplicationError(
            f"The application deadline for this job was {job.deadline.isoformat()}."
        )

    result = evaluate_eligibility(student, job)
    if not result.eligible:
        raise ApplicationError("You are not eligible: " + result.summary)

    application = Application(
        job_id=job.id,
        student_id=student.id,
        status=APP_APPLIED,
        cover_letter=(cover_letter or "").strip()[:5000] or None,
        status_updated_at=utcnow(),
    )
    db.session.add(application)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise ApplicationError("You have already applied to this job.")

    notify(
        job.recruiter.user_id,
        "New application received",
        f"{student.full_name} applied for {job.title}.",
        link=f"/recruiter/jobs/{job.id}/applicants",
        commit=False,
    )
    log_action(
        actor, "application.create", "Application", application.id,
        f"student={student.id} job={job.id} status={APP_APPLIED}", commit=False,
    )
    db.session.commit()
    return application


def withdraw_application(application: Application, student) -> Application:
    if application.student_id != student.id:
        raise ApplicationError("You can only withdraw your own applications.")

    if application.status not in WITHDRAWABLE_STATUSES:
        raise ApplicationError(
            f"An application with status '{application.status}' can no longer be withdrawn."
        )

    application.status = APP_WITHDRAWN
    application.status_updated_at = utcnow()
    notify(
        application.job.recruiter.user_id,
        "Application withdrawn",
        f"{student.full_name} withdrew their application for {application.job.title}.",
        link=f"/recruiter/jobs/{application.job_id}/applicants",
        commit=False,
    )
    log_action(
        student.user, "application.withdraw", "Application", application.id,
        f"job={application.job_id} previous={APP_APPLIED}", commit=False,
    )
    db.session.commit()
    return application


def allowed_next_statuses(status: str) -> tuple[str, ...]:
    return APPLICATION_TRANSITIONS.get(status, ())


def verifies_recruiter_owns(application: Application, recruiter_profile) -> bool:
    return application.job.recruiter_id == recruiter_profile.id


def set_application_status(application: Application, new_status: str, actor,
                           note: str | None = None) -> Application:
    """Validate and persist a recruiter driven status change."""
    recruiter = actor.recruiter_profile
    if recruiter is None or application.job.recruiter_id != recruiter.id:
        raise ApplicationError("This application does not belong to your job posting.")

    permitted = allowed_next_statuses(application.status)
    if new_status not in permitted:
        raise ApplicationError(
            f"Cannot move an application from '{application.status}' to '{new_status}'. "
            + (f"Allowed next status: {', '.join(permitted)}." if permitted
               else "This application has reached a final status.")
        )

    previous = application.status
    application.status = new_status
    application.status_updated_at = utcnow()

    notify(
        application.student.user_id,
        f"Application update: {new_status}",
        f"Your application for {application.job.title} at "
        f"{application.job.company.name} is now marked '{new_status}'."
        + (f" Note: {note}" if note else ""),
        link=f"/student/applications/{application.id}",
        commit=False,
    )
    log_action(
        actor, "application.status_change", "Application", application.id,
        f"{previous} -> {new_status}" + (f" | {note}" if note else ""), commit=False,
    )
    db.session.commit()
    return application


def schedule_interview(application: Application, actor, *, round_name: str,
                       scheduled_at, duration_minutes: int, mode: str,
                       venue: str | None, meeting_link: str | None,
                       interviewer_name: str | None) -> Interview:
    """Create an interview and advance the application to 'Interview Scheduled'."""
    recruiter = actor.recruiter_profile
    if recruiter is None or application.job.recruiter_id != recruiter.id:
        raise ApplicationError("This application does not belong to your job posting.")

    if application.status in (APP_REJECTED, APP_WITHDRAWN):
        raise ApplicationError(
            f"You cannot schedule an interview while the application is '{application.status}'."
        )

    last_round = (
        db.session.query(db.func.max(Interview.round_number))
        .filter(Interview.application_id == application.id)
        .scalar()
    )
    next_round = int(last_round or 0) + 1

    interview = Interview(
        application_id=application.id,
        round_number=next_round,
        round_name=(round_name or f"Round {next_round}")[:120],
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        mode=mode,
        venue=(venue or None),
        meeting_link=(meeting_link or None),
        interviewer_name=(interviewer_name or None),
        status=INTERVIEW_SCHEDULED,
        created_by_id=actor.id,
    )
    db.session.add(interview)

    previous = application.status
    if application.status in (APP_APPLIED, APP_SHORTLISTED, APP_INTERVIEW):
        application.status = APP_INTERVIEW
        application.status_updated_at = utcnow()

    notify(
        application.student.user_id,
        "Interview scheduled",
        f"{round_name or 'Round ' + str(next_round)} for {application.job.title} "
        f"at {application.job.company.name} is scheduled on "
        f"{scheduled_at:%d %b %Y, %I:%M %p} ({mode}).",
        link=f"/student/applications/{application.id}",
        commit=False,
    )
    log_action(
        actor, "interview.schedule", "Interview", None,
        f"application={application.id} round={next_round} at={scheduled_at.isoformat()} "
        f"status {previous} -> {application.status}", commit=False,
    )
    db.session.commit()
    return interview


def update_interview(interview: Interview, actor, *, status: str | None = None,
                     result: str | None = None, feedback: str | None = None,
                     scheduled_at=None, mode: str | None = None,
                     venue: str | None = None, meeting_link: str | None = None):
    application = interview.application
    recruiter = actor.recruiter_profile
    if recruiter is None or application.job.recruiter_id != recruiter.id:
        raise ApplicationError("This interview does not belong to your job posting.")

    changes = []
    if status and status != interview.status:
        changes.append(f"status {interview.status} -> {status}")
        interview.status = status
    if result and result != interview.result:
        changes.append(f"result {interview.result} -> {result}")
        interview.result = result
    if feedback is not None:
        interview.feedback = feedback.strip()[:5000] or None
    if scheduled_at and scheduled_at != interview.scheduled_at:
        changes.append(f"rescheduled to {scheduled_at.isoformat()}")
        interview.scheduled_at = scheduled_at
    if mode:
        interview.mode = mode
    if venue is not None:
        interview.venue = venue.strip()[:255] or None
    if meeting_link is not None:
        interview.meeting_link = meeting_link.strip()[:500] or None

    if changes:
        notify(
            application.student.user_id,
            "Interview updated",
            f"Interview update for {application.job.title}: " + "; ".join(changes) + ".",
            link=f"/student/applications/{application.id}",
            commit=False,
        )
        log_action(
            actor, "interview.update", "Interview", interview.id,
            " | ".join(changes), commit=False,
        )
    db.session.commit()
    return interview
