"""Recruiter area: company profile, job postings, applicants and interviews."""
from __future__ import annotations

from datetime import date

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..forms import (
    ApplicationStatusForm,
    CompanyForm,
    InterviewForm,
    InterviewUpdateForm,
    JobForm,
    RejectForm,
)
from ..models import (
    APPLICATION_STATUSES,
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    JOB_APPROVED,
    JOB_CLOSED,
    JOB_PENDING,
    Application,
    Company,
    Interview,
    Job,
    JobRequiredSkill,
    ROLE_ADMIN,
    StudentProfile,
    User,
    utcnow,
)
from ..security import approved_recruiter_required, current_user, recruiter_required
from ..services.applications import (
    ApplicationError,
    schedule_interview,
    set_application_status,
    update_interview,
)
from ..services.audit import log_action
from ..services.stats import recruiter_stats
from ..utils import get_page, notify, parse_department_list, parse_skill_list

recruiter_bp = Blueprint("recruiter", __name__, template_folder="../templates/recruiter")


def _recruiter():
    profile = current_user().recruiter_profile
    if profile is None:
        abort(500, description="Recruiter profile is missing for this account.")
    return profile


def _own_job_or_404(job_id: int) -> Job:
    job = Job.query.get_or_404(job_id)
    if job.recruiter_id != _recruiter().id:
        abort(403, description="This job posting belongs to another recruiter.")
    return job


def _own_application_or_404(application_id: int) -> Application:
    application = Application.query.get_or_404(application_id)
    if application.job.recruiter_id != _recruiter().id:
        abort(403, description="This application belongs to another recruiter's job posting.")
    return application


@recruiter_bp.route("/dashboard")
@recruiter_required
def dashboard():
    recruiter = _recruiter()
    stats = recruiter_stats(recruiter)

    recent_applications = []
    if stats["total_jobs"]:
        recent_applications = (
            Application.query
            .join(Job, Application.job_id == Job.id)
            .filter(Job.recruiter_id == recruiter.id)
            .order_by(Application.applied_at.desc())
            .limit(5)
            .all()
        )

    if recruiter.company_id:
        upcoming_interviews = (
            Interview.query
            .join(Application, Interview.application_id == Application.id)
            .join(Job, Application.job_id == Job.id)
            .filter(Job.recruiter_id == recruiter.id,
                    Interview.scheduled_at >= db.func.now(),
                    Interview.status == "Scheduled")
            .order_by(Interview.scheduled_at)
            .limit(5)
            .all()
        )
    else:
        upcoming_interviews = []

    return render_template(
        "recruiter/dashboard.html",
        recruiter=recruiter,
        stats=stats,
        recent_applications=recent_applications,
        upcoming_interviews=upcoming_interviews,
    )


@recruiter_bp.route("/company", methods=["GET", "POST"])
@recruiter_required
def company():
    recruiter = _recruiter()
    record = recruiter.company
    form = CompanyForm(obj=record)

    if form.validate_on_submit():
        duplicate = Company.query.filter(
            db.func.lower(Company.name) == form.name.data.strip().lower(),
        )
        if record is not None:
            duplicate = duplicate.filter(Company.id != record.id)
        clash = duplicate.first()
        if clash:
            form.name.errors.append("Another company already uses this name.")
        else:
            if record is None:
                record = Company(created_by_id=current_user().id)
                db.session.add(record)
                db.session.flush()
                recruiter.company_id = record.id
            record.name = form.name.data.strip()
            record.website = (form.website.data or "").strip() or None
            record.industry = (form.industry.data or "").strip() or None
            record.location = (form.location.data or "").strip() or None
            record.description = (form.description.data or "").strip() or None
            db.session.commit()
            log_action(current_user(), "company.save", "Company", record.id)
            flash("Company profile saved.", "success")
            return redirect(url_for("recruiter.company"))

    return render_template("recruiter/company.html", form=form, recruiter=recruiter,
                           company=record)


