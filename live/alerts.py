"""Transforma a análise em mensagens de mapeamento para o Telegram.

Foco: SMC (liquidez, captura, CHoCH, BOS, Order Block) e um toque de Wyckoff
(volume do candle comparado à média: esforço x resultado).

As mensagens descrevem o que aconteceu no gráfico. NÃO são sinal de compra/venda:
no backtest, operar o Modelo 1 no automático não mostrou vantagem.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from analysis.candles import Candle
from analysis.choch_bos import BOS, CHOCH, TRANSICAO_INVALIDADA, analyze_choch_bos
from analysis.liquidity import (
    BSL, CAPTURA_CONFIRMADA, ROMPIMENTO_FECHAMENTO, analyze_liquidity,
)
from analysis.model1 import Model1Config, find_model1_setups

BRT = ZoneInfo("America/Sao_Paulo")
AVISO = "Mapeamento para estudo. Não é sinal de entrada."


@dataclass(frozen=True)
class Alert:
    time: datetime  # candle em que o evento ficou conhecido
    kind: str
    text: str


def money(p: float) -> str:
    s = f"{p:,.2f}" if p >= 1 else f"{p:,.5f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def relative_volume(candles: list[Candle], index: int, lookback: int = 20) -> float | None:
    """Volume do candle dividido pela média dos anteriores (Wyckoff: esforço)."""
    past = [c.volume for c in candles[max(0, index - lookback):index]]
    avg = sum(past) / len(past) if past else 0
    return candles[index].volume / avg if avg > 0 else None


def _volume_line(candles: list[Candle], index: int) -> str:
    rv = relative_volume(candles, index)
    if rv is None:
        return ""
    label = "alto" if rv >= 1.5 else "baixo" if rv <= 0.7 else "normal"
    return f"\nVolume: {rv:.1f}x a média ({label})".replace(".", ",", 1)


def build_alerts(symbol: str, interval: str, candles: list[Candle],
                 config: Model1Config = Model1Config()) -> list[Alert]:
    """Todos os eventos de mapeamento encontrados nos candles (todos já fechados)."""
    if len(candles) < 10:
        return []
    head = f"{symbol} · {interval}"
    alerts: list[Alert] = []

    def add(index: int, kind: str, body: str) -> None:
        c = candles[index]
        when = c.timestamp.astimezone(BRT).strftime("%d/%m %H:%M")
        alerts.append(Alert(c.timestamp, kind,
                            f"{head}\n{body}{_volume_line(candles, index)}\n"
                            f"Candle das {when} (Brasília)\n{AVISO}"))

    structure = analyze_choch_bos(candles, True, config.window)
    for e in structure.events:
        if e.type == CHOCH:
            lado = "baixa" if e.direction == "BAIXA" else "alta"
            add(e.index, "CHOCH",
                f"CHoCH de {lado}: fechou além da proteção em {money(e.level)}.\n"
                f"Possível mudança de direção. Falta retração e BOS para confirmar.")
        elif e.type == BOS:
            lado = "alta" if e.direction == "ALTA" else "baixa"
            if e.context == "confirmacao_do_choch":
                txt = f"BOS de {lado} confirmou o CHoCH: nova tendência de {lado}."
            else:
                txt = f"BOS de {lado}: fechou além de {money(e.level)}. Tendência de {lado} continua."
            if e.protection is not None:
                txt += f"\nProteção da tendência: {money(e.protection.price)}."
            add(e.index, "BOS", txt)
        elif e.type == TRANSICAO_INVALIDADA:
            add(e.index, "INVALIDACAO",
                f"CHoCH anterior invalidado: o preço recuperou {money(e.level)}.")

    liq = analyze_liquidity(candles, True, config.tolerance, config.window)
    for e in liq.events:
        if e.level_touches < 2:
            continue  # só níveis nítidos (topos/fundos iguais)
        onde = "acima dos topos iguais" if e.side == BSL else "abaixo dos fundos iguais"
        if e.type == CAPTURA_CONFIRMADA:
            add(e.index, "CAPTURA",
                f"Captura de liquidez {onde} em {money(e.level_price)} "
                f"({e.level_touches} toques).\nO preço foi até {money(e.extreme)} e voltou.")
        elif e.type == ROMPIMENTO_FECHAMENTO:
            add(e.index, "ROMPIMENTO",
                f"Rompimento {onde} em {money(e.level_price)} "
                f"({e.level_touches} toques), com fechamento além do nível.")

    for s in find_model1_setups(candles, True, config):
        lado = "venda" if s.direction == "VENDA" else "compra"
        extra = []
        if s.rsi_divergence:
            extra.append("divergência no RSI")
        if s.fvg:
            extra.append("ineficiência (FVG) no movimento")
        obs = f"\nReforços: {', '.join(extra)}." if extra else ""
        add(s.index, "MODELO1",
            f"Cenário do Modelo 1 ({lado}): captura em {money(s.level_price)} + CHoCH.\n"
            f"Zona de Order Block: {money(s.zone_low)} a {money(s.zone_high)}\n"
            f"Referências do modelo: entrada {money(s.entry)}, stop {money(s.stop)}, "
            f"alvo {money(s.target)} (risco x retorno {f'{s.rr:.1f}'.replace('.', ',')})." + obs)

    alerts.sort(key=lambda a: a.time)
    return alerts
