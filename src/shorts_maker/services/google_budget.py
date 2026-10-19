"""Local, conservative monthly reserve for this app's Google visual requests."""

import json
import math
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from zoneinfo import ZoneInfo

from shorts_maker.services.visual_cost import estimated_scene_cost
from shorts_maker.utils.config import settings


_BUDGET_TIMEZONE = ZoneInfo("America/Los_Angeles")  # Cloud Billing calendar periods.
# shortcut: Cloud Billing is not queried; add verified SKU reconciliation before unattended spending.
_SCHEMA = """CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, period TEXT NOT NULL, model TEXT NOT NULL,
    estimated_usd TEXT NOT NULL, reserved_krw INTEGER NOT NULL,
    status TEXT NOT NULL, created_utc TEXT NOT NULL
)"""


def _period() -> str:
    return datetime.now(_BUDGET_TIMEZONE).strftime("%Y-%m")


def _reserve_krw(estimated_usd: float) -> int:
    amount = Decimal(str(estimated_usd))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Google 비용 추정액은 0 이상의 유한한 값이어야 합니다.")
    return int((amount * Decimal(str(settings.google_usd_krw_rate))).to_integral_value(rounding=ROUND_CEILING))


def _budget_period() -> str | None:
    if settings.google_monthly_budget_krw is None:
        return None
    period = _period()
    if settings.google_budget_month != period:
        raise RuntimeError("GOOGLE_BUDGET_EXCEEDED: 이번 달 Google 사용액 기준을 다시 설정하세요.")
    return period


def _database_path():
    return settings.output_dir / "evaluation" / "google_budget.sqlite3"


def _connect_existing() -> sqlite3.Connection:
    # Opening an absent ledger must never reset this month's recorded spend.
    return sqlite3.connect(_database_path().resolve().as_uri() + "?mode=rw", uri=True, timeout=5)


def initialize_google_budget() -> dict:
    """Create the ledger once, after the configured opening spend is checked."""
    if _budget_period() is None:
        raise ValueError("Google 월 예산 설정을 먼저 활성화하세요.")
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    try:
        with closing(_connect_existing()) as db, db:
            db.execute(_SCHEMA)
    except (OSError, sqlite3.Error):
        path.unlink(missing_ok=True)
        raise
    return budget_status()


def _total(db: sqlite3.Connection, period: str) -> int:
    row = db.execute("SELECT COALESCE(SUM(reserved_krw), 0) FROM requests WHERE period = ?", (period,)).fetchone()
    return row[0]


def _check(db: sqlite3.Connection, period: str, additional_krw: int) -> int:
    used = settings.google_budget_opening_krw + _total(db, period)
    if used + additional_krw > settings.google_monthly_budget_krw:
        raise RuntimeError(
            f"GOOGLE_BUDGET_EXCEEDED: 이번 달 예약액 {used + additional_krw:,}원이 "
            f"프로그램 상한 {settings.google_monthly_budget_krw:,}원을 초과합니다."
        )
    return used


def check_google_budget(estimated_usd: float, request_count: int = 1) -> None:
    """Preflight a batch before narration; each actual request reserves atomically later."""
    if not math.isfinite(estimated_usd) or estimated_usd < 0:
        raise ValueError("Google 비용 추정액은 0 이상의 유한한 값이어야 합니다.")
    if not isinstance(request_count, int) or isinstance(request_count, bool) or request_count < 1:
        raise ValueError("Google 요청 수는 1 이상이어야 합니다.")
    if estimated_usd == 0:
        return
    period = _budget_period()
    if period is None:
        return
    amount = _reserve_krw(estimated_usd) + request_count - 1
    try:
        with closing(_connect_existing()) as db:
            _check(db, period, amount)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError("GOOGLE_BUDGET_EXCEEDED: 비용 장부에 접근할 수 없습니다.") from error


def reserve_google_output(mode: str, model: str, duration_seconds: int = 0) -> str | None:
    """Persist one model-priced request before sending it; failed calls stay reserved."""
    estimate = estimated_scene_cost(mode, model, duration_seconds)
    period = _budget_period()
    if period is None:
        return None
    amount = _reserve_krw(estimate)
    request_id = uuid.uuid4().hex
    try:
        with closing(_connect_existing()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            _check(db, period, amount)
            db.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)",
                (request_id, period, model, str(estimate), amount, "reserved",
                 datetime.now(timezone.utc).isoformat()),
            )
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError("GOOGLE_BUDGET_EXCEEDED: 비용 장부에 접근할 수 없습니다.") from error
    return request_id


def mark_google_result(request_id: str | None, status: str) -> bool:
    if request_id is None:
        return True
    try:
        with closing(_connect_existing()) as db, db:
            return db.execute("UPDATE requests SET status = ? WHERE id = ?", (status, request_id)).rowcount == 1
    except (OSError, sqlite3.Error):
        return False  # The existing reservation still counts if its status cannot be updated.


def budget_status() -> dict:
    """Show local reserves and the manually entered opening spend, never billed cost."""
    period = _budget_period()
    if period is None:
        return {"enabled": False}
    try:
        with closing(_connect_existing()) as db:
            local = _total(db, period)
            by_model = dict(db.execute(
                "SELECT model, SUM(reserved_krw) FROM requests WHERE period = ? GROUP BY model", (period,),
            ).fetchall())
            by_status = {status: {"requests": count, "reserved_krw": reserved}
                         for status, count, reserved in db.execute(
                             "SELECT status, COUNT(*), SUM(reserved_krw) FROM requests "
                             "WHERE period = ? GROUP BY status", (period,),
                         )}
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError("GOOGLE_BUDGET_EXCEEDED: 비용 장부에 접근할 수 없습니다. --init으로 최초 생성해야 합니다.") from error
    used = settings.google_budget_opening_krw + local
    return {"enabled": True, "period": period,
            "budget_krw": settings.google_monthly_budget_krw,
            "opening_krw": settings.google_budget_opening_krw,
            "local_reserved_krw": local,
            "reserved_by_model_krw": by_model,
            "requests_by_status": by_status,
            "remaining_krw": max(0, settings.google_monthly_budget_krw - used),
            "usd_krw_reserve_rate": settings.google_usd_krw_rate}


if __name__ == "__main__":
    print(json.dumps(initialize_google_budget() if sys.argv[1:] == ["--init"] else budget_status(),
                     ensure_ascii=False))
