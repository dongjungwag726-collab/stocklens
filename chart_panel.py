"""슬라이딩 차트 패널 — QWebEngineView + lightweight-charts v4.

오버레이 우측에서 펼쳐지는 토스증권 스타일 차트.
- 캔들 / 선 / 영역 전환, MA5·MA20·MA60, 거래량, 전일 종가 기준선
- 크로스헤어 OHLCV 툴팁, 최고/최저가 마커
- 기간 탭(1일/1주/1개월/3개월/1년), 마우스 휠 줌·드래그 스크롤(내장)
- 차트 더블클릭 시 컨트롤 바 토글, '정보' 버튼으로 종목 정보 패널 토글
"""

from __future__ import annotations

import json

from PyQt6.QtCore import QObject, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
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


# ---------------------------------------------------------------------------
# 포맷 헬퍼 (overlay 와 순환 import 방지 위해 로컬 정의)
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


# ---------------------------------------------------------------------------
# JS ↔ Python 브리지 (차트 더블클릭 신호)
# ---------------------------------------------------------------------------
class _Bridge(QObject):
    dbl_clicked = pyqtSignal()

    @pyqtSlot()
    def chartDoubleClicked(self) -> None:
        self.dbl_clicked.emit()


# ---------------------------------------------------------------------------
# HTML/JS 템플릿 (f-string 중괄호 회피 위해 placeholder 치환)
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin:0; padding:0; height:100%; background:__BG__;
               font-family:"Malgun Gothic", sans-serif; overflow:hidden; }
  #chart { position:absolute; top:0; left:0; right:0; bottom:0; }
  #tip { position:absolute; display:none; pointer-events:none; z-index:10;
         background:rgba(22,27,34,0.95); border:1px solid #30363D;
         border-radius:4px; padding:6px 8px; color:__TEXT__; font-size:11px;
         line-height:1.5; white-space:nowrap; }
  #tip .t { color:__DIM__; }
</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="__CDN__"></script>
</head>
<body>
<div id="chart"></div>
<div id="tip"></div>
<script>
var UP="__UP__", DOWN="__DOWN__", DIM="__DIM__";
var MA_COLOR = {5:"__MA5__", 20:"__MA20__", 60:"__MA60__"};
var P=null, TYPE="candle", MAon={5:true,20:true,60:true}, VOLon=true, INTRADAY=false;
var chart, mainSeries=null, volumeSeries=null, maSeries={5:null,20:null,60:null};
var prevLine=null, byTime={};

function fmtWon(v){ return "₩"+Math.round(v).toLocaleString(); }
function fmtTime(t){
  var d=new Date(t*1000);
  function p(n){ return (n<10?"0":"")+n; }
  if(INTRADAY) return p(d.getMonth()+1)+"/"+p(d.getDate())+" "+p(d.getHours())+":"+p(d.getMinutes());
  return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());
}

function initChart(){
  var el=document.getElementById("chart");
  chart=LightweightCharts.createChart(el,{
    layout:{ background:{color:"__BG__"}, textColor:"__TEXT__", fontSize:11 },
    grid:{ vertLines:{color:"__GRID__"}, horzLines:{color:"__GRID__"} },
    rightPriceScale:{ borderColor:"__GRID__" },
    timeScale:{ borderColor:"__GRID__", timeVisible:true, secondsVisible:false,
                rightOffset:4 },
    crosshair:{ mode: LightweightCharts.CrosshairMode.Normal,
                vertLine:{color:DIM,width:1,style:0,labelBackgroundColor:"#30363D"},
                horzLine:{color:DIM,width:1,style:0,labelBackgroundColor:"#30363D"} },
    handleScroll:true, handleScale:true,
    width: el.clientWidth, height: el.clientHeight
  });
  volumeSeries=chart.addHistogramSeries({ priceFormat:{type:"volume"},
                                          priceScaleId:"vol", lastValueVisible:false });
  chart.priceScale("vol").applyOptions({ scaleMargins:{top:0.8, bottom:0} });
  [5,20,60].forEach(function(pd){
    maSeries[pd]=chart.addLineSeries({ color:MA_COLOR[pd], lineWidth:1,
      priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false });
  });
  buildMain();
  chart.subscribeCrosshairMove(onCrosshair);
  window.addEventListener("resize", function(){
    chart.resize(el.clientWidth, el.clientHeight);
  });
  el.addEventListener("dblclick", function(){
    if(window.bridge) window.bridge.chartDoubleClicked();
  });
}

