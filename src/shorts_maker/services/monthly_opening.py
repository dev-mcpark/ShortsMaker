"""Record a confirmed provider-month opening in the existing reservation ledger."""

from datetime import datetime, timezone


class MonthOpeningRequired(RuntimeError):
    def __init__(self, period: str, message: str):
        self.period = period
        super().__init__(message)


def saved_month_opening(db, period: str) -> int | None:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='month_openings'").fetchone():
        return None
    row = db.execute('SELECT amount FROM month_openings WHERE period = ?', (period,)).fetchone()
    if row is None:
        return None
    if type(row[0]) is not int or row[0] < 0:
        raise ValueError('월 기준 사용액 기록이 손상됐습니다. 기존 장부를 복구하세요.')
    return row[0]


def save_month_opening(db, period: str, amount: int, evidence: str) -> None:
    """Append inside the ledger's existing reservation transaction, before any requests."""
    if type(amount) is not int or not 0 <= amount <= 2**63 - 1:
        raise ValueError('0 이상의 유효한 기준 사용액을 입력하세요.')
    if not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 500:
        raise ValueError('사용액을 확인한 보고서와 시점을 기록하세요. 최대 500자입니다.')
    if saved_month_opening(db, period) is not None:
        raise ValueError('이 월의 기준 사용액이 이미 저장돼 있습니다. 장부를 다시 조회하세요.')
    if db.execute('SELECT 1 FROM requests WHERE period = ? LIMIT 1', (period,)).fetchone():
        raise ValueError('이 월에 이미 예약 기록이 있습니다. 기존 기준 사용액과 예약을 먼저 대조하세요.')
    db.execute('''CREATE TABLE IF NOT EXISTS month_openings (
        period TEXT PRIMARY KEY, amount INTEGER NOT NULL CHECK (amount >= 0),
        evidence TEXT NOT NULL, confirmed_utc TEXT NOT NULL
    )''')
    db.execute('INSERT INTO month_openings VALUES (?, ?, ?, ?)',
               (period, amount, evidence.strip(), datetime.now(timezone.utc).isoformat()))