@recruiter_bp.route("/jobs")
@recruiter_required
def jobs():
    recruiter = _recruiter()
    page = get_page()
    status = (request.args.get("status") or "").strip()
    keyword = (request.args.get("q") or "").strip()

    query = Job.query.filter_by(recruiter_id=recruiter.id)
    if status:
        query = query.filter(Job.status == status)
    if keyword:
        query = query.filter(Job.title.like(f"%{keyword}%"))

    sort = request.args.get("sort", "newest")
    if sort == "deadline":
        query = query.order_by(Job.deadline.asc())
    elif sort == "applications":
        query = query.order_by(Job.created_at.desc())
    else:
        query = query.order_by(Job.created_at.desc())

    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)

    counts = dict(
        db.session.query(Job.id, db.func.count(Application.id))
        .outerjoin(Application, Application.job_id == Job.id)
        .filter(Job.recruiter_id == recruiter.id)
        .group_by(Job.id)
        .all()
    )

    return render_template("recruiter/jobs.html", pagination=pagination,
                           items=pagination.items, counts=counts, status=status,
                           keyword=keyword)


@recruiter_bp.route("/jobs/new", methods=["GET", "POST"])
@approved_recruiter_required
def create_job():
    recruiter = _recruiter()
    if recruiter.company_id is None:
        flash("Create your company profile before posting a job.", "warning")
        return redirect(url_for("recruiter.company"))

    form = JobForm()
    if form.validate_on_submit():
        job = Job(
            company_id=recruiter.company_id,
            recruiter_id=recruiter.id,
            status=JOB_PENDING,
            approval_status=APPROVAL_PENDING,
        )
        _apply_job_form(job, form)
        db.session.add(job)
        db.session.flush()
        _sync_skills(job, form.required_skills.data)
        _notify_admins(job, "New job posting awaiting approval",
                       f"{job.company.name} posted '{job.title}'.")
        log_action(current_user(), "job.create", "Job", job.id,
                   f"title={job.title} status={job.status}", commit=False)
        db.session.commit()
        flash("Job posting created and submitted for placement cell approval.", "success")
        return redirect(url_for("recruiter.job_detail", job_id=job.id))

    return render_template("recruiter/job_form.html", form=form, job=None)


@recruiter_bp.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@approved_recruiter_required
def edit_job(job_id: int):
    job = _own_job_or_404(job_id)
    if job.status == JOB_CLOSED:
        flash("Closed postings cannot be edited. Reopen the posting first.", "warning")
        return redirect(url_for("recruiter.job_detail", job_id=job.id))

    form = JobForm(obj=job)
    if request.method == "GET":
        form.required_skills.data = ", ".join(job.skill_names)
        form.required_departments.data = ", ".join(job.department_list)

    if form.validate_on_submit():
        _apply_job_form(job, form)
        db.session.flush()
        _sync_skills(job, form.required_skills.data)

        # Any material change invalidates the previous approval.
        was_approved = job.approval_status == APPROVAL_APPROVED
        if was_approved:
            job.approval_status = APPROVAL_PENDING
            job.status = JOB_PENDING
            job.approved_by_id = None
            job.approved_at = None
            job.rejection_reason = None

        _notify_admins(job, "Job posting updated",
                       f"'{job.title}' was edited and needs review again."
                       if was_approved else f"'{job.title}' was updated.")
        log_action(current_user(), "job.update", "Job", job.id,
                   f"approval {'reset to pending' if was_approved else 'unchanged'}",
                   commit=False)
        db.session.commit()

        if was_approved:
            flash("Job posting updated. It is back in the approval queue "
                  "because the criteria changed.", "info")
        else:
            flash("Job posting updated.", "success")
        return redirect(url_for("recruiter.job_detail", job_id=job.id))

    return render_template("recruiter/job_form.html", form=form, job=job)


@recruiter_bp.route("/jobs/<int:job_id>")
@recruiter_required
def job_detail(job_id: int):
    job = _own_job_or_404(job_id)
    counts = dict(
        db.session.query(Application.status, db.func.count(Application.id))
        .filter(Application.job_id == job.id)
        .group_by(Application.status)
        .all()
    )
    total_applications = sum(counts.values())
    interviews = (
        Interview.query
        .join(Application, Interview.application_id == Application.id)
        .filter(Application.job_id == job.id)
        .order_by(Interview.scheduled_at.desc())
        .all()
    )
    return render_template("recruiter/job_detail.html", job=job, counts=counts,
                           total_applications=total_applications, interviews=interviews,
                           statuses=APPLICATION_STATUSES)


