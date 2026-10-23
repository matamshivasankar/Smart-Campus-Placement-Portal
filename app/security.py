"""Session based authentication and role based authorisation helpers.

Authentication uses Flask's signed cookie session plus Werkzeug password
hashing (no third party identity provider, as required).  Authorisation is
enforced with explicit decorators applied to every protected route.
"""
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from werkzeug.exceptions import Forbidden

from .models import ROLE_ADMIN, ROLE_RECRUITER, ROLE_STUDENT, User

SESSION_USER_KEY = "uid"


# --------------------------------------------------------------------------
# Session helpers
# --------------------------------------------------------------------------
def login_user(user: User, remember: bool = False) -> None:
    session.clear()
    session[SESSION_USER_KEY] = user.id
    session["role"] = user.role
    session.permanent = True


def logout_user() -> None:
    session.clear()


def load_logged_in_user() -> None:
    """Populate ``g.user`` for the current request (``None`` when anonymous)."""
    g.user = None
    user_id = session.get(SESSION_USER_KEY)
    if user_id is None:
        return
    user = User.query.get(user_id)
    if user is None or not user.is_active:
        # Account deleted or deactivated after the session was created.
        logout_user()
        return
    g.user = user


def current_user() -> User | None:
    return getattr(g, "user", None)


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.remote_addr or "")[:45]


# --------------------------------------------------------------------------
# Decorators
# --------------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles: str):
    """Restrict a view to the given roles.  Anonymous users are sent to login."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if user.role not in roles:
                current_app.logger.warning(
                    "Access denied: user=%s role=%s path=%s", user.id, user.role, request.path
                )
                raise Forbidden(
                    description="Your account role is not allowed to open this page."
                )
            return view(*args, **kwargs)

        return wrapped

    return decorator


def student_required(view):
    return roles_required(ROLE_STUDENT)(view)


def recruiter_required(view):
    return roles_required(ROLE_RECRUITER)(view)


def admin_required(view):
    return roles_required(ROLE_ADMIN)(view)


def approved_recruiter_required(view):
    """Recruiters must be approved by the placement cell before acting."""

    @wraps(view)
    @recruiter_required
    def wrapped(*args, **kwargs):
        profile = current_user().recruiter_profile
        if profile is None or not profile.is_approved:
            abort(403, description="Your recruiter account is awaiting approval.")
        return view(*args, **kwargs)

    return wrapped
