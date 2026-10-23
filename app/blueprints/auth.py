"""Registration, login, logout and password management."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..forms import (
    ChangePasswordForm,
    LoginForm,
    RecruiterRegistrationForm,
    StudentRegistrationForm,
)
from ..models import (
    APPROVAL_PENDING,
    ROLE_ADMIN,
    ROLE_RECRUITER,
    ROLE_STUDENT,
    Company,
    RecruiterProfile,
    StudentProfile,
    StudentSkill,
    User,
    utcnow,
)
from ..security import current_user, login_required, login_user, logout_user
from ..services.audit import log_action
from ..utils import notify, parse_skill_list

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")


def _safe_next(target: str | None) -> str | None:
    """Only allow same-site relative redirects (prevents open redirect abuse)."""
    if not target:
        return None
    if target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _dashboard_for(user: User) -> str:
    if user.role == ROLE_ADMIN:
        return url_for("admin.dashboard")
    if user.role == ROLE_RECRUITER:
        return url_for("recruiter.dashboard")
    return url_for("student.dashboard")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(_dashboard_for(current_user()))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(form.password.data):
            # Generic message: never reveal whether the email exists.
            flash("Invalid email address or password.", "danger")
        elif not user.is_active:
            flash("This account has been deactivated. Contact the placement cell.", "danger")
        else:
            login_user(user, remember=form.remember.data)
            user.last_login_at = utcnow()
            db.session.commit()
            log_action(user, "auth.login", "User", user.id, f"role={user.role}")
            flash(f"Welcome back, {user.display_name}.", "success")
            return redirect(_safe_next(request.args.get("next")) or _dashboard_for(user))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    user = current_user()
    if user is not None:
        log_action(user, "auth.logout", "User", user.id)
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.home"))


@auth_bp.route("/register/student", methods=["GET", "POST"])
def register_student():
    if current_user() is not None:
        return redirect(_dashboard_for(current_user()))

    form = StudentRegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors.append("An account with this email already exists.")
        elif StudentProfile.query.filter_by(roll_number=form.roll_number.data.strip()).first():
            form.roll_number.errors.append("This roll number is already registered.")
        else:
            user = User(email=email, role=ROLE_STUDENT, is_active=True)
            user.set_password(form.password.data)
            profile = StudentProfile(
                user=user,
                full_name=form.full_name.data.strip(),
                roll_number=form.roll_number.data.strip(),
                department=form.department.data,
                degree=form.degree.data.strip(),
                cgpa=form.cgpa.data,
                graduation_year=form.graduation_year.data,
                phone=(form.phone.data or "").strip() or None,
            )
            for skill in parse_skill_list(form.skills.data):
                profile.skills.append(StudentSkill(skill=skill))

            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("That email or roll number is already registered.", "danger")
                return render_template("auth/register_student.html", form=form)

            log_action(user, "auth.register", "User", user.id, "role=student")
            notify(
                user.id,
                "Welcome to the placement portal",
                "Complete your profile and upload a resume so you can apply for jobs.",
                link="/student/profile",
                commit=True,
            )
            login_user(user)
            flash("Student account created. Please complete your profile and resume.", "success")
            return redirect(url_for("student.profile"))

    return render_template("auth/register_student.html", form=form)


@auth_bp.route("/register/recruiter", methods=["GET", "POST"])
def register_recruiter():
    if current_user() is not None:
        return redirect(_dashboard_for(current_user()))

    form = RecruiterRegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors.append("An account with this email already exists.")
        else:
            company_name = form.company_name.data.strip()
            company = Company.query.filter(db.func.lower(Company.name) == company_name.lower()).first()
            if company is None:
                company = Company(
                    name=company_name,
                    website=(form.company_website.data or "").strip() or None,
                    industry=(form.company_industry.data or "").strip() or None,
                    location=(form.company_location.data or "").strip() or None,
                )
                db.session.add(company)
                db.session.flush()

            user = User(email=email, role=ROLE_RECRUITER, is_active=True)
            user.set_password(form.password.data)
            profile = RecruiterProfile(
                user=user,
                full_name=form.full_name.data.strip(),
                designation=(form.designation.data or "").strip() or None,
                phone=(form.phone.data or "").strip() or None,
                company_id=company.id,
                approval_status=APPROVAL_PENDING,
            )
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("That email address is already registered.", "danger")
                return render_template("auth/register_recruiter.html", form=form)

            log_action(user, "auth.register", "User", user.id, "role=recruiter")
            for admin in User.query.filter_by(role=ROLE_ADMIN).all():
                notify(
                    admin.id,
                    "New recruiter awaiting approval",
                    f"{profile.full_name} ({company.name}) registered and needs approval.",
                    link="/admin/recruiters?status=pending",
                    commit=False,
                )
            db.session.commit()

            login_user(user)
            flash(
                "Recruiter account created. A placement officer must approve your account "
                "before you can post jobs.",
                "info",
            )
            return redirect(url_for("recruiter.dashboard"))

    return render_template("auth/register_recruiter.html", form=form)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not user.check_password(form.current_password.data):
            form.current_password.errors.append("Your current password is incorrect.")
        else:
            user.set_password(form.new_password.data)
            db.session.commit()
            log_action(user, "auth.password_change", "User", user.id)
            flash("Your password has been updated.", "success")
            return redirect(_dashboard_for(user))
    return render_template("auth/change_password.html", form=form)
