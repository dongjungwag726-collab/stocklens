"""StockLens 진입점 — 오버레이/트레이/데이터 스레드/알림 타이머를 연결한다."""

from __future__ import annotations

import copy
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

import config
import market_hours as mh
from data_fetcher import FetchThread
from overlay import OverlayWindow
from tray import TrayController


class StockLensApp:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.refresh_seconds = config.DEFAULT_REFRESH_SECONDS
        self.notify_settings = copy.deepcopy(config.DEFAULT_NOTIFY)
        self._fetch_thread: FetchThread | None = None
        self._scheduler = mh.NotificationScheduler()

        # 오버레이
        self.overlay = OverlayWindow()
        self.overlay.watchlist_changed.connect(self.refresh_now)

        # 트레이
        self.tray = TrayController(
            self.overlay,
            self.notify_settings,
            on_interval_change=self.set_interval,
            on_quit=self.quit,
        )

        # 시세 새로고침 타이머
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_now)
        self.refresh_timer.start(self.refresh_seconds * 1000)

        # 시장 상태 + 알림 체크 타이머 (15초마다)
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._tick)
        self.clock_timer.start(15 * 1000)

        # 초기 표시
        self.overlay.show()
        self._update_market_status()
        self.refresh_now()

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._update_market_status()
        self._check_notifications()

    def _update_market_status(self) -> None:
        self.overlay.set_market_status(mh.market_status())

    def _check_notifications(self) -> None:
        for event in self._scheduler.check():
            title, msg = mh.NOTIFY_MESSAGES.get(event, (config.APP_NAME, ""))
            self.tray.notify_event(event, title, msg)
            # 장 시작/마감 시 자동 새로고침
            if event in ("open", "close"):
                self.refresh_now()

    # ------------------------------------------------------------------
    def refresh_now(self) -> None:
        """워치리스트 시세를 백그라운드에서 새로 가져온다."""
        if self._fetch_thread is not None and self._fetch_thread.isRunning():
            return  # 이전 조회 진행 중이면 건너뜀
        watchlist = self.overlay.current_watchlist()
        if not watchlist:
            return
        self._fetch_thread = FetchThread(watchlist)
        self._fetch_thread.quote_ready.connect(self.overlay.apply_quote)
        self._fetch_thread.start()

    def set_interval(self, seconds: int) -> None:
        self.refresh_seconds = seconds
        self.refresh_timer.start(seconds * 1000)

    # ------------------------------------------------------------------
    def quit(self) -> None:
        if self._fetch_thread is not None and self._fetch_thread.isRunning():
            self._fetch_thread.requestInterruption()
            self._fetch_thread.wait(2000)
        self.tray.tray.hide()
        self.app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # 창 닫아도 트레이로 유지
    app.setFont(QFont(config.FONT_FAMILY, 9))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        # 트레이 없는 환경에서도 오버레이는 동작하도록 경고만
        print("경고: 시스템 트레이를 사용할 수 없습니다.")

    StockLensApp(app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
