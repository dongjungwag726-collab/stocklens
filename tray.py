"""시스템 트레이 아이콘 + 메뉴 + Windows 토스트 알림."""

from __future__ import annotations

import os

from PyQt6.QtGui import QAction, QActionGroup, QIcon, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

import config


def _load_icon() -> QIcon:
    if os.path.exists(config.ICON_PATH):
        return QIcon(config.ICON_PATH)
    # 폴백: 단색 픽스맵
    pix = QPixmap(32, 32)
    pix.fill()
    return QIcon(pix)


def send_toast(title: str, message: str) -> None:
    """Windows 토스트 알림. 실패 시 조용히 무시."""
    try:
        from win10toast import ToastNotifier

        ToastNotifier().show_toast(
            title, message,
            icon_path=config.ICON_PATH if os.path.exists(config.ICON_PATH) else None,
            duration=5, threaded=True,
        )
    except Exception:
        # 비-Windows 또는 미설치 환경: 트레이 메시지로 폴백 (호출 측에서 처리)
        pass


class TrayController:
    """트레이 아이콘과 메뉴를 관리한다.

    overlay: OverlayWindow
    on_interval_change: callable(int seconds)
    notify_settings: dict (config.DEFAULT_NOTIFY 복사본) — 직접 수정됨
    on_quit: callable
    """

    def __init__(self, overlay, notify_settings: dict,
                 on_interval_change, on_quit) -> None:
        self.overlay = overlay
        self.notify = notify_settings
        self._on_interval_change = on_interval_change
        self._on_quit = on_quit

        self.tray = QSystemTrayIcon(_load_icon())
        self.tray.setToolTip(config.APP_NAME)
        self.tray.activated.connect(self._on_activated)

        self._build_menu()
        self.tray.show()

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menu = QMenu()

        # 창 표시/숨기기
        toggle = QAction("창 표시 / 숨기기", menu)
        toggle.triggered.connect(self.toggle_window)
        menu.addAction(toggle)
        menu.addSeparator()

        # 알림 설정
        notify_menu = menu.addMenu("알림 설정")
        self._notify_actions = {}
        for key, label in (
            ("open", "장 시작 (09:00)"),
            ("close", "장 마감 (15:30)"),
            ("lunch", "점심 (12:00)"),
        ):
            act = QAction(label, notify_menu, checkable=True)
            act.setChecked(self.notify.get(key, False))
            act.toggled.connect(lambda checked, k=key: self._set_notify(k, checked))
            notify_menu.addAction(act)
            self._notify_actions[key] = act

        # 새로고침 간격
        interval_menu = menu.addMenu("새로고침 간격")
        group = QActionGroup(interval_menu)
        group.setExclusive(True)
        for label, seconds in config.REFRESH_INTERVALS.items():
            act = QAction(label, interval_menu, checkable=True)
            act.setChecked(seconds == config.DEFAULT_REFRESH_SECONDS)
            act.triggered.connect(
                lambda _=False, s=seconds: self._on_interval_change(s)
            )
            group.addAction(act)
            interval_menu.addAction(act)

        menu.addSeparator()
        quit_act = QAction("종료", menu)
        quit_act.triggered.connect(self._on_quit)
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)

    # ------------------------------------------------------------------
    def _on_activated(self, reason) -> None:
        # 좌클릭(Trigger): 창 토글
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()

    def toggle_window(self) -> None:
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()
            self.overlay.raise_()
            self.overlay.activateWindow()

    def _set_notify(self, key: str, value: bool) -> None:
        self.notify[key] = value

    # ------------------------------------------------------------------
    def notify_event(self, event_key: str, title: str, message: str) -> None:
        """알림 이벤트 발생 시 호출. 사용자 설정 on일 때만 표시."""
        if not self.notify.get(event_key, False):
            return
        send_toast(title, message)
        # 트레이 풍선 알림 (모든 OS에서 동작하는 폴백 겸용)
        self.tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 5000
        )
