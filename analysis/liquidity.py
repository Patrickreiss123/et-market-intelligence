"""Liquidez: onde ela está e quando é capturada.

Ideia da apostila: todo topo e todo fundo tem ordens (stops) logo além dele.
Topos/fundos nivelados (EQH/EQL) juntam ainda mais liquidez.

O que este módulo faz, candle a candle, sem olhar o futuro:
1. Cada topo/fundo CONFIRMADO vira um nível de liquidez.
2. Topos (ou fundos) quase no mesmo preço se juntam em um nível só (EQH/EQL).
3. Quando o preço passa do nível, registramos o que aconteceu:
   - TOQUE: passou só um fio (dentro da tolerância) e fechou de volta.
     O nível continua valendo, agora no novo extremo.
   - CAPTURA_PAVIO: passou do nível mas FECHOU de volta (só o pavio ficou além).
   - CAPTURA_CONFIRMADA: o candle seguinte fechou de volta e não renovou o
     extremo do candle da captura (regra descrita na apostila, pág. 377).
   - ROMPIMENTO_FECHAMENTO: o candle fechou além do nível (aceitação).
4. Nível capturado ou rompido deixa de existir: a liquidez dele já foi usada.

Formalizações técnicas (não são números da apostila, são configuráveis):
- tolerance: distância máxima para considerar dois topos "iguais" (padrão 0,1%).
- window: velas de cada lado para confirmar um topo/fundo (padrão 2).

Importante: preço (OHLC) não prova que existiam ordens reais naquele nível.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .candles import CandleInput
from .market_structure import Swing, analyze_structure

BSL = "BSL"  # liquidez acima de topos (buy-side)
SSL = "SSL"  # liquidez abaixo de fundos (sell-side)

TOQUE = "TOQUE"
CAPTURA_PAVIO = "CAPTURA_PAVIO"
CAPTURA_CONFIRMADA = "CAPTURA_CONFIRMADA"
ROMPIMENTO_FECHAMENTO = "ROMPIMENTO_FECHAMENTO"


@dataclass
class LiquidityLevel:
    side: str  # BSL ou SSL
    price: float
    swings: list[Swing] = field(default_factory=list)
    formed_index: int = 0  # candle em que o nível passou a ser conhecido (último reforço)
    active: bool = True
    created_index: int = 0  # candle em que o nível nasceu
    consumed_index: int | None = None  # candle em que foi capturado/rompido

    def active_at(self, index: int) -> bool:
        """O nível existia e ainda não tinha sido usado ao fechar o candle `index`?"""
        return self.created_index <= index and (
            self.consumed_index is None or self.consumed_index > index)

    @property
    def touches(self) -> int:
        return len(self.swings)

    @property
    def kind(self) -> str:
        if self.side == BSL:
            return "EQH" if self.touches >= 2 else "SH"
        return "EQL" if self.touches >= 2 else "SL"


@dataclass(frozen=True)
class LiquidityEvent:
    type: str
    index: int  # candle em que o evento ficou conhecido
    time: datetime
    side: str
    level_kind: str
    level_price: float  # preço do nível no momento do evento
    level_touches: int
    extreme: float  # até onde o preço foi além do nível
    depth_pct: float  # quanto passou do nível, em % (mede se foi "expressiva")
    sweep_index: int  # candle que passou do nível


@dataclass(frozen=True)
class LiquidityResult:
    levels: tuple[LiquidityLevel, ...]  # todos os níveis (ativos e usados)
    events: tuple[LiquidityEvent, ...]  # em ordem cronológica

    @property
    def active_levels(self) -> tuple[LiquidityLevel, ...]:
        return tuple(l for l in self.levels if l.active)


def analyze_liquidity(
    values: Iterable[CandleInput],
    last_candle_closed: bool,
    tolerance: float = 0.001,
    window: int = 2,
) -> LiquidityResult:
    if tolerance < 0:
        raise ValueError("tolerance não pode ser negativa")
    structure = analyze_structure(values, last_candle_closed, window)
    candles = structure.candles

    confirmed_at: dict[int, list[Swing]] = {}
    for s in structure.swings:
        confirmed_at.setdefault(s.confirmation_index, []).append(s)

    levels: list[LiquidityLevel] = []
    events: list[LiquidityEvent] = []
    pending: list[tuple[LiquidityLevel, LiquidityEvent]] = []  # capturas aguardando o candle seguinte

    for j, c in enumerate(candles):
        # 1) Capturas por pavio do candle anterior: este candle confirma?
        for level, sweep in pending:
            sign = 1 if level.side == BSL else -1
            ext = c.high if sign > 0 else c.low
            renewed = sign * (ext - sweep.extreme) > 0
            closed_back = sign * (c.close - sweep.level_price) < 0
            if not renewed and closed_back:
                events.append(LiquidityEvent(
                    CAPTURA_CONFIRMADA, j, c.timestamp, sweep.side, sweep.level_kind,
                    sweep.level_price, sweep.level_touches, sweep.extreme,
                    sweep.depth_pct, sweep.sweep_index))
        pending = []

        # 2) Este candle passou de algum nível já conhecido?
        for level in levels:
            if not level.active or level.formed_index >= j:
                continue
            sign = 1 if level.side == BSL else -1
            ext = c.high if sign > 0 else c.low
            beyond = sign * (ext - level.price)
            if beyond <= 0:
                continue
            depth = beyond / level.price * 100 if level.price else 0.0
            closed_beyond = sign * (c.close - level.price) > 0

            def make(kind: str) -> LiquidityEvent:
                return LiquidityEvent(kind, j, c.timestamp, level.side, level.kind,
                                      level.price, level.touches, ext, depth, j)

            if closed_beyond:
                events.append(make(ROMPIMENTO_FECHAMENTO))
                level.active = False
                level.consumed_index = j
            elif beyond <= tolerance * level.price:
                events.append(make(TOQUE))
                level.price = ext  # a liquidez agora descansa além do novo extremo
            else:
                event = make(CAPTURA_PAVIO)
                events.append(event)
                pending.append((level, event))
                level.active = False
                level.consumed_index = j

        # 3) Topos/fundos confirmados neste candle viram (ou reforçam) níveis.
        for s in confirmed_at.get(j, []):
            side = BSL if s.kind == "high" else SSL
            match = next(
                (l for l in levels if l.active and l.side == side
                 and abs(s.price - l.price) <= tolerance * l.price),
                None,
            )
            if match is None:
                levels.append(LiquidityLevel(side, s.price, [s], j, True, j))
            else:
                match.swings.append(s)
                match.formed_index = j
                match.price = max(match.price, s.price) if side == BSL else min(match.price, s.price)

    return LiquidityResult(tuple(levels), tuple(events))
