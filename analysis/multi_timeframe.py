"""Alinhamento de tempos gráficos.

Apostila (cap. 18.1): o tempo maior dá o contexto, o menor dá a entrada, e os
dois devem apontar para o mesmo lado. Aqui só respondemos duas perguntas:
1. Qual era o último candle FECHADO do tempo maior em certo momento?
2. Para que lado a estrutura do tempo maior apontava?
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta
from typing import Optional, Sequence

INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def last_closed_index(opens: Sequence[datetime], when: datetime, interval: str) -> Optional[int]:
    """Índice do último candle do tempo maior já fechado no instante `when`."""
    limit = when - timedelta(seconds=INTERVAL_SECONDS[interval])
    i = bisect_right(opens, limit) - 1
    return i if i >= 0 else None


def direction_of(state: str) -> Optional[str]:
    """ALTA, BAIXA ou None (sem direção clara / em transição)."""
    if state.startswith("ALTA"):
        return "ALTA"
    if state.startswith("BAIXA"):
        return "BAIXA"
    return None


def aligned(setup_direction: str, htf_state: str) -> Optional[bool]:
    """True = a favor do tempo maior; False = contra; None = tempo maior sem direção."""
    d = direction_of(htf_state)
    if d is None:
        return None
    return (setup_direction == "COMPRA") == (d == "ALTA")
