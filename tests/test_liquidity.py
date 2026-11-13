from datetime import datetime, timedelta, timezone

from analysis.candles import Candle
from analysis.liquidity import (
    BSL, SSL, CAPTURA_CONFIRMADA, CAPTURA_PAVIO, ROMPIMENTO_FECHAMENTO, TOQUE,
    analyze_liquidity,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
BASE = [100, 101, 110, 102, 101]  # topo em 110 (índice 2), confirmado no índice 4


def bars(specs, mirror=False):
    """specs: máxima, ou (máxima, fechamento). mirror=True espelha para testar fundos."""
    out = []
    for i, spec in enumerate(specs):
        h, cl = spec if isinstance(spec, tuple) else (spec, None)
        l = h - 5
        cl = l + 1 if cl is None else cl
        o = l + 1
        if mirror:
            o, h, l, cl = 1000 - o, 1000 - l, 1000 - h, 1000 - cl
        out.append(Candle(T0 + timedelta(hours=i), o, h, l, cl, 1.0))
    return out


def run(specs, side=BSL, mirror=False, closed=True):
    r = analyze_liquidity(bars(specs, mirror), closed)
    return r, [e for e in r.events if e.side == side]


def test_captura_por_pavio_e_confirmacao():
    r, ev = run(BASE + [(112, 108), (109, 105)])
    assert [e.type for e in ev] == [CAPTURA_PAVIO, CAPTURA_CONFIRMADA]
    assert (ev[0].index, ev[1].index) == (5, 6)
    assert ev[0].level_price == 110 and ev[0].extreme == 112
    assert round(ev[0].depth_pct, 2) == 1.82
    assert not [l for l in r.levels if l.side == BSL and l.price == 110][0].active


def test_sem_confirmacao_se_proximo_candle_renova_o_extremo():
    _, ev = run(BASE + [(112, 108), (113, 109)])
    assert [e.type for e in ev] == [CAPTURA_PAVIO]


def test_sem_candle_seguinte_fica_potencial():
    _, ev = run(BASE + [(112, 108)])
    assert [e.type for e in ev] == [CAPTURA_PAVIO]


def test_rompimento_por_fechamento():
    _, ev = run(BASE + [(115, 113), (116, 114)])
    assert [e.type for e in ev] == [ROMPIMENTO_FECHAMENTO]


def test_fechamento_igual_ao_nivel_nao_e_rompimento():
    _, ev = run(BASE + [(112, 110)])
    assert [e.type for e in ev] == [CAPTURA_PAVIO]


def test_topos_iguais_viram_eqh():
    r, ev = run(BASE + [103, 110, 102, 101])
    assert ev == []
    lv = [l for l in r.active_levels if l.side == BSL]
    assert [(l.kind, l.price, l.touches) for l in lv] == [("EQH", 110, 2)]


def test_toque_dentro_da_tolerancia_mantem_o_nivel():
    r, ev = run(BASE + [103, 110.05, 102, 101])
    assert [e.type for e in ev] == [TOQUE]
    lv = [l for l in r.active_levels if l.side == BSL]
    assert [(l.kind, l.price, l.touches) for l in lv] == [("EQH", 110.05, 2)]


def test_nivel_capturado_nao_se_junta_com_topo_novo():
    r, ev = run(BASE + [103, (112, 108), 102, 101])
    assert [e.type for e in ev] == [CAPTURA_PAVIO, CAPTURA_CONFIRMADA]
    lv = [l for l in r.active_levels if l.side == BSL]
    assert [(l.kind, l.price) for l in lv] == [("SH", 112)]


def test_fundos_espelhado():
    _, ev = run(BASE + [(112, 108), (109, 105)], side=SSL, mirror=True)
    assert [e.type for e in ev] == [CAPTURA_PAVIO, CAPTURA_CONFIRMADA]
    assert ev[0].level_price == 890 and ev[0].extreme == 888


def test_candle_aberto_e_ignorado():
    _, ev = run(BASE + [(112, 108)], closed=False)
    assert ev == []


def test_sem_lookahead():
    specs = BASE + [103, (112, 108), 102, 101, 104, (118, 116), 105]
    full = analyze_liquidity(bars(specs), True).events
    for n in range(1, len(specs) + 1):
        part = analyze_liquidity(bars(specs[:n]), True).events
        assert part == tuple(e for e in full if e.index < n)
