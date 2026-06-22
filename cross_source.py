"""Cross-source card matching — casar a MESMA carta entre as 4 fontes.

> **O que isto resolve, em uma frase:** hoje a mesma carta (ex.: Umbreon ex
> 161/131 de Prismatic) aparece como até 4 LINHAS soltas na tabela unificada —
> uma por fonte (MYP, CardTrader, COMC, Liga) — espalhadas por margem. Você não
> consegue ver de relance "essa carta está mais barata em qual fonte?". Este
> módulo agrupa essas linhas numa única, com o **preço de cada fonte lado a
> lado**, marcando onde comprar mais barato.

═══════════════════════════════════════════════════════════════════════════════
COMO É O CASAMENTO (e por que é CONSERVADOR de propósito)

Identidade de uma carta = (set canônico, número de coleção, nome/variante). As
fontes nomeiam tudo diferente, então:

  1. SET: cada fonte emite o set na SUA convenção (MYP = substring do título EN,
     Liga = nome completo, CT = código próprio, COMC = nome/slug). Revertemos pro
     código CANÔNICO via set_registry (caminho inverso do que o --sets faz). Se
     não der pra resolver o set com segurança → a carta NÃO entra no cross-source
     (fica só na tabela plana). Nunca chutamos o set.

  2. NÚMERO: a ÂNCORA forte. Dentro de um set, o número de coleção é ~único.
     Mesmo set canônico + mesmo número normalizado ("173/165" == "173" == "013"→
     "13") = altíssima confiança de ser a mesma carta.

  3. NOME: sinal secundário / sanity-check. A Liga não exporta número no report
     → só dá pra casá-la por (set + nome). Casamento por-nome é mais fraco (duas
     raridades do mesmo Pokémon no mesmo set podem colidir) → vai SEMPRE marcado
     "validar manualmente".

Regra dura (lição do ASI-Evolve, citada no CLAUDE.md: "aliases deduzidos por LLM
saíram alucinados"): preferimos PERDER um casamento a INVENTAR um. Sem fuzzy de
nome nesta v1 — só igualdade normalizada. Tudo incerto sai flagado, nunca
escondido. O integrado não decide compra; só põe o preço lado a lado e avisa.
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from normalize import Deal
from set_registry import entries

# Ordem canônica das fontes nas colunas lado-a-lado (estável p/ a tabela).
SOURCE_ORDER = ("MYP", "CardTrader", "COMC", "Liga")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(text: str) -> str:
    """lowercase + sem acento + não-alfanumérico vira espaço único. Pra casar
    nomes de set escritos de formas levemente diferentes (slug, pontuação)."""
    s = _strip_accents(str(text or "")).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


# ── número de coleção ───────────────────────────────────────────────────────
_NUM_SPLIT_RE = re.compile(r"([a-z]*)(\d+)(.*)")


def normalize_card_number(numero: str) -> str:
    """Número de coleção normalizado pra comparação entre fontes.

    "173/165"→"173"; "013/110"→"13" (tira zero à esquerda); "TG12/TG30"→"tg12";
    "161"→"161"; ""→"". Só o lado ESQUERDO da barra (número da carta, não o total
    do set). Mantém prefixo/sufixo de letra (TG, a/b de variantes)."""
    s = (numero or "").strip().lower()
    if not s:
        return ""
    s = s.split("/")[0].strip()           # "173/165" → "173"
    s = re.sub(r"[^a-z0-9]", "", s)        # só alfanumérico
    if not s:
        return ""
    m = _NUM_SPLIT_RE.match(s)
    if m:
        prefix, digits, rest = m.groups()
        digits = digits.lstrip("0") or "0"   # "013"→"13", mas "000"→"0"
        return f"{prefix}{digits}{rest}"
    return s


# ── nome da carta ───────────────────────────────────────────────────────────
_TRAILING_NUM_RES = (
    re.compile(r"\s*\(?\d+[a-z]?\s*/\s*\d+\)?\s*$"),   # "(161/131)" / "161/131"
    re.compile(r"\s*#\s*\d+[a-z]?\s*$"),               # "#161"
    re.compile(r"\s*-\s*\d+[a-z]?/\d+\s*$"),           # " - 173/165"
)


def normalize_card_name(carta: str) -> str:
    """Nome da carta normalizado pra comparação (lowercase, sem acento, sem o
    número de coleção pendurado, pontuação colapsada).

    "Umbreon ex (161/131)"→"umbreon ex"; "Umbreon EX"→"umbreon ex";
    "Pikachu 173/165"→"pikachu". NÃO mexe em sufixo de variante (ex/gx/vmax):
    eles ficam (lowercased) — distinguem cartas diferentes do mesmo Pokémon."""
    s = _strip_accents(str(carta or "")).lower()
    for rx in _TRAILING_NUM_RES:
        s = rx.sub("", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def _clean_display_name(carta: str) -> str:
    """Tira o número de coleção pendurado do nome de EXIBIÇÃO (o Nº tem coluna
    própria), preservando caixa e o sufixo de variante. 'Umbreon ex (161/131)'
    → 'Umbreon ex'. Cosmético — não afeta o casamento (que usa normalize_card_name)."""
    s = str(carta or "")
    for rx in _TRAILING_NUM_RES:
        s = rx.sub("", s)
    return s.strip()


def _name_compatible(a: str, b: str) -> bool:
    """Dois nomes normalizados descrevem a MESMA carta?

    True se um é SUBCONJUNTO de tokens do outro: 'umbreon' ⊆ 'umbreon ex' (uma
    fonte só omitiu o sufixo de variante). False pra 'umbreon ex' vs 'espeon ex'
    (Pokémon diferente), 'umbreon ex' vs 'umbreon v' (variante diferente) e
    'mr mime' vs 'mr rime' (nome composto diferente) — cartas DIFERENTES que
    colidiram no mesmo número por mapeamento furado de alguma fonte."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return a == b
    return ta <= tb or tb <= ta


