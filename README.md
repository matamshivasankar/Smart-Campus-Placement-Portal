# Smart Campus Placement Portal

A Flask placement workflow for students, recruiters, and placement officers. It uses deterministic eligibility rules and SQLAlchemy models; it does not include AI or machine learning.

## Local setup

Python 3.10 or newer is recommended.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a unique `SECRET_KEY` in `.env`. Without `DATABASE_URL`, the app stores durable local data in `instance/placement.db`; no database server or Supabase credentials are needed.

```powershell
flask --app run.py init-db
flask --app run.py create-admin
flask --app run.py run
```

The first command creates all tables. `flask --app run.py seed-db` optionally adds reproducible demo data. Demo accounts use `Admin@12345` for `placement.officer@campus.edu` and `Student@12345` for seeded student/recruiter accounts. Change or remove demo credentials before using a shared environment. `seed-db --admin-only` creates only the development administrator.

## Roles and workflow

- Students register, maintain academic details and skills, upload a resume, review eligibility, apply, withdraw, and follow interview and status updates.
- Recruiters register for placement officer approval, maintain company details, create postings, review their own applicants, move candidates through allowed stages, and schedule interviews.
- Placement officers approve recruiters and jobs, manage accounts, inspect applications and interviews, export filtered CSV reports, and review audit activity.

Applications are unique per student and job. The server checks profile completeness, job approval/open state, deadline, CGPA, required skills, department, graduation year, backlog cap, and resume presence again when applying.

## Database options

SQLite is the default local database. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL to use PostgreSQL instead. A PostgreSQL URL does not synchronize or copy existing SQLite data. Back up and migrate data separately before switching.

Tables are created by `init-db`; Flask-Migrate is available for future schema changes. For an existing database, use migrations rather than expecting `create_all` to alter tables.

## Optional Supabase

- **Supabase PostgreSQL:** configure `DATABASE_URL` with a `postgresql+psycopg://...` connection string. The app uses SQLAlchemy directly; it does not automatically migrate or synchronize records.
- **Supabase Storage:** configure `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_RESUME_BUCKET`. The bucket must exist and be private. Uploads use per-user object paths; authorized resume downloads receive a five-minute signed URL by default. The service-role key is used only by the server and must never be placed in frontend settings.
- If these storage values are incomplete, uploads remain local under `instance/uploads/resumes/`. Supabase behavior requires valid credentials and bucket access and is not verified in this local setup.

## Security and operations

Flask-WTF CSRF protection is enabled on forms. Passwords use Werkzeug's password hashing. Role checks and ownership checks protect private routes and resume downloads. Uploads accept PDF/DOC/DOCX with basic content signatures and the configured size cap. Keep `.env`, `instance/`, and uploaded files out of version control. Use HTTPS and a strong secret key outside local development.

## Automated tests

Tests use a separate in-memory SQLite database by default and do not touch `instance/placement.db`.

```powershell
python -m pytest
```

## Supabase storage policy

Keep the resume bucket private. This application signs downloads after its own student, recruiter-application, or administrator authorization check. Do not add public read access. The server-side service key bypasses object policies, so access control must remain in the Flask route.
