"""Small stateless utilities."""

from __future__ import annotations

from datetime import datetime


def fmt_date(iso: str) -> str:
    try:
        iso = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16]
