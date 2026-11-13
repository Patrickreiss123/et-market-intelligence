"""Roda o bot uma vez: busca candles, analisa e envia os alertas novos.

Uso:  python -m live.run            (envia ao Telegram)
      python -m live.run --teste    (só mostra na tela, não envia)

Feito para ser chamado de tempos em tempos (ex.: a cada 15 minutos).
O arquivo state.json guarda o que já foi avisado, para não repetir alertas.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Callable

from live.alerts import build_alerts
from live.binance import fetch_candles
from live.telegram import send_message

SYMBOLS = ("SOLUSDT", "BTCUSDT", "ETHUSDT", "BNBUSDT")
INTERVALS = ("1h", "4h")
STATE_FILE = "state.json"


def run_once(fetch: Callable, send: Callable[[str], None], state: dict,
             symbols=SYMBOLS, intervals=INTERVALS) -> dict:
    """Devolve o novo estado. Na primeira vez só avisa o que aconteceu no último candle."""
    for symbol in symbols:
        for interval in intervals:
            key = f"{symbol}:{interval}"
            try:
                candles = fetch(symbol, interval)
            except Exception as error:  # uma moeda com problema não derruba as outras
                print(f"[erro] {key}: {error}")
                continue
            if not candles:
                continue
            latest = candles[-1].timestamp
            last_sent = state.get(key)
            if last_sent is None:
                cutoff = candles[-2].timestamp if len(candles) > 1 else latest
            else:
                cutoff = datetime.fromisoformat(last_sent)
            for alert in build_alerts(symbol, interval, candles):
                if alert.time > cutoff:
                    send(alert.text)
            state[key] = latest.isoformat()
    return state


def main() -> None:
    dry = "--teste" in sys.argv
    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    send = (lambda text: print(text + "\n" + "-" * 40)) if dry else send_message
    state = run_once(fetch_candles, send, state)
    if not dry:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