@recruiter_bp.route("/jobs/<int:job_id>/close", methods=["POST"])
@recruiter_required
def close_job(job_id: int):
    job = _own_job_or_404(job_id)
    if job.status == JOB_CLOSED:
        flash("This posting is already closed.", "info")
    else:
        job.status = JOB_CLOSED
        job.closed_at = utcnow()
        log_action(current_user(), "job.close", "Job", job.id, commit=False)
        db.session.commit()
        flash("Job posting closed. Students can no longer apply.", "success")
    return redirect(url_for("recruiter.job_detail", job_id=job.id))


@recruiter_bp.route("/jobs/<int:job_id>/reopen", methods=["POST"])
@recruiter_required
def reopen_job(job_id: int):
    job = _own_job_or_404(job_id)
    if job.deadline < date.today():
        flash("Extend the application deadline before reopening this posting.", "warning")
        return redirect(url_for("recruiter.job_detail", job_id=job.id))

    job.status = JOB_APPROVED if job.approval_status == APPROVAL_APPROVED else JOB_PENDING
    job.closed_at = None
    log_action(current_user(), "job.reopen", "Job", job.id, f"status={job.status}", commit=False)
    db.session.commit()
    flash("Job posting reopened.", "success")
    return redirect(url_for("recruiter.job_detail", job_id=job.id))


# --------------------------------------------------------------------------
# Applicants
# --------------------------------------------------------------------------
@recruiter_bp.route("/jobs/<int:job_id>/applicants")
@recruiter_required
def applicants(job_id: int):
    job = _own_job_or_404(job_id)
    page = get_page()

    query = (
        Application.query
        .join(StudentProfile, Application.student_id == StudentProfile.id)
        .filter(Application.job_id == job.id)
    )

    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(Application.status == status)

    department = (request.args.get("department") or "").strip()
    if department:
        query = query.filter(StudentProfile.department == department)

    batch = (request.args.get("batch") or "").strip()
    if batch.isdigit():
        query = query.filter(StudentProfile.graduation_year == int(batch))

    min_cgpa = (request.args.get("min_cgpa") or "").strip()
    if min_cgpa:
        try:
            query = query.filter(StudentProfile.cgpa >= float(min_cgpa))
        except ValueError:
            pass

    keyword = (request.args.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(StudentProfile.full_name.like(like),
                                    StudentProfile.roll_number.like(like)))

    sort = request.args.get("sort", "recent")
    if sort == "cgpa":
        query = query.order_by(StudentProfile.cgpa.desc())
    elif sort == "name":
        query = query.order_by(StudentProfile.full_name.asc())
    elif sort == "oldest":
        query = query.order_by(Application.applied_at.asc())
    else:
        query = query.order_by(Application.applied_at.desc())

    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)

    departments = [
        row[0] for row in db.session.query(StudentProfile.department)
        .join(Application, Application.student_id == StudentProfile.id)
        .filter(Application.job_id == job.id).distinct().order_by(StudentProfile.department).all()
    ]
    batches = [
        row[0] for row in db.session.query(StudentProfile.graduation_year)
        .join(Application, Application.student_id == StudentProfile.id)
        .filter(Application.job_id == job.id).distinct()
        .order_by(StudentProfile.graduation_year).all()
    ]

    return render_template("recruiter/applicants.html", job=job, pagination=pagination,
                           items=pagination.items, status=status, departments=departments,
                           batches=batches, statuses=APPLICATION_STATUSES,
                           filters=request.args)


@recruiter_bp.route("/applications/<int:application_id>")
@recruiter_required
def application_detail(application_id: int):
    application = _own_application_or_404(application_id)
    status_form = ApplicationStatusForm(current_status=application.status)
    interview_form = InterviewForm()
    return render_template(
        "recruiter/application_detail.html",
        application=application,
        status_form=status_form,
        interview_form=interview_form,
    )


@recruiter_bp.route("/applications/<int:application_id>/status", methods=["POST"])
@recruiter_required
def update_application_status(application_id: int):
    application = _own_application_or_404(application_id)
    form = ApplicationStatusForm(current_status=application.status)
    if not form.validate_on_submit():
        flash("Select a valid status.", "danger")
        return redirect(url_for("recruiter.application_detail", application_id=application.id))

    try:
        set_application_status(application, form.status.data, current_user(), form.note.data)
    except ApplicationError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"Application moved to '{form.status.data}'.", "success")
    return redirect(url_for("recruiter.application_detail", application_id=application.id))


