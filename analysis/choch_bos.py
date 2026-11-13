"""CHoCH e BOS: a "máquina de estados" da estrutura.

Em linguagem simples:
- BOS  = o preço FECHA além do último topo (na alta) ou fundo (na baixa):
         a tendência continua.
- Proteção = o fundo (na alta) ou topo (na baixa) deixado antes do BOS.
- CHoCH = o preço FECHA além da proteção: possível mudança de direção.
- CHoCH sozinho não vira a tendência. Entramos em TRANSIÇÃO e esperamos:
      CHoCH -> pivô de continuação -> pivô corretivo -> BOS na nova direção
  (apostila, pág. 326: CHoCH válido pede retração e BOS a favor).

Garantias:
- Só candles fechados. Só topos/fundos já confirmados ANTES do candle avaliado.
- Candles futuros nunca mudam eventos passados.
- "Fechar exatamente no nível" não conta como rompimento.
- Rompimento só por pavio vira evento separado e não muda o estado.
- Candle que atinge níveis opostos (ordem impossível de saber) = AMBIGUO,
  não muda o estado.

Formalizações técnicas (não são frases literais da apostila):
- Referência do BOS: topo/fundo mais extremo confirmado desde o último BOS.
- Proteção: fundo/topo mais extremo entre o topo/fundo rompido e o candle do BOS.
- Tendência sem proteção só vira para o lado oposto se topos e fundos novos
  mostrarem claramente a direção contrária.
- Tipo 2 da apostila (fechamento além de "referência de fechamentos" sem
  romper o pavio) NÃO está implementado: a referência exata está pendente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from .candles import Candle, CandleInput
from .market_structure import ALTA, BAIXA, Swing, analyze_structure, classify_trend

INSUFICIENTE = "ESTRUTURA_INSUFICIENTE"
MISTA = "ESTRUTURA_MISTA_OU_INDEFINIDA"

# tipos de evento
TENDENCIA_DEFINIDA = "TENDENCIA_DEFINIDA"
TENDENCIA_REDEFINIDA = "TENDENCIA_REDEFINIDA"
BOS = "BOS"
CHOCH = "CHOCH"
SOMENTE_PAVIO = "SOMENTE_PAVIO"
AMBIGUO = "AMBIGUO"
PIVO_CONTINUACAO = "PIVO_CONTINUACAO"
PIVO_CORRETIVO = "PIVO_CORRETIVO"
ROMPIMENTO_PREMATURO = "ROMPIMENTO_PREMATURO"
TRANSICAO_INVALIDADA = "TRANSICAO_INVALIDADA"


def _name(direction: int) -> str:
    return "ALTA" if direction > 0 else "BAIXA"


@dataclass(frozen=True)
class StructureEvent:
    type: str
    index: int  # candle cujo fechamento tornou o evento conhecido
    time: datetime
    direction: Optional[str]  # ALTA ou BAIXA
    state_before: str
    state_after: str
    level: Optional[float] = None  # preço rompido/testado
    swing: Optional[Swing] = None  # topo/fundo ligado ao nível
    protection: Optional[Swing] = None  # proteção vigente após o evento
    context: str = ""  # detalhe (ex.: "confirmacao_do_choch")
    candle: Optional[Candle] = None
    choch_index: Optional[int] = None  # CHoCH que iniciou a transição, se houver


@dataclass
class _Transition:
    prev_dir: int
    choch_index: int
    old_protection: Swing  # só referência de invalidação; não é proteção ativa
    cont: Optional[Swing] = None
    corr: Optional[Swing] = None

    @property
    def frozen(self) -> bool:
        return self.corr is not None


@dataclass(frozen=True)
class ChochBosResult:
    candles: tuple[Candle, ...]
    swings: tuple[Swing, ...]
    events: tuple[StructureEvent, ...]
    states: tuple[str, ...]  # estado ao fechar cada candle
    protection: Optional[Swing]  # proteção vigente no fim

    @property
    def state(self) -> str:
        return self.states[-1] if self.states else INSUFICIENTE


def analyze_choch_bos(
    values: Iterable[CandleInput], last_candle_closed: bool, window: int = 2
) -> ChochBosResult:
    structure = analyze_structure(values, last_candle_closed, window)
    candles, swings = structure.candles, structure.swings

    direction = 0  # 0 = sem tendência; +1 alta; -1 baixa
    base_state = INSUFICIENTE
    protection: Optional[Swing] = None
    transition: Optional[_Transition] = None
    last_bos_index: Optional[int] = None
    entered_at = 0  # quando entramos na tendência atual sem proteção
    used: set[tuple[str, int]] = set()  # níveis já rompidos ou já anotados
    events: list[StructureEvent] = []
    states: list[str] = []
    known: list[Swing] = []  # swings confirmados até o candle anterior

    def state() -> str:
        if transition is not None:
            new = _name(-transition.prev_dir)
            step = ("BOS" if transition.frozen else
                    "PIVO_CORRETIVO" if transition.cont else "PIVO_CONTINUACAO")
            return f"TRANSICAO_PARA_{new}_AGUARDANDO_{step}"
        if direction == 0:
            return base_state
        return f"{_name(direction)}_{'PROTEGIDA' if protection else 'SEM_PROTECAO'}"

    def beyond(a: float, b: float, d: int) -> bool:
        return d * (a - b) > 0

    def ext(c: Candle, d: int) -> float:
        return c.high if d > 0 else c.low

    def fresh(s: Swing, j: int, d: int) -> bool:
        """Nenhum candle anterior já fechou além deste nível."""
        return not any(beyond(candles[k].close, s.price, d)
                       for k in range(s.origin_index + 1, j))

    def bos_reference(d: int, j: int) -> Optional[Swing]:
        kind = "high" if d > 0 else "low"
        pool = [s for s in known if s.kind == kind and (BOS, id(s)) not in used]
        if last_bos_index is not None:
            pool = [s for s in pool if s.origin_index >= last_bos_index]
            pool.sort(key=lambda s: d * s.price)
        else:
            pool.sort(key=lambda s: s.origin_index)
        ref = pool[-1] if pool else None
        return ref if ref and fresh(ref, j, d) else None

    def protection_candidate(d: int, broken: Swing) -> Optional[Swing]:
        kind = "low" if d > 0 else "high"
        pool = [s for s in known if s.kind == kind and s.origin_index > broken.origin_index]
        return min(pool, key=lambda s: d * s.price) if pool else None

    def once(tag: str, s: Swing) -> bool:
        key = (tag, id(s))
        if key in used:
            return False
        used.add(key)
        return True

    for j, c in enumerate(candles):
        before = state()

        def emit(kind: str, d: Optional[int], **kw) -> None:
            events.append(StructureEvent(
                kind, j, c.timestamp, _name(d) if d else None, before, state(),
                protection=protection, candle=c,
                choch_index=kw.pop("choch_index", transition.choch_index if transition else None),
                **kw))

        # ---------- 1) O que o preço deste candle fez ----------
        if direction != 0 and transition is None:
            d = direction
            ref, prot = bos_reference(d, j), protection
            up_touch = ref is not None and beyond(ext(c, d), ref.price, d)
            dn_touch = prot is not None and beyond(ext(c, -d), prot.price, -d)
            if up_touch and dn_touch:
                emit(AMBIGUO, None, context=f"atingiu {ref.price} e {prot.price} no mesmo candle")
            elif up_touch and beyond(c.close, ref.price, d):
                used.add((BOS, id(ref)))
                protection = protection_candidate(d, ref)
                last_bos_index = j
                if protection is None:
                    entered_at = j
                emit(BOS, d, level=ref.price, swing=ref, context="pavio_e_fechamento")
            elif up_touch:
                if once("pavio_bos", ref):
                    emit(SOMENTE_PAVIO, d, level=ref.price, swing=ref, context="BOS")
            elif dn_touch and beyond(c.close, prot.price, -d):
                transition = _Transition(d, j, prot)
                protection = None
                emit(CHOCH, -d, level=prot.price, swing=prot, context="pavio_e_fechamento")
            elif dn_touch:
                if once("pavio_choch", prot):
                    emit(SOMENTE_PAVIO, -d, level=prot.price, swing=prot, context="CHOCH")

        elif transition is not None:
            t = transition
            d, n = t.prev_dir, -t.prev_dir
            old, cont = t.old_protection, t.cont
            ref = bos_reference(d, j)
            back_touch = beyond(ext(c, d), old.price, d)
            fwd_touch = cont is not None and beyond(ext(c, n), cont.price, n)
            if back_touch and fwd_touch:
                emit(AMBIGUO, None, context=f"atingiu {old.price} e {cont.price} no mesmo candle")
            elif ref is not None and beyond(c.close, ref.price, d):
                # BOS na direção anterior: encerra a transição. Nunca reativa a proteção antiga.
                idx = t.choch_index
                used.add((BOS, id(ref)))
                transition = None
                protection = protection_candidate(d, ref)
                last_bos_index = j
                if protection is None:
                    entered_at = j
                emit(BOS, d, level=ref.price, swing=ref,
                     context="direcao_anterior_durante_transicao", choch_index=idx)
            elif beyond(c.close, old.price, d):
                idx = t.choch_index
                transition = None
                protection = None
                entered_at = j
                emit(TRANSICAO_INVALIDADA, d, level=old.price, swing=old, choch_index=idx)
            elif fwd_touch and beyond(c.close, cont.price, n):
                if t.frozen and fresh(cont, j, n):
                    idx = t.choch_index
                    used.add((BOS, id(cont)))
                    direction = n
                    protection = t.corr
                    last_bos_index = j
                    transition = None
                    emit(BOS, n, level=cont.price, swing=cont,
                         context="confirmacao_do_choch", choch_index=idx)
                elif once("prematuro", cont):
                    emit(ROMPIMENTO_PREMATURO, n, level=cont.price, swing=cont)
            elif fwd_touch and once("pavio_conf", cont):
                emit(SOMENTE_PAVIO, n, level=cont.price, swing=cont, context="BOS_DE_CONFIRMACAO")

        # ---------- 2) Topos/fundos que este candle confirmou ----------
        new = [s for s in swings if s.confirmation_index == j]
        known.extend(new)
        before = state()

        if direction == 0:
            trend = classify_trend(known)
            if trend in (ALTA, BAIXA):
                direction = 1 if trend == ALTA else -1
                entered_at = j
                emit(TENDENCIA_DEFINIDA, direction)
            else:
                base_state = trend

        elif transition is None and protection is None and new:
            highs = [s for s in known if s.kind == "high"]
            lows = [s for s in known if s.kind == "low"]
            if highs and lows and min(highs[-1].origin_index, lows[-1].origin_index) > entered_at:
                opposite = ("LH", "LL") if direction > 0 else ("HH", "HL")
                if (highs[-1].label, lows[-1].label) == opposite:
                    direction = -direction
                    entered_at = j
                    last_bos_index = None
                    emit(TENDENCIA_REDEFINIDA, direction)

        elif transition is not None and not transition.frozen:
            t = transition
            n = -t.prev_dir
            cont_kind = "low" if n < 0 else "high"
            previous_cont = t.cont
            for s in new:
                if s.kind == cont_kind and s.origin_index >= t.choch_index and (
                        t.cont is None or beyond(s.price, t.cont.price, n)):
                    t.cont = s
                    emit(PIVO_CONTINUACAO, n, level=s.price, swing=s)
                    before = state()
            if previous_cont is not None and t.cont is previous_cont:
                for s in new:
                    if (s.kind != cont_kind
                            and s.origin_index > t.cont.origin_index
                            and t.cont.confirmation_index < s.confirmation_index
                            and fresh(t.cont, j + 1, n)):
                        t.corr = s  # par congelado
                        emit(PIVO_CORRETIVO, n, level=s.price, swing=s)
                        break

        states.append(state())

    return ChochBosResult(candles, swings, tuple(events), tuple(states), protection)
