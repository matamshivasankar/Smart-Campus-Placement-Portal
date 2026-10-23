"""Resume upload / download handling with strict validation."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx"}

# Leading bytes of the formats we accept, used as a light content sniff.
_MAGIC_SIGNATURES = {
    b"%PDF": "pdf",
    b"\xd0\xcf\x11\xe0": "doc",       # legacy OLE compound file
    b"PK\x03\x04": "docx",            # zip container (docx)
}


class ResumeError(Exception):
    """Raised when an uploaded resume fails validation."""


def allowed_extension(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in {
        e.strip() for e in current_app.config.get("ALLOWED_RESUME_EXTENSIONS", ALLOWED_EXTENSIONS)
    }


def _resume_dir(user_id: int) -> Path:
    base = Path(current_app.config["UPLOAD_FOLDER"]) / current_app.config.get(
        "RESUMES_SUBDIR", "resumes"
    ) / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def validate_resume(file_storage) -> str:
    """Validate a Werkzeug FileStorage and return the normalised file extension."""
    if file_storage is None or not file_storage.filename:
        raise ResumeError("Choose a resume file to upload.")

    filename = file_storage.filename
    if not allowed_extension(filename):
        raise ResumeError("Only PDF, DOC and DOCX resume files are accepted.")

    if "/" in filename or "\\" in filename or ".." in filename:
        raise ResumeError("The file name contains invalid characters.")

    ext = filename.rsplit(".", 1)[1].lower()
    max_bytes = int(current_app.config.get("MAX_RESUME_SIZE_MB", 5)) * 1024 * 1024

    head = file_storage.stream.read(8)
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)

    if size == 0:
        raise ResumeError("The uploaded file is empty.")
    if size > max_bytes:
        raise ResumeError(
            f"Resume must be smaller than {current_app.config.get('MAX_RESUME_SIZE_MB', 5)} MB."
        )

    matched = [value for signature, value in _MAGIC_SIGNATURES.items() if head.startswith(signature)]
    if not matched:
        raise ResumeError("The file content does not look like a PDF or Word document.")
    if ext not in matched and not (ext == "docx" and "docx" in matched):
        raise ResumeError("The file extension does not match its content.")
    return ext


def save_resume(file_storage, user_id: int) -> tuple[str, str]:
    """Store locally or in the configured private Supabase bucket."""
    ext = validate_resume(file_storage)
    original = secure_filename(file_storage.filename) or f"resume.{ext}"
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    if supabase_storage_enabled():
        object_key = f"{user_id}/{stored_name}"
        file_storage.stream.seek(0)
        supabase_client().storage.from_(current_app.config["SUPABASE_RESUME_BUCKET"]).upload(
            path=object_key, file=file_storage.stream.read(),
            file_options={"content-type": file_storage.mimetype or "application/octet-stream",
                          "upsert": "false"},
        )
        return object_key, original[:255]
    destination = _resume_dir(user_id) / stored_name
    file_storage.stream.seek(0)
    file_storage.save(destination)
    return stored_name, original[:255]


def supabase_storage_enabled() -> bool:
    return bool(current_app.config.get("SUPABASE_URL") and
                current_app.config.get("SUPABASE_SERVICE_ROLE_KEY") and
                current_app.config.get("SUPABASE_RESUME_BUCKET"))


def supabase_client():
    try:
        from supabase import create_client
    except ImportError as exc:
        raise ResumeError("Install the optional Supabase dependency to enable cloud resume storage.") from exc
    return create_client(current_app.config["SUPABASE_URL"],
                         current_app.config["SUPABASE_SERVICE_ROLE_KEY"])


def resume_path(user_id: int, stored_name: str) -> Path | None:
    """Resolve a stored resume path, refusing anything that escapes the upload root."""
    if not stored_name:
        return None
    safe_name = os.path.basename(stored_name)
    if safe_name != stored_name or ".." in stored_name:
        return None
    base = (Path(current_app.config["UPLOAD_FOLDER"])
            / current_app.config.get("RESUMES_SUBDIR", "resumes")).resolve()
    candidate = (_resume_dir(user_id) / safe_name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def delete_resume(user_id: int, stored_name: str | None) -> None:
    if not stored_name:
        return
    if supabase_storage_enabled() and stored_name.startswith(f"{user_id}/"):
        supabase_client().storage.from_(current_app.config["SUPABASE_RESUME_BUCKET"]).remove([stored_name])
        return
    path = resume_path(user_id, stored_name)
    if path:
        try:
            path.unlink()
        except OSError:  # pragma: no cover - file already gone
            pass


def signed_resume_url(user_id: int, stored_name: str) -> str | None:
    if not supabase_storage_enabled() or not stored_name.startswith(f"{user_id}/"):
        return None
    result = supabase_client().storage.from_(current_app.config["SUPABASE_RESUME_BUCKET"]).create_signed_url(
        stored_name, int(current_app.config.get("SUPABASE_SIGNED_URL_TTL", 300)),
        {"download": True},
    )
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl")
    return getattr(result, "signed_url", None) or getattr(result, "signedURL", None)
