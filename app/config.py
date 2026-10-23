"""Configuration objects. All secrets and connection details come from the
environment (see .env.example) and never from source code."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def database_uri() -> str:
    """Use a persistent local SQLite file unless a database is explicitly configured."""
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        if configured.startswith("postgres://"):
            configured = "postgresql+psycopg://" + configured[len("postgres://"):]
        elif configured.startswith("postgresql://") and "+" not in configured.split(":", 1)[0]:
            configured = "postgresql+psycopg://" + configured[len("postgresql://"):]
        return configured
    return f"sqlite:///{(BASE_DIR / 'instance' / 'placement.db').as_posix()}"


class Config:
    """Base configuration shared by every environment."""

    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-insecure-key-change-me"

    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Uploads -----------------------------------------------------------
    INSTANCE_DIR = BASE_DIR / "instance"
    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    RESUMES_SUBDIR = "resumes"
    ALLOWED_RESUME_EXTENSIONS = {"pdf", "doc", "docx"}
    MAX_RESUME_SIZE_MB = int(os.getenv("MAX_RESUME_SIZE_MB", "5"))
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_RESUME_BUCKET = os.getenv("SUPABASE_RESUME_BUCKET")
    SUPABASE_SIGNED_URL_TTL = int(os.getenv("SUPABASE_SIGNED_URL_TTL", "300"))

    # Sessions ----------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = int(os.getenv("SESSION_LIFETIME_MINUTES", "120")) * 60

    # Pagination --------------------------------------------------------
    RECORDS_PER_PAGE = 10

    WTF_CSRF_TIME_LIMIT = None


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    """Production settings require a real key instead of the dev fallback."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(Config):
    """Used by the pytest suite.

    Tests use an isolated in-memory SQLite database by default.
    """

    TESTING = True
    WTF_CSRF_ENABLED = False
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config(name: str | None = None):
    name = name or os.getenv("FLASK_CONFIG", "default")
    return CONFIG_MAP.get(name, DevelopmentConfig)
