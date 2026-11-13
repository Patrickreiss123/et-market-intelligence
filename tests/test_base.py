import math
from datetime import datetime, timedelta, timezone

import pytest

from analysis.candles import Candle, CandleError, parse_candles
from analysis.market_structure import (
    ALTA, BAIXA, INSUFICIENTE, MISTA, analyze_structure,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def c(i, o, h, l, cl, v=1.0):
    return Candle(T0 + timedelta(hours=i), o, h, l, cl, v)


def from_extremes(pairs):
    """Monta candles a partir de (máxima, mínima)."""
    return [c(i, l, h, l, h) for i, (h, l) in enumerate(pairs)]


# ---------- candles ----------

def test_medidas_do_candle():
    k = c(0, 10, 15, 8, 12)
    assert (k.direction, k.range, k.body, k.upper_wick, k.lower_wick) == ("alta", 7, 2, 3, 2)
    assert c(0, 12, 15, 8, 10).direction == "baixa"
    assert c(0, 10, 15, 8, 10).direction == "neutro"


@pytest.mark.parametrize("o,h,l,cl,v", [
    (10, 9, 8, 9.5, 1),      # máxima abaixo da abertura
    (10, 12, 11, 11.5, 1),   # mínima acima da abertura
    (-1, 5, -2, 3, 1),       # preço negativo
    (10, 12, 8, 11, -5),     # volume negativo
    (10, math.inf, 8, 11, 1),
    (10, math.nan, 8, 11, 1),
    ("10", 12, 8, 11, 1),    # texto no lugar de número
])
def test_candle_invalido(o, h, l, cl, v):
    with pytest.raises(CandleError):
        Candle(T0, o, h, l, cl, v)


def test_fuso_horario_vira_utc():
    assert Candle(datetime(2026, 1, 1, 12), 1, 2, 1, 2).timestamp.tzinfo == timezone.utc
    br = timezone(timedelta(hours=-3))
    k = Candle(datetime(2026, 1, 1, 9, tzinfo=br), 1, 2, 1, 2)
    assert k.timestamp == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_parse_ordena_e_aceita_dicionario():
    d = {"timestamp": T0, "open": 1, "high": 2, "low": 1, "close": 2}
    out = parse_candles([c(2, 1, 2, 1, 2), d, c(1, 1, 2, 1, 2)])
    assert [k.timestamp for k in out] == sorted(k.timestamp for k in out)
    assert out[0].volume == 0.0


def test_parse_rejeita_horario_repetido_e_campo_ausente():
    with pytest.raises(CandleError):
        parse_candles([c(0, 1, 2, 1, 2), c(0, 1, 2, 1, 2)])
    with pytest.raises(CandleError):
        parse_candles([{"timestamp": T0, "open": 1}])


# ---------- swings ----------

def test_swing_high_e_confirmacao():
    r = analyze_structure(from_extremes([(10, 9), (11, 10), (15, 12), (12, 11), (11, 10)]), True)
    highs = [s for s in r.swings if s.kind == "high"]
    assert len(highs) == 1
    s = highs[0]
    assert (s.price, s.origin_index, s.confirmation_index) == (15, 2, 4)
    assert s.confirmation_time == T0 + timedelta(hours=4)
    assert s.label is None


def test_swing_low():
    r = analyze_structure(from_extremes([(20, 15), (19, 14), (17, 10), (19, 13), (20, 14)]), True)
    lows = [s for s in r.swings if s.kind == "low"]
    assert [(s.price, s.origin_index) for s in lows] == [(10, 2)]


def test_empate_nao_forma_swing():
    r = analyze_structure(from_extremes([(10, 9), (15, 10), (15, 12), (12, 11), (11, 10)]), True)
    assert not [s for s in r.swings if s.kind == "high"]


def test_candle_aberto_e_ignorado():
    data = from_extremes([(10, 9), (11, 10), (15, 12), (12, 11), (11, 10)])
    assert analyze_structure(data, False).swings == ()
    assert len(analyze_structure(data, False).candles) == 4


def test_sem_lookahead():
    """Candles futuros não mudam swings já confirmados."""
    data = from_extremes([(10, 9), (11, 10), (15, 12), (12, 11), (11, 10)])
    antes = analyze_structure(data, True).swings
    depois = analyze_structure(data + from_extremes([(30, 29)] * 0) + [c(5, 20, 40, 19, 39)], True).swings
    assert depois[: len(antes)] == antes


def test_swings_known_before():
    r = analyze_structure(from_extremes([(10, 9), (11, 10), (15, 12), (12, 11), (11, 10), (10, 9)]), True)
    assert r.swings_known_before(4) == ()  # confirmado no 4: só vale a partir do 5
    assert len(r.swings_known_before(5)) == 1


# ---------- tendência ----------

def zigzag(points):
    """Cada ponto vira um pico/vale cercado por 2 candles neutros de cada lado."""
    pairs = []
    for kind, price in points:
        mid = 100.0
        filler = (mid + 0.5, mid - 0.5)
        peak = (price, mid - 0.5) if kind == "H" else (mid + 0.5, price)
        pairs += [filler, filler, peak]
    pairs += [(100.5, 99.5)] * 2
    return from_extremes(pairs)


def test_tendencia_de_alta():
    r = analyze_structure(zigzag([("L", 90), ("H", 110), ("L", 92), ("H", 115)]), True)
    assert [s.label for s in r.swings] == [None, None, "HL", "HH"]
    assert r.trend == ALTA


def test_tendencia_de_baixa():
    r = analyze_structure(zigzag([("H", 115), ("L", 92), ("H", 110), ("L", 90)]), True)
    assert r.trend == BAIXA


def test_estrutura_mista():
    r = analyze_structure(zigzag([("L", 90), ("H", 110), ("L", 88), ("H", 115)]), True)
    assert r.trend == MISTA


def test_estrutura_insuficiente():
    r = analyze_structure(zigzag([("L", 90), ("H", 110)]), True)
    assert r.trend == INSUFICIENTE


def test_topos_iguais_recebem_eqh():
    r = analyze_structure(zigzag([("H", 110), ("H", 110)]), True)
    assert [s.label for s in r.swings if s.kind == "high"] == [None, "EQH"]
