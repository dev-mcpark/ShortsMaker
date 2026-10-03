"""One explicit switch for optional provider requests that may incur charges."""

from shorts_maker.utils.config import settings


def require_paid_production_enabled() -> None:
    """Stop direct provider helpers as well as the orchestrated workflow."""
    if not settings.paid_production_enabled:
        raise RuntimeError(
            "유료 API 호출이 꺼져 있습니다. 이번 라운드 예산과 제공자 사용량을 "
            "확인한 뒤 PAID_PRODUCTION_ENABLED=true로 설정하세요."
        )
