from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app import create_app
from app.extensions import db
from app.models import Company, Job, JobRequiredSkill, RecruiterProfile, StudentProfile, StudentSkill, User


@pytest.fixture
def app():
    application = create_app("testing")
    upload_tmp = TemporaryDirectory(prefix="test-uploads-", dir=Path(application.instance_path))
    application.config["UPLOAD_FOLDER"] = Path(upload_tmp.name)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
    upload_tmp.cleanup()


@pytest.fixture
def records(app):
    with app.app_context():
        admin = User(email="officer@example.edu", role="admin", is_active=True)
        admin.set_password("OfficerPass123")
        student_user = User(email="student@example.edu", role="student", is_active=True)
        student_user.set_password("StudentPass123")
        recruiter_user = User(email="recruiter@example.com", role="recruiter", is_active=True)
        recruiter_user.set_password("RecruiterPass123")
        db.session.add_all([admin, student_user, recruiter_user])
        db.session.flush()
        student = StudentProfile(
            user=student_user, full_name="Test Student", roll_number="TST001",
            department="Computer Science and Engineering", degree="B.Tech", cgpa=8.5,
            graduation_year=date.today().year + 1, active_backlogs=0,
            resume_filename="resume.pdf", resume_original_name="resume.pdf",
        )
        db.session.add(student)
        student.skills.append(StudentSkill(skill="Python"))
        company = Company(name="Example Systems")
        db.session.add(company)
        db.session.flush()
        recruiter = RecruiterProfile(
            user=recruiter_user, full_name="Test Recruiter", company_id=company.id,
            approval_status="approved", approved_by_id=admin.id,
        )
        db.session.add(recruiter)
        db.session.flush()
        job = Job(
            company_id=company.id, recruiter_id=recruiter.id, title="Python Engineer",
            description="Build services.", location="Remote", deadline=date.today() + timedelta(days=14),
            min_cgpa=7.0, eligible_graduation_year=student.graduation_year,
            required_departments="Computer Science and Engineering", max_backlogs=0,
            status="approved", approval_status="approved", approved_by_id=admin.id,
        )
        job.required_skills.append(JobRequiredSkill(skill="Python"))
        db.session.add(job)
        db.session.commit()
        return {"admin_id": admin.id, "student_user_id": student_user.id,
                "student_id": student.id, "recruiter_user_id": recruiter_user.id,
                "recruiter_id": recruiter.id, "company_id": company.id, "job_id": job.id}