@recruiter_bp.route("/applications/<int:application_id>/interview", methods=["POST"])
@recruiter_required
def create_interview(application_id: int):
    application = _own_application_or_404(application_id)
    form = InterviewForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for message in errors:
                flash(f"{getattr(form, field).label.text}: {message}", "danger")
        return redirect(url_for("recruiter.application_detail", application_id=application.id))

    try:
        schedule_interview(
            application,
            current_user(),
            round_name=form.round_name.data,
            scheduled_at=form.scheduled_at.data,
            duration_minutes=form.duration_minutes.data,
            mode=form.mode.data,
            venue=form.venue.data,
            meeting_link=form.meeting_link.data,
            interviewer_name=form.interviewer_name.data,
        )
    except ApplicationError as exc:
        flash(str(exc), "danger")
    else:
        flash("Interview scheduled and the student has been notified.", "success")
    return redirect(url_for("recruiter.application_detail", application_id=application.id))


@recruiter_bp.route("/interviews")
@recruiter_required
def interviews():
    recruiter = _recruiter()
    page = get_page()
    query = (
        Interview.query
        .join(Application, Interview.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .filter(Job.recruiter_id == recruiter.id)
    )
    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(Interview.status == status)

    upcoming_only = request.args.get("upcoming") == "1"
    if upcoming_only:
        query = query.filter(Interview.scheduled_at >= db.func.now())

    sort = request.args.get("sort", "soonest")
    if sort == "latest":
        query = query.order_by(Interview.scheduled_at.desc())
    else:
        query = query.order_by(Interview.scheduled_at.asc())

    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)
    return render_template("recruiter/interviews.html", pagination=pagination,
                           items=pagination.items, status=status, upcoming_only=upcoming_only)


@recruiter_bp.route("/interviews/<int:interview_id>", methods=["GET", "POST"])
@recruiter_required
def interview_detail(interview_id: int):
    interview = Interview.query.get_or_404(interview_id)
    if interview.application.job.recruiter_id != _recruiter().id:
        abort(403, description="This interview belongs to another recruiter's job posting.")

    form = InterviewUpdateForm(obj=interview)
    if form.validate_on_submit():
        try:
            update_interview(
                interview, current_user(),
                status=form.status.data,
                result=form.result.data,
                feedback=form.feedback.data,
                scheduled_at=form.scheduled_at.data,
                mode=form.mode.data,
                venue=form.venue.data,
                meeting_link=form.meeting_link.data,
            )
        except ApplicationError as exc:
            flash(str(exc), "danger")
        else:
            flash("Interview updated.", "success")
        return redirect(url_for("recruiter.interview_detail", interview_id=interview.id))

    return render_template("recruiter/interview_detail.html", interview=interview, form=form)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _apply_job_form(job: Job, form: JobForm) -> None:
    job.title = form.title.data.strip()
    job.description = form.description.data.strip()
    job.responsibilities = (form.responsibilities.data or "").strip() or None
    job.location = form.location.data.strip()
    job.employment_type = form.employment_type.data
    job.openings = form.openings.data
    job.currency = form.currency.data
    job.salary_min = form.salary_min.data
    job.salary_max = form.salary_max.data
    job.min_cgpa = form.min_cgpa.data
    job.eligible_graduation_year = form.eligible_graduation_year.data
    departments = parse_department_list(form.required_departments.data)
    job.required_departments = ", ".join(departments)[:500] or None
    job.max_backlogs = form.max_backlogs.data
    job.deadline = form.deadline.data


def _sync_skills(job: Job, raw_skills: str) -> None:
    job.required_skills.clear()
    db.session.flush()
    for skill in parse_skill_list(raw_skills):
        job.required_skills.append(JobRequiredSkill(skill=skill))


def _notify_admins(job: Job, title: str, message: str) -> None:
    for admin in User.query.filter_by(role=ROLE_ADMIN, is_active=True).all():
        notify(admin.id, title, message, link=f"/admin/jobs/{job.id}", commit=False)
