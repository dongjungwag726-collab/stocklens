"""StockLens 전역 상수 및 기본 설정값."""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 앱 메타
# ---------------------------------------------------------------------------
APP_NAME = "StockLens"
APP_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "icon.png")
# 사용자 데이터(워치리스트)는 홈 디렉터리에 저장 → .exe 재배포 시에도 유지
DATA_DIR = os.path.join(os.path.expanduser("~"), ".stocklens")
WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlist.json")

# ---------------------------------------------------------------------------
# 테마 (다크 전용)
# ---------------------------------------------------------------------------
COLOR_BG = "#0D1117"
COLOR_TEXT = "#E6EDF3"
COLOR_TEXT_DIM = "#8B949E"
COLOR_HANDLE = "#161B22"
COLOR_ACCENT = "#238636"
COLOR_UP = "#FF4B4B"     # 상승 = 빨강 (한국 관습)
COLOR_DOWN = "#4B8BFF"   # 하락 = 파랑 (한국 관습)
COLOR_FLAT = "#8B949E"   # 보합

FONT_FAMILY = "Malgun Gothic"

# 차트 패널
CHART_PANEL_WIDTH = 400
COLOR_MA5 = "#FFD700"    # 노랑
COLOR_MA20 = "#4B8BFF"   # 파랑
COLOR_MA60 = "#A371F7"   # 보라

# ---------------------------------------------------------------------------
# 한국 증시 운영 시간 (KST, UTC+9)
# ---------------------------------------------------------------------------
KST_OFFSET_HOURS = 9
MARKET_OPEN = (9, 0)     # 09:00
MARKET_CLOSE = (15, 30)  # 15:30
LUNCH_TIME = (12, 0)     # 12:00 (점심 알림)

# 시장 상태 라벨
STATUS_PRE = "장 준비중"
STATUS_OPEN = "장 중 🟢"
STATUS_CLOSED = "장 마감 🔴"
STATUS_WEEKEND = "주말 휴장"

# ---------------------------------------------------------------------------
# 데이터 새로고침 간격 (초). 트레이 메뉴에서 선택 가능.
# ---------------------------------------------------------------------------
REFRESH_INTERVALS = {
    "30초": 30,
    "1분": 60,
    "5분": 300,
}
DEFAULT_REFRESH_SECONDS = 60

# ---------------------------------------------------------------------------
# 첫 실행 기본 워치리스트
# yfinance 형식: KOSPI = .KS, KOSDAQ = .KQ
# ---------------------------------------------------------------------------
DEFAULT_WATCHLIST = [
    {"ticker": "005930.KS", "name": "삼성전자"},
    {"ticker": "000660.KS", "name": "SK하이닉스"},
    {"ticker": "035720.KQ", "name": "카카오"},
    {"ticker": "035420.KS", "name": "NAVER"},
    {"ticker": "005380.KS", "name": "현대차"},
]

# ---------------------------------------------------------------------------
# 증권사 바로가기
# ---------------------------------------------------------------------------
BROKERS = [
    ("토스증권", "https://tossinvest.com"),
    ("키움증권", "https://www1.kiwoom.com"),
    ("삼성증권", "https://www.samsungpop.com"),
    ("미래에셋", "https://securities.miraeasset.com"),
]

# ---------------------------------------------------------------------------
# 기타 UI
# ---------------------------------------------------------------------------
DISCLAIMER = "※ 데이터는 약 15분 지연됩니다 (yfinance)"

# 알림 기본 on/off
DEFAULT_NOTIFY = {
    "open": True,    # 09:00 장 시작
    "close": True,   # 15:30 장 마감
    "lunch": False,  # 12:00 점심
}

# 기본 창 크기 (compact, ~5종목)
DEFAULT_WINDOW_WIDTH = 300
DEFAULT_WINDOW_HEIGHT = 320
DEFAULT_OPACITY = 0.95
