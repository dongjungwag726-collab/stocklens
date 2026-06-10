"""StockLens 오버레이 창 (PyQt6).

프레임리스 + 항상 위 + 투명도 조절 + 드래그 이동/리사이즈.
종목 행은 더블클릭으로 확장/축소되며, 하단에 증권사 바로가기 버튼이 있다.
"""

from __future__ import annotations

import webbrowser

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import config
import watchlist as wl
from data_fetcher import Quote

try:
    from chart_panel import ChartPanel
    CHART_AVAILABLE = True
except Exception:  # PyQt6-WebEngine 미설치 등
    ChartPanel = None  # type: ignore
    CHART_AVAILABLE = False


def fmt_won(value: float | None) -> str:
    if value is None:
        return "-"
    return f"₩{value:,.0f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    arrow = "▲" if value > 0 else ("▼" if value < 0 else "■")
    return f"{arrow} {value:+.2f}%"


def fmt_volume(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def fmt_cap(value: float | None) -> str:
    if value is None:
        return "-"
    # 조 / 억 단위 한국식 표기
    if value >= 1e12:
        return f"{value / 1e12:.2f}조"
    if value >= 1e8:
        return f"{value / 1e8:.0f}억"
    return f"{value:,.0f}"


class TickerRow(QFrame):
    """단일 종목 행. 더블클릭으로 상세 정보 확장/축소."""

    delete_requested = pyqtSignal(str)  # ticker
    move_requested = pyqtSignal(str, int)  # ticker, delta (-1 위로 / +1 아래로)
    selected = pyqtSignal(str, str)  # ticker, name (차트 대상 선택)

    def __init__(self, entry: dict, parent=None) -> None:
        super().__init__(parent)
        self.ticker: str = entry["ticker"]
        self.name: str = entry.get("name", self.ticker)
        self._expanded = False
        self._quote: Quote | None = None

        self.setObjectName("tickerRow")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        # --- 메인 행 (이름 / 가격 / 등락) ---
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name_lbl = QLabel(self.name)
        self.name_lbl.setObjectName("nameLbl")
        self.price_lbl = QLabel("-")
        self.price_lbl.setObjectName("priceLbl")
        self.price_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.pct_lbl = QLabel("-")
        self.pct_lbl.setObjectName("pctLbl")
        self.pct_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.pct_lbl.setMinimumWidth(72)

        top.addWidget(self.name_lbl, 3)
        top.addWidget(self.price_lbl, 3)
        top.addWidget(self.pct_lbl, 2)
        outer.addLayout(top)

        # --- 상세 행 (확장 시) ---
        self.detail = QLabel("")
        self.detail.setObjectName("detailLbl")
        self.detail.setWordWrap(True)
        self.detail.setMaximumHeight(0)  # 접힌 상태
        self.detail.setVisible(True)
        outer.addWidget(self.detail)

        self._anim = QPropertyAnimation(self.detail, b"maximumHeight")
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self.update_quote(None)

    # ------------------------------------------------------------------
    def update_quote(self, quote: Quote | None) -> None:
        self._quote = quote
        if quote is None:
            self.price_lbl.setText("…")
            self.pct_lbl.setText("")
            return

        if quote.error:
            self.price_lbl.setText("조회 실패")
            self.price_lbl.setStyleSheet(f"color: {config.COLOR_TEXT_DIM};")
            self.pct_lbl.setText("")
            return

        self.name_lbl.setText(quote.name or self.name)
        self.price_lbl.setText(fmt_won(quote.price))
        self.pct_lbl.setText(fmt_pct(quote.change_pct))

        if quote.is_up:
            color = config.COLOR_UP
        elif quote.is_down:
            color = config.COLOR_DOWN
        else:
            color = config.COLOR_FLAT
        self.price_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.pct_lbl.setStyleSheet(f"color: {color};")

        self._refresh_detail()

    def _refresh_detail(self) -> None:
        q = self._quote
        if q is None:
            return
        self.detail.setText(
            f"거래량 {fmt_volume(q.volume)}   시가총액 {fmt_cap(q.market_cap)}\n"
            f"당일 고가 {fmt_won(q.day_high)}   당일 저가 {fmt_won(q.day_low)}"
        )

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.ticker, self.name)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.toggle_expand()
        event.accept()

    def toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._refresh_detail()
        start = self.detail.maximumHeight()
        end = self.detail.sizeHint().height() if self._expanded else 0
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        up = QAction("위로 이동", self)
        up.triggered.connect(lambda: self.move_requested.emit(self.ticker, -1))
        down = QAction("아래로 이동", self)
        down.triggered.connect(lambda: self.move_requested.emit(self.ticker, 1))
        menu.addAction(up)
        menu.addAction(down)
        menu.addSeparator()
        act = QAction(f"'{self.name}' 삭제", self)
        act.triggered.connect(lambda: self.delete_requested.emit(self.ticker))
        menu.addAction(act)
        menu.exec(self.mapToGlobal(pos))


