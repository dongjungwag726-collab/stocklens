"""슬라이딩 차트 패널 — pyqtgraph 렌더링.

QWebEngineView 대신 pyqtgraph 로 네이티브 렌더링하여 Python 3.13 DLL 문제를 회피.
오버레이 우측에서 펼쳐지는 토스증권 스타일 차트.
- 캔들 / 선 / 영역 전환, MA5·MA20·MA60, 거래량, 전일 종가 기준선
- 크로스헤어 OHLCV 툴팁, 최고/최저가 마커
- 기간 탭(1일/1주/1개월/3개월/1년), 마우스 휠 줌·드래그 스크롤(pyqtgraph 내장)
- 차트 더블클릭 시 컨트롤 바 토글, '정보' 버튼으로 종목 정보 패널 토글
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPicture
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from data_fetcher import ChartFetchThread

# pyqtgraph 전역 설정 (다크 테마)
pg.setConfigOptions(antialias=True, background=config.COLOR_BG,
                    foreground=config.COLOR_TEXT)


# ---------------------------------------------------------------------------
# 포맷 헬퍼
# ---------------------------------------------------------------------------
def _won(v) -> str:
    return f"₩{v:,.0f}" if isinstance(v, (int, float)) else "-"


def _pct(v) -> str:
    if not isinstance(v, (int, float)):
        return "-"
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "■")
    return f"{arrow} {v:+.2f}%"


def _num(v) -> str:
    return f"{v:,}" if isinstance(v, (int, float)) else "-"


def _ratio(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "-"


def _cap(v) -> str:
    if not isinstance(v, (int, float)):
        return "-"
    if v >= 1e12:
        return f"{v / 1e12:.2f}조"
    if v >= 1e8:
        return f"{v / 1e8:.0f}억"
    return f"{v:,.0f}"


def _moving_average(closes: np.ndarray, period: int) -> np.ndarray:
    """단순이동평균. 앞쪽 (period-1) 구간은 NaN (그래프에서 끊김)."""
    n = len(closes)
    out = np.full(n, np.nan)
    if n >= period:
        c = np.cumsum(np.insert(closes, 0, 0.0))
        out[period - 1:] = (c[period:] - c[:-period]) / period
    return out


# ---------------------------------------------------------------------------
# 캔들스틱 아이템
# ---------------------------------------------------------------------------
class CandlestickItem(pg.GraphicsObject):
    """x = 인덱스, 봉 = open/high/low/close 인 캔들 차트 아이템."""

    def __init__(self, bars: list[dict]) -> None:
        super().__init__()
        self._bars = bars
        self._picture = QPicture()
        self._generate()

    def _generate(self) -> None:
        self._picture = QPicture()
        painter = QPainter(self._picture)
        up = QColor(config.COLOR_UP)
        down = QColor(config.COLOR_DOWN)
        half = 0.35
        for i, b in enumerate(self._bars):
            o, h, l, c = b["open"], b["high"], b["low"], b["close"]
            if None in (o, h, l, c):
                continue
            color = up if c >= o else down
            painter.setPen(pg.mkPen(color, width=1))
            # 심지 (고가-저가)
            painter.drawLine(QPointF(i, l), QPointF(i, h))
            # 몸통 (시가-종가)
            top, bot = max(o, c), min(o, c)
            if top == bot:  # 도지: 얇은 선이라도 보이게
                top = bot + max(abs(bot) * 1e-4, 1.0)
            painter.setBrush(pg.mkBrush(color))
            painter.drawRect(QRectF(i - half, bot, half * 2, top - bot))
        painter.end()

    def paint(self, painter, *args) -> None:
        painter.drawPicture(0, 0, self._picture)

    def boundingRect(self) -> QRectF:
        return QRectF(self._picture.boundingRect())


# ---------------------------------------------------------------------------
# 시간(인덱스→라벨) 축
# ---------------------------------------------------------------------------
class TimeAxisItem(pg.AxisItem):
    """인덱스 tick 을 시간 문자열로 변환하는 하단 축."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._times: list[int] = []
        self._intraday = False

    def set_times(self, times: list[int], intraday: bool) -> None:
        self._times = times
        self._intraday = intraday
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            i = int(round(v))
            if 0 <= i < len(self._times):
                d = datetime.fromtimestamp(self._times[i])
                out.append(d.strftime("%H:%M") if self._intraday
                           else d.strftime("%m/%d"))
            else:
                out.append("")
        return out


