"""Backtest do Modelo 1 com alinhamento de tempos gráficos e filtros de intenção.

Uso:  python -m backtest.run_mtf PASTA_DOS_DADOS
Hipóteses testadas (todas tiradas da apostila, definidas ANTES de olhar o resultado):
  H1. Entrar só a favor da estrutura do tempo maior.
  H2. O movimento do CHoCH deixou ineficiência (FVG).
  H3. O candle do CHoCH é "cheio" (corpo >= 60% do candle).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import timedelta

from analysis.choch_bos import analyze_choch_bos
from analysis.model1 import Model1Config
from analysis.multi_timeframe import INTERVAL_SECONDS, aligned, last_closed_index
from backtest.run_model1 import STEP, WARMUP, backtest, load, summarize

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
PAIRS = (("4h", "1h"), ("4h", "15m"), ("1h", "15m"))  # (tempo maior, tempo menor)


def rolling_states(candles) -> list[str]:
    """Estado da estrutura ao fechar cada candle, calculado em janelas (como ao vivo)."""
    states: list[str] = []
    for start in range(0, len(candles), STEP):
        lo = max(0, start - WARMUP)
        r = analyze_choch_bos(candles[lo:start + STEP], True)
        states.extend(r.states[start - lo:])
    return states


def main(folder: str) -> None:
    cfg = Model1Config()
    data = {(s, i): load(folder, s, i) for s in SYMBOLS for i in ("4h", "1h", "15m")}
    states = {k: rolling_states(v) for k, v in data.items() if k[1] in ("4h", "1h")}
    trades = {k: backtest(v, cfg) for k, v in data.items() if k[1] in ("1h", "15m")}
    groups = defaultdict(list)
    for htf, ltf in PAIRS:
        for sym in SYMBOLS:
            opens = [c.timestamp for c in data[(sym, htf)]]
            for t in trades[(sym, ltf)]:
                s = t["setup"]
                close_time = s.time + timedelta(seconds=INTERVAL_SECONDS[ltf])
                i = last_closed_index(opens, close_time, htf)
                a = None if i is None else aligned(s.direction, states[(sym, htf)][i])
                tag = {True: "A FAVOR", False: "CONTRA", None: "sem direcao"}[a]
                pair = f"{htf}>{ltf}"
                full = s.choch_body_ratio >= 0.6
                groups[f"{pair} | {tag}"].append(t)
                groups[f"{pair} | FVG={s.fvg}"].append(t)
                groups[f"{pair} | candle cheio={full}"].append(t)
                if a:
                    groups[f"{pair} | A FAVOR + FVG={s.fvg}"].append(t)
                    groups[f"{pair} | A FAVOR + cheio={full}"].append(t)
                    if s.fvg and full:
                        groups[f"{pair} | A FAVOR + FVG + cheio"].append(t)
                        period = "ate 2025" if s.time.year <= 2025 else "2026"
                        groups[f"{pair} | A FAVOR + FVG + cheio | {period}"].append(t)
                        groups[f"{pair} | A FAVOR + FVG + cheio | {sym}"].append(t)
                    period = "ate 2025" if s.time.year <= 2025 else "2026"
                    groups[f"{pair} | A FAVOR | {period}"].append(t)
    for name in sorted(groups):
        r = summarize(groups[name])
        print(f"{name:48s} entradas={r['entradas']:5d} acerto={r['acerto_pct']}% "
              f"total={r['resultado_R']}R media={r['media_R']}R")


if __name__ == "__main__":
    main(sys.argv[1])
