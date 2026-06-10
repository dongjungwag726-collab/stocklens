"""KST 기준 한국 증시(KRX) 시장 상태 및 알림 트리거 로직."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import config

# KST = UTC+9 (한국은 서머타임 없음 → 고정 오프셋)
KST = timezone(timedelta(hours=config.KST_OFFSET_HOURS))


def now_kst() -> datetime:
    """현재 KST 시각을 반환한다."""
    return datetime.now(KST)


def is_weekend(dt: datetime | None = None) -> bool:
    dt = dt or now_kst()
    # Monday=0 ... Saturday=5, Sunday=6
    return dt.weekday() >= 5


def market_status(dt: datetime | None = None) -> str:
    """현재 시장 상태 문자열을 반환한다 (config 라벨 사용)."""
    dt = dt or now_kst()

    if is_weekend(dt):
        return config.STATUS_WEEKEND

    open_t = time(*config.MARKET_OPEN)
    close_t = time(*config.MARKET_CLOSE)
    now_t = dt.time()

    if now_t < open_t:
        return config.STATUS_PRE
    if open_t <= now_t <= close_t:
        return config.STATUS_OPEN
    return config.STATUS_CLOSED


def is_market_open(dt: datetime | None = None) -> bool:
    return market_status(dt) == config.STATUS_OPEN


class NotificationScheduler:
    """장 시작/마감/점심 시각을 한 번씩만 알리도록 추적한다.

    매 분(또는 그보다 자주) `check()`를 호출하면, 해당 시각을 막 지났을 때
    한 번만 (이벤트_키) 문자열을 yield 한다. 같은 날 같은 이벤트는 중복 발화하지
    않는다. 주말에는 발화하지 않는다.
    """

    def __init__(self) -> None:
        # (date, event) 튜플로 발화 여부 기록
        self._fired: set[tuple] = set()

    def _maybe_fire(self, dt: datetime, hh: int, mm: int, event: str,
                    fired: list[str]) -> None:
        target = dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # 목표 시각 ~ +59초 구간에 있을 때 발화 (1분 폴링 가정, 여유 포함)
        delta = (dt - target).total_seconds()
        if 0 <= delta < 90:
            key = (dt.date(), event)
            if key not in self._fired:
                self._fired.add(key)
                fired.append(event)

    def check(self, dt: datetime | None = None) -> list[str]:
        """발화해야 할 이벤트 키 목록을 반환한다.

        반환 가능한 키: "open", "close", "lunch"
        호출 측에서 사용자 on/off 설정에 따라 필터링한다.
        """
        dt = dt or now_kst()
        fired: list[str] = []

        if is_weekend(dt):
            return fired

        self._maybe_fire(dt, *config.MARKET_OPEN, "open", fired)
        self._maybe_fire(dt, *config.LUNCH_TIME, "lunch", fired)
        self._maybe_fire(dt, *config.MARKET_CLOSE, "close", fired)
        return fired


# 알림 메시지 (이벤트 키 → (제목, 본문))
NOTIFY_MESSAGES = {
    "open": ("StockLens", "📈 장이 시작되었습니다"),
    "close": ("StockLens", "📉 장이 마감되었습니다"),
    "lunch": ("StockLens", "☕ 점심시간입니다. 잠깐 확인해보세요"),
}