def _name_components(items: list[tuple]) -> list[list[tuple]]:
    """Particiona itens em componentes de nome COMPATÍVEL (union-find sobre
    _name_compatible). Itens cujos nomes apontam pra cartas diferentes ficam em
    componentes SEPARADOS — assim duas cartas distintas que colidiram num número
    não viram uma linha enganosa (nome de uma + preço da outra); cada uma segue
    seu caminho (e some do cross-source se ficar com 1 fonte só)."""
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _name_compatible(items[i][3], items[j][3]):
                parent[find(i)] = find(j)
    comps: dict[int, list[tuple]] = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(items[i])
    return list(comps.values())


# ── set canônico (caminho inverso) ──────────────────────────────────────────
def _build_set_lookups():
    by_name: dict[str, str] = {}
    by_ct: dict[str, str] = {}
    by_liga: dict[str, str] = {}
    by_canon: dict[str, str] = {}
    by_comc: dict[str, str] = {}
    myp_subs: list[tuple[str, str]] = []
    for e in entries():
        by_canon[e.canonical.upper()] = e.canonical
        by_name[_norm(e.name)] = e.canonical
        if e.ct:
            by_ct[e.ct.lower()] = e.canonical
        if e.liga:
            by_liga[e.liga.upper()] = e.canonical
        if e.comc:
            by_comc[e.comc[1].upper()] = e.canonical
        if e.myp:
            myp_subs.append((e.myp.lower(), e.canonical))
    # substrings MYP mais longas primeiro (evita "151" casar antes de algo maior)
    myp_subs.sort(key=lambda t: len(t[0]), reverse=True)
    return by_name, by_ct, by_liga, by_canon, by_comc, myp_subs


_BY_NAME, _BY_CT, _BY_LIGA, _BY_CANON, _BY_COMC, _MYP_SUBS = _build_set_lookups()


