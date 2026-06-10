"""yfinance를 사용한 백그라운드 시세 조회 (QThread)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal


@dataclass
class Quote:
    """단일 종목 시세 스냅샷."""
    ticker: str
    name: str
    price: float | None = None        # 현재가
    prev_close: float | None = None   # 전일 종가
    change_pct: float | None = None   # 등락률 (%)
    volume: int | None = None         # 거래량
    market_cap: float | None = None   # 시가총액
    day_high: float | None = None     # 당일 고가
    day_low: float | None = None      # 당일 저가
    currency: str = "KRW"
    error: bool = False

    @property
    def is_up(self) -> bool:
        return self.change_pct is not None and self.change_pct > 0

    @property
    def is_down(self) -> bool:
        return self.change_pct is not None and self.change_pct < 0


def _safe(d: dict, *keys):
    """딕셔너리에서 여러 후보 키 중 첫 유효값을 반환."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def fetch_quote(ticker: str, name: str) -> Quote:
    """단일 종목 시세를 조회한다. 네트워크/파싱 실패 시 error=True 반환."""
    import yfinance as yf

    q = Quote(ticker=ticker, name=name)
    try:
        tk = yf.Ticker(ticker)

        # fast_info: 빠르고 가벼움 (가격/전일종가/거래량/시총)
        fi = getattr(tk, "fast_info", None)
        if fi is not None:
            try:
                q.price = _to_float(fi.get("last_price"))
                q.prev_close = _to_float(fi.get("previous_close"))
                q.day_high = _to_float(fi.get("day_high"))
                q.day_low = _to_float(fi.get("day_low"))
                q.volume = _to_int(fi.get("last_volume") or fi.get("volume"))
                q.market_cap = _to_float(fi.get("market_cap"))
                q.currency = fi.get("currency") or q.currency
            except Exception:
                pass

        # 가격이 비었으면 1일 히스토리로 폴백
        if q.price is None or q.prev_close is None:
            hist = tk.history(period="2d")
            if not hist.empty:
                last = hist.iloc[-1]
                if q.price is None:
                    q.price = _to_float(last.get("Close"))
                if q.day_high is None:
                    q.day_high = _to_float(last.get("High"))
                if q.day_low is None:
                    q.day_low = _to_float(last.get("Low"))
                if q.volume is None:
                    q.volume = _to_int(last.get("Volume"))
                if q.prev_close is None and len(hist) >= 2:
                    q.prev_close = _to_float(hist.iloc[-2].get("Close"))

        # 등락률 계산
        if q.price is not None and q.prev_close:
            q.change_pct = (q.price - q.prev_close) / q.prev_close * 100.0

        if q.price is None:
            q.error = True
    except Exception:
        q.error = True

    return q


def _to_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


class FetchThread(QThread):
    """워치리스트 전체를 순회하며 시세를 조회하고 결과를 시그널로 전달."""

    # 단일 종목 완료 시 (실시간 갱신용)
    quote_ready = pyqtSignal(object)  # Quote
    # 전체 배치 완료 시
    finished_all = pyqtSignal(list)   # list[Quote]

    def __init__(self, watchlist: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._watchlist = list(watchlist)

    def run(self) -> None:
        results: list[Quote] = []
        for entry in self._watchlist:
            if self.isInterruptionRequested():
                break
            q = fetch_quote(entry["ticker"], entry.get("name", entry["ticker"]))
            results.append(q)
            self.quote_ready.emit(q)
        self.finished_all.emit(results)
