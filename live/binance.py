"""Busca candles nos dados públicos da Binance (sem conta, sem chave)."""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone

from analysis.candles import Candle

BASE_URL = "https://data-api.binance.vision/api/v3/klines"


def parse_klines(rows: list, now_ms: int | None = None) -> list[Candle]:
    """Converte a resposta da Binance em candles, descartando o candle ainda aberto."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    out = []
    for k in rows:
        if int(k[6]) >= now_ms:  # k[6] = horário de fechamento; ainda não fechou
            continue
        out.append(Candle(datetime.fromtimestamp(int(k[0]) / 1000, timezone.utc),
                          float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
    return out


def fetch_candles(symbol: str, interval: str, limit: int = 1000) -> list[Candle]:
    url = f"{BASE_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return parse_klines(json.load(response))
