from datetime import timedelta

from live.alerts import build_alerts, money, relative_volume
from live.binance import parse_klines
from live.run import run_once
from tests.test_choch_bos import FULL, T0, path


def test_parse_klines_descarta_candle_aberto():
    t = int(T0.timestamp() * 1000)
    rows = [[t, "1", "2", "0.5", "1.5", "10", t + 3599999],
            [t + 3600000, "1.5", "2", "1", "1.8", "5", t + 7199999]]
    out = parse_klines(rows, now_ms=t + 3600000 + 10)
    assert len(out) == 1 and out[0].close == 1.5 and out[0].timestamp == T0


def test_formato_de_preco_brasileiro():
    assert money(104567.5) == "104.567,50"
    assert money(152.4) == "152,40"
    assert money(0.12345) == "0,12345"


def test_volume_relativo():
    candles = path(FULL)
    assert relative_volume(candles, 10) == 1.0
    assert relative_volume(candles, 0) is None


def test_alertas_descrevem_a_sequencia_e_trazem_aviso():
    alerts = build_alerts("SOLUSDT", "1h", path(FULL))
    kinds = [a.kind for a in alerts]
    assert "CHOCH" in kinds and kinds.count("BOS") >= 2
    assert all("Não é sinal de entrada" in a.text for a in alerts)
    assert all(a.text.startswith("SOLUSDT · 1h") for a in alerts)
    assert [a.time for a in alerts] == sorted(a.time for a in alerts)
    choch = next(a for a in alerts if a.kind == "CHOCH")
    assert "112,00" in choch.text and "Volume: 1,0x a média" in choch.text


def test_run_once_nao_repete_alertas():
    candles = path(FULL)
    sent = []
    cut = 24  # CHoCH acontece no candle 23

    def fetch_until(n):
        return lambda symbol, interval: candles[:n]

    state = run_once(fetch_until(cut), sent.append, {}, ("SOLUSDT",), ("1h",))
    first = len(sent)
    assert first >= 1 and "CHoCH de baixa" in sent[0]          # só o último candle
    assert all("20:00" in text for text in sent)
    assert state == {"SOLUSDT:1h": candles[cut - 1].timestamp.isoformat()}

    run_once(fetch_until(cut), sent.append, state, ("SOLUSDT",), ("1h",))
    assert len(sent) == first                                   # nada repetido

    run_once(fetch_until(len(candles)), sent.append, state, ("SOLUSDT",), ("1h",))
    assert any("confirmou o CHoCH" in s for s in sent[first:])


def test_run_once_sobrevive_a_erro_de_uma_moeda():
    candles = path(FULL)

    def fetch(symbol, interval):
        if symbol == "BTCUSDT":
            raise OSError("sem conexão")
        return candles

    state = run_once(fetch, lambda text: None, {}, ("BTCUSDT", "SOLUSDT"), ("1h",))
    assert list(state) == ["SOLUSDT:1h"]
