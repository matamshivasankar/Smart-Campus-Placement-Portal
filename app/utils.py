"""Small shared helpers: parsing, formatting, pagination, notifications."""
from __future__ import annotations

from datetime import date, datetime
from math import ceil

from flask import request

from .extensions import db
from .models import Notification


class SimplePagination:
    """Pagination shape used when filtering a bounded result set in Python."""
    def __init__(self, total: int, page: int, per_page: int, items: list):
        self.total, self.page, self.per_page, self.items = total, page, per_page, items
        self.pages = max(ceil(total / per_page), 1)
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1

    def iter_pages(self, left_edge=1, left_current=2, right_current=2, right_edge=1):
        return range(1, self.pages + 1)


def clean_str(value: str | None, max_length: int | None = None) -> str | None:
    """Trim whitespace and collapse internal runs of whitespace."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def parse_skill_list(raw: str | None, max_skills: int = 40) -> list[str]:
    """Turn a comma / newline separated skill string into a de-duplicated list."""
    if not raw:
        return []
    seen: dict[str, str] = {}
    for part in raw.replace("\n", ",").split(","):
        item = clean_str(part, 80)
        if item and item.lower() not in seen:
            seen[item.lower()] = item
    return list(seen.values())[:max_skills]


def parse_department_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [d.strip() for d in raw.split(",") if d.strip()]


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def get_page() -> int:
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    return max(page, 1)


def notify(user_id: int, title: str, message: str, link: str | None = None,
           commit: bool = True) -> Notification:
    """Create an in-app notification for a user."""
    note = Notification(
        user_id=user_id,
        title=title[:200],
        message=message[:500],
        link=link[:255] if link else None,
    )
    db.session.add(note)
    if commit:
        db.session.commit()
    return note


def money(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"