# ---------------------------------------------------------------------------
# 더블클릭 신호를 주는 그래픽스 위젯
# ---------------------------------------------------------------------------
class _ChartView(pg.GraphicsLayoutWidget):
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(ev)


# ---------------------------------------------------------------------------
# 차트 패널 위젯
# ---------------------------------------------------------------------------
class ChartPanel(QWidget):
    """오버레이 우측에 슬라이드되는 차트 패널 (pyqtgraph)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chartPanel")

        self._ticker: str | None = None
        self._name: str = ""
        self._period = "1M"
        self._chart_type = "candle"
        self._ma = {5: True, 20: True, 60: True}
        self._volume = True
        self._thread: ChartFetchThread | None = None

        # 차트 데이터
        self._bars: list[dict] = []
        self._times: list[int] = []
        self._prev_close: float | None = None
        self._intraday = False

        # 렌더링 아이템 핸들
        self._main_item = None
        self._ma_items: dict[int, pg.PlotDataItem] = {}
        self._vol_item = None
        self._prev_line = None
        self._markers: list = []

        self._build_ui()
        self._build_chart()
        self._apply_style()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 헤더: 종목명 + 정보 토글
        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 6, 2)
        self.title_lbl = QLabel("종목 미선택")
        self.title_lbl.setObjectName("chartTitle")
        self.info_btn = QPushButton("정보")
        self.info_btn.setObjectName("ctrlBtn")
        self.info_btn.setCheckable(True)
        self.info_btn.setFixedWidth(44)
        self.info_btn.toggled.connect(self._toggle_info)
        header.addWidget(self.title_lbl, 1)
        header.addWidget(self.info_btn)
        root.addLayout(header)

        # 컨트롤 바 (차트 더블클릭으로 토글, 기본 숨김)
        self.control_bar = QFrame()
        self.control_bar.setObjectName("controlBar")
        cb = QHBoxLayout(self.control_bar)
        cb.setContentsMargins(6, 2, 6, 2)
        cb.setSpacing(3)

        type_group = QButtonGroup(self)
        type_group.setExclusive(True)
        for label, key in (("캔들", "candle"), ("선", "line"), ("영역", "area")):
            b = QPushButton(label)
            b.setObjectName("ctrlBtn")
            b.setCheckable(True)
            b.setChecked(key == self._chart_type)
            b.clicked.connect(lambda _=False, k=key: self._on_type(k))
            type_group.addButton(b)
            cb.addWidget(b)

        sep = QLabel("|")
        sep.setObjectName("sep")
        cb.addWidget(sep)

        for period, label, color in (
            (5, "MA5", config.COLOR_MA5),
            (20, "MA20", config.COLOR_MA20),
            (60, "MA60", config.COLOR_MA60),
        ):
            b = QPushButton(label)
            b.setObjectName("ctrlBtn")
            b.setCheckable(True)
            b.setChecked(True)
            b.setStyleSheet(f"#ctrlBtn:checked {{ color:{color}; }}")
            b.toggled.connect(lambda on, p=period: self._on_ma(p, on))
            cb.addWidget(b)

        self.vol_btn = QPushButton("거래량")
        self.vol_btn.setObjectName("ctrlBtn")
        self.vol_btn.setCheckable(True)
        self.vol_btn.setChecked(True)
        self.vol_btn.toggled.connect(self._on_volume)
        cb.addWidget(self.vol_btn)
        cb.addStretch(1)

        self.control_bar.setVisible(False)
        root.addWidget(self.control_bar)

        # 차트 (pyqtgraph)
        self.view = _ChartView()
        self.view.double_clicked.connect(self._toggle_control)
        root.addWidget(self.view, 1)

        # 종목 정보 패널 (기본 숨김)
        self.info_panel = QFrame()
        self.info_panel.setObjectName("infoPanel")
        grid = QGridLayout(self.info_panel)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self._info_vals: dict[str, QLabel] = {}
        fields = [
            ("현재가", "price"), ("등락률", "change_pct"), ("거래량", "volume"),
            ("시가총액", "market_cap"), ("PER", "per"), ("PBR", "pbr"),
            ("52주 최고", "w52_high"), ("52주 최저", "w52_low"), ("", None),
            ("시가", "day_open"), ("고가", "day_high"), ("저가", "day_low"),
        ]
        for i, (label, key) in enumerate(fields):
            r, c = divmod(i, 3)
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            cap = QLabel(label)
            cap.setObjectName("infoCap")
            val = QLabel("-")
            val.setObjectName("infoVal")
            box.addWidget(cap)
            box.addWidget(val)
            grid.addWidget(cell, r, c)
            if key:
                self._info_vals[key] = val
        self.info_panel.setVisible(False)
        root.addWidget(self.info_panel)

        # 기간 탭 (하단, 항상 표시)
        period_bar = QHBoxLayout()
        period_bar.setContentsMargins(4, 2, 4, 4)
        period_bar.setSpacing(2)
        pg_group = QButtonGroup(self)
        pg_group.setExclusive(True)
        for key, label in (("1D", "1일"), ("1W", "1주"), ("1M", "1개월"),
                           ("3M", "3개월"), ("1Y", "1년")):
            b = QPushButton(label)
            b.setObjectName("periodBtn")
            b.setCheckable(True)
            b.setChecked(key == self._period)
            b.clicked.connect(lambda _=False, k=key: self._on_period(k))
            pg_group.addButton(b)
            period_bar.addWidget(b)
        root.addLayout(period_bar)

    def _build_chart(self) -> None:
        """가격/거래량 플롯, 크로스헤어, 툴팁을 1회 구성."""
        grid = "#21262D"
        self.price_plot = self.view.addPlot(row=0, col=0)
        self.price_plot.showGrid(x=True, y=True, alpha=0.15)
        self.price_plot.hideAxis("bottom")
        self.price_plot.getAxis("left").setWidth(54)

        self.time_axis = TimeAxisItem(orientation="bottom")
        self.volume_plot = self.view.addPlot(
            row=1, col=0, axisItems={"bottom": self.time_axis}
        )
        self.volume_plot.showGrid(x=True, y=True, alpha=0.15)
        self.volume_plot.setXLink(self.price_plot)
        self.volume_plot.getAxis("left").setWidth(54)
        self.volume_plot.setMaximumHeight(110)

        # 가격:거래량 = 3:1
        self.view.ci.layout.setRowStretchFactor(0, 3)
        self.view.ci.layout.setRowStretchFactor(1, 1)

        # 크로스헤어 + 툴팁
        pen = pg.mkPen(config.COLOR_TEXT_DIM, width=1,
                       style=pg.QtCore.Qt.PenStyle.DashLine)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        self.price_plot.addItem(self.vline, ignoreBounds=True)
        self.price_plot.addItem(self.hline, ignoreBounds=True)
        self.tooltip = pg.TextItem(anchor=(0, 1))
        self.tooltip.setZValue(100)
        self.price_plot.addItem(self.tooltip)
        self._set_crosshair_visible(False)

        self.view.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            #chartPanel {{
                background-color: {config.COLOR_BG};
                border-left: 1px solid #21262D;
            }}
            #chartTitle {{ font-weight: 600; color: {config.COLOR_TEXT}; }}
            #controlBar, #infoPanel {{ background-color: {config.COLOR_HANDLE}; }}
            #ctrlBtn, #periodBtn {{
                background-color: {config.COLOR_HANDLE};
                color: {config.COLOR_TEXT};
                border: 1px solid #30363D;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }}
            #ctrlBtn:checked, #periodBtn:checked {{
                background-color: {config.COLOR_ACCENT};
                border-color: {config.COLOR_ACCENT};
            }}
            #periodBtn {{ padding: 3px 0; }}
            #sep {{ color: #30363D; }}
            #infoCap {{ color: {config.COLOR_TEXT_DIM}; font-size: 10px; }}
            #infoVal {{ color: {config.COLOR_TEXT}; font-size: 12px; font-weight: 600; }}
        """)

    # ------------------------------------------------------------------
    # 외부 API
    # ------------------------------------------------------------------
    def set_symbol(self, ticker: str, name: str) -> None:
        self._ticker = ticker
        self._name = name
        self.title_lbl.setText(name or ticker)
        self._fetch()

    # ------------------------------------------------------------------
    # 데이터 조회
    # ------------------------------------------------------------------
    def _fetch(self) -> None:
        if not self._ticker:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        self.title_lbl.setText(f"{self._name or self._ticker}  ⏳")
        self._thread = ChartFetchThread(self._ticker, self._name, self._period)
        self._thread.chart_ready.connect(self._on_chart)
        self._thread.start()

    def _on_chart(self, result: dict) -> None:
        name = result.get("name") or result.get("ticker", "")
        if result.get("error"):
            self.title_lbl.setText(f"{name}  (조회 실패)")
        else:
            self.title_lbl.setText(name)

        self._bars = result.get("ohlcv", []) or []
        self._times = [b["time"] for b in self._bars]
        self._prev_close = result.get("prev_close")
        self._intraday = bool(result.get("intraday", False))

        self._render_all()
        self._update_info(result.get("info", {}))

    # ------------------------------------------------------------------
    # 렌더링
    # ------------------------------------------------------------------
    def _render_all(self) -> None:
        self.time_axis.set_times(self._times, self._intraday)
        self._render_volume()
        self._render_ma()
        self._render_main()
        self._render_prev_line()
        self._render_markers()
        if self._bars:
            self.price_plot.setXRange(-1, len(self._bars), padding=0.02)
            self.price_plot.enableAutoRange(axis="y")

    def _clear_main(self) -> None:
        if self._main_item is not None:
            self.price_plot.removeItem(self._main_item)
            self._main_item = None

    def _render_main(self) -> None:
        self._clear_main()
        if not self._bars:
            return
        x = np.arange(len(self._bars))
        closes = np.array([b["close"] for b in self._bars], dtype=float)

        if self._chart_type == "candle":
            self._main_item = CandlestickItem(self._bars)
            self.price_plot.addItem(self._main_item)
        elif self._chart_type == "line":
            self._main_item = pg.PlotDataItem(
                x, closes, pen=pg.mkPen(config.COLOR_UP, width=2)
            )
            self.price_plot.addItem(self._main_item)
        else:  # area
            base = float(np.nanmin([b["low"] for b in self._bars]))
            self._main_item = pg.PlotDataItem(
                x, closes, pen=pg.mkPen(config.COLOR_UP, width=2),
                fillLevel=base, brush=pg.mkBrush(255, 75, 75, 60)
            )
            self.price_plot.addItem(self._main_item)

    def _render_ma(self) -> None:
        for item in self._ma_items.values():
            self.price_plot.removeItem(item)
        self._ma_items.clear()
        if not self._bars:
            return
        x = np.arange(len(self._bars))
        closes = np.array([b["close"] for b in self._bars], dtype=float)
        colors = {5: config.COLOR_MA5, 20: config.COLOR_MA20, 60: config.COLOR_MA60}
        for period, color in colors.items():
            y = _moving_average(closes, period)
            item = pg.PlotDataItem(
                x, y, pen=pg.mkPen(color, width=1), connect="finite"
            )
            item.setVisible(self._ma[period])
            self.price_plot.addItem(item)
            self._ma_items[period] = item

    def _render_volume(self) -> None:
        if self._vol_item is not None:
            self.volume_plot.removeItem(self._vol_item)
            self._vol_item = None
        if not self._bars:
            return
        x = np.arange(len(self._bars))
        heights = np.array([b.get("volume") or 0 for b in self._bars], dtype=float)
        brushes = [
            pg.mkBrush(255, 75, 75, 130) if b["close"] >= b["open"]
            else pg.mkBrush(75, 139, 255, 130)
            for b in self._bars
        ]
        self._vol_item = pg.BarGraphItem(x=x, height=heights, width=0.7,
                                         brushes=brushes, pen=None)
        self._vol_item.setVisible(self._volume)
        self.volume_plot.addItem(self._vol_item)

    def _render_prev_line(self) -> None:
        if self._prev_line is not None:
            self.price_plot.removeItem(self._prev_line)
            self._prev_line = None
        if self._prev_close:
            pen = pg.mkPen(config.COLOR_TEXT_DIM, width=1,
                           style=pg.QtCore.Qt.PenStyle.DotLine)
            self._prev_line = pg.InfiniteLine(
                pos=self._prev_close, angle=0, pen=pen,
                label="전일 {value:,.0f}",
                labelOpts={"color": config.COLOR_TEXT_DIM, "position": 0.02},
            )
            self.price_plot.addItem(self._prev_line, ignoreBounds=True)

    def _render_markers(self) -> None:
        for m in self._markers:
            self.price_plot.removeItem(m)
        self._markers = []
        if not self._bars:
            return
        highs = [b["high"] for b in self._bars]
        lows = [b["low"] for b in self._bars]
        hi_i = int(np.argmax(highs))
        lo_i = int(np.argmin(lows))
        hi = pg.TextItem(f"최고 {_won(highs[hi_i])}", color=config.COLOR_UP,
                         anchor=(0.5, 1.2))
        hi.setPos(hi_i, highs[hi_i])
        lo = pg.TextItem(f"최저 {_won(lows[lo_i])}", color=config.COLOR_DOWN,
                         anchor=(0.5, -0.2))
        lo.setPos(lo_i, lows[lo_i])
        for m in (hi, lo):
            m.setZValue(50)
            self.price_plot.addItem(m)
            self._markers.append(m)

    # ------------------------------------------------------------------
    # 크로스헤어 / 툴팁
    # ------------------------------------------------------------------
    def _set_crosshair_visible(self, on: bool) -> None:
        self.vline.setVisible(on)
        self.hline.setVisible(on)
        self.tooltip.setVisible(on)

    def _on_mouse_moved(self, pos) -> None:
        if not self._bars:
            self._set_crosshair_visible(False)
            return
        vb = self.price_plot.vb
        if not self.price_plot.sceneBoundingRect().contains(pos):
            self._set_crosshair_visible(False)
            return
        mp = vb.mapSceneToView(pos)
        i = int(round(mp.x()))
        if i < 0 or i >= len(self._bars):
            self._set_crosshair_visible(False)
            return

        b = self._bars[i]
        self._set_crosshair_visible(True)
        self.vline.setPos(i)
        self.hline.setPos(mp.y())

        chg = ((b["close"] - self._prev_close) / self._prev_close * 100.0
               if self._prev_close else None)
        d = datetime.fromtimestamp(b["time"])
        t_str = d.strftime("%m/%d %H:%M" if self._intraday else "%Y-%m-%d")
        chg_str = f"  ({chg:+.2f}%)" if chg is not None else ""
        html = (
            f"<div style='background:rgba(22,27,34,0.95);"
            f"border:1px solid #30363D;padding:4px 6px;"
            f"color:{config.COLOR_TEXT};font-size:11px;'>"
            f"<span style='color:{config.COLOR_TEXT_DIM}'>{t_str}</span><br>"
            f"시 {_won(b['open'])}  고 {_won(b['high'])}<br>"
            f"저 {_won(b['low'])}  종 {_won(b['close'])}<br>"
            f"거래량 {b.get('volume', 0):,}{chg_str}</div>"
        )
        self.tooltip.setHtml(html)
        # 커서가 우측 절반이면 왼쪽으로 펼치도록 anchor 전환
        right_half = i > len(self._bars) / 2
        self.tooltip.setAnchor((1, 1) if right_half else (0, 1))
        self.tooltip.setPos(i, mp.y())

    # ------------------------------------------------------------------
    # 정보 패널
    # ------------------------------------------------------------------
    def _update_info(self, info: dict) -> None:
        fmt = {
            "price": _won, "change_pct": _pct, "volume": _num,
            "market_cap": _cap, "per": _ratio, "pbr": _ratio,
            "w52_high": _won, "w52_low": _won,
            "day_open": _won, "day_high": _won, "day_low": _won,
        }
        for key, lbl in self._info_vals.items():
            lbl.setText(fmt.get(key, str)(info.get(key)))
        chg = info.get("change_pct")
        if "change_pct" in self._info_vals and isinstance(chg, (int, float)):
            color = (config.COLOR_UP if chg > 0
                     else config.COLOR_DOWN if chg < 0 else config.COLOR_TEXT_DIM)
            self._info_vals["change_pct"].setStyleSheet(
                f"#infoVal {{ color:{color}; }}"
            )

    # ------------------------------------------------------------------
    # 핸들러
    # ------------------------------------------------------------------
    def _on_type(self, key: str) -> None:
        self._chart_type = key
        self._render_main()

    def _on_ma(self, period: int, on: bool) -> None:
        self._ma[period] = on
        item = self._ma_items.get(period)
        if item is not None:
            item.setVisible(on)

    def _on_volume(self, on: bool) -> None:
        self._volume = on
        if self._vol_item is not None:
            self._vol_item.setVisible(on)

    def _on_period(self, key: str) -> None:
        self._period = key
        self._fetch()

    def _toggle_info(self, on: bool) -> None:
        self.info_panel.setVisible(on)

    def _toggle_control(self) -> None:
        self.control_bar.setVisible(not self.control_bar.isVisible())
