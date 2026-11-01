"""Pinned production roles and known provider shutdown boundaries, not an access check."""

from datetime import date, datetime, timezone


PRIMARY_CHAT_MODEL = 'gpt-4o'
FAST_CHAT_MODEL = 'gpt-4o-mini'
SPEECH_MODEL = 'tts-1'

# Official deprecations checked 2026-11-01: https://developers.openai.com/api/docs/deprecations
# Stop at UTC midnight on the announced date; do not guess the provider's shutdown hour.
SHUTDOWN_DATES = {
    'tts-1': date(2027, 1, 6),
    'gpt-4o': date(2027, 1, 14),
    'gpt-4o-mini': date(2027, 1, 14),
}


class ModelMigrationRequired(RuntimeError):
    """A known retired model must not consume a request reservation."""


def require_model_active(model: str) -> None:
    shutdown = SHUTDOWN_DATES.get(model)
    if shutdown is not None and datetime.now(timezone.utc).date() >= shutdown:
        raise ModelMigrationRequired(
            f'OPENAI_MODEL_RETIRED: {model} 지원 종료 기준일 {shutdown.isoformat()}. '
            '대체 모델의 접근·가격·응답·음색을 검증한 뒤 새 요청을 재개하세요.'
        )


def require_production_models_active() -> None:
    for model in (PRIMARY_CHAT_MODEL, FAST_CHAT_MODEL, SPEECH_MODEL):
        require_model_active(model)
