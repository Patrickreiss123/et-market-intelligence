from datetime import datetime, timedelta, timezone

from analysis.candles import Candle
from analysis.choch_bos import (
    AMBIGUO, BOS, CHOCH, INSUFICIENTE, MISTA, PIVO_CONTINUACAO, PIVO_CORRETIVO,
    ROMPIMENTO_PREMATURO, SOMENTE_PAVIO, TENDENCIA_DEFINIDA, TRANSICAO_INVALIDADA,
    analyze_choch_bos,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def path(pivots, extra=(), mirror=False, steps=3):
    """Preço andando em linha reta entre os pontos, 3 candles por perna.
    extra: candles manuais (open, high, low, close) colocados no fim."""
    rows = []
    for a, b in zip(pivots, pivots[1:]):
        sign = 1 if b > a else -1
        prev = a + 0.01 * sign
        for k in range(1, steps + 1):
            cl = a + (b - a) * k / steps
            rows.append((prev, max(prev, cl), min(prev, cl), cl))
            prev = cl
    rows += list(extra)
    out = []
    for i, (o, h, l, cl) in enumerate(rows):
        if mirror:
            o, h, l, cl = 1000 - o, 1000 - l, 1000 - h, 1000 - cl
        out.append(Candle(T0 + timedelta(hours=i), o, h, l, cl, 1.0))
    return out


UP = [100, 110, 105, 115, 108, 120, 112, 124]  # alta com BOS protegido no candle 20
FULL = UP + [106, 110, 107, 100]               # CHoCH + retração + BOS de baixa


def types(r):
    return [(e.type, e.index) for e in r.events]


def test_estrutura_insuficiente_e_mista_sao_estados_diferentes():
    assert analyze_choch_bos(path([100, 110, 105]), True).state == INSUFICIENTE
    assert analyze_choch_bos(path([100, 110, 105, 115, 103, 109]), True).state == MISTA


def test_bos_de_alta_com_protecao():
    r = analyze_choch_bos(path(UP), True)
    assert types(r) == [(TENDENCIA_DEFINIDA, 13), (BOS, 20)]
    assert r.states[13] == "ALTA_SEM_PROTECAO"
    assert r.states[19] == "ALTA_SEM_PROTECAO"  # fechou exatamente em 120: não rompe
    assert r.state == "ALTA_PROTEGIDA"
    assert r.protection.price == 112
    bos = r.events[-1]
    assert bos.level == 120 and bos.swing.confirmation_index < bos.index
    assert r.protection.confirmation_index < bos.index


def test_bos_sem_protecao_quando_fundo_confirma_no_mesmo_candle():
    r = analyze_choch_bos(path(UP[:-1] + [125]), True)
    assert types(r)[-1] == (BOS, 19)
    assert r.state == "ALTA_SEM_PROTECAO" and r.protection is None


def test_sequencia_completa_choch_de_baixa():
    r = analyze_choch_bos(path(FULL), True)
    assert types(r) == [
        (TENDENCIA_DEFINIDA, 13), (BOS, 20), (CHOCH, 23),
        (PIVO_CONTINUACAO, 25), (PIVO_CORRETIVO, 28), (BOS, 30),
    ]
    assert r.states[22] == "ALTA_PROTEGIDA"  # fechou exatamente na proteção
    assert r.states[23] == "TRANSICAO_PARA_BAIXA_AGUARDANDO_PIVO_CONTINUACAO"
    assert r.states[25] == "TRANSICAO_PARA_BAIXA_AGUARDANDO_PIVO_CORRETIVO"
    assert r.states[28] == "TRANSICAO_PARA_BAIXA_AGUARDANDO_BOS"
    assert r.state == "BAIXA_PROTEGIDA"
    choch, final = r.events[2], r.events[-1]
    assert choch.direction == "BAIXA" and choch.level == 112 and choch.protection is None
    assert final.context == "confirmacao_do_choch" and final.choch_index == 23
    assert final.level == 106 and r.protection.price == 110


def test_sequencia_completa_choch_de_alta_espelhado():
    r = analyze_choch_bos(path(FULL, mirror=True), True)
    assert [t for t, _ in types(r)] == [
        TENDENCIA_DEFINIDA, BOS, CHOCH, PIVO_CONTINUACAO, PIVO_CORRETIVO, BOS]
    assert r.states[23] == "TRANSICAO_PARA_ALTA_AGUARDANDO_PIVO_CONTINUACAO"
    assert r.state == "ALTA_PROTEGIDA" and r.protection.price == 890


def test_choch_nao_inverte_tendencia_sozinho():
    r = analyze_choch_bos(path(UP + [106]), True)
    assert r.events[-1].type == CHOCH
    assert r.state.startswith("TRANSICAO_PARA_BAIXA") and r.protection is None


def test_sem_retracao_fica_aguardando():
    r = analyze_choch_bos(path(UP + [106, 90, 70]), True)
    assert r.state == "TRANSICAO_PARA_BAIXA_AGUARDANDO_PIVO_CONTINUACAO"


def test_transicao_invalidada_nao_reativa_protecao_antiga():
    r = analyze_choch_bos(path(UP + [106, 114]), True)
    assert r.events[-1].type == TRANSICAO_INVALIDADA
    assert r.state == "ALTA_SEM_PROTECAO" and r.protection is None


def test_bos_na_direcao_anterior_depois_de_invalidar_cria_protecao_nova():
    r = analyze_choch_bos(path(UP + [106, 130]), True)
    assert [t for t, _ in types(r)][-2:] == [TRANSICAO_INVALIDADA, BOS]
    assert r.state == "ALTA_PROTEGIDA" and r.protection.price == 106  # não é a antiga (112)


def test_bos_na_direcao_anterior_durante_a_transicao_sem_fundo_confirmado():
    r = analyze_choch_bos(path(UP + [106], extra=[(106, 131, 105.9, 130)]), True)
    last = r.events[-1]
    assert last.type == BOS and last.context == "direcao_anterior_durante_transicao"
    assert r.state == "ALTA_SEM_PROTECAO" and r.protection is None


def test_rompimento_prematuro_nao_vira_bos_de_confirmacao():
    r = analyze_choch_bos(path(UP + [106, 110, 100]), True)
    kinds = [t for t, _ in types(r)]
    assert ROMPIMENTO_PREMATURO in kinds and PIVO_CORRETIVO not in kinds
    assert kinds.count(BOS) == 1  # só o BOS de alta original
    assert r.state == "TRANSICAO_PARA_BAIXA_AGUARDANDO_PIVO_CORRETIVO"


def test_somente_pavio_nao_muda_estado():
    r = analyze_choch_bos(path(UP, extra=[(124, 124.5, 111, 123)]), True)
    last = r.events[-1]
    assert (last.type, last.context) == (SOMENTE_PAVIO, "CHOCH")
    assert r.state == "ALTA_PROTEGIDA" and r.protection.price == 112


def test_candle_ambiguo_nao_muda_estado():
    r = analyze_choch_bos(path(UP + [118], extra=[(118, 125, 111, 119)]), True)
    assert r.events[-1].type == AMBIGUO
    assert r.state == "ALTA_PROTEGIDA" and r.protection.price == 112


def test_candle_aberto_e_ignorado():
    r = analyze_choch_bos(path(UP), False)
    assert types(r) == [(TENDENCIA_DEFINIDA, 13)]


def test_sem_lookahead():
    candles = path(FULL + [104, 95])
    full = analyze_choch_bos(candles, True)
    for n in range(1, len(candles) + 1):
        part = analyze_choch_bos(candles[:n], True)
        assert part.events == tuple(e for e in full.events if e.index < n)
        assert part.states == full.states[:n]
