"""Student area: dashboard, profile, resume, job browsing and applications."""
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

from ..extensions import db
from ..forms import ApplyForm, ResumeUploadForm, StudentProfileForm
from ..models import (
    ACTIVE_APPLICATION_STATUSES,
    Application,
    Job,
    StudentSkill,
)
from ..security import current_user, student_required
from ..services.applications import (
    ApplicationError,
    apply_to_job,
    current_application,
    withdraw_application,
)
from ..services.audit import log_action
from ..services.eligibility import evaluate_eligibility
from ..services.files import ResumeError, delete_resume, save_resume, supabase_storage_enabled
from ..services.jobs import apply_job_filters, paginate, sort_jobs, visible_jobs_query
from ..services.stats import student_stats
from ..utils import SimplePagination, get_page, parse_skill_list

student_bp = Blueprint("student", __name__, template_folder="../templates/student")


def _profile_of_current_user():
    profile = current_user().student_profile
    if profile is None:
        abort(500, description="Student profile is missing for this account.")
    return profile


@student_bp.route("/dashboard")
@student_required
def dashboard():
    student = _profile_of_current_user()
    stats = student_stats(student)

    recent_applications = (
        Application.query
        .filter_by(student_id=student.id)
        .order_by(Application.applied_at.desc())
        .limit(5)
        .all()
    )

    # Deterministic scan of open postings the student currently qualifies for.
    open_jobs = (
        visible_jobs_query()
        .filter(Job.deadline >= date.today())
        .order_by(Job.deadline.asc())
        .limit(200)
        .all()
    )
    eligible_jobs = []
    for job in open_jobs:
        if current_application(student, job) is not None:
            continue
        if evaluate_eligibility(student, job).eligible:
            eligible_jobs.append(job)
    stats["eligible_jobs"] = len(eligible_jobs)

    return render_template(
        "student/dashboard.html",
        student=student,
        stats=stats,
        recent_applications=recent_applications,
        eligible_jobs=eligible_jobs[:5],
    )


@student_bp.route("/profile", methods=["GET", "POST"])
@student_required
def profile():
    student = _profile_of_current_user()
    form = StudentProfileForm(obj=student)
    resume_form = ResumeUploadForm()

    if request.method == "GET":
        form.skills.data = ", ".join(student.skill_names)

    if form.submit.data and form.validate_on_submit():
        student.full_name = form.full_name.data.strip()
        duplicate = StudentProfile.query.filter(
            StudentProfile.roll_number == form.roll_number.data.strip(),
            StudentProfile.id != student.id,
        ).first()
        if duplicate:
            form.roll_number.errors.append("Another student already uses this roll number.")
        else:
            student.roll_number = form.roll_number.data.strip()
            student.department = form.department.data
            student.degree = form.degree.data.strip()
            student.cgpa = form.cgpa.data
            student.graduation_year = form.graduation_year.data
            student.phone = (form.phone.data or "").strip() or None
            student.active_backlogs = form.active_backlogs.data or 0
            student.about = (form.about.data or "").strip() or None
            student.linkedin_url = (form.linkedin_url.data or "").strip() or None
            student.github_url = (form.github_url.data or "").strip() or None

            student.skills.clear()
            db.session.flush()
            for skill in parse_skill_list(form.skills.data):
                student.skills.append(StudentSkill(skill=skill))

            db.session.commit()
            log_action(current_user(), "student.profile_update", "StudentProfile", student.id)
            flash("Profile updated. Eligibility is recalculated from these details.", "success")
            return redirect(url_for("student.profile"))

    return render_template("student/profile.html", form=form, student=student,
                           resume_form=resume_form)


@student_bp.route("/resume", methods=["POST"])
@student_required
def upload_resume():
    student = _profile_of_current_user()
    form = ResumeUploadForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for message in errors:
                flash(message, "danger")
        return redirect(url_for("student.profile"))

    try:
        stored_name, original_name = save_resume(form.resume.data, current_user().id)
    except ResumeError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("student.profile"))

    previous = student.resume_filename
    student.resume_filename = stored_name
    student.resume_storage = "supabase" if supabase_storage_enabled() else "local"
    student.resume_original_name = original_name
    from ..models import utcnow
    student.resume_uploaded_at = utcnow()
    db.session.commit()

    if previous and previous != stored_name:
        delete_resume(current_user().id, previous)

    log_action(current_user(), "student.resume_upload", "StudentProfile", student.id,
               f"file={original_name}")
    flash("Resume uploaded successfully.", "success")
    return redirect(url_for("student.profile"))


