"""Shared date helpers for pipeline code that hands values to asyncpg.

asyncpg's DATE codec calls `.toordinal()` on the bound value, so ISO
strings raise ``AttributeError: 'str' object has no attribute 'toordinal'``
at the moment they hit a DATE column. Every fetcher / transformer that
stages rows into a Postgres DATE column therefore has to normalize its
date values to ``datetime.date`` first.

``coerce_date`` is the single normalizer — accepts None, str, date,
and datetime — so callers never have to re-invent the conversion.
"""

from datetime import date, datetime


def coerce_date(value) -> date:
    """Normalize a date-ish value to a concrete ``datetime.date``.

    - ``None`` → ``date.today()``
    - ``datetime`` → narrowed via ``.date()``
    - ``date`` → returned as-is
    - ISO ``str`` → ``date.fromisoformat(value)``
    - anything else → ``TypeError``
    """
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"coerce_date: unsupported date value {value!r}")
