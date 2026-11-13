"""Backtest do Modelo 1 em candles históricos da Binance.

Uso:  python -m backtest.run_model1 PASTA_DOS_DADOS
A pasta deve ter arquivos PASTA/SIMBOLO/INTERVALO/*.json no formato de klines
da Binance ([abertura_ms, open, high, low, close, volume, ...]).

Como funciona: o histórico é analisado em janelas (como o bot fará ao vivo,
olhando só os candles recentes). Cada cenário encontrado é acompanhado nos
candles seguintes até bater no alvo ou no stop.

Limitações honestas: não desconta taxas nem "escorregão" de preço; se stop e
alvo caem no mesmo candle, conta como stop; resultado passado não garante futuro.
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

from analysis.candles import Candle
from analysis.model1 import Model1Config, evaluate_setup, find_model1_setups

WARMUP, STEP, HORIZON = 500, 1000, 400


def load(folder: str, symbol: str, interval: str) -> list[Candle]:
    rows = {}
    for path in sorted(glob.glob(f"{folder}/{symbol}/{interval}/*.json")):
        with open(path, encoding="utf-8") as f:
            for k in json.load(f):
                rows[int(k[0])] = k
    return [Candle(datetime.fromtimestamp(t / 1000, timezone.utc),
                   float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
            for t, k in sorted(rows.items())]


def backtest(candles: list[Candle], cfg: Model1Config) -> list[dict]:
    trades = []
    for start in range(0, len(candles), STEP):
        lo = max(0, start - WARMUP)
        window = candles[lo:start + STEP]
        for s in find_model1_setups(window, True, cfg):
            pos = lo + s.index                 # posição no histórico completo
            if pos < start:
                continue                       # parte de aquecimento: já contada antes
            future = candles[pos + 1: pos + 1 + HORIZON]
            out = evaluate_setup(s, [None] * (s.index + 1) + future)  # type: ignore[list-item]
            trades.append({"setup": s, "outcome": out})
    return trades


def summarize(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["outcome"].status in ("ALVO", "STOP")]
    wins = sum(t["outcome"].status == "ALVO" for t in closed)
    total_r = sum(t["outcome"].result_r for t in closed)
    return {
        "cenarios": len(trades),
        "entradas": len(closed),
        "alvos": wins,
        "stops": len(closed) - wins,
        "acerto_pct": round(100 * wins / len(closed), 1) if closed else None,
        "resultado_R": round(total_r, 1),
        "media_R": round(total_r / len(closed), 3) if closed else None,
    }


def main(folder: str) -> None:
    cfg = Model1Config()
    everything, groups = [], defaultdict(list)
    for interval in ("4h", "1h", "15m"):
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"):
            candles = load(folder, symbol, interval)
            trades = backtest(candles, cfg)
            for t in trades:
                t["symbol"], t["interval"] = symbol, interval
            everything += trades
            print(interval, symbol, len(candles), "candles",
                  candles[0].timestamp.date(), "->", candles[-1].timestamp.date(),
                  summarize(trades))
    print("\nTOTAL", summarize(everything))
    for t in everything:
        s = t["setup"]
        groups["tempo " + t["interval"]].append(t)
        groups["moeda " + t["symbol"]].append(t)
        groups["direcao " + s.direction].append(t)
        groups["captura " + s.capture_type].append(t)
        groups["nivel " + ("EQ (2+ toques)" if s.level_touches >= 2 else "simples")].append(t)
        groups["rsi_divergencia " + str(s.rsi_divergence)].append(t)
        groups["order_block " + str(s.has_order_block)].append(t)
        groups["alvo " + s.target_kind].append(t)
        groups["ano " + str(s.time.year)].append(t)
    for name in sorted(groups):
        print(name, summarize(groups[name]))


if __name__ == "__main__":
    main(sys.argv[1])
