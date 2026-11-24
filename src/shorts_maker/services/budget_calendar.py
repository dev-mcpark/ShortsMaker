"""Provider month boundaries shared by reservation ledgers and schedule previews."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


GOOGLE_BUDGET_TIMEZONE = ZoneInfo('America/Los_Angeles')
OPENAI_BUDGET_TIMEZONE = timezone.utc


def budget_month_starts(instant: datetime) -> dict[str, datetime]:
    """Return the start of each provider month containing an aware instant."""
    if instant.utcoffset() is None:
        raise ValueError('A timezone-aware slot is required.')
    return {
        name: instant.astimezone(zone).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for name, zone in (('Google', GOOGLE_BUDGET_TIMEZONE), ('OpenAI', OPENAI_BUDGET_TIMEZONE))
    }
