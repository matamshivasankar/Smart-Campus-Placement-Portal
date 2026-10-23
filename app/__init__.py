"""Application factory for the Smart Campus Placement Portal."""
from __future__ import annotations

import logging
import os
from datetime import date, datetime

import click
from flask import Flask, g, jsonify, render_template, request

from .config import Config, ProductionConfig, get_config
from .extensions import csrf, db, migrate
from .models import Notification, User
from .security import current_user, load_logged_in_user


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    selected_config = get_config(config_name)
    secret = os.getenv("SECRET_KEY", "")
    if selected_config is ProductionConfig and (len(secret) < 32 or secret.startswith("change-me")):
        raise RuntimeError("Set a unique SECRET_KEY of at least 32 characters for production.")
    app.config.from_object(selected_config)
    if config_name == "testing":
        app.config["TESTING"] = True

    _ensure_directories(app)
    _register_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_template_helpers(app)
    _register_cli(app)
    _configure_logging(app)

    @app.before_request
    def _load_user():
        load_logged_in_user()

    app.logger.info("Database URI: %s", _redact(app.config["SQLALCHEMY_DATABASE_URI"]))
    return app


def _ensure_directories(app: Flask) -> None:
    app.config["INSTANCE_DIR"].mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)


def _register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Import models so that Flask-Migrate can see them.
    from . import models  # noqa: F401


def _register_blueprints(app: Flask) -> None:
    from .blueprints.admin import admin_bp
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.recruiter import recruiter_bp
    from .blueprints.student import student_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(recruiter_bp, url_prefix="/recruiter")
    app.register_blueprint(admin_bp, url_prefix="/admin")


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(error):  # pragma: no cover - rendered through tests
        return render_template("errors/403.html", error=error), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html", error=error), 404

    @app.errorhandler(413)
    def too_large(error):
        limit = app.config.get("MAX_RESUME_SIZE_MB", 5)
        return render_template(
            "errors/400.html",
            message=f"The uploaded file is larger than the {limit} MB limit.",
            error=error,
        ), 413

    @app.errorhandler(500)
    def server_error(error):  # pragma: no cover
        db.session.rollback()
        return render_template("errors/500.html", error=error), 500

    @app.errorhandler(Exception)
    def unhandled(error):  # pragma: no cover - safety net
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return error
        db.session.rollback()
        app.logger.exception("Unhandled error on %s", request.path)
        if request.path.startswith("/api/"):
            return jsonify({"error": "Internal server error"}), 500
        return render_template("errors/500.html", error=None), 500


def _register_template_helpers(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        user = current_user()
        unread = 0
        if user is not None:
            unread = Notification.query.filter_by(user_id=user.id, is_read=False).count()
        return {
            "current_user": user,
            "unread_notifications": unread,
            "today": date.today(),
            "current_year": date.today().year,
        }

    @app.template_filter("dt")
    def format_datetime(value, fmt: str = "%d %b %Y, %I:%M %p"):
        if not value:
            return "-"
        if isinstance(value, datetime):
            return value.strftime(fmt)
        return str(value)

    @app.template_filter("d")
    def format_date(value, fmt: str = "%d %b %Y"):
        if not value:
            return "-"
        if isinstance(value, (date, datetime)):
            return value.strftime(fmt)
        return str(value)

    @app.template_filter("num")
    def format_number(value):
        if value is None:
            return "-"
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)

    @app.template_filter("status_class")
    def status_class(status: str) -> str:
        mapping = {
            "Applied": "secondary",
            "Shortlisted": "info",
            "Interview Scheduled": "primary",
            "Selected": "success",
            "Rejected": "danger",
            "Withdrawn": "dark",
            "approved": "success",
            "pending": "warning",
            "rejected": "danger",
            "closed": "dark",
            "draft": "secondary",
            "Scheduled": "primary",
            "Completed": "success",
            "Cancelled": "dark",
        }
        return mapping.get(status or "", "secondary")


def _register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    @click.option("--drop", is_flag=True, help="Drop all existing tables first.")
    def init_db(drop: bool):
        """Create every table from the SQLAlchemy metadata."""
        if drop:
            click.confirm("This deletes ALL data. Continue?", abort=True)
            db.drop_all()
        db.create_all()
        click.echo(f"Schema created on {_redact(app.config['SQLALCHEMY_DATABASE_URI'])}")

    @app.cli.command("seed-db")
    @click.option("--with-demo-data/--admin-only", default=True,
                  help="Seed demo companies/jobs/applications in addition to the admin.")
    def seed_db(with_demo_data: bool):
        """Populate the database with reproducible sample data for local testing."""
        from .seed import seed_database

        summary = seed_database(with_demo_data=with_demo_data)
        for line in summary:
            click.echo(line)

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(email: str, password: str):
        """Create (or update) a placement officer / administrator account."""
        email = email.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            user.role = "admin"
            user.is_active = True
            user.set_password(password)
            db.session.commit()
            click.echo(f"Updated existing account {email} to role=admin.")
            return
        user = User(email=email, role="admin", is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created administrator {email}.")


def _configure_logging(app: Flask) -> None:
    if app.debug or app.testing:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    ))
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _redact(uri: str) -> str:
    """Hide the password when logging a connection string."""
    if "@" in uri and "://" in uri:
        scheme, rest = uri.split("://", 1)
        credentials, host = rest.split("@", 1)
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return uri


__all__ = ["create_app", "Config"]
