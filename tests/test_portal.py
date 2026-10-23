from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import pytest

from app.extensions import db
from app.models import Application, Interview, Job, StudentProfile, User
from app.services.applications import (
    ApplicationError,
    apply_to_job,
    schedule_interview,
    set_application_status,
)
from app.services.eligibility import evaluate_eligibility


def login_as(client, user_id):
    with client.session_transaction() as session:
        session["uid"] = user_id


def test_public_pages_and_role_dashboards_render(app, records):
    client = app.test_client()
    for path in ["/", "/jobs", "/placements", "/auth/login", "/auth/register/student"]:
        response = client.get(path)
        assert response.status_code == 200, path

    login_as(client, records["student_user_id"])
    for path in ["/student/dashboard", "/student/profile", "/student/jobs",
                 f"/student/jobs/{records['job_id']}", "/student/applications"]:
        response = client.get(path)
        assert response.status_code == 200, path

    login_as(client, records["recruiter_user_id"])
    for path in ["/recruiter/dashboard", "/recruiter/company", "/recruiter/jobs",
                 "/recruiter/jobs/new", f"/recruiter/jobs/{records['job_id']}",
                 f"/recruiter/jobs/{records['job_id']}/applicants", "/recruiter/interviews"]:
        response = client.get(path)
        assert response.status_code == 200, path

    login_as(client, records["admin_id"])
    for path in ["/admin/dashboard", "/admin/recruiters", f"/admin/recruiters/{records['recruiter_id']}",
                 "/admin/students", f"/admin/students/{records['student_id']}", "/admin/jobs",
                 f"/admin/jobs/{records['job_id']}", "/admin/applications", "/admin/reports",
                 "/admin/audit-logs"]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_role_authorization_blocks_student_from_admin(app, records):
    client = app.test_client()
    login_as(client, records["student_user_id"])
    assert client.get("/admin/dashboard").status_code == 403


def test_student_registration_and_login(app):
    client = app.test_client()
    payload = {
        "full_name": "New Student", "email": "new@student.example",
        "roll_number": "NEW2026", "department": "Computer Science and Engineering",
        "degree": "B.Tech", "cgpa": "8.25", "graduation_year": str(date.today().year + 1),
        "skills": "Python, SQL", "password": "StrongPass123",
        "confirm_password": "StrongPass123", "submit": "Create student account",
    }
    response = client.post("/auth/register/student", data=payload)
    assert response.status_code == 302
    assert client.get("/student/profile").status_code == 200
    client.post("/auth/logout")
    response = client.post("/auth/login", data={
        "email": "new@student.example", "password": "StrongPass123", "submit": "Log in",
    })
    assert response.status_code == 302
    assert client.get("/student/dashboard").status_code == 200


def test_resume_upload_and_download_authorization(app, records):
    client = app.test_client()
    login_as(client, records["student_user_id"])
    response = client.post("/student/resume", data={
        "resume": (BytesIO(b"%PDF-1.4 test resume"), "my_resume.pdf"),
        "submit": "Upload resume",
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    download = client.get(f"/resumes/{records['student_id']}")
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment;")

    login_as(client, records["recruiter_user_id"])
    assert client.get(f"/resumes/{records['student_id']}").status_code == 403


def test_recruiter_and_job_approval_workflow(app, records):
    client = app.test_client()
    registration = {
        "full_name": "New Recruiter", "email": "hiring@example.com",
        "designation": "Talent Partner", "company_name": "Hiring Co",
        "company_location": "Pune", "company_industry": "Software",
        "password": "RecruiterPass123", "confirm_password": "RecruiterPass123",
        "submit": "Register recruiter account",
    }
    assert client.post("/auth/register/recruiter", data=registration).status_code == 302
    assert client.get("/recruiter/jobs/new").status_code == 403

    with app.app_context():
        recruiter_user = User.query.filter_by(email="hiring@example.com").first()
        recruiter_id, recruiter_user_id = recruiter_user.recruiter_profile.id, recruiter_user.id

    login_as(client, records["admin_id"])
    assert client.post(f"/admin/recruiters/{recruiter_id}/approve").status_code == 302
    login_as(client, recruiter_user_id)
    job_payload = {
        "title": "Graduate Developer", "description": "Build and maintain software.",
        "location": "Pune", "employment_type": "Full time", "openings": "2",
        "currency": "INR", "min_cgpa": "7.0",
        "eligible_graduation_year": str(date.today().year + 1),
        "required_departments": "Computer Science and Engineering", "max_backlogs": "0",
        "required_skills": "Python", "deadline": (date.today() + timedelta(days=15)).isoformat(),
        "submit": "Save job posting",
    }
    assert client.post("/recruiter/jobs/new", data=job_payload).status_code == 302

    with app.app_context():
        job = Job.query.filter_by(title="Graduate Developer").one()
        job_id = job.id
        assert job.approval_status == "pending"

    login_as(client, records["admin_id"])
    assert client.post(f"/admin/jobs/{job_id}/approve").status_code == 302
    with app.app_context():
        assert db.session.get(Job, job_id).approval_status == "approved"


def test_eligibility_application_uniqueness_and_workflow(app, records):
    with app.app_context():
        student = db.session.get(StudentProfile, records["student_id"])
        job = db.session.get(Job, records["job_id"])
        recruiter_user = db.session.get(User, records["recruiter_user_id"])
        result = evaluate_eligibility(student, job)
        assert result.eligible
        application = apply_to_job(student, job, "I am interested.", student.user)
        assert application.status == "Applied"
        with pytest.raises(ApplicationError, match="already applied"):
            apply_to_job(student, job, None, student.user)

        set_application_status(application, "Shortlisted", recruiter_user)
        interview = schedule_interview(
            application, recruiter_user, round_name="Technical", 
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2), duration_minutes=45,
            mode="Online", venue=None, meeting_link="https://meet.example.com/test",
            interviewer_name="Hiring team",
        )
        assert application.status == "Interview Scheduled"
        assert interview.status == "Scheduled"
        assert Interview.query.count() == 1
        application_id, interview_id = application.id, interview.id

    client = app.test_client()
    login_as(client, records["recruiter_user_id"])
    assert client.get(f"/recruiter/applications/{application_id}").status_code == 200
    assert client.get(f"/recruiter/interviews/{interview_id}").status_code == 200
    login_as(client, records["student_user_id"])
    assert client.get(f"/student/applications/{application_id}").status_code == 200
    login_as(client, records["admin_id"])
    assert client.get(f"/admin/applications/{application_id}").status_code == 200


def test_deadline_and_missing_resume_are_checked(app, records):
    from app.models import utcnow

    with app.app_context():
        student = db.session.get(StudentProfile, records["student_id"])
        job = db.session.get(Job, records["job_id"])
        job.deadline = date.today() - timedelta(days=1)
        assert not evaluate_eligibility(student, job).eligible
        with pytest.raises(ApplicationError, match="deadline"):
            apply_to_job(student, job, None, student.user)
        job.deadline = date.today() + timedelta(days=1)
        student.resume_filename = None
        assert not evaluate_eligibility(student, job).eligible
        with pytest.raises(ApplicationError, match="resume"):
            apply_to_job(student, job, None, student.user)
