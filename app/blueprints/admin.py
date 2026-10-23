"""Placement officer / administrator console."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from ..extensions import db
from ..forms import RejectForm
from ..models import (
    APPLICATION_STATUSES,
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    JOB_APPROVED,
    JOB_CLOSED,
    JOB_PENDING,
    Application,
    AuditLog,
    Company,
    Interview,
    Job,
    RecruiterProfile,
    StudentProfile,
    User,
    utcnow,
)
from ..security import admin_required, current_user
from ..services.audit import log_action
from ..services.stats import admin_stats
from ..utils import get_page, notify

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    stats = admin_stats()
    pending_recruiter_rows = (
        RecruiterProfile.query
        .filter_by(approval_status=APPROVAL_PENDING)
        .order_by(RecruiterProfile.created_at.desc())
        .limit(5)
        .all()
    )
    pending_job_rows = (
        Job.query
        .filter_by(approval_status=APPROVAL_PENDING)
        .order_by(Job.created_at.desc())
        .limit(5)
        .all()
    )
    recent_audit = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()
    recent_applications = (
        Application.query.order_by(Application.applied_at.desc()).limit(6).all()
    )
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        pending_recruiters=pending_recruiter_rows,
        pending_jobs=pending_job_rows,
        recent_audit=recent_audit,
        recent_applications=recent_applications,
    )


# --------------------------------------------------------------------------
# Recruiter approvals and account management
# --------------------------------------------------------------------------
@admin_bp.route("/recruiters")
@admin_required
def recruiters():
    page = get_page()
    query = RecruiterProfile.query.join(User, RecruiterProfile.user_id == User.id)
    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(RecruiterProfile.approval_status == status)
    keyword = (request.args.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(RecruiterProfile.full_name.like(like),
                                    User.email.like(like),
                                    RecruiterProfile.designation.like(like)))
    company = (request.args.get("company") or "").strip()
    if company:
        query = query.join(Company, RecruiterProfile.company_id == Company.id).filter(
            Company.name.like(f"%{company}%")
        )
    query = query.order_by(RecruiterProfile.created_at.desc())
    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)
    return render_template("admin/recruiters.html", pagination=pagination,
                           items=pagination.items, status=status, keyword=keyword,
                           reject_form=RejectForm())


@admin_bp.route("/recruiters/<int:recruiter_id>")
@admin_required
def recruiter_detail(recruiter_id: int):
    recruiter = RecruiterProfile.query.get_or_404(recruiter_id)
    jobs = Job.query.filter_by(recruiter_id=recruiter.id).order_by(Job.created_at.desc()).all()
    job_ids = [j.id for j in jobs]
    application_count = 0
    if job_ids:
        application_count = Application.query.filter(Application.job_id.in_(job_ids)).count()
    audit = (
        AuditLog.query.filter_by(actor_user_id=recruiter.user_id)
        .order_by(AuditLog.created_at.desc()).limit(20).all()
    )
    return render_template("admin/recruiter_detail.html", recruiter=recruiter, jobs=jobs,
                           application_count=application_count, audit=audit,
                           reject_form=RejectForm())


@admin_bp.route("/recruiters/<int:recruiter_id>/approve", methods=["POST"])
@admin_required
def approve_recruiter(recruiter_id: int):
    recruiter = RecruiterProfile.query.get_or_404(recruiter_id)
    if recruiter.approval_status == APPROVAL_APPROVED:
        flash("This recruiter is already approved.", "info")
        return redirect(url_for("admin.recruiter_detail", recruiter_id=recruiter.id))

    recruiter.approval_status = APPROVAL_APPROVED
    recruiter.rejection_reason = None
    recruiter.approved_by_id = current_user().id
    recruiter.approved_at = utcnow()
    notify(
        recruiter.user_id,
        "Recruiter account approved",
        "Your account has been approved. You can now post job openings.",
        link="/recruiter/jobs/new",
        commit=False,
    )
    log_action(current_user(), "recruiter.approve", "RecruiterProfile", recruiter.id,
               f"company={recruiter.company.name if recruiter.company else 'n/a'}", commit=False)
    db.session.commit()
    flash(f"{recruiter.full_name} has been approved.", "success")
    return redirect(request.referrer or url_for("admin.recruiters"))


@admin_bp.route("/recruiters/<int:recruiter_id>/reject", methods=["POST"])
@admin_required
def reject_recruiter(recruiter_id: int):
    recruiter = RecruiterProfile.query.get_or_404(recruiter_id)
    form = RejectForm()
    if not form.validate_on_submit():
        flash("Provide a reason (at least 5 characters) for rejecting this registration.", "danger")
        return redirect(url_for("admin.recruiter_detail", recruiter_id=recruiter.id))

    recruiter.approval_status = APPROVAL_REJECTED
    recruiter.rejection_reason = form.reason.data.strip()
    recruiter.approved_by_id = current_user().id
    recruiter.approved_at = utcnow()
    notify(
        recruiter.user_id,
        "Recruiter registration rejected",
        f"Reason: {recruiter.rejection_reason}",
        link="/recruiter/dashboard",
        commit=False,
    )
    log_action(current_user(), "recruiter.reject", "RecruiterProfile", recruiter.id,
               recruiter.rejection_reason, commit=False)
    db.session.commit()
    flash(f"{recruiter.full_name}'s registration was rejected.", "warning")
    return redirect(request.referrer or url_for("admin.recruiters"))


@admin_bp.route("/students")
@admin_required
def students():
    page = get_page()
    query = StudentProfile.query.join(User, StudentProfile.user_id == User.id)

    department = (request.args.get("department") or "").strip()
    if department:
        query = query.filter(StudentProfile.department == department)
    batch = (request.args.get("batch") or "").strip()
    if batch.isdigit():
        query = query.filter(StudentProfile.graduation_year == int(batch))
    keyword = (request.args.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(StudentProfile.full_name.like(like),
                                    StudentProfile.roll_number.like(like),
                                    User.email.like(like)))
    placed = (request.args.get("placed") or "").strip()
    if placed == "1":
        subquery = (
            db.session.query(Application.student_id)
            .filter(Application.status == "Selected").subquery()
        )
        query = query.filter(StudentProfile.id.in_(db.select(subquery.c.student_id)))
    elif placed == "0":
        subquery = (
            db.session.query(Application.student_id)
            .filter(Application.status == "Selected").subquery()
        )
        query = query.filter(~StudentProfile.id.in_(db.select(subquery.c.student_id)))

    sort = request.args.get("sort", "name")
    if sort == "cgpa":
        query = query.order_by(StudentProfile.cgpa.desc())
    elif sort == "recent":
        query = query.order_by(StudentProfile.created_at.desc())
    else:
        query = query.order_by(StudentProfile.full_name.asc())

    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)

    departments = [r[0] for r in db.session.query(StudentProfile.department)
                   .distinct().order_by(StudentProfile.department).all()]
    batches = [r[0] for r in db.session.query(StudentProfile.graduation_year)
               .distinct().order_by(StudentProfile.graduation_year).all()]

    return render_template("admin/students.html", pagination=pagination,
                           items=pagination.items, departments=departments, batches=batches,
                           filters=request.args)


@admin_bp.route("/students/<int:student_id>")
@admin_required
def student_detail(student_id: int):
    student = StudentProfile.query.get_or_404(student_id)
    applications = (
        Application.query.filter_by(student_id=student.id)
        .order_by(Application.applied_at.desc()).all()
    )
    interviews = (
        Interview.query.join(Application, Interview.application_id == Application.id)
        .filter(Application.student_id == student.id)
        .order_by(Interview.scheduled_at.desc()).all()
    )
    return render_template("admin/student_detail.html", student=student,
                           applications=applications, interviews=interviews)


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_user_active(user_id: int):
    user = User.query.get_or_404(user_id)
    if user.id == current_user().id:
        flash("You cannot deactivate your own administrator account.", "danger")
        return redirect(request.referrer or url_for("admin.dashboard"))
    if user.is_admin:
        flash("Administrator accounts can only be managed from the database.", "warning")
        return redirect(request.referrer or url_for("admin.dashboard"))

    user.is_active = not user.is_active
    log_action(current_user(), "user.toggle_active", "User", user.id,
               f"is_active={user.is_active}", commit=False)
    notify(
        user.id,
        "Account status changed",
        "Your account was activated by the placement cell." if user.is_active
        else "Your account was deactivated by the placement cell.",
        commit=False,
    )
    db.session.commit()
    flash(f"{user.display_name} is now {'active' if user.is_active else 'deactivated'}.",
          "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


# --------------------------------------------------------------------------
# Job moderation
# --------------------------------------------------------------------------
@admin_bp.route("/jobs")
@admin_required
def jobs():
    page = get_page()
    query = Job.query.join(Company, Job.company_id == Company.id)

    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(Job.status == status)
    approval = (request.args.get("approval") or "").strip()
    if approval:
        query = query.filter(Job.approval_status == approval)
    company = (request.args.get("company") or "").strip()
    if company:
        query = query.filter(Company.name.like(f"%{company}%"))
    keyword = (request.args.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(Job.title.like(like), Job.location.like(like)))
    batch = (request.args.get("batch") or "").strip()
    if batch.isdigit():
        query = query.filter(Job.eligible_graduation_year == int(batch))

    sort = request.args.get("sort", "newest")
    if sort == "deadline":
        query = query.order_by(Job.deadline.asc())
    else:
        query = query.order_by(Job.created_at.desc())

    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)
    counts = dict(
        db.session.query(Job.id, db.func.count(Application.id))
        .outerjoin(Application, Application.job_id == Job.id)
        .group_by(Job.id).all()
    )
    return render_template("admin/jobs.html", pagination=pagination, items=pagination.items,
                           counts=counts, filters=request.args, reject_form=RejectForm())


@admin_bp.route("/jobs/<int:job_id>")
@admin_required
def job_detail(job_id: int):
    job = Job.query.get_or_404(job_id)
    counts = dict(
        db.session.query(Application.status, db.func.count(Application.id))
        .filter(Application.job_id == job.id)
        .group_by(Application.status).all()
    )
    applications = (
        Application.query.filter_by(job_id=job.id)
        .order_by(Application.applied_at.desc()).all()
    )
    return render_template("admin/job_detail.html", job=job, counts=counts,
                           applications=applications, reject_form=RejectForm())


@admin_bp.route("/jobs/<int:job_id>/approve", methods=["POST"])
@admin_required
def approve_job(job_id: int):
    job = Job.query.get_or_404(job_id)
    if job.deadline < date.today():
        flash("This posting's deadline has already passed; ask the recruiter to extend it.", "warning")
        return redirect(url_for("admin.job_detail", job_id=job.id))

    job.approval_status = APPROVAL_APPROVED
    job.status = JOB_APPROVED
    job.approved_by_id = current_user().id
    job.approved_at = utcnow()
    job.rejection_reason = None
    notify(
        job.recruiter.user_id,
        "Job posting approved",
        f"'{job.title}' is now visible to eligible students.",
        link=f"/recruiter/jobs/{job.id}",
        commit=False,
    )
    log_action(current_user(), "job.approve", "Job", job.id, f"title={job.title}", commit=False)
    db.session.commit()
    flash(f"'{job.title}' approved and published.", "success")
    return redirect(request.referrer or url_for("admin.jobs"))


@admin_bp.route("/jobs/<int:job_id>/reject", methods=["POST"])
@admin_required
def reject_job(job_id: int):
    job = Job.query.get_or_404(job_id)
    form = RejectForm()
    if not form.validate_on_submit():
        flash("Provide a reason (at least 5 characters) for rejecting this posting.", "danger")
        return redirect(url_for("admin.job_detail", job_id=job.id))

    job.approval_status = APPROVAL_REJECTED
    job.status = "rejected"
    job.rejection_reason = form.reason.data.strip()
    job.approved_by_id = current_user().id
    job.approved_at = utcnow()
    notify(
        job.recruiter.user_id,
        "Job posting rejected",
        f"'{job.title}' was rejected. Reason: {job.rejection_reason}",
        link=f"/recruiter/jobs/{job.id}",
        commit=False,
    )
    log_action(current_user(), "job.reject", "Job", job.id, job.rejection_reason, commit=False)
    db.session.commit()
    flash(f"'{job.title}' rejected.", "warning")
    return redirect(request.referrer or url_for("admin.jobs"))


@admin_bp.route("/jobs/<int:job_id>/deactivate", methods=["POST"])
@admin_required
def deactivate_job(job_id: int):
    job = Job.query.get_or_404(job_id)
    if job.status == JOB_CLOSED:
        flash("This posting is already closed.", "info")
    else:
        job.status = JOB_CLOSED
        job.closed_at = utcnow()
        notify(
            job.recruiter.user_id,
            "Job posting deactivated",
            f"Placement policy review has closed '{job.title}'.",
            link=f"/recruiter/jobs/{job.id}",
            commit=False,
        )
        log_action(current_user(), "job.deactivate", "Job", job.id, commit=False)
        db.session.commit()
        flash(f"'{job.title}' has been closed.", "success")
    return redirect(request.referrer or url_for("admin.jobs"))


# --------------------------------------------------------------------------
# Application monitoring & reports
# --------------------------------------------------------------------------
def _applications_query(args):
    """Shared, fully parameterised filter used by the applications page and CSV export."""
    query = (
        Application.query
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .join(StudentProfile, Application.student_id == StudentProfile.id)
    )
    company = (args.get("company") or "").strip()
    if company:
        query = query.filter(Company.name.like(f"%{company}%"))
    job_id = (args.get("job_id") or "").strip()
    if job_id.isdigit():
        query = query.filter(Job.id == int(job_id))
    job_title = (args.get("job") or "").strip()
    if job_title:
        query = query.filter(Job.title.like(f"%{job_title}%"))
    department = (args.get("department") or "").strip()
    if department:
        query = query.filter(StudentProfile.department == department)
    batch = (args.get("batch") or "").strip()
    if batch.isdigit():
        query = query.filter(StudentProfile.graduation_year == int(batch))
    status = (args.get("status") or "").strip()
    if status:
        query = query.filter(Application.status == status)
    keyword = (args.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(StudentProfile.full_name.like(like),
                                    StudentProfile.roll_number.like(like),
                                    Job.title.like(like),
                                    Company.name.like(like)))
    return query


def _date_filters(args, query):
    start = args.get("start")
    end = args.get("end")
    if start:
        try:
            query = query.filter(Application.applied_at >= datetime.strptime(start, "%Y-%m-%d"))
        except ValueError:
            pass
    if end:
        try:
            query = query.filter(
                Application.applied_at < datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            )
        except ValueError:
            pass
    return query


@admin_bp.route("/applications")
@admin_required
def applications():
    page = get_page()
    query = _date_filters(request.args, _applications_query(request.args))
    query = query.order_by(Application.applied_at.desc())
    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"],
                             error_out=False)

    companies = [r[0] for r in db.session.query(Company.name).distinct().order_by(Company.name).all()]
    departments = [r[0] for r in db.session.query(StudentProfile.department)
                   .distinct().order_by(StudentProfile.department).all()]
    batches = [r[0] for r in db.session.query(StudentProfile.graduation_year)
               .distinct().order_by(StudentProfile.graduation_year).all()]
    jobs_list = db.session.query(Job.id, Job.title, Company.name).join(
        Company, Job.company_id == Company.id).order_by(Job.title).all()

    return render_template("admin/applications.html", pagination=pagination,
                           items=pagination.items, companies=companies,
                           departments=departments, batches=batches, jobs_list=jobs_list,
                           statuses=APPLICATION_STATUSES, filters=request.args)


@admin_bp.route("/applications/<int:application_id>")
@admin_required
def application_detail(application_id: int):
    application = Application.query.get_or_404(application_id)
    return render_template("admin/application_detail.html", application=application)


@admin_bp.route("/reports")
@admin_required
def reports():
    """Placement report built entirely from stored applications and interviews."""
    query = _date_filters(request.args, _applications_query(request.args))
    applications = query.order_by(Application.applied_at.desc()).limit(500).all()

    status_counts = dict(
        db.session.query(Application.status, db.func.count(Application.id))
        .group_by(Application.status).all()
    )

    filters = request.args

    by_company = (
        db.session.query(Company.name, db.func.count(db.distinct(Job.id)).label("jobs"),
                         db.func.count(Application.id).label("applications"),
                         db.func.count(db.distinct(Application.student_id)).label("students"))
        .outerjoin(Job, Job.company_id == Company.id)
        .outerjoin(Application, Application.job_id == Job.id)
        .group_by(Company.name)
        .order_by(db.func.count(Application.id).desc())
        .all()
    )

    # Department / batch breakdown honouring the active filters.
    breakdown = (
        db.session.query(
            StudentProfile.department,
            StudentProfile.graduation_year,
            Application.status,
            db.func.count(Application.id),
        )
        .join(Application, Application.student_id == StudentProfile.id)
        .join(Job, Application.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .group_by(StudentProfile.department, StudentProfile.graduation_year, Application.status)
        .order_by(StudentProfile.department, StudentProfile.graduation_year)
        .all()
    )

    selected_students = sorted(
        {app.student for app in Application.query.filter(Application.status == "Selected").all()},
        key=lambda s: s.full_name,
    )

    return render_template("admin/reports.html", applications=applications,
                           status_counts=status_counts, by_company=by_company,
                           breakdown=breakdown, selected_students=selected_students,
                           statuses=APPLICATION_STATUSES, filters=filters)


@admin_bp.route("/reports/export.csv")
@admin_required
def export_applications_csv():
    query = _date_filters(request.args, _applications_query(request.args))
    query = query.order_by(Application.applied_at.desc())

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Application ID", "Student", "Roll number", "Department", "Degree", "CGPA",
        "Graduation year", "Company", "Job title", "Application status",
        "Applied at", "Latest interview", "Latest interview result",
    ])
    for app in query.limit(5000).all():
        interview = app.interviews[-1] if app.interviews else None
        writer.writerow([
            app.id,
            app.student.full_name,
            app.student.roll_number,
            app.student.department,
            app.student.degree,
            f"{float(app.student.cgpa):.2f}" if app.student.cgpa is not None else "",
            app.student.graduation_year or "",
            app.job.company.name,
            app.job.title,
            app.status,
            app.applied_at.strftime("%Y-%m-%d %H:%M"),
            interview.scheduled_at.strftime("%Y-%m-%d %H:%M") if interview else "",
            interview.result if interview else "",
        ])

    log_action(current_user(), "report.export", "Application", None,
               f"filters={dict(request.args)}")
    filename = f"placement_applications_{date.today().isoformat()}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/audit-logs")
@admin_required
def audit_logs():
    page = get_page()
    query = AuditLog.query

    action = (request.args.get("action") or "").strip()
    if action:
        query = query.filter(AuditLog.action.like(f"%{action}%"))
    entity = (request.args.get("entity") or "").strip()
    if entity:
        query = query.filter(AuditLog.entity_type == entity)
    actor = (request.args.get("actor") or "").strip()
    if actor:
        query = query.join(User, AuditLog.actor_user_id == User.id).filter(
            User.email.like(f"%{actor}%")
        )
    start = (request.args.get("start") or "").strip()
    if start:
        try:
            query = query.filter(AuditLog.created_at >= datetime.strptime(start, "%Y-%m-%d"))
        except ValueError:
            pass
    end = (request.args.get("end") or "").strip()
    if end:
        try:
            query = query.filter(AuditLog.created_at < datetime.strptime(end, "%Y-%m-%d")
                                 + timedelta(days=1))
        except ValueError:
            pass

    query = query.order_by(AuditLog.created_at.desc())
    pagination = db.paginate(query, page=page,
                             per_page=current_app.config["RECORDS_PER_PAGE"] * 2,
                             error_out=False)
    entities = [r[0] for r in db.session.query(AuditLog.entity_type)
                .distinct().order_by(AuditLog.entity_type).all()]
    return render_template("admin/audit_logs.html", pagination=pagination,
                           items=pagination.items, entities=entities, filters=request.args)