function buildMain(){
  if(mainSeries){ chart.removeSeries(mainSeries); mainSeries=null; prevLine=null; }
  if(TYPE==="candle"){
    mainSeries=chart.addCandlestickSeries({ upColor:UP, downColor:DOWN,
      borderUpColor:UP, borderDownColor:DOWN, wickUpColor:UP, wickDownColor:DOWN });
  } else if(TYPE==="line"){
    mainSeries=chart.addLineSeries({ color:UP, lineWidth:2 });
  } else {
    mainSeries=chart.addAreaSeries({ lineColor:UP, topColor:"rgba(255,75,75,0.4)",
      bottomColor:"rgba(255,75,75,0.0)", lineWidth:2 });
  }
  renderMain();
}

function renderMain(){
  if(!P || !mainSeries) return;
  var data;
  if(TYPE==="candle"){
    data=P.ohlcv.map(function(d){ return {time:d.time, open:d.open,
      high:d.high, low:d.low, close:d.close}; });
  } else {
    data=P.ohlcv.map(function(d){ return {time:d.time, value:d.close}; });
  }
  mainSeries.setData(data);
  addMarkers();
  addPrevLine();
}

function addMarkers(){
  if(!P || !P.ohlcv.length) return;
  var hi=-Infinity, lo=Infinity, hiB=null, loB=null;
  P.ohlcv.forEach(function(d){
    if(d.high>hi){ hi=d.high; hiB=d; }
    if(d.low<lo){ lo=d.low; loB=d; }
  });
  var marks=[
    { time:hiB.time, position:"aboveBar", color:UP, shape:"arrowDown",
      text:"최고 "+fmtWon(hi) },
    { time:loB.time, position:"belowBar", color:DOWN, shape:"arrowUp",
      text:"최저 "+fmtWon(lo) }
  ];
  marks.sort(function(a,b){ return a.time-b.time; });
  mainSeries.setMarkers(marks);
}

function addPrevLine(){
  if(prevLine){ mainSeries.removePriceLine(prevLine); prevLine=null; }
  if(P && P.prev_close){
    prevLine=mainSeries.createPriceLine({ price:P.prev_close, color:DIM,
      lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dotted,
      axisLabelVisible:true, title:"전일" });
  }
}

function sma(period){
  var out=[], closes=P.ohlcv;
  for(var i=0;i<closes.length;i++){
    if(i<period-1) continue;
    var s=0; for(var j=i-period+1;j<=i;j++) s+=closes[j].close;
    out.push({time:closes[i].time, value:s/period});
  }
  return out;
}

function buildAll(){
  byTime={};
  P.ohlcv.forEach(function(d){ byTime[d.time]=d; });
  INTRADAY = !!P.intraday;
  chart.applyOptions({ timeScale:{ timeVisible: INTRADAY } });
  volumeSeries.setData(P.ohlcv.map(function(d){
    return { time:d.time, value:d.volume,
             color: d.close>=d.open ? "rgba(255,75,75,0.5)" : "rgba(75,139,255,0.5)" };
  }));
  volumeSeries.applyOptions({ visible: VOLon });
  [5,20,60].forEach(function(pd){
    maSeries[pd].setData(sma(pd));
    maSeries[pd].applyOptions({ visible: MAon[pd] });
  });
  renderMain();
  chart.timeScale().fitContent();
}

function onCrosshair(param){
  var tip=document.getElementById("tip");
  if(!param.time || !param.point || param.point.x<0){ tip.style.display="none"; return; }
  var d=byTime[param.time];
  if(!d){ tip.style.display="none"; return; }
  var chg = (P.prev_close ? ((d.close-P.prev_close)/P.prev_close*100) : null);
  tip.innerHTML =
    "<div class='t'>"+fmtTime(d.time)+"</div>"+
    "<div>시 "+fmtWon(d.open)+"  고 "+fmtWon(d.high)+"</div>"+
    "<div>저 "+fmtWon(d.low)+"  종 "+fmtWon(d.close)+"</div>"+
    "<div>거래량 "+d.volume.toLocaleString()+
      (chg!==null ? "  ("+(chg>=0?"+":"")+chg.toFixed(2)+"%)" : "")+"</div>";
  tip.style.display="block";
  var w=tip.offsetWidth, h=tip.offsetHeight, cw=document.getElementById("chart").clientWidth;
  var x=param.point.x+14; if(x+w>cw) x=param.point.x-w-14; if(x<0) x=4;
  var y=param.point.y+14; if(y<4) y=4;
  tip.style.left=x+"px"; tip.style.top=y+"px";
}

// ---- Python 에서 호출하는 API ----
function setData(p){ P=p; if(!chart) initChart(); else buildAll(); }
function setChartType(t){ TYPE=t; if(chart) buildMain(); }
function toggleMA(period,on){ MAon[period]=on;
  if(maSeries[period]) maSeries[period].applyOptions({visible:on}); }
function toggleVolume(on){ VOLon=on;
  if(volumeSeries) volumeSeries.applyOptions({visible:on}); }