@student_bp.route("/resume/delete", methods=["POST"])
@student_required
def remove_resume():
    student = _profile_of_current_user()
    if not student.has_resume:
        flash("There is no resume on file.", "info")
        return redirect(url_for("student.profile"))

    delete_resume(current_user().id, student.resume_filename)
    log_action(current_user(), "student.resume_delete", "StudentProfile", student.id,
               f"file={student.resume_original_name}")
    student.resume_filename = None
    student.resume_storage = "local"
    student.resume_original_name = None
    student.resume_uploaded_at = None
    db.session.commit()
    flash("Resume removed. You cannot apply to new jobs without a resume.", "info")
    return redirect(url_for("student.profile"))


@student_bp.route("/jobs")
@student_required
def jobs():
    student = _profile_of_current_user()
    page = get_page()
    query = apply_job_filters(visible_jobs_query().filter(Job.deadline >= date.today()), request.args)
    query = sort_jobs(query, request.args)
    eligible_only = request.args.get("eligible_only") == "1"
    if eligible_only:
        jobs = query.all()
        rows = []
        for job in jobs:
            application = current_application(student, job)
            result = evaluate_eligibility(student, job, already_applied=application is not None)
            if result.eligible:
                rows.append({"job": job, "eligibility": result, "application": application})
        total = len(rows)
        pagination = SimplePagination(total, page, 9, rows[(page - 1) * 9:page * 9])
    else:
        pagination = paginate(query, page, 9)
        rows = []
        jobs = pagination.items
        for job in jobs:
            application = current_application(student, job)
            result = evaluate_eligibility(student, job, already_applied=application is not None)
            rows.append({"job": job, "eligibility": result, "application": application})

    return render_template("student/jobs.html", rows=rows, pagination=pagination)


@student_bp.route("/jobs/<int:job_id>")
@student_required
def job_detail(job_id: int):
    student = _profile_of_current_user()
    job = Job.query.get_or_404(job_id)
    if job.approval_status != "approved":
        abort(404)

    application = current_application(student, job)
    eligibility = evaluate_eligibility(student, job, already_applied=application is not None)
    form = ApplyForm()
    return render_template(
        "student/job_detail.html",
        job=job,
        student=student,
        application=application,
        eligibility=eligibility,
        form=form,
    )


@student_bp.route("/jobs/<int:job_id>/apply", methods=["POST"])
@student_required
def apply(job_id: int):
    student = _profile_of_current_user()
    job = Job.query.get_or_404(job_id)

    if job.approval_status != "approved" or job.status != "approved":
        flash("This job posting is not open for applications.", "danger")
        return redirect(url_for("student.job_detail", job_id=job.id))

    form = ApplyForm()
    if not form.validate_on_submit():
        flash("Could not submit your application. Please try again.", "danger")
        return redirect(url_for("student.job_detail", job_id=job.id))

    try:
        application = apply_to_job(student, job, form.cover_letter.data, current_user())
    except ApplicationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("student.job_detail", job_id=job.id))

    flash(f"Application submitted for {job.title}.", "success")
    return redirect(url_for("student.application_detail", application_id=application.id))


@student_bp.route("/applications")
@student_required
def applications():
    student = _profile_of_current_user()
    page = get_page()
    status = (request.args.get("status") or "").strip()
    keyword = (request.args.get("q") or "").strip()

    query = Application.query.filter_by(student_id=student.id).join(Job, Application.job_id == Job.id)
    if status:
        query = query.filter(Application.status == status)
    if keyword:
        query = query.filter(Job.title.like(f"%{keyword}%"))

    sort = request.args.get("sort", "recent")
    if sort == "oldest":
        query = query.order_by(Application.applied_at.asc())
    elif sort == "status":
        query = query.order_by(Application.status.asc())
    else:
        query = query.order_by(Application.applied_at.desc())

    pagination = paginate(query, page, current_app.config["RECORDS_PER_PAGE"])
    return render_template("student/applications.html", pagination=pagination,
                           items=pagination.items, status=status, keyword=keyword)


@student_bp.route("/applications/<int:application_id>")
@student_required
def application_detail(application_id: int):
    student = _profile_of_current_user()
    application = Application.query.get_or_404(application_id)
    if application.student_id != student.id:
        abort(403, description="You can only view your own applications.")
    return render_template("student/application_detail.html", application=application)


@student_bp.route("/applications/<int:application_id>/withdraw", methods=["POST"])
@student_required
def withdraw(application_id: int):
    student = _profile_of_current_user()
    application = Application.query.get_or_404(application_id)
    try:
        withdraw_application(application, student)
    except ApplicationError as exc:
        flash(str(exc), "danger")
    else:
        flash("Application withdrawn.", "info")
    return redirect(url_for("student.application_detail", application_id=application.id))
