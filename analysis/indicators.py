"""Indicadores simples. Por enquanto só o RSI (Índice de Força Relativa)."""
from __future__ import annotations

from typing import Optional, Sequence


def rsi(closes: Sequence[float], period: int = 14) -> list[Optional[float]]:
    """RSI clássico (suavização de Wilder). Devolve None enquanto não há dados suficientes.

    O período 14 é o padrão de mercado (a apostila não fixa um número).
    """
    if period < 1:
        raise ValueError("period precisa ser >= 1")
    out: list[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period

    def value() -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    out[period] = value()
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = value()
    return out
