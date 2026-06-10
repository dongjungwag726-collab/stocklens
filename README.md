# StockLens 📈

**한국 직장인을 위한 Windows 데스크톱 주식 오버레이 앱**

업무 화면 위에 반투명 주식 티커를 띄워, 창 전환 없이 근무 중 KRX(KOSPI/KOSDAQ)
시세를 모니터링합니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **오버레이 창** | 프레임리스 · 항상 위 · 투명도 10~100% · 드래그 이동 · 모서리 리사이즈 |
| **KRX 장 상태** | 핸들 바에 `장 준비중 / 장 중 🟢 / 장 마감 🔴 / 주말 휴장` (KST 기준) |
| **시세 표시** | 한글 종목명 + ₩가격(콤마) + 등락률. 상승=빨강 `#FF4B4B`, 하락=파랑 `#4B8BFF` |
| **2단 확장** | 행 더블클릭 → 거래량 / 시가총액 / 당일 고가·저가 부드럽게 펼침 |
| **워치리스트** | 종목명·코드 검색, 우클릭 삭제·이동, `watchlist.json` 저장 |
| **증권사 바로가기** | 토스 · 키움 · 삼성 · 미래에셋 버튼 (브라우저 열기) |
| **알림** | 09:00 장 시작 / 15:30 장 마감 / 12:00 점심(옵션) Windows 토스트 |
| **시스템 트레이** | 좌클릭 토글, 우클릭 메뉴(표시·알림·새로고침 간격·종료) |

---

## 설치 & 실행

```bash
cd stocklens
pip install -r requirements.txt
python main.py
```

> Python 3.10+ 권장. `win10toast`는 Windows에서만 설치됩니다.
> 다른 OS에서는 토스트 대신 트레이 풍선 알림으로 대체됩니다.

---

## 빌드 (단일 .exe)

Windows에서:

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed ^
  --name StockLens ^
  --icon assets\icon.png ^
  --add-data "assets;assets" ^
  main.py
```

생성물: `dist/StockLens.exe`

---

## 파일 구조

```
stocklens/
├── main.py           # 진입점 — 모든 모듈 연결
├── overlay.py        # 오버레이 창 (PyQt6)
├── tray.py           # 시스템 트레이 + 알림
├── data_fetcher.py   # yfinance 백그라운드 조회 (QThread)
├── watchlist.py      # JSON 저장/로드 + 종목 검색
├── market_hours.py   # KST 장 상태 + 알림 스케줄러
├── config.py         # 상수 · 기본 설정 · 테마
├── assets/icon.png   # 트레이 아이콘
├── requirements.txt
└── README.md
```

---

## 참고

- 시세 데이터는 `yfinance` 기반으로 **약 15분 지연**될 수 있습니다.
- KRX 티커 형식: KOSPI = `005930.KS`, KOSDAQ = `035720.KQ`
- 워치리스트는 `~/.stocklens/watchlist.json`에 저장됩니다.

> ⚠️ 본 앱은 정보 제공용이며 투자 권유가 아닙니다.