class DragHandle(QFrame):
    """상단 드래그 핸들 바. 시장 상태 표시 + 창 이동."""

    def __init__(self, parent_window: "OverlayWindow") -> None:
        super().__init__(parent_window)
        self._win = parent_window
        self._drag_offset: QPoint | None = None
        self.setObjectName("handleBar")
        self.setFixedHeight(26)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 4, 0)
        lay.setSpacing(4)

        self.status_lbl = QLabel(config.STATUS_PRE)
        self.status_lbl.setObjectName("statusLbl")
        lay.addWidget(self.status_lbl)
        lay.addStretch(1)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setFixedSize(18, 18)
        self.close_btn.setToolTip("숨기기 (트레이로)")
        self.close_btn.clicked.connect(self._win.hide)
        lay.addWidget(self.close_btn)

    def set_status(self, text: str) -> None:
        self.status_lbl.setText(text)

    # 창 이동
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self._win.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._win.move(
                event.globalPosition().toPoint() - self._drag_offset
            )
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        event.accept()


class OverlayWindow(QWidget):
    """메인 오버레이 창."""

    # 트레이/메인이 워치리스트 변경을 알 수 있도록
    watchlist_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._watchlist = wl.load_watchlist()
        self._rows: dict[str, TickerRow] = {}
        self._chart_open = False
        self._chart_symbol: dict | None = None
        self._chart_anim = None

        self.setWindowTitle(config.APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # 작업표시줄에 안 뜸
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowOpacity(config.DEFAULT_OPACITY)
        self.resize(config.DEFAULT_WINDOW_WIDTH, config.DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(220, 180)

        self._build_ui()
        self._apply_style()
        self._populate_rows()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 최상위는 수평: [본문][화살표][차트 패널]
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._content = QWidget()
        self._content.setObjectName("contentArea")
        root = QVBoxLayout(self._content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 드래그 핸들
        self.handle = DragHandle(self)
        root.addWidget(self.handle)

        # 검색 + 추가
        search_row = QHBoxLayout()
        search_row.setContentsMargins(6, 4, 6, 2)
        search_row.setSpacing(4)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("종목명 또는 코드 (예: 삼성전자 / 005930)")
        self.search_box.returnPressed.connect(self._on_add)
        add_btn = QPushButton("＋")
        add_btn.setObjectName("addBtn")
        add_btn.setFixedWidth(28)
        add_btn.clicked.connect(self._on_add)
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(add_btn)
        root.addLayout(search_row)

        # 종목 리스트 (스크롤)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(2)
        self.list_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.list_container)
        self.scroll.setObjectName("scroll")
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        root.addWidget(self.scroll, 1)

        # 투명도 슬라이더
        op_row = QHBoxLayout()
        op_row.setContentsMargins(8, 2, 8, 2)
        op_row.setSpacing(6)
        op_row.addWidget(QLabel("투명도"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(config.DEFAULT_OPACITY * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        op_row.addWidget(self.opacity_slider, 1)
        root.addLayout(op_row)

        # 면책 문구
        disclaimer = QLabel(config.DISCLAIMER)
        disclaimer.setObjectName("disclaimer")
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(disclaimer)

        # 증권사 바로가기 버튼
        broker_row = QHBoxLayout()
        broker_row.setContentsMargins(4, 2, 4, 4)
        broker_row.setSpacing(3)
        for label, url in config.BROKERS:
            btn = QPushButton(label)
            btn.setObjectName("brokerBtn")
            btn.setToolTip(url)
            btn.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            broker_row.addWidget(btn)
        root.addLayout(broker_row)

        # 우하단 리사이즈 그립
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 2)
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(self))
        root.addLayout(grip_row)

        # 본문 + 차트 토글 화살표 + 차트 패널 조립
        outer.addWidget(self._content)

        self.chart_btn = QPushButton("◀")
        self.chart_btn.setObjectName("chartToggle")
        self.chart_btn.setFixedWidth(16)
        self.chart_btn.setToolTip("차트 패널 열기/닫기")
        self.chart_btn.clicked.connect(self._toggle_chart)
        outer.addWidget(self.chart_btn)

        if CHART_AVAILABLE:
            self.chart_panel = ChartPanel()
            self.chart_panel.setMaximumWidth(0)
            self.chart_panel.setMinimumWidth(0)
            outer.addWidget(self.chart_panel)
        else:
            self.chart_panel = None
            self.chart_btn.setEnabled(False)
            self.chart_btn.setToolTip("PyQt6-WebEngine 미설치 — 차트 비활성")

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {config.COLOR_BG};
                color: {config.COLOR_TEXT};
                font-family: "{config.FONT_FAMILY}";
                font-size: 12px;
            }}
            #handleBar {{
                background-color: {config.COLOR_HANDLE};
            }}
            #statusLbl {{
                font-weight: 600;
                color: {config.COLOR_TEXT};
            }}
            #closeBtn {{
                background-color: transparent;
                color: {config.COLOR_TEXT_DIM};
                border: none;
                font-size: 11px;
            }}
            #closeBtn:hover {{ color: {config.COLOR_UP}; }}
            #tickerRow {{
                background-color: {config.COLOR_BG};
                border-radius: 4px;
            }}
            #tickerRow:hover {{
                background-color: {config.COLOR_HANDLE};
            }}
            #nameLbl {{ font-weight: 600; }}
            #priceLbl {{ font-weight: 600; }}
            #detailLbl {{
                color: {config.COLOR_TEXT_DIM};
                font-size: 11px;
            }}
            #disclaimer {{
                color: {config.COLOR_TEXT_DIM};
                font-size: 10px;
            }}
            #searchBox {{
                background-color: {config.COLOR_HANDLE};
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 3px 6px;
            }}
            #addBtn, #brokerBtn {{
                background-color: {config.COLOR_HANDLE};
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 3px 0;
            }}
            #addBtn:hover, #brokerBtn:hover {{
                background-color: {config.COLOR_ACCENT};
            }}
            #chartToggle {{
                background-color: {config.COLOR_HANDLE};
                color: {config.COLOR_TEXT};
                border: none;
                border-left: 1px solid #21262D;
                font-size: 11px;
            }}
            #chartToggle:hover {{ background-color: {config.COLOR_ACCENT}; }}
            #chartToggle:disabled {{ color: #30363D; }}
            #scroll {{ border: none; }}
            QScrollBar:vertical {{
                background: {config.COLOR_BG};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: #30363D;
                border-radius: 4px;
            }}
            QSlider::groove:horizontal {{
                height: 4px; background: #30363D; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {config.COLOR_ACCENT};
                width: 12px; margin: -5px 0; border-radius: 6px;
            }}
        """)

    # ------------------------------------------------------------------
    # 워치리스트 행 관리
    # ------------------------------------------------------------------
    def _populate_rows(self) -> None:
        for row in self._rows.values():
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        # stretch는 항상 마지막. 새 행은 그 앞에 삽입.
        for entry in self._watchlist:
            self._add_row_widget(entry)

    def _add_row_widget(self, entry: dict) -> None:
        row = TickerRow(entry)
        row.delete_requested.connect(self._on_delete)
        row.move_requested.connect(self._on_move)
        row.selected.connect(self._on_select_symbol)
        # stretch 앞(= count-1)에 삽입
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)
        self._rows[entry["ticker"]] = row

    # ------------------------------------------------------------------
    # 데이터 갱신 (data_fetcher 시그널에 연결됨)
    # ------------------------------------------------------------------
    def apply_quote(self, quote: Quote) -> None:
        row = self._rows.get(quote.ticker)
        if row is not None:
            row.update_quote(quote)

    def set_market_status(self, text: str) -> None:
        self.handle.set_status(text)

    def current_watchlist(self) -> list[dict]:
        return list(self._watchlist)

    # ------------------------------------------------------------------
    # 사용자 액션
    # ------------------------------------------------------------------
    def _on_add(self) -> None:
        query = self.search_box.text().strip()
        if not query:
            return
        results = wl.search(query)
        if not results:
            return

        if len(results) == 1:
            chosen = results[0]
        else:
            labels = [f"{r['name']} ({r['ticker']})" for r in results]
            label, ok = QInputDialog.getItem(
                self, "종목 선택", "추가할 종목:", labels, 0, False
            )
            if not ok:
                return
            chosen = results[labels.index(label)]

        if any(e["ticker"] == chosen["ticker"] for e in self._watchlist):
            self.search_box.clear()
            return

        self._watchlist.append(chosen)
        self._add_row_widget(chosen)
        wl.save_watchlist(self._watchlist)
        self.search_box.clear()
        self.watchlist_changed.emit()

    def _on_delete(self, ticker: str) -> None:
        self._watchlist = [e for e in self._watchlist if e["ticker"] != ticker]
        row = self._rows.pop(ticker, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        wl.save_watchlist(self._watchlist)
        self.watchlist_changed.emit()

    def _on_move(self, ticker: str, delta: int) -> None:
        idx = next(
            (i for i, e in enumerate(self._watchlist) if e["ticker"] == ticker),
            None,
        )
        if idx is None:
            return
        new_idx = idx + delta
        if not (0 <= new_idx < len(self._watchlist)):
            return
        self._watchlist[idx], self._watchlist[new_idx] = (
            self._watchlist[new_idx],
            self._watchlist[idx],
        )
        # 위젯 순서 재배치 (간단히 전부 다시 그림, 시세는 다음 갱신에 반영)
        self._populate_rows()
        wl.save_watchlist(self._watchlist)
        self.watchlist_changed.emit()

    def _on_opacity(self, value: int) -> None:
        self.setWindowOpacity(max(0.1, value / 100.0))

    # ------------------------------------------------------------------
    # 차트 패널
    # ------------------------------------------------------------------
    def _on_select_symbol(self, ticker: str, name: str) -> None:
        self._chart_symbol = {"ticker": ticker, "name": name}
        if self.chart_panel is not None and self._chart_open:
            self.chart_panel.set_symbol(ticker, name)

    def _toggle_chart(self) -> None:
        if self.chart_panel is None:
            return
        self._chart_open = not self._chart_open

        if self._chart_open:
            sym = self._chart_symbol or (
                self._watchlist[0] if self._watchlist else None
            )
            if sym:
                self._chart_symbol = sym
                self.chart_panel.set_symbol(sym["ticker"], sym.get("name", ""))
            self.chart_btn.setText("▶")
            target = config.CHART_PANEL_WIDTH
        else:
            self.chart_btn.setText("◀")
            target = 0

        start = self.chart_panel.maximumWidth()
        base = self.width() - start  # 본문+화살표 폭은 고정 유지

        anim = QPropertyAnimation(self.chart_panel, b"maximumWidth", self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.setStartValue(start)
        anim.setEndValue(target)

        def on_val(v):
            self.chart_panel.setMinimumWidth(int(v))
            self.resize(base + int(v), self.height())

        anim.valueChanged.connect(on_val)
        anim.start()
        self._chart_anim = anim  # GC 방지

    def sizeHint(self) -> QSize:
        return QSize(config.DEFAULT_WINDOW_WIDTH, config.DEFAULT_WINDOW_HEIGHT)


# 단독 실행 시 (디버그용)
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    w = OverlayWindow()
    w.show()
    sys.exit(app.exec())
