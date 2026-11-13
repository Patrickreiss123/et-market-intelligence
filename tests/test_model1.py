from dataclasses import replace

from analysis.candles import Candle
from analysis.indicators import rsi
from analysis.model1 import (
    COMPRA, VENDA, Model1Config, evaluate_setup, find_model1_setups,
)
from tests.test_choch_bos import T0, path, timedelta

# topo em 110, topo menor em 108, captura até 112 e queda rompendo o fundo de 105
SHORT = [100, 110, 104, 108, 105, 112, 104]


def more(candles, rows):
    out = list(candles)
    for o, h, l, cl in rows:
        out.append(Candle(T0 + timedelta(hours=len(out)), o, h, l, cl, 1.0))
    return out


def one(candles, cfg=Model1Config()):
    setups = find_model1_setups(candles, True, cfg)
    assert len(setups) == 1
    return setups[0]


def test_venda_apos_captura_e_choch():
    s = one(path(SHORT))
    assert s.direction == VENDA and s.model == 1
    assert s.level_price in (108, 110) and s.extreme == 112
    assert s.choch_level == 105 and s.index > s.capture_index
    assert s.has_order_block
    assert (s.extreme + 104) / 2 <= s.entry < s.extreme  # entrada acima dos 50%
    assert s.stop > s.extreme                             # stop além do extremo
    assert s.target < s.entry and s.rr >= 2.0
    assert s.zone_low <= s.entry <= s.zone_high


def test_compra_espelhada():
    s = one(path(SHORT, mirror=True))
    assert s.direction == COMPRA and s.extreme == 888 and s.choch_level == 895
    assert s.stop < s.extreme < s.entry < s.target and s.rr >= 2.0


def test_sem_captura_nao_ha_cenario():
    assert find_model1_setups(path([100, 110, 104, 108, 105, 107, 101]), True) == []


def test_prazo_maximo_entre_captura_e_choch():
    assert find_model1_setups(path(SHORT), True, Model1Config(max_bars=1)) == []


def test_filtros_de_qualidade():
    assert find_model1_setups(path(SHORT), True, Model1Config(min_touches=2)) == []
    assert find_model1_setups(path(SHORT), True, Model1Config(min_depth_pct=50)) == []


def test_candle_aberto_e_ignorado():
    assert find_model1_setups(path(SHORT), False) == []


def test_sem_lookahead():
    candles = path(SHORT + [111, 99, 106])
    full = find_model1_setups(candles, True)
    assert full
    for n in range(1, len(candles) + 1):
        assert find_model1_setups(candles[:n], True) == [s for s in full if s.index < n]


def test_resultado_alvo_stop_e_sem_entrada():
    base = path(SHORT)
    s = one(base)
    e, st, tg = s.entry, s.stop, s.target
    assert evaluate_setup(s, base).status == "AGUARDANDO_ENTRADA"
    entrou = (104, e + 0.1, 103.9, e - 0.5)
    r = evaluate_setup(s, more(base, [entrou]))
    assert r.status == "EM_ANDAMENTO" and r.entry_index == len(base)
    r = evaluate_setup(s, more(base, [entrou, (e - 0.5, e, tg - 0.1, tg)]))
    assert r.status == "ALVO" and r.result_r == s.rr
    r = evaluate_setup(s, more(base, [entrou, (e - 0.5, st + 0.1, e - 1, st)]))
    assert r.status == "STOP" and r.result_r == -1.0
    r = evaluate_setup(s, more(base, [(104, st + 1, 103.9, st)]))
    assert r.status == "STOP"                      # entrou e estopou no mesmo candle
    r = evaluate_setup(s, more(base, [(104, 104.1, tg - 1, 104)]))
    assert r.status == "SEM_ENTRADA"               # foi ao alvo sem dar entrada
    # stop e alvo no mesmo candle depois da entrada: conta como stop
    r = evaluate_setup(s, more(base, [entrou, (e - 0.5, st + 1, tg - 1, e)]))
    assert r.status == "STOP"


def test_rsi():
    assert rsi([1, 2, 3], 14) == [None, None, None]
    up = rsi(list(range(1, 30)), 14)
    assert up[13] is None and up[14] == 100.0 and up[-1] == 100.0
    down = rsi(list(range(30, 1, -1)), 14)
    assert down[-1] == 0.0
    mixed = rsi([10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10], 14)
    assert mixed[-1] == 50.0
