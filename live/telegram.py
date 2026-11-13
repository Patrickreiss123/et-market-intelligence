"""Envio de mensagens ao Telegram. O token vem de variáveis de ambiente, nunca do código."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def send_message(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(url, data=data, timeout=30) as response:
        if not json.load(response).get("ok"):
            raise RuntimeError("Telegram recusou a mensagem")
