"""yfinance를 사용한 백그라운드 시세 조회 (QThread)."""

from __future__ import annotations

# SSL 우회: 사내망 등 SSL 인터셉션 환경에서 인증서 검증 오류를 회피한다.
# ⚠️ 인증서 검증을 사실상 끄는 것이므로 신뢰할 수 있는 네트워크에서만 사용할 것.
import os

os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""

import math
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


# ---------------------------------------------------------------------------
# 차트용 OHLCV 히스토리 조회
# ---------------------------------------------------------------------------
# 기간 키 → (yfinance period, interval, 분봉 여부)
CHART_PERIODS = {
    "1D": ("1d", "5m", True),
    "1W": ("5d", "30m", True),
    "1M": ("1mo", "1d", False),
    "3M": ("3mo", "1d", False),
    "1Y": ("1y", "1d", False),
}


def _isnan(v) -> bool:
    return isinstance(v, float) and math.isnan(v)


def fetch_chart(ticker: str, name: str, period_key: str) -> dict:
    """차트 패널용 OHLCV + 종목 정보를 조회한다.

    반환 dict: ohlcv(list), prev_close, intraday(bool), info(dict), error(bool)
    lightweight-charts에 바로 넘길 수 있도록 time은 UNIX epoch(초)로 통일한다.
    """
    import yfinance as yf

    period, interval, intraday = CHART_PERIODS.get(
        period_key, CHART_PERIODS["1M"]
    )
    out: dict = {
        "ticker": ticker, "name": name, "period": period_key,
        "ohlcv": [], "prev_close": None, "intraday": intraday,
        "info": {}, "error": False,
    }
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period=period, interval=interval)

        # time(초) → bar. 중복 시각은 마지막 값으로 덮어써 오름차순·유일성 보장.
        by_time: dict[int, dict] = {}
        for idx, row in hist.iterrows():
            close = _to_float(row.get("Close"))
            if close is None or _isnan(row.get("Close")):
                continue
            t = int(idx.timestamp())
            by_time[t] = {
                "time": t,
                "open": _to_float(row.get("Open")),
                "high": _to_float(row.get("High")),
                "low": _to_float(row.get("Low")),
                "close": close,
                "volume": _to_int(row.get("Volume")) or 0,
            }
        out["ohlcv"] = [by_time[t] for t in sorted(by_time)]

        fi = getattr(tk, "fast_info", None)
        prev = _to_float(fi.get("previous_close")) if fi else None
        out["prev_close"] = prev
        out["info"] = _build_info(tk, fi, out["ohlcv"], prev)

        if not out["ohlcv"]:
            out["error"] = True
    except Exception:
        out["error"] = True

    return out


def _build_info(tk, fi, ohlcv: list, prev: float | None) -> dict:
    """종목 정보 패널용 데이터를 모은다 (fast_info 우선, .info 보강)."""
    info: dict = {}
    last_close = ohlcv[-1]["close"] if ohlcv else None
    info["price"] = last_close
    info["change_pct"] = (
        (last_close - prev) / prev * 100.0
        if (last_close is not None and prev) else None
    )
    info["prev_close"] = prev

    if fi is not None:
        try:
            info["volume"] = _to_int(fi.get("last_volume") or fi.get("volume"))
            info["market_cap"] = _to_float(fi.get("market_cap"))
            info["w52_high"] = _to_float(fi.get("year_high"))
            info["w52_low"] = _to_float(fi.get("year_low"))
            info["day_open"] = _to_float(fi.get("open"))
            info["day_high"] = _to_float(fi.get("day_high"))
            info["day_low"] = _to_float(fi.get("day_low"))
        except Exception:
            pass

    # PER/PBR 등은 .info 에서만 제공 (느리고 불안정 → best-effort)
    info["per"] = None
    info["pbr"] = None
    try:
        di = tk.info or {}
        info["per"] = di.get("trailingPE")
        info["pbr"] = di.get("priceToBook")
        info.setdefault("market_cap", None)
        if not info.get("market_cap"):
            info["market_cap"] = di.get("marketCap")
        if not info.get("w52_high"):
            info["w52_high"] = di.get("fiftyTwoWeekHigh")
        if not info.get("w52_low"):
            info["w52_low"] = di.get("fiftyTwoWeekLow")
        if not info.get("day_open"):
            info["day_open"] = di.get("regularMarketOpen") or di.get("open")
    except Exception:
        pass

    info["day_close"] = last_close
    return info


class ChartFetchThread(QThread):
    """단일 종목의 OHLCV 히스토리를 백그라운드에서 조회."""

    chart_ready = pyqtSignal(object)  # dict (fetch_chart 결과)

    def __init__(self, ticker: str, name: str, period_key: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._ticker = ticker
        self._name = name
        self._period_key = period_key

    def run(self) -> None:
        result = fetch_chart(self._ticker, self._name, self._period_key)
        self.chart_ready.emit(result)


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