def canonical_set_of(deal: Deal) -> Optional[str]:
    """String de set de uma fonte → código canônico, ou None se não for seguro.

    Conservador por design: resolve por igualdade exata (nome EN, código
    canônico, código Liga, code CT, abbrev COMC) e — só pro MYP, cujo set_name é
    um TÍTULO que contém a substring tunada — por substring. Não casou com
    segurança → None (a carta fica fora do cross-source, nunca num set chutado).
    """
    raw = (deal.set_name or "").strip()
    if not raw:
        return None
    fonte = (deal.fonte or "").lower()
    rawn = _norm(raw)            # normalizado (slug/pontuação viram espaço)
    up = raw.upper()

    # 1) igualdade exata — vale pra qualquer fonte que emita o nome/código limpo
    if rawn in _BY_NAME:
        return _BY_NAME[rawn]
    if up in _BY_CANON:
        return _BY_CANON[up]
    if up in _BY_LIGA:
        return _BY_LIGA[up]

    # 2) específico por fonte
    if "myp" in fonte:
        # set_name do MYP = título EN ("SV08: Surging Sparks") → substring tunada
        low = raw.lower()
        for sub, canon in _MYP_SUBS:
            if sub in low:
                return canon
    if "card" in fonte or fonte == "ct":
        if raw.lower() in _BY_CT:
            return _BY_CT[raw.lower()]
    if "comc" in fonte:
        if up in _BY_COMC:
            return _BY_COMC[up]
        # COMC pode emitir slug ("prismatic-evolutions") → já normalizado em rawn
        if rawn in _BY_NAME:
            return _BY_NAME[rawn]

    return None


# ══════════════════════════════════════════════════════════════════════════
# AGRUPAMENTO
# ══════════════════════════════════════════════════════════════════════════
@dataclass
class CrossSourceCard:
    """Uma carta encontrada em ≥2 fontes, com o melhor deal de cada fonte."""
    canonical_set: str
    number: str                              # número normalizado ("" se nenhuma fonte deu)
    display_name: str                        # nome mais completo entre as fontes
    display_number: str                      # número cru (pra exibir), "" se ausente
    deals_by_source: dict[str, Deal] = field(default_factory=dict)
    validar: bool = False                    # casamento incerto (nome-only / nome diverge)
    motivo: str = ""                         # por que está marcado validar

    @property
    def sources(self) -> list[str]:
        return sorted(self.deals_by_source, key=_source_sort_key)

    @property
    def cheapest_source(self) -> str:
        """Fonte com o menor preço de compra (R$)."""
        return min(self.deals_by_source,
                   key=lambda f: self.deals_by_source[f].compra_brl)

    @property
    def cheapest_deal(self) -> Deal:
        return self.deals_by_source[self.cheapest_source]

    @property
    def best_margin(self) -> float:
        """Maior margem entre as fontes (a melhor oportunidade da carta)."""
        return max(d.margem_pct for d in self.deals_by_source.values())


def _source_sort_key(fonte: str) -> tuple[int, str]:
    norm = _canon_source(fonte)
    order = {s: i for i, s in enumerate(SOURCE_ORDER)}
    return (order.get(norm, len(SOURCE_ORDER)), norm)


def _canon_source(fonte: str) -> str:
    """Normaliza o rótulo da fonte pras colunas (CT→CardTrader etc.)."""
    f = (fonte or "").strip().lower()
    if "myp" in f:
        return "MYP"
    if "comc" in f:
        return "COMC"
    if "liga" in f:
        return "Liga"
    if "card" in f or f == "ct":
        return "CardTrader"
    return fonte or "?"


# item interno: (deal, canonical_set, norm_number, norm_name)
def _annotate(deals: list[Deal]) -> list[tuple[Deal, str, str, str]]:
    items = []
    for d in deals:
        cset = canonical_set_of(d)
        if not cset:
            continue          # sem set seguro → fora do cross-source
        items.append((d, cset,
                      normalize_card_number(d.numero),
                      normalize_card_name(d.carta)))
    return items


