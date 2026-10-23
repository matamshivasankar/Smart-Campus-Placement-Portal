"""Job listing queries shared by the public board, student board and admin console."""
from __future__ import annotations

from sqlalchemy import or_

from ..extensions import db
from ..models import APPROVAL_APPROVED, JOB_APPROVED, Company, Job


def visible_jobs_query():
    """Jobs that are approved by the placement cell and not closed."""
    return (
        Job.query
        .join(Company, Job.company_id == Company.id)
        .filter(Job.approval_status == APPROVAL_APPROVED, Job.status == JOB_APPROVED)
    )


def apply_job_filters(query, args, *, include_closed: bool = False):
    """Apply keyword / company / location / department / batch filters from a request."""
    keyword = (args.get("q") or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(
            Job.title.like(like),
            Job.description.like(like),
            Job.location.like(like),
            Company.name.like(like),
        ))

    company = (args.get("company") or "").strip()
    if company:
        query = query.filter(Company.name.like(f"%{company}%"))

    location = (args.get("location") or "").strip()
    if location:
        query = query.filter(Job.location.like(f"%{location}%"))

    department = (args.get("department") or "").strip()
    if department:
        query = query.filter(Job.required_departments.like(f"%{department}%"))

    batch = (args.get("batch") or "").strip()
    if batch.isdigit():
        query = query.filter(Job.eligible_graduation_year == int(batch))

    employment = (args.get("employment_type") or "").strip()
    if employment:
        query = query.filter(Job.employment_type == employment)

    if not include_closed:
        from datetime import date
        query = query.filter(Job.deadline >= date.today())

    return query


def sort_jobs(query, args):
    sort = (args.get("sort") or "deadline").strip()
    if sort == "newest":
        return query.order_by(Job.created_at.desc())
    if sort == "title":
        return query.order_by(Job.title.asc())
    if sort == "salary":
        return query.order_by(Job.salary_max.desc().nullslast())
    return query.order_by(Job.deadline.asc(), Job.created_at.desc())


def paginate(query, page: int, per_page: int):
    return db.paginate(query, page=page, per_page=per_page, error_out=False)


def distinct_locations(limit: int = 30) -> list[str]:
    rows = (
        db.session.query(Job.location)
        .filter(Job.approval_status == APPROVAL_APPROVED, Job.status == JOB_APPROVED)
        .distinct()
        .order_by(Job.location)
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows if r[0]]
