from datetime import datetime, timedelta, timezone

from analysis.multi_timeframe import aligned, direction_of, last_closed_index

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
OPENS = [T0 + timedelta(hours=4 * i) for i in range(5)]


def test_ultimo_candle_fechado_do_tempo_maior():
    assert last_closed_index(OPENS, T0 + timedelta(hours=3, minutes=59), "4h") is None
    assert last_closed_index(OPENS, T0 + timedelta(hours=4), "4h") == 0
    assert last_closed_index(OPENS, T0 + timedelta(hours=7, minutes=45), "4h") == 0
    assert last_closed_index(OPENS, T0 + timedelta(hours=8), "4h") == 1
    assert last_closed_index(OPENS, T0 + timedelta(days=30), "4h") == 4


def test_direcao_e_alinhamento():
    assert direction_of("ALTA_PROTEGIDA") == "ALTA"
    assert direction_of("BAIXA_SEM_PROTECAO") == "BAIXA"
    assert direction_of("TRANSICAO_PARA_BAIXA_AGUARDANDO_BOS") is None
    assert direction_of("ESTRUTURA_MISTA_OU_INDEFINIDA") is None
    assert aligned("COMPRA", "ALTA_PROTEGIDA") is True
    assert aligned("VENDA", "ALTA_PROTEGIDA") is False
    assert aligned("VENDA", "BAIXA_PROTEGIDA") is True
    assert aligned("COMPRA", "ESTRUTURA_INSUFICIENTE") is None
