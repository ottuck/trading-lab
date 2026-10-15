"""캔들분석 AI 봇에게 보여줄 차트 그림 (project.md 14절 "캔들분석 AI 봇").

익명 표(지수로 바꾼 일봉·주봉)만으로 그린다: 종목 이름·날짜·실제 가격은 들어가지 않는다. 같은
표면 늘 같은 그림이라 판단 기록에는 그림 대신 표를 남긴다. 그림 크기는 실험(2026-10-09)과 같은
800×500으로 고정한다: 크기가 바뀌면 AI 입력 토큰(비용)과 읽는 결과가 달라진다.
"""

import io
from collections.abc import Sequence
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")  # 화면 없는 서버에서 그린다
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import Rectangle

UP, DOWN = "#d6302f", "#2f6fd6"  # 빨강은 오른 봉, 파랑은 내린 봉 (국내 관례)
SIZE = (8, 5)  # 인치, DPI 100으로 800×500 픽셀
DPI = 100

Ohlc = tuple[Decimal, Decimal, Decimal, Decimal]


def _candles(ax: Axes, rows: Sequence[Ohlc]) -> None:
    for i, (o, h, lo, c) in enumerate(rows):
        o_, h_, lo_, c_ = float(o), float(h), float(lo), float(c)
        color = UP if c_ >= o_ else DOWN
        ax.vlines(i, lo_, h_, color=color, linewidth=0.8)
        body = max(abs(c_ - o_), 0.05)  # 시가 = 종가인 봉도 보이게
        ax.add_patch(Rectangle((i - 0.35, min(o_, c_)), 0.7, body, color=color))
    ax.set_xlim(-1, len(rows))
    ax.set_xticks([])
    ax.grid(axis="y", alpha=0.3)


def candle_chart(label: str, daily: Sequence[Ohlc], weekly: Sequence[Ohlc]) -> bytes:
    """위는 일봉, 아래는 주봉인 PNG (세로축은 판단일 종가 = 100인 지수)."""
    fig, (top, bottom) = plt.subplots(2, 1, figsize=SIZE, dpi=DPI, height_ratios=[3, 2])
    try:
        _candles(top, daily)
        _candles(bottom, weekly)
        top.set_title(f"{label} daily {len(daily)}", fontsize=10, loc="left")
        bottom.set_title(f"{label} weekly {len(weekly)}", fontsize=10, loc="left")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        plt.close(fig)