window.addEventListener("load", function(){
  new QWebChannel(qt.webChannelTransport, function(channel){
    window.bridge = channel.objects.bridge;
  });
  initChart();
});
</script>
</body>
</html>
"""


def _render_html() -> str:
    repl = {
        "__CDN__": config.LIGHTWEIGHT_CHARTS_CDN,
        "__BG__": config.COLOR_BG,
        "__TEXT__": config.COLOR_TEXT,
        "__DIM__": config.COLOR_TEXT_DIM,
        "__GRID__": "#21262D",
        "__UP__": config.COLOR_UP,
        "__DOWN__": config.COLOR_DOWN,
        "__MA5__": config.COLOR_MA5,
        "__MA20__": config.COLOR_MA20,
        "__MA60__": config.COLOR_MA60,
    }
    html = _HTML_TEMPLATE
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


# ---------------------------------------------------------------------------
# 차트 패널 위젯
# ---------------------------------------------------------------------------
class ChartPanel(QWidget):
    """오버레이 우측에 슬라이드되는 차트 패널."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chartPanel")

        self._loaded = False
        self._payload: dict | None = None
        self._ticker: str | None = None
        self._name: str = ""
        self._period = "1M"
        self._chart_type = "candle"
        self._ma = {5: True, 20: True, 60: True}
        self._volume = True
        self._thread: ChartFetchThread | None = None

        self._build_ui()
        self._init_web()
        self._apply_style()

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

        # 웹뷰 (차트 본체)
        self.view = QWebEngineView()
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
        pg = QButtonGroup(self)
        pg.setExclusive(True)
        for key, label in (("1D", "1일"), ("1W", "1주"), ("1M", "1개월"),
                           ("3M", "3개월"), ("1Y", "1년")):
            b = QPushButton(label)
            b.setObjectName("periodBtn")
            b.setCheckable(True)
            b.setChecked(key == self._period)
            b.clicked.connect(lambda _=False, k=key: self._on_period(k))
            pg.addButton(b)
            period_bar.addWidget(b)
        root.addLayout(period_bar)

    def _init_web(self) -> None:
        self.channel = QWebChannel()
        self.bridge = _Bridge()
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.bridge.dbl_clicked.connect(self._toggle_control)
        self.view.loadFinished.connect(self._on_loaded)
        self.view.setHtml(_render_html(), QUrl("https://unpkg.com/"))

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
        self.title_lbl.setText(result.get("name") or result.get("ticker", ""))
        if result.get("error"):
            self.title_lbl.setText(
                f"{result.get('name') or result.get('ticker','')}  (조회 실패)"
            )
        self._payload = {
            "ohlcv": result.get("ohlcv", []),
            "prev_close": result.get("prev_close"),
            "intraday": result.get("intraday", False),
        }
        self._apply_payload()
        self._update_info(result.get("info", {}))

    def _apply_payload(self) -> None:
        if not self._loaded or self._payload is None:
            return
        page = self.view.page()
        # 현재 토글 상태를 먼저 반영한 뒤 데이터 적용
        page.runJavaScript(f"setChartType({json.dumps(self._chart_type)});")
        for period, on in self._ma.items():
            page.runJavaScript(f"toggleMA({period}, {str(on).lower()});")
        page.runJavaScript(f"toggleVolume({str(self._volume).lower()});")
        page.runJavaScript(f"setData({json.dumps(self._payload)});")

    def _update_info(self, info: dict) -> None:
        fmt = {
            "price": _won, "change_pct": _pct, "volume": _num,
            "market_cap": _cap, "per": _ratio, "pbr": _ratio,
            "w52_high": _won, "w52_low": _won,
            "day_open": _won, "day_high": _won, "day_low": _won,
        }
        for key, lbl in self._info_vals.items():
            lbl.setText(fmt.get(key, str)(info.get(key)))
        # 등락률 색상
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
    def _on_loaded(self, ok: bool) -> None:
        self._loaded = bool(ok)
        if ok:
            self._apply_payload()

    def _on_type(self, key: str) -> None:
        self._chart_type = key
        if self._loaded:
            self.view.page().runJavaScript(f"setChartType({json.dumps(key)});")

    def _on_ma(self, period: int, on: bool) -> None:
        self._ma[period] = on
        if self._loaded:
            self.view.page().runJavaScript(
                f"toggleMA({period}, {str(on).lower()});"
            )

    def _on_volume(self, on: bool) -> None:
        self._volume = on
        if self._loaded:
            self.view.page().runJavaScript(f"toggleVolume({str(on).lower()});")

    def _on_period(self, key: str) -> None:
        self._period = key
        self._fetch()

    def _toggle_info(self, on: bool) -> None:
        self.info_panel.setVisible(on)

    def _toggle_control(self) -> None:
        self.control_bar.setVisible(not self.control_bar.isVisible())
