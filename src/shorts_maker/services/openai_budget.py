"""Conservative local monthly reserve for this app's OpenAI requests."""

import json
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING

from shorts_maker.utils.config import settings


# shortcut: these standard-tier list prices were checked on 2026-10-23; recheck before changing models or enabling a new month.
_CHAT_PRICES = {
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
}
_SPEECH_PRICES = {"tts-1": Decimal("15.00")}
_SCHEMA = """CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, period TEXT NOT NULL, model TEXT NOT NULL,
    reserved_micro_usd INTEGER NOT NULL, created_utc TEXT NOT NULL, source_url TEXT
)"""


class OpenAIBudgetExceeded(RuntimeError):
    """A request cannot be reserved against the configured monthly limit."""


def _period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _configured_period() -> str | None:
    if settings.openai_monthly_budget_usd is None:
        return None
    period = _period()
    if settings.openai_budget_month != period:
        raise OpenAIBudgetExceeded("OPENAI_BUDGET_EXCEEDED: 이번 달 OpenAI 사용액 기준을 다시 설정하세요.")
    return period


def _micro_usd(amount: Decimal) -> int:
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def _database_path():
    return settings.output_dir / "evaluation" / "openai_budget.sqlite3"


def _connect_existing() -> sqlite3.Connection:
    return sqlite3.connect(_database_path().resolve().as_uri() + "?mode=rw", uri=True, timeout=5)


def initialize_openai_budget() -> dict:
    """Create a new ledger after checking the configured opening usage."""
    if _configured_period() is None:
        raise ValueError("OpenAI 월 예산 설정을 먼저 활성화하세요.")
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


def _reserve(model: str, amount: Decimal, source_url: str | None = None) -> str | None:
    period = _configured_period()
    if period is None:
        return None
    if source_url is not None and not isinstance(source_url, str):
        raise ValueError("OpenAI 요청 출처는 URL 문자열이어야 합니다.")
    if source_url is not None:
        source_url = source_url.strip() or None
    reserve = _micro_usd(amount)
    ceiling = int(Decimal(str(settings.openai_monthly_budget_usd)) * 1_000_000)
    opening = _micro_usd(Decimal(str(settings.openai_budget_opening_usd)))
    request_id = uuid.uuid4().hex
    try:
        with closing(_connect_existing()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute(
                "SELECT COALESCE(SUM(reserved_micro_usd), 0) FROM requests WHERE period = ?", (period,)
            ).fetchone()[0]
            if opening + used + reserve > ceiling:
                raise OpenAIBudgetExceeded(
                    f"OPENAI_BUDGET_EXCEEDED: 월 예약 추정액 "
                    f"${(opening + used + reserve) / 1_000_000:.6f}이 "
                    f"프로그램 상한 ${ceiling / 1_000_000:.6f}을 초과합니다."
                )
            if "source_url" not in {column[1] for column in db.execute("PRAGMA table_info(requests)")}:
                db.execute("ALTER TABLE requests ADD COLUMN source_url TEXT")
            db.execute(
                "INSERT INTO requests (id, period, model, reserved_micro_usd, created_utc, source_url) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (request_id, period, model, reserve, datetime.now(timezone.utc).isoformat(), source_url),
            )
    except (OSError, sqlite3.Error) as error:
        raise OpenAIBudgetExceeded("OPENAI_BUDGET_EXCEEDED: 비용 장부에 접근할 수 없습니다.") from error
    return request_id


def reserve_openai_chat(model: str, messages: list[dict], max_completion_tokens: int,
                        *, source_url: str | None = None) -> str | None:
    """Reserve a text request before submission, including its full output-token ceiling."""
    if _configured_period() is None:
        return None
    if model not in _CHAT_PRICES or type(max_completion_tokens) is not int or max_completion_tokens < 1:
        raise OpenAIBudgetExceeded("OPENAI_BUDGET_EXCEEDED: 확인되지 않은 채팅 모델 또는 출력 상한입니다.")
    input_price, output_price = _CHAT_PRICES[model]
    # UTF-8 bytes plus message framing are a conservative input-token bound for text-only prompts.
    input_bound = len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 1024
    estimate = (Decimal(input_bound) * input_price
                + Decimal(max_completion_tokens) * output_price) / 1_000_000
    return _reserve(model, estimate, source_url)


def reserve_openai_speech(model: str, text: str, *, source_url: str | None = None) -> str | None:
    """Reserve each speech attempt separately; failures continue to count."""
    if _configured_period() is None:
        return None
    if model not in _SPEECH_PRICES or not isinstance(text, str) or not text:
        raise OpenAIBudgetExceeded("OPENAI_BUDGET_EXCEEDED: 확인되지 않은 음성 모델 또는 빈 대본입니다.")
    return _reserve(model, Decimal(len(text)) * _SPEECH_PRICES[model] / 1_000_000, source_url)


def budget_status() -> dict:
    """Return local reserves, not the provider's billed usage."""
    period = _configured_period()
    if period is None:
        return {"enabled": False}
    try:
        with closing(_connect_existing()) as db:
            local = db.execute(
                "SELECT COALESCE(SUM(reserved_micro_usd), 0) FROM requests WHERE period = ?", (period,)
            ).fetchone()[0]
            by_model = dict(db.execute(
                "SELECT model, SUM(reserved_micro_usd) FROM requests "
                "WHERE period = ? GROUP BY model", (period,)
            ).fetchall())
            by_source = dict(db.execute(
                "SELECT source_url, SUM(reserved_micro_usd) FROM requests "
                "WHERE period = ? AND source_url IS NOT NULL GROUP BY source_url", (period,),
            )) if "source_url" in {column[1] for column in db.execute("PRAGMA table_info(requests)")} else {}
    except (OSError, sqlite3.Error) as error:
        raise OpenAIBudgetExceeded("OPENAI_BUDGET_EXCEEDED: 비용 장부에 접근할 수 없습니다. --init으로 최초 생성해야 합니다.") from error
    opening = _micro_usd(Decimal(str(settings.openai_budget_opening_usd)))
    ceiling = int(Decimal(str(settings.openai_monthly_budget_usd)) * 1_000_000)
    return {"enabled": True, "period": period,
            "budget_usd": ceiling / 1_000_000,
            "opening_usd": opening / 1_000_000,
            "local_reserved_usd": local / 1_000_000,
            "reserved_by_model_usd": {model: value / 1_000_000 for model, value in by_model.items()},
            "reserved_by_source_usd": {source: value / 1_000_000 for source, value in by_source.items()},
            "unattributed_reserved_usd": (local - sum(by_source.values())) / 1_000_000,
            "remaining_usd": max(0, ceiling - opening - local) / 1_000_000}


if __name__ == "__main__":
    print(json.dumps(initialize_openai_budget() if sys.argv[1:] == ["--init"] else budget_status(),
                     ensure_ascii=False))
