"""Public pages: home, job board, job details and notifications."""
from __future__ import annotations

from datetime import date

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from ..extensions import db
from ..forms import ApplyForm
from ..models import (
    ACTIVE_APPLICATION_STATUSES,
    APP_SELECTED,
    Application,
    Company,
    Interview,
    Job,
    JobRequiredSkill,
    Notification,
    StudentProfile,
)
from ..security import current_user, login_required
from ..services.applications import current_application
from ..services.audit import log_action
from ..services.eligibility import evaluate_eligibility
from ..services.files import resume_path, signed_resume_url
from ..services.jobs import apply_job_filters, paginate, sort_jobs, visible_jobs_query
from ..utils import get_page

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Home page. Every figure comes from a live database query."""
    open_jobs_query = visible_jobs_query().filter(Job.deadline >= date.today())
    latest_jobs = (
        sort_jobs(open_jobs_query, {"sort": "newest"})
        .limit(6)
        .all()
    )

    stats = {
        "open_jobs": open_jobs_query.count(),
        "companies": (
            db.session.query(db.func.count(db.distinct(Job.company_id)))
            .filter(Job.approval_status == "approved", Job.status == "approved",
                    Job.deadline >= date.today())
            .scalar() or 0
        ),
        "students": StudentProfile.query.count(),
        "placed": (
            db.session.query(db.func.count(db.distinct(Application.student_id)))
            .filter(Application.status == APP_SELECTED)
            .scalar() or 0
        ),
    }
    top_companies = (
        db.session.query(Company.name, db.func.count(Job.id).label("jobs"))
        .join(Job, Job.company_id == Company.id)
        .filter(Job.approval_status == "approved", Job.status == "approved")
        .group_by(Company.name)
        .order_by(db.func.count(Job.id).desc())
        .limit(6)
        .all()
    )

    return render_template(
        "main/home.html", latest_jobs=latest_jobs, stats=stats, top_companies=top_companies
    )


@main_bp.route("/jobs")
def job_board():
    page = get_page()
    query = apply_job_filters(visible_jobs_query().filter(Job.deadline >= date.today()), request.args)
    query = sort_jobs(query, request.args)
    pagination = paginate(query, page, 9)

    eligibility_map = {}
    applications_map = {}
    student = current_user().student_profile if (current_user() and current_user().is_student) else None
    if student is not None:
        for job in pagination.items:
            application = current_application(student, job)
            applications_map[job.id] = application
            eligibility_map[job.id] = evaluate_eligibility(
                student, job, already_applied=application is not None
            )

    return render_template(
        "main/jobs.html",
        pagination=pagination,
        jobs=pagination.items,
        eligibility_map=eligibility_map,
        applications_map=applications_map,
    )


@main_bp.route("/jobs/<int:job_id>")
def job_detail(job_id: int):
    job = Job.query.get_or_404(job_id)

    student = None
    application = None
    eligibility = None
    user = current_user()

    if user is not None and user.is_student:
        student = user.student_profile
        application = current_application(student, job) if student else None
        eligibility = evaluate_eligibility(student, job, already_applied=application is not None)
    elif not job.is_open:
        # Anonymous visitors may only see live postings.
        if job.status != "closed" and job.approval_status == "approved" and job.deadline < date.today():
            pass  # expired postings stay readable
        elif job.status != "closed" and job.approval_status != "approved":
            abort(404)

    return render_template(
        "main/job_detail.html",
        job=job,
        student=student,
        application=application,
        eligibility=eligibility,
        form=ApplyForm(),
    )


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
@main_bp.route("/notifications")
@login_required
def notifications():
    user = current_user()
    page = get_page()
    query = Notification.query.filter_by(user_id=user.id).order_by(Notification.created_at.desc())
    pagination = paginate(query, page, 15)
    return render_template("main/notifications.html", pagination=pagination,
                           items=pagination.items)


@main_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id: int):
    user = current_user()
    note = Notification.query.filter_by(id=notification_id, user_id=user.id).first_or_404()
    note.is_read = True
    db.session.commit()
    return redirect(note.link or url_for("main.notifications"))


@main_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    user = current_user()
    Notification.query.filter_by(user_id=user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("main.notifications"))


# --------------------------------------------------------------------------
# Transparency pages driven by real database rows
# --------------------------------------------------------------------------
@main_bp.route("/placements")
def placement_highlights():
    """Public snapshot of placement activity computed from stored records."""
    total_interviews = Interview.query.count()
    active_applications = Application.query.filter(
        Application.status.in_(ACTIVE_APPLICATION_STATUSES)
    ).count()
    selected = Application.query.filter_by(status=APP_SELECTED).count()
    by_company = (
        db.session.query(
            Company.name,
            db.func.count(Job.id).label("jobs"),
            db.func.count(Application.id).label("applications"),
        )
        .outerjoin(Job, Job.company_id == Company.id)
        .outerjoin(Application, Application.job_id == Job.id)
        .filter(Job.status == "approved")
        .group_by(Company.name)
        .order_by(db.func.count(Application.id).desc())
        .limit(10)
        .all()
    )
    top_skills = (
        db.session.query(JobRequiredSkill.skill, db.func.count(JobRequiredSkill.id).label("demand"))
        .group_by(JobRequiredSkill.skill)
        .order_by(db.func.count(JobRequiredSkill.id).desc())
        .limit(10)
        .all()
    )
    stats = {
        "companies": Company.query.count(),
        "jobs": Job.query.count(),
        "interviews": total_interviews,
        "active_applications": active_applications,
        "selected": selected,
    }
    return render_template("main/placements.html", stats=stats, by_company=by_company,
                           top_skills=top_skills)


# --------------------------------------------------------------------------
# Resume downloads (authorised per viewer)
# --------------------------------------------------------------------------
@main_bp.route("/resumes/<int:student_id>")
@login_required
def download_resume(student_id: int):
    """Serve a resume only to its owner, an administrator, or a recruiter who
    has received an application from that student."""
    user = current_user()
    student = StudentProfile.query.get_or_404(student_id)

    if not student.has_resume:
        abort(404, description="No resume has been uploaded for this student.")

    allowed = False
    if user.is_admin:
        allowed = True
    elif user.is_student and user.student_profile and user.student_profile.id == student.id:
        allowed = True
    elif user.is_recruiter and user.recruiter_profile:
        allowed = (
            Application.query
            .join(Job, Application.job_id == Job.id)
            .filter(Application.student_id == student.id,
                    Job.recruiter_id == user.recruiter_profile.id)
            .first()
            is not None
        )

    if not allowed:
        abort(403, description="You are not allowed to download this resume.")

    log_action(user, "resume.download", "StudentProfile", student.id,
               f"by={user.role}")
    if student.resume_storage == "supabase":
        signed_url = signed_resume_url(student.user_id, student.resume_filename)
        if not signed_url:
            abort(404, description="The configured private resume object could not be accessed.")
        return redirect(signed_url)
    path = resume_path(student.user_id, student.resume_filename)
    if path is None:
        abort(404, description="The stored resume file could not be found.")
    download_name = student.resume_original_name or "resume" + path.suffix
    if not download_name.lower().endswith(path.suffix.lower()):
        download_name = f"{download_name}{path.suffix}"
    return send_file(path, as_attachment=True, download_name=download_name,
                     mimetype="application/octet-stream")
