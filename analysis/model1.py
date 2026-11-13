"""Modelo 1 da apostila (Checklist Operacional #1): captura de liquidez + CHoCH.

Passo a passo (exemplo de VENDA; a COMPRA é o espelho):
1. Existe uma liquidez nítida acima de um topo (ou de topos iguais).
2. O preço passa desse nível: a liquidez foi capturada.
3. Depois da captura, um candle FECHA abaixo do último fundo confirmado
   deixado antes do extremo da captura: é o CHoCH contrário.
4. Entrada: na região do Order Block (último candle de alta antes da queda),
   nunca abaixo dos 50% do movimento. Sem Order Block, entrada nos 50%.
5. Stop: logo além do extremo da captura.
6. Alvo: a próxima liquidez do lado oposto que entregue o risco x retorno
   mínimo. Se não houver, alvo projetado pelo risco x retorno mínimo.

O que vem da apostila: os 5 itens do checklist, entrada no Order Block,
região acima dos 50%, stop técnico além do extremo, alvo em região de liquidez,
divergência de RSI como bônus (não obrigatória).

Formalizações técnicas (ajustáveis; o backtest vai calibrar):
- qual fundo/topo conta para o CHoCH (último confirmado antes do extremo);
- prazo máximo entre captura e CHoCH (max_bars);
- risco x retorno mínimo (min_rr) e folga do stop (stop_buffer_pct);
- quantos candles olhar para achar o Order Block (ob_lookback);
- profundidade/toques mínimos da captura (min_depth_pct, min_touches).

Este módulo só descreve cenários. Não envia ordens nem garante resultado.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from .candles import Candle, CandleInput
from .choch_bos import analyze_choch_bos
from .indicators import rsi
from .liquidity import (
    BSL, CAPTURA_PAVIO, ROMPIMENTO_FECHAMENTO, SSL, LiquidityEvent, analyze_liquidity,
)

VENDA, COMPRA = "VENDA", "COMPRA"


@dataclass(frozen=True)
class Model1Config:
    tolerance: float = 0.001      # topos/fundos "iguais": até 0,1% de diferença
    window: int = 2               # candles de cada lado para confirmar topo/fundo
    max_bars: int = 20            # prazo (em candles) entre a captura e o CHoCH
    min_rr: float = 2.0           # risco x retorno mínimo
    stop_buffer_pct: float = 0.05 # folga do stop além do extremo, em %
    ob_lookback: int = 5          # candles para trás na busca do Order Block
    min_depth_pct: float = 0.0    # profundidade mínima da captura, em %
    min_touches: int = 1          # toques mínimos no nível (2 = só EQH/EQL)
    rsi_period: int = 14


@dataclass(frozen=True)
class Setup:
    model: int
    direction: str               # VENDA ou COMPRA
    index: int                   # candle do CHoCH (quando o cenário ficou conhecido)
    time: datetime
    level_kind: str              # SH, SL, EQH, EQL
    level_price: float
    level_touches: int
    capture_type: str            # CAPTURA_PAVIO ou ROMPIMENTO_FECHAMENTO
    capture_index: int
    depth_pct: float             # quanto o preço passou do nível, em %
    extreme: float               # ponto mais distante atingido na captura
    choch_level: float           # fundo/topo rompido no CHoCH
    has_order_block: bool
    zone_low: float              # região de entrada
    zone_high: float
    entry: float
    stop: float
    target: float
    target_kind: str             # "liquidez" ou "projecao_rr"
    rr: float                    # risco x retorno até o alvo
    rsi_divergence: Optional[bool]  # None = sem dados suficientes
    trend_state: str             # estado da estrutura neste tempo gráfico
    fvg: bool = False            # o movimento do CHoCH deixou ineficiência (FVG)?
    choch_body_ratio: float = 0.0  # corpo/tamanho do candle do CHoCH (1.0 = candle cheio)


@dataclass(frozen=True)
class Outcome:
    status: str  # AGUARDANDO_ENTRADA, SEM_ENTRADA, EM_ANDAMENTO, ALVO, STOP
    entry_index: Optional[int] = None
    exit_index: Optional[int] = None
    result_r: Optional[float] = None  # resultado em múltiplos do risco (+rr ou -1)


def find_model1_setups(
    values: Iterable[CandleInput], last_candle_closed: bool,
    config: Model1Config = Model1Config(),
) -> list[Setup]:
    cfg = config
    liq = analyze_liquidity(values, last_candle_closed, cfg.tolerance, cfg.window)
    structure = analyze_choch_bos(values, last_candle_closed, cfg.window)
    candles, swings = structure.candles, structure.swings
    rsi_values = rsi([c.close for c in candles], cfg.rsi_period)

    captures: dict[int, list[LiquidityEvent]] = {}
    for e in liq.events:
        if e.type in (CAPTURA_PAVIO, ROMPIMENTO_FECHAMENTO):
            captures.setdefault(e.index, []).append(e)

    open_sweeps: list[dict] = []
    found: dict[tuple[str, int], Setup] = {}

    for j, c in enumerate(candles):
        still_open = []
        for sw in open_sweeps:
            e: LiquidityEvent = sw["event"]
            up = e.side == BSL            # capturou acima -> procuramos VENDA
            s = 1 if up else -1           # direção da captura
            ext = c.high if up else c.low
            if s * (ext - sw["extreme"]) > 0:
                sw["extreme"], sw["extreme_index"] = ext, j
            if j - e.index > cfg.max_bars:
                continue  # passou do prazo: descarta
            ref_kind = "low" if up else "high"
            refs = [x for x in swings if x.kind == ref_kind
                    and x.confirmation_index < j and x.origin_index < sw["extreme_index"]]
            ref = max(refs, key=lambda x: x.origin_index) if refs else None
            if ref is not None and any(
                    s * (candles[k].close - ref.price) < 0
                    for k in range(ref.origin_index + 1, j)):
                ref = None  # esse nível já tinha sido rompido antes
            if ref is None or not s * (c.close - ref.price) < 0:
                still_open.append(sw)
                continue
            setup = _build(cfg, candles, liq, rsi_values, structure.states[j], sw, ref, j)
            if setup is not None:
                key = (setup.direction, j)
                best = found.get(key)
                if best is None or (setup.level_touches, setup.depth_pct) > (
                        best.level_touches, best.depth_pct):
                    found[key] = setup
        open_sweeps = still_open

        for e in captures.get(j, []):
            if e.level_touches >= cfg.min_touches:
                open_sweeps.append({"event": e, "extreme": e.extreme, "extreme_index": j})

    return sorted(found.values(), key=lambda x: x.index)


def _build(cfg, candles, liq, rsi_values, trend_state, sw, ref, j) -> Optional[Setup]:
    e: LiquidityEvent = sw["event"]
    c: Candle = candles[j]
    up = e.side == BSL
    s = 1 if up else -1
    extreme, x = sw["extreme"], sw["extreme_index"]
    depth = s * (extreme - e.level_price) / e.level_price * 100
    if depth < cfg.min_depth_pct:
        return None

    leg_end = c.low if up else c.high          # até onde o movimento do CHoCH foi
    mid = (extreme + leg_end) / 2              # 50% do movimento

    # Order Block: último candle a favor da captura antes do movimento contrário.
    ob = None
    for k in range(x, max(x - cfg.ob_lookback, -1), -1):
        if s * (candles[k].close - candles[k].open) > 0:
            ob = candles[k]
            break
    if ob is not None:
        near = ob.low if up else ob.high       # borda do bloco que o preço toca primeiro
        entry = max(near, mid) if up else min(near, mid)
        zone = sorted((near, extreme))
    else:
        entry = mid
        zone = sorted((mid, extreme))

    stop = extreme * (1 + s * cfg.stop_buffer_pct / 100)
    risk = s * (stop - entry)
    if risk <= 0:
        return None

    # Alvo: liquidez do lado oposto, a mais próxima que entregue o RR mínimo.
    opposite = SSL if up else BSL
    candidates = sorted(
        (l.price for l in liq.levels
         if l.side == opposite and l.active_at(j) and s * (leg_end - l.price) > 0),
        key=lambda p: s * (entry - p))
    target, kind = None, "liquidez"
    for p in candidates:
        if s * (entry - p) / risk >= cfg.min_rr:
            target = p
            break
    if target is None:
        target, kind = entry - s * cfg.min_rr * risk, "projecao_rr"
    rr = s * (entry - target) / risk

    # Divergência de RSI: preço renovou o extremo, RSI não acompanhou.
    divergence = None
    level = next((l for l in liq.levels if l.side == e.side and l.consumed_index == e.index
                  and l.swings), None)
    if level is not None:
        a, b = rsi_values[level.swings[-1].origin_index], rsi_values[x]
        if a is not None and b is not None:
            divergence = s * (b - a) < 0

    # Intenção: ineficiência (FVG) no movimento do CHoCH e candle de CHoCH "cheio".
    fvg = False
    for k in range(x + 1, j):
        a, b = candles[k - 1], candles[k + 1]
        if s * ((a.low if up else a.high) - (b.high if up else b.low)) > 0:
            fvg = True
            break
    body_ratio = c.body / c.range if c.range > 0 else 0.0

    return Setup(
        model=1, direction=VENDA if up else COMPRA, index=j, time=c.timestamp,
        level_kind=e.level_kind, level_price=e.level_price, level_touches=e.level_touches,
        capture_type=e.type, capture_index=e.index, depth_pct=depth, extreme=extreme,
        choch_level=ref.price, has_order_block=ob is not None,
        zone_low=zone[0], zone_high=zone[1], entry=entry, stop=stop,
        target=target, target_kind=kind, rr=rr, rsi_divergence=divergence,
        trend_state=trend_state, fvg=fvg, choch_body_ratio=body_ratio,
    )


def evaluate_setup(setup: Setup, candles: list[Candle]) -> Outcome:
    """Acompanha o cenário nos candles seguintes (usado no backtest).

    Regras conservadoras: se o mesmo candle toca stop e alvo, conta como STOP.
    Se o preço chega ao alvo antes de dar entrada, o cenário é descartado.
    """
    s = 1 if setup.direction == VENDA else -1  # s=1: entrada acima, alvo abaixo
    entry_index = None
    for j in range(setup.index + 1, len(candles)):
        c = candles[j]
        far, near = (c.high, c.low) if s > 0 else (c.low, c.high)
        if entry_index is None:
            if s * (far - setup.entry) >= 0:
                entry_index = j
                if s * (far - setup.stop) >= 0:
                    return Outcome("STOP", j, j, -1.0)
                continue
            if s * (setup.target - near) >= 0:
                return Outcome("SEM_ENTRADA", exit_index=j)
        else:
            if s * (far - setup.stop) >= 0:
                return Outcome("STOP", entry_index, j, -1.0)
            if s * (setup.target - near) >= 0:
                return Outcome("ALVO", entry_index, j, setup.rr)
    if entry_index is None:
        return Outcome("AGUARDANDO_ENTRADA")
    return Outcome("EM_ANDAMENTO", entry_index)
