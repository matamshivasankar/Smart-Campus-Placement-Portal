"""Reproducible seed data for local development and manual testing.

Run with::

    flask --app run.py seed-db
    flask --app run.py seed-db --admin-only

The demo credentials created here are documented in the README.  They are
development fixtures only - never run this against production data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app

from .extensions import db
from .models import (
    APP_INTERVIEW,
    APP_SELECTED,
    APP_SHORTLISTED,
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    JOB_APPROVED,
    JOB_PENDING,
    Application,
    Company,
    Interview,
    Job,
    JobRequiredSkill,
    RecruiterProfile,
    StudentProfile,
    StudentSkill,
    User,
)

ADMIN_EMAIL = "placement.officer@campus.edu"
ADMIN_PASSWORD = "Admin@12345"
DEMO_PASSWORD = "Student@12345"
RECRUITER_PASSWORD = "Recruiter@12345"


def seed_database(with_demo_data: bool = True) -> list[str]:
    """Create the default accounts (and optionally demo records).

    Returns a list of human readable lines describing what was created.
    """
    summary: list[str] = []

    admin = User.query.filter_by(email=ADMIN_EMAIL).first()
    if admin is None:
        admin = User(email=ADMIN_EMAIL, role="admin", is_active=True)
        admin.set_password(ADMIN_PASSWORD)
        db.session.add(admin)
        summary.append(f"admin account created: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    else:
        summary.append(f"admin account already present: {ADMIN_EMAIL}")
    db.session.commit()

    if not with_demo_data:
        return summary

    recruiters = _seed_recruiters(summary)
    students = _seed_students(summary)
    jobs = _seed_jobs(recruiters, summary)
    _seed_applications(students, jobs, summary)

    db.session.commit()
    return summary


# --------------------------------------------------------------------------
def _write_demo_resume(user_id: int, student_name: str) -> str:
    """Write a small placeholder PDF so seeded students have a downloadable resume."""
    directory = (
        Path(current_app.config["UPLOAD_FOLDER"])
        / current_app.config.get("RESUMES_SUBDIR", "resumes")
        / str(user_id)
    )
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = "seed_demo_resume.pdf"
    body = f"Demo resume for {student_name} - generated seed data".encode("ascii", "replace")
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(len(body) + 34).encode() + b" >>\nstream\n"
        b"BT /F1 12 Tf 20 120 Td (" + body + b") Tj ET\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )
    (directory / stored_name).write_bytes(content)
    return stored_name


def _seed_recruiters(summary: list[str]) -> dict[str, RecruiterProfile]:
    data = [
        {
            "email": "priya.sharma@technova.example",
            "name": "Priya Sharma",
            "designation": "University Relations Manager",
            "company": "TechNova Solutions",
            "website": "https://technova.example",
            "industry": "Software Product",
            "location": "Bengaluru, India",
            "description": (
                "TechNova Solutions builds cloud platforms for logistics companies. "
                "The company hires final-year engineering students every year."
            ),
            "approval_status": APPROVAL_APPROVED,
        },
        {
            "email": "rahul.verma@dataflow.example",
            "name": "Rahul Verma",
            "designation": "Talent Acquisition Lead",
            "company": "Dataflow Analytics",
            "website": "https://dataflow.example",
            "industry": "Data and Analytics",
            "location": "Pune, India",
            "description": (
                "Dataflow Analytics delivers business intelligence projects for "
                "retail and banking clients."
            ),
            "approval_status": APPROVAL_APPROVED,
        },
        {
            "email": "anita.desai@greenbuild.example",
            "name": "Anita Desai",
            "designation": "HR Business Partner",
            "company": "GreenBuild Infra",
            "website": "https://greenbuild.example",
            "industry": "Construction and Infrastructure",
            "location": "Chennai, India",
            "description": "GreenBuild Infra works on sustainable civil infrastructure projects.",
            "approval_status": APPROVAL_PENDING,
        },
    ]

    profiles: dict[str, RecruiterProfile] = {}
    for item in data:
        existing = User.query.filter_by(email=item["email"]).first()
        if existing is not None:
            profiles[item["company"]] = existing.recruiter_profile
            continue

        company = Company.query.filter(db.func.lower(Company.name) == item["company"].lower()).first()
        if company is None:
            company = Company(
                name=item["company"], website=item["website"], industry=item["industry"],
                location=item["location"], description=item["description"],
            )
            db.session.add(company)
            db.session.flush()

        user = User(email=item["email"], role="recruiter", is_active=True)
        user.set_password(RECRUITER_PASSWORD)
        profile = RecruiterProfile(
            user=user,
            full_name=item["name"],
            designation=item["designation"],
            company_id=company.id,
            approval_status=item["approval_status"],
        )
        if item["approval_status"] == APPROVAL_APPROVED:
            profile.approved_at = datetime.now()
            profile.approved_by_id = User.query.filter_by(email=ADMIN_EMAIL).first().id
        db.session.add(user)
        db.session.flush()
        profiles[item["company"]] = profile
        summary.append(
            f"recruiter created: {item['email']} / {RECRUITER_PASSWORD} "
            f"({item['company']}, {item['approval_status']})"
        )

    db.session.commit()
    return profiles


def _seed_students(summary: list[str]) -> dict[str, StudentProfile]:
    data = [
        {
            "email": "aditya.rao@student.campus.edu",
            "name": "Aditya Rao",
            "roll": "CSE2023001",
            "department": "Computer Science and Engineering",
            "degree": "B.Tech",
            "cgpa": 8.60,
            "year": date.today().year + 1,
            "backlogs": 0,
            "skills": ["Python", "Java", "SQL", "Flask", "Data Structures"],
        },
        {
            "email": "meera.iyer@student.campus.edu",
            "name": "Meera Iyer",
            "roll": "IT2023007",
            "department": "Information Technology",
            "degree": "B.Tech",
            "cgpa": 7.20,
            "year": date.today().year + 1,
            "backlogs": 1,
            "skills": ["Java", "Spring Boot", "MySQL", "REST API"],
        },
        {
            "email": "karan.singh@student.campus.edu",
            "name": "Karan Singh",
            "roll": "ECE2023012",
            "department": "Electronics and Communication Engineering",
            "degree": "B.Tech",
            "cgpa": 6.80,
            "year": date.today().year + 1,
            "backlogs": 2,
            "skills": ["C++", "Embedded C", "MATLAB"],
        },
        {
            "email": "sneha.gupta@student.campus.edu",
            "name": "Sneha Gupta",
            "roll": "AIDS2023003",
            "department": "Artificial Intelligence and Data Science",
            "degree": "B.Tech",
            "cgpa": 9.10,
            "year": date.today().year + 1,
            "backlogs": 0,
            "skills": ["Python", "SQL", "Pandas", "Statistics", "Power BI"],
        },
        {
            "email": "vikram.nair@student.campus.edu",
            "name": "Vikram Nair",
            "roll": "MECH2023021",
            "department": "Mechanical Engineering",
            "degree": "B.Tech",
            "cgpa": 7.80,
            "year": date.today().year + 1,
            "backlogs": 0,
            "skills": ["AutoCAD", "SolidWorks", "Project Management"],
        },
    ]

    profiles: dict[str, StudentProfile] = {}
    for item in data:
        existing = User.query.filter_by(email=item["email"]).first()
        if existing is not None:
            profiles[item["roll"]] = existing.student_profile
            continue

        user = User(email=item["email"], role="student", is_active=True)
        user.set_password(DEMO_PASSWORD)
        profile = StudentProfile(
            user=user,
            full_name=item["name"],
            roll_number=item["roll"],
            department=item["department"],
            degree=item["degree"],
            cgpa=item["cgpa"],
            graduation_year=item["year"],
            phone="9876543210",
            active_backlogs=item["backlogs"],
            about=f"{item['name']} is a {item['degree']} student in {item['department']}.",
        )
        for skill in item["skills"]:
            profile.skills.append(StudentSkill(skill=skill))
        db.session.add(user)
        db.session.flush()

        stored_name = _write_demo_resume(user.id, item["name"])
        profile.resume_filename = stored_name
        profile.resume_original_name = f"{item['name'].replace(' ', '_')}_resume.pdf"
        profile.resume_uploaded_at = datetime.now()

        profiles[item["roll"]] = profile
        summary.append(f"student created: {item['email']} / {DEMO_PASSWORD} (CGPA {item['cgpa']})")

    db.session.commit()
    return profiles


def _seed_jobs(recruiters: dict[str, RecruiterProfile], summary: list[str]) -> dict[str, Job]:
    today = date.today()
    data = [
        {
            "key": "technova-backend",
            "company": "TechNova Solutions",
            "title": "Backend Engineer (Python)",
            "description": (
                "Design and build REST services that power our logistics platform. "
                "You will work with Flask, MySQL and containerised deployments."
            ),
            "responsibilities": "Write APIs, review code, own service reliability.",
            "location": "Bengaluru, India",
            "salary_min": 800000,
            "salary_max": 1200000,
            "min_cgpa": 7.5,
            "year": today.year + 1,
            "departments": "Computer Science and Engineering, Information Technology",
            "max_backlogs": 0,
            "skills": ["Python", "Flask", "SQL"],
            "deadline": today + timedelta(days=30),
            "openings": 4,
            "status": JOB_APPROVED,
        },
        {
            "key": "technova-frontend",
            "company": "TechNova Solutions",
            "title": "Frontend Engineer (JavaScript)",
            "description": (
                "Build responsive interfaces with HTML, CSS, Bootstrap and vanilla "
                "JavaScript for our customer portal."
            ),
            "responsibilities": "Own UI components and accessibility.",
            "location": "Bengaluru, India",
            "salary_min": 600000,
            "salary_max": 950000,
            "min_cgpa": 6.5,
            "year": today.year + 1,
            "departments": "",
            "max_backlogs": 1,
            "skills": ["JavaScript", "HTML", "CSS"],
            "deadline": today + timedelta(days=21),
            "openings": 2,
            "status": JOB_APPROVED,
        },
        {
            "key": "dataflow-analyst",
            "company": "Dataflow Analytics",
            "title": "Data Analyst",
            "description": (
                "Turn raw operational data into dashboards and reports for banking "
                "clients using SQL and Power BI."
            ),
            "responsibilities": "Write SQL, build dashboards, present findings.",
            "location": "Pune, India",
            "salary_min": 550000,
            "salary_max": 850000,
            "min_cgpa": 8.0,
            "year": today.year + 1,
            "departments": "Artificial Intelligence and Data Science, Computer Science and Engineering",
            "max_backlogs": 0,
            "skills": ["SQL", "Power BI", "Statistics"],
            "deadline": today + timedelta(days=14),
            "openings": 3,
            "status": JOB_APPROVED,
        },
        {
            "key": "dataflow-intern",
            "company": "Dataflow Analytics",
            "title": "Data Engineering Intern",
            "description": (
                "Six month paid internship on our ETL team. Strong performers receive "
                "a full time offer."
            ),
            "responsibilities": "Assist with pipeline development and data quality checks.",
            "location": "Pune, India",
            "salary_min": 25000,
            "salary_max": 35000,
            "min_cgpa": 7.0,
            "year": today.year + 1,
            "departments": "",
            "max_backlogs": 2,
            "skills": ["Python", "SQL"],
            "deadline": today + timedelta(days=40),
            "openings": 5,
            "status": JOB_APPROVED,
            "employment_type": "Internship",
        },
        {
            "key": "greenbuild-site",
            "company": "GreenBuild Infra",
            "title": "Graduate Site Engineer",
            "description": (
                "Join our sustainable infrastructure division and supervise site "
                "execution for green building projects."
            ),
            "responsibilities": "Site supervision, quality checks, client coordination.",
            "location": "Chennai, India",
            "salary_min": 450000,
            "salary_max": 700000,
            "min_cgpa": 6.0,
            "year": today.year + 1,
            "departments": "Civil Engineering, Mechanical Engineering",
            "max_backlogs": 2,
            "skills": ["AutoCAD", "Project Management"],
            "deadline": today + timedelta(days=45),
            "openings": 2,
            "status": JOB_PENDING,
        },
    ]

    jobs: dict[str, Job] = {}
    for item in data:
        recruiter = recruiters.get(item["company"])
        if recruiter is None:
            summary.append(f"skipped job '{item['title']}': recruiter missing")
            continue

        existing = Job.query.filter_by(recruiter_id=recruiter.id, title=item["title"]).first()
        if existing is not None:
            jobs[item["key"]] = existing
            continue

        approved = item["status"] == JOB_APPROVED
        job = Job(
            company_id=recruiter.company_id,
            recruiter_id=recruiter.id,
            title=item["title"],
            description=item["description"],
            responsibilities=item["responsibilities"],
            location=item["location"],
            employment_type=item.get("employment_type", "Full time"),
            salary_min=item["salary_min"],
            salary_max=item["salary_max"],
            openings=item["openings"],
            min_cgpa=item["min_cgpa"],
            eligible_graduation_year=item["year"],
            required_departments=item["departments"] or None,
            max_backlogs=item["max_backlogs"],
            deadline=item["deadline"],
            status=item["status"],
            approval_status=APPROVAL_APPROVED if approved else APPROVAL_PENDING,
        )
        if approved:
            job.approved_at = datetime.now()
            job.approved_by_id = User.query.filter_by(email=ADMIN_EMAIL).first().id
        for skill in item["skills"]:
            job.required_skills.append(JobRequiredSkill(skill=skill))
        db.session.add(job)
        db.session.flush()
        jobs[item["key"]] = job
        summary.append(
            f"job created: '{item['title']}' at {item['company']} "
            f"(min CGPA {item['min_cgpa']}, {'approved' if approved else 'pending approval'})"
        )

    db.session.commit()
    return jobs


def _seed_applications(students: dict[str, StudentProfile], jobs: dict[str, Job],
                       summary: list[str]) -> None:
    from .services.applications import apply_to_job

    plans = [
        ("CSE2023001", "technova-backend", APP_SHORTLISTED),
        ("AIDS2023003", "dataflow-analyst", APP_INTERVIEW),
        ("IT2023007", "technova-frontend", "Applied"),
        ("AIDS2023003", "technova-backend", "Applied"),
    ]

    created = 0
    for roll, job_key, target_status in plans:
        student = students.get(roll)
        job = jobs.get(job_key)
        if student is None or job is None:
            continue
        if Application.query.filter_by(student_id=student.id, job_id=job.id).first():
            continue
        try:
            application = apply_to_job(student, job, "Seeded demo application.", student.user)
        except Exception as exc:  # student not eligible for the seeded criteria
            summary.append(f"skipped application {roll} -> {job.title}: {exc}")
            continue

        created += 1
        if target_status == APP_SHORTLISTED:
            application.status = APP_SHORTLISTED
        elif target_status == APP_INTERVIEW:
            application.status = APP_INTERVIEW
            db.session.add(Interview(
                application_id=application.id,
                round_number=1,
                round_name="Technical Round 1",
                scheduled_at=datetime.now() + timedelta(days=5, hours=3),
                duration_minutes=45,
                mode="Online",
                meeting_link="https://meet.example.com/dataflow-round1",
                interviewer_name="Rahul Verma",
                created_by_id=job.recruiter.user_id,
            ))
        elif target_status == APP_SELECTED:
            application.status = APP_SELECTED

    db.session.commit()
    if created:
        summary.append(f"{created} demo application(s) created")
    return None