def _cluster_within_set(items: list[tuple]) -> list[list[tuple]]:
    """Agrupa itens de UM set canônico em clusters de 'mesma carta'.

    1) Número é a âncora: cluster por número normalizado.
    2) Cada cluster numerado é PARTIDO por compatibilidade de nome — duas cartas
       diferentes que colidiram no mesmo número (mapeamento furado de uma fonte)
       viram componentes separados, nunca uma linha só enganosa.
    3) Itens SEM número (a Liga não exporta número) se juntam a um componente
       numerado SÓ se houver UM único cujo nome seja compatível (casamento por
       nome → marcado validar depois); 0 ou >1 compatíveis = ambíguo, não chuta,
       e eles se agrupam entre si por nome."""
    numbered = [it for it in items if it[2]]
    unnumbered = [it for it in items if not it[2]]

    num_clusters: dict[str, list[tuple]] = defaultdict(list)
    for it in numbered:
        num_clusters[it[2]].append(it)
    clusters: list[list[tuple]] = []
    for cl in num_clusters.values():
        clusters.extend(_name_components(cl))   # split nº-colisão de cartas distintas

    leftover: list[tuple] = []
    for it in unnumbered:
        compatible = [cl for cl in clusters
                      if any(_name_compatible(it[3], x[3]) for x in cl)]
        if len(compatible) == 1:        # único componente compatível → anexa
            compatible[0].append(it)
        else:                           # 0 ou >1 → ambíguo, não chuta
            leftover.append(it)

    if leftover:                        # sem-número órfãos: agrupam entre si por nome
        clusters.extend(_name_components(leftover))
    return clusters


def _make_card(cset: str, cluster: list[tuple]) -> CrossSourceCard:
    # melhor deal POR fonte = o mais barato daquela fonte (foco em "onde comprar")
    by_source: dict[str, Deal] = {}
    for deal, _cs, _num, _nm in cluster:
        src = _canon_source(deal.fonte)
        cur = by_source.get(src)
        if cur is None or deal.compra_brl < cur.compra_brl:
            by_source[src] = deal

    # número/nome de exibição: número cru de algum deal numerado; nome mais longo
    display_number = ""
    for deal, _cs, num, _nm in cluster:
        if num:
            display_number = str(deal.numero).strip()
            break
    display_name = _clean_display_name(
        max((d.carta for d in by_source.values()), key=lambda s: len(s or "")))
    number = next((it[2] for it in cluster if it[2]), "")

    # flags de incerteza (validar manualmente). Após o split por compatibilidade
    # de nome, um cluster já é coerente (mesma carta) — o único casamento "fraco"
    # que resta é o por NOME (fonte sem número, ex.: Liga), sempre flagado.
    has_unnumbered = any(not it[2] for it in cluster)
    has_numbered = any(it[2] for it in cluster)

    motivos = []
    if has_unnumbered and not has_numbered:
        motivos.append("casado só por nome (nenhuma fonte deu número)")
    elif has_unnumbered and has_numbered:
        motivos.append("fonte sem número (ex.: Liga) casada por nome")

    return CrossSourceCard(
        canonical_set=cset,
        number=number,
        display_name=display_name,
        display_number=display_number,
        deals_by_source=by_source,
        validar=bool(motivos),
        motivo="; ".join(motivos),
    )


def group_cross_source(deals: list[Deal]) -> list[CrossSourceCard]:
    """Lista de Deals (de QUALQUER fonte) → cartas presentes em ≥2 fontes.

    Só retorna cartas com set canônico resolvido E ≥2 fontes distintas. Ordena
    por maior margem desc (melhor oportunidade primeiro). Cartas de 1 fonte só,
    ou com set não-resolvido, NÃO aparecem aqui (continuam na tabela plana)."""
    by_set: dict[str, list[tuple]] = defaultdict(list)
    for it in _annotate(deals):
        by_set[it[1]].append(it)

    cards: list[CrossSourceCard] = []
    for cset, group in by_set.items():
        for cluster in _cluster_within_set(group):
            distinct_sources = {_canon_source(it[0].fonte) for it in cluster}
            if len(distinct_sources) < 2:
                continue          # não é cross-source
            cards.append(_make_card(cset, cluster))

    # ordena pela margem da COMPRA MAIS BARATA (a oportunidade acionável: é o
    # número que a tabela exibe — comprar onde está mais barato).
    cards.sort(key=lambda c: c.cheapest_deal.margem_pct, reverse=True)
    return cards
