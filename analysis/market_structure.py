"""Estrutura de mercado: topos e fundos (swings) e tendência.

Regras:
- Topo (swing high): máxima MAIOR que as máximas das N velas antes e das N depois.
- Fundo (swing low): mínima MENOR que as mínimas das N velas antes e das N depois.
- Empate não forma topo nem fundo.
- Um topo/fundo só é "conhecido" depois que as N velas seguintes fecharam
  (confirmação). Nunca usamos um swing antes disso: evita "olhar o futuro".
- N (window) = 2 por padrão. É uma formalização técnica, não número da apostila.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from .candles import Candle, CandleInput, parse_candles

INSUFICIENTE = "ESTRUTURA_INSUFICIENTE"
MISTA = "ESTRUTURA_MISTA_OU_INDEFINIDA"
ALTA = "ALTA"
BAIXA = "BAIXA"


@dataclass(frozen=True)
class Swing:
    kind: str  # "high" (topo) ou "low" (fundo)
    price: float
    origin_index: int  # candle onde o topo/fundo aconteceu
    origin_time: datetime
    confirmation_index: int  # candle cujo fechamento confirma o swing
    confirmation_time: datetime
    label: Optional[str] = None  # HH, LH, EQH, HL, LL, EQL (None = primeiro do tipo)


@dataclass(frozen=True)
class StructureResult:
    candles: tuple[Candle, ...]  # somente candles fechados
    swings: tuple[Swing, ...]  # em ordem de confirmação
    trend: str

    def swings_known_before(self, index: int) -> tuple[Swing, ...]:
        """Swings que já estavam confirmados ANTES do candle `index`."""
        return tuple(s for s in self.swings if s.confirmation_index < index)


def find_swings(candles: list[Candle], window: int = 2) -> list[Swing]:
    if window < 1:
        raise ValueError("window precisa ser >= 1")
    swings: list[Swing] = []
    last_high: Optional[float] = None
    last_low: Optional[float] = None
    for i in range(window, len(candles) - window):
        neighbors = candles[i - window : i] + candles[i + 1 : i + window + 1]
        c = candles[i]
        confirm = i + window
        if all(c.high > n.high for n in neighbors):
            label = None if last_high is None else (
                "HH" if c.high > last_high else "LH" if c.high < last_high else "EQH"
            )
            swings.append(Swing("high", c.high, i, c.timestamp, confirm,
                                candles[confirm].timestamp, label))
            last_high = c.high
        if all(c.low < n.low for n in neighbors):
            label = None if last_low is None else (
                "HL" if c.low > last_low else "LL" if c.low < last_low else "EQL"
            )
            swings.append(Swing("low", c.low, i, c.timestamp, confirm,
                                candles[confirm].timestamp, label))
            last_low = c.low
    return swings


def classify_trend(swings: Iterable[Swing]) -> str:
    """Tendência pelos swings mais recentes: HH+HL = alta, LH+LL = baixa."""
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return INSUFICIENTE
    pair = (highs[-1].label, lows[-1].label)
    if pair == ("HH", "HL"):
        return ALTA
    if pair == ("LH", "LL"):
        return BAIXA
    return MISTA


def analyze_structure(
    values: Iterable[CandleInput], last_candle_closed: bool, window: int = 2
) -> StructureResult:
    """Analisa a estrutura. Se o último candle ainda está aberto, ele é ignorado."""
    candles = parse_candles(values)
    if not last_candle_closed:
        candles = candles[:-1]
    swings = find_swings(candles, window)
    return StructureResult(tuple(candles), tuple(swings), classify_trend(swings))
