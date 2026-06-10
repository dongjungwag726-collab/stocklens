"""watchlist.json 영속화 + KRX 종목 검색."""

from __future__ import annotations

import copy
import json
import os

import config


# ---------------------------------------------------------------------------
# 영속화
# ---------------------------------------------------------------------------
def load_watchlist() -> list[dict]:
    """저장된 워치리스트를 로드한다. 없거나 손상 시 기본값을 반환/생성."""
    try:
        with open(config.WATCHLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and all(
            isinstance(d, dict) and "ticker" in d for d in data
        ):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    default = copy.deepcopy(config.DEFAULT_WATCHLIST)
    save_watchlist(default)
    return default


def save_watchlist(watchlist: list[dict]) -> None:
    """워치리스트를 디스크에 저장한다."""
    os.makedirs(os.path.dirname(config.WATCHLIST_PATH), exist_ok=True)
    tmp = config.WATCHLIST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config.WATCHLIST_PATH)  # 원자적 교체


# ---------------------------------------------------------------------------
# 검색
# ---------------------------------------------------------------------------
# 자주 쓰는 KRX 종목 사전 (이름 ↔ yfinance 티커).
# yfinance 자체 검색이 불안정할 때를 대비한 로컬 폴백 + 빠른 조회용.
KRX_DIRECTORY: dict[str, str] = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "LG에너지솔루션": "373220.KS",
    "삼성바이오로직스": "207940.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "셀트리온": "068270.KS",
    "NAVER": "035420.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KQ",
    "POSCO홀딩스": "005490.KS",
    "포스코홀딩스": "005490.KS",
    "LG화학": "051910.KS",
    "삼성SDI": "006400.KS",
    "현대모비스": "012330.KS",
    "삼성물산": "028260.KS",
    "KB금융": "105560.KS",
    "신한지주": "055550.KS",
    "하나금융지주": "086790.KS",
    "삼성생명": "032830.KS",
    "SK이노베이션": "096770.KS",
    "LG전자": "066570.KS",
    "한국전력": "015760.KS",
    "삼성전기": "009150.KS",
    "에코프로비엠": "247540.KQ",
    "에코프로": "086520.KQ",
    "알테오젠": "196170.KQ",
    "엔켐": "348370.KQ",
    "HLB": "028300.KQ",
    "리노공업": "058470.KQ",
    "JYP Ent.": "035900.KQ",
    "카카오게임즈": "293490.KQ",
    "펄어비스": "263750.KQ",
    "셀트리온제약": "068760.KQ",
}


def _looks_like_ticker(text: str) -> bool:
    """숫자 6자리(혹은 6자리.접미사)면 코드로 간주."""
    core = text.split(".")[0]
    return core.isdigit() and len(core) == 6


def normalize_ticker_code(code: str) -> list[str]:
    """6자리 코드에 접미사가 없으면 .KS/.KQ 후보를 만들어 반환."""
    code = code.strip().upper()
    if "." in code:
        return [code]
    return [f"{code}.KS", f"{code}.KQ"]


def search(query: str) -> list[dict]:
    """이름 또는 코드로 KRX 종목을 검색한다.

    반환: [{"ticker": ..., "name": ...}, ...]
    1) 코드 형태면 코드로 직접 후보 생성 (이름은 사전에서 역조회)
    2) 이름이면 로컬 사전에서 부분일치
    3) 결과 없으면 yfinance 검색으로 폴백
    """
    query = query.strip()
    if not query:
        return []

    results: list[dict] = []

    if _looks_like_ticker(query):
        for cand in normalize_ticker_code(query):
            name = _name_for_ticker(cand) or query
            results.append({"ticker": cand, "name": name})
        return results

    # 이름 부분일치 (대소문자 무시)
    q_lower = query.lower()
    for name, ticker in KRX_DIRECTORY.items():
        if q_lower in name.lower():
            results.append({"ticker": ticker, "name": name})

    if results:
        # 중복 티커 제거 (이름 별칭 때문에)
        seen = set()
        deduped = []
        for r in results:
            if r["ticker"] not in seen:
                seen.add(r["ticker"])
                deduped.append(r)
        return deduped

    # 폴백: yfinance 검색
    return _yfinance_search(query)


def _name_for_ticker(ticker: str) -> str | None:
    for name, t in KRX_DIRECTORY.items():
        if t == ticker:
            return name
    return None


def _yfinance_search(query: str) -> list[dict]:
    """yfinance Search API로 KRX 종목을 검색 (best-effort)."""
    try:
        import yfinance as yf

        s = yf.Search(query, max_results=10)
        out: list[dict] = []
        for q in getattr(s, "quotes", []) or []:
            sym = q.get("symbol", "")
            if sym.endswith((".KS", ".KQ")):
                name = q.get("shortname") or q.get("longname") or sym
                out.append({"ticker": sym, "name": name})
        return out
    except Exception:
        return []
