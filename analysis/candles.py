"""Candles (velas): validação e leitura básica.

Cada candle tem horário, abertura, máxima, mínima, fechamento e volume.
Este módulo só confere se os dados fazem sentido e calcula medidas simples
(corpo, pavios, direção). Não toma nenhuma decisão de trade.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Union


class CandleError(ValueError):
    """Dado de candle inválido."""


@dataclass(frozen=True)
class Candle:
    timestamp: datetime  # horário de abertura do candle, sempre em UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        ts = self.timestamp
        if not isinstance(ts, datetime):
            raise CandleError("timestamp precisa ser uma data/hora")
        # Sem fuso informado = tratamos como UTC. Com fuso = convertemos para UTC.
        ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        object.__setattr__(self, "timestamp", ts)

        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CandleError(f"{name} precisa ser número")
            value = float(value)
            if not math.isfinite(value):
                raise CandleError(f"{name} precisa ser um número finito")
            if value < 0:
                raise CandleError(f"{name} não pode ser negativo")
            object.__setattr__(self, name, value)

        if self.high < max(self.open, self.close):
            raise CandleError("máxima menor que abertura/fechamento")
        if self.low > min(self.open, self.close):
            raise CandleError("mínima maior que abertura/fechamento")

    @property
    def direction(self) -> str:
        if self.close > self.open:
            return "alta"
        if self.close < self.open:
            return "baixa"
        return "neutro"

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


CandleInput = Union[Candle, Mapping[str, object]]


def to_candle(item: CandleInput) -> Candle:
    if isinstance(item, Candle):
        return item
    if isinstance(item, Mapping):
        try:
            return Candle(
                timestamp=item["timestamp"],  # type: ignore[arg-type]
                open=item["open"],  # type: ignore[arg-type]
                high=item["high"],  # type: ignore[arg-type]
                low=item["low"],  # type: ignore[arg-type]
                close=item["close"],  # type: ignore[arg-type]
                volume=item.get("volume", 0.0),  # type: ignore[arg-type]
            )
        except KeyError as missing:
            raise CandleError(f"campo ausente no candle: {missing}") from None
    raise CandleError("candle precisa ser Candle ou dicionário")


def parse_candles(items: Iterable[CandleInput]) -> list[Candle]:
    """Valida e devolve os candles em ordem cronológica, sem horários repetidos."""
    candles = sorted((to_candle(i) for i in items), key=lambda c: c.timestamp)
    for previous, current in zip(candles, candles[1:]):
        if previous.timestamp == current.timestamp:
            raise CandleError(f"horário repetido: {current.timestamp.isoformat()}")
    return candles
