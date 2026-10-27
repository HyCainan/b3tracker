"""
Motor de recomendações do B3Tracker.

Camada de serviço pura (sem Streamlit): recebe a carteira, busca os
históricos via cache existente e devolve indicadores + recomendações
baseadas em regras fixas e sinais de tendência.

IMPORTANTE: os sinais de tendência DESCREVEM o comportamento passado do
preço; não são previsão de preço futuro. O conteúdo é informativo e
educacional, e não constitui recomendação de investimento.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from services.api_rendafixa import rendimento_desde
from services.cache import buscar_ativos_paralelo
from services.carteira import calcular_posicoes, listar_operacoes
from services.renda_fixa import calcular_posicoes as calcular_posicoes_rf

# 1 ano de histórico: suficiente para SMA50 + janela de cruzamento,
# regressão e volatilidade. Reaproveita a chave de cache "TICKER:1y".
PERIODO_ANALISE = "1y"
PREGOES_POR_ANO = 252

LIMITES_PADRAO = {
    # Regras de carteira
    "concentracao_max_pct": 40.0,  # peso máx. de um ativo na carteira total
    "hhi_max": 0.25,  # HHI (0 a 1) da parcela de renda variável
    "prejuizo_max_pct": 10.0,  # queda máx. sobre o preço médio
    # Sinais por ativo
    "r2_min": 0.5,  # R² mínimo para considerar a tendência "definida"
    "rsi_sobrecompra": 70.0,
    "rsi_sobrevenda": 30.0,
    "janela_cruzamento": 10,  # pregões para considerar o cruzamento "recente"
    "vol_atencao_pct": 40.0,  # volatilidade anualizada
    "vol_alerta_pct": 60.0,
    "drawdown_atencao_pct": 30.0,  # queda máxima pico-vale no período
}

ORDEM_SEVERIDADE = {"alerta": 0, "atencao": 1, "info": 2}


@dataclass
class Recomendacao:
    regra: str
    escopo: str  # "carteira" | "ativo"
    severidade: str  # "alerta" | "atencao" | "info"
    titulo: str
    mensagem: str
    ativo: Optional[str] = None
    evidencia: dict = field(default_factory=dict)


# =========================
# Indicadores técnicos (funções puras sobre lista de preços)
# =========================


def extrair_fechamentos(stock):
    """Fechamentos em ordem cronológica a partir de historicalDataPrice."""
    historico = (stock or {}).get("historicalDataPrice") or []
    validos = [h for h in historico if h.get("close") and h["close"] > 0]
    validos.sort(key=lambda h: h.get("date", 0))
    return [float(h["close"]) for h in validos]


def tendencia_regressao(precos):
    """
    Regressão linear sobre o log do preço (log P = a + b·t).
    `b` é a inclinação diária; o R² indica o quanto a reta explica a
    série (confiança da tendência).
    """
    n = len(precos)
    if n < 20:
        return None

    y = [math.log(p) for p in precos]
    x_med = (n - 1) / 2
    y_med = sum(y) / n

    sxx = sum((i - x_med) ** 2 for i in range(n))
    sxy = sum((i - x_med) * (y[i] - y_med) for i in range(n))

    inclinacao = sxy / sxx
    intercepto = y_med - inclinacao * x_med

    ss_tot = sum((v - y_med) ** 2 for v in y)
    ss_res = sum((y[i] - (intercepto + inclinacao * i)) ** 2 for i in range(n))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return {
        "inclinacao_diaria": inclinacao,
        "tendencia_anual_pct": (math.exp(inclinacao * PREGOES_POR_ANO) - 1) * 100,
        "r2": r2,
    }


def media_movel(precos, janela, deslocamento=0):
    """SMA de `janela` pregões, terminando `deslocamento` pregões atrás."""
    fim = len(precos) - deslocamento
    if janela <= 0 or fim < janela:
        return None
    return sum(precos[fim - janela : fim]) / janela


def cruzamento_sma(precos, curta=20, longa=50, janela_recente=10):
    """
    Estado atual (SMA curta acima/abaixo da longa) e cruzamento mais
    recente dentro de `janela_recente` pregões.
    """
    if len(precos) < longa + janela_recente:
        return None

    sma_curta = media_movel(precos, curta)
    sma_longa = media_movel(precos, longa)

    cruzamento = None
    dias_desde = None

    for d in range(janela_recente):
        hoje = media_movel(precos, curta, d) - media_movel(precos, longa, d)
        ontem = media_movel(precos, curta, d + 1) - media_movel(precos, longa, d + 1)

        if ontem <= 0 < hoje:
            cruzamento, dias_desde = "alta", d
            break
        if ontem >= 0 > hoje:
            cruzamento, dias_desde = "baixa", d
            break

    return {
        "sma_curta": sma_curta,
        "sma_longa": sma_longa,
        "estado": "alta" if sma_curta > sma_longa else "baixa",
        "cruzamento": cruzamento,
        "dias_desde_cruzamento": dias_desde,
    }


def rsi(precos, periodo=14):
    """RSI de Wilder (suavização exponencial)."""
    if len(precos) < periodo + 1:
        return None

    deltas = [precos[i] - precos[i - 1] for i in range(1, len(precos))]

    media_ganho = sum(max(d, 0) for d in deltas[:periodo]) / periodo
    media_perda = sum(max(-d, 0) for d in deltas[:periodo]) / periodo

    for d in deltas[periodo:]:
        media_ganho = (media_ganho * (periodo - 1) + max(d, 0)) / periodo
        media_perda = (media_perda * (periodo - 1) + max(-d, 0)) / periodo

    if media_perda == 0:
        return 50.0 if media_ganho == 0 else 100.0

    rs = media_ganho / media_perda
    return 100 - 100 / (1 + rs)


def volatilidade_anualizada(precos):
    """Desvio-padrão dos retornos log diários, anualizado (em %)."""
    if len(precos) < 20:
        return None

    retornos = [math.log(precos[i] / precos[i - 1]) for i in range(1, len(precos))]
    media = sum(retornos) / len(retornos)
    variancia = sum((r - media) ** 2 for r in retornos) / (len(retornos) - 1)

    return math.sqrt(variancia) * math.sqrt(PREGOES_POR_ANO) * 100


def drawdown(precos):
    """Queda máxima pico-vale no período e distância atual do topo (em %)."""
    pico = precos[0]
    max_dd = 0.0

    for p in precos:
        pico = max(pico, p)
        max_dd = min(max_dd, p / pico - 1)

    return {
        "max_pct": max_dd * 100,
        "atual_pct": (precos[-1] / max(precos) - 1) * 100,
    }


def calcular_indicadores(stock, janela_cruzamento=10):
    """Consolida todos os indicadores de um ativo. None se histórico curto."""
    precos = extrair_fechamentos(stock)

    if len(precos) < 20:
        return None

    return {
        "n_pregoes": len(precos),
        "tendencia": tendencia_regressao(precos),
        "sma": cruzamento_sma(precos, janela_recente=janela_cruzamento),
        "rsi": rsi(precos),
        "volatilidade_pct": volatilidade_anualizada(precos),
        "drawdown": drawdown(precos),
    }


# =========================
# Regras por ativo
# =========================


def regras_ativo(ticker, ind, lim):
    recs = []

    # --- Tendência (regressão log-linear) ---
    t = ind.get("tendencia")
    if t and t["r2"] >= lim["r2_min"]:
        alta = t["tendencia_anual_pct"] > 0
        recs.append(
            Recomendacao(
                regra="tendencia_regressao",
                escopo="ativo",
                ativo=ticker,
                severidade="info" if alta else "atencao",
                titulo=f"Tendência de {'alta' if alta else 'baixa'}",
                mensagem=(
                    f"A reta ajustada ao log do preço aponta inclinação de "
                    f"{t['tendencia_anual_pct']:+.1f}% ao ano, com R² de "
                    f"{t['r2']:.2f} (a tendência explica bem a série). "
                    "Descreve o passado, não prevê o futuro."
                ),
                evidencia=t,
            )
        )

    # --- Cruzamento de médias móveis ---
    s = ind.get("sma")
    if s and s["cruzamento"]:
        alta = s["cruzamento"] == "alta"
        recs.append(
            Recomendacao(
                regra="cruzamento_sma",
                escopo="ativo",
                ativo=ticker,
                severidade="info" if alta else "atencao",
                titulo=f"Cruzamento de {'alta' if alta else 'baixa'} (SMA20/SMA50)",
                mensagem=(
                    f"A SMA20 cruzou {'acima' if alta else 'abaixo'} da SMA50 há "
                    f"{s['dias_desde_cruzamento']} pregão(ões) "
                    f"(SMA20 = R$ {s['sma_curta']:.2f}, SMA50 = R$ {s['sma_longa']:.2f})."
                ),
                evidencia=s,
            )
        )

    # --- RSI ---
    r = ind.get("rsi")
    if r is not None:
        if r >= lim["rsi_sobrecompra"]:
            recs.append(
                Recomendacao(
                    regra="rsi",
                    escopo="ativo",
                    ativo=ticker,
                    severidade="atencao",
                    titulo="Sobrecompra (RSI)",
                    mensagem=(
                        f"RSI(14) em {r:.0f}, acima de {lim['rsi_sobrecompra']:.0f}: "
                        "alta recente intensa, com risco maior de correção."
                    ),
                    evidencia={"rsi": r},
                )
            )
        elif r <= lim["rsi_sobrevenda"]:
            recs.append(
                Recomendacao(
                    regra="rsi",
                    escopo="ativo",
                    ativo=ticker,
                    severidade="info",
                    titulo="Sobrevenda (RSI)",
                    mensagem=(
                        f"RSI(14) em {r:.0f}, abaixo de {lim['rsi_sobrevenda']:.0f}: "
                        "queda recente intensa; pode indicar exagero ou deterioração real."
                    ),
                    evidencia={"rsi": r},
                )
            )

    # --- Volatilidade ---
    v = ind.get("volatilidade_pct")
    if v is not None and v >= lim["vol_atencao_pct"]:
        recs.append(
            Recomendacao(
                regra="volatilidade",
                escopo="ativo",
                ativo=ticker,
                severidade="alerta" if v >= lim["vol_alerta_pct"] else "atencao",
                titulo="Volatilidade elevada",
                mensagem=f"Volatilidade anualizada de {v:.1f}% no período analisado.",
                evidencia={"volatilidade_pct": v},
            )
        )

    # --- Drawdown ---
    dd = ind.get("drawdown")
    if dd and dd["max_pct"] <= -lim["drawdown_atencao_pct"]:
        recs.append(
            Recomendacao(
                regra="drawdown",
                escopo="ativo",
                ativo=ticker,
                severidade="atencao",
                titulo="Queda máxima relevante",
                mensagem=(
                    f"Queda máxima de {dd['max_pct']:.1f}% (pico ao vale) no período; "
                    f"hoje o preço está {dd['atual_pct']:.1f}% do topo."
                ),
                evidencia=dd,
            )
        )

    return recs


def regra_prejuizo(ticker, quantidade, preco_medio, preco_atual, lim):
    """Posição com prejuízo acima do limite sobre o preço médio."""
    if not preco_medio:
        return []

    variacao = (preco_atual / preco_medio - 1) * 100

    if variacao > -lim["prejuizo_max_pct"]:
        return []

    return [
        Recomendacao(
            regra="prejuizo_posicao",
            escopo="ativo",
            ativo=ticker,
            severidade="alerta",
            titulo="Posição com prejuízo acima do limite",
            mensagem=(
                f"Preço atual R$ {preco_atual:.2f} contra preço médio de "
                f"R$ {preco_medio:.2f} ({variacao:.1f}%), prejuízo latente de "
                f"R$ {quantidade * (preco_medio - preco_atual):.2f}. "
                f"Limite configurado: {lim['prejuizo_max_pct']:.0f}%."
            ),
            evidencia={"variacao_pct": variacao, "limite_pct": lim["prejuizo_max_pct"]},
        )
    ]


# =========================
# Regras de carteira
# =========================


def regras_concentracao(acoes, total_carteira, lim):
    """
    Peso de cada ação sobre a carteira total (ações + renda fixa) e HHI da
    parcela de renda variável (pesos normalizados dentro das ações).
    """
    recs = []

    if total_carteira <= 0 or not acoes:
        return recs, None

    for a in acoes:
        peso = a["valor_atual"] / total_carteira * 100
        a["peso_pct"] = peso

        if peso > lim["concentracao_max_pct"]:
            recs.append(
                Recomendacao(
                    regra="concentracao_ativo",
                    escopo="ativo",
                    ativo=a["ticker"],
                    severidade="atencao",
                    titulo="Concentração em um único ativo",
                    mensagem=(
                        f"{a['ticker']} representa {peso:.1f}% da carteira "
                        f"(limite configurado: {lim['concentracao_max_pct']:.0f}%)."
                    ),
                    evidencia={"peso_pct": peso},
                )
            )

    total_acoes = sum(a["valor_atual"] for a in acoes)
    hhi = None

    if total_acoes > 0:
        hhi = sum((a["valor_atual"] / total_acoes) ** 2 for a in acoes)

        if len(acoes) >= 2 and hhi > lim["hhi_max"]:
            recs.append(
                Recomendacao(
                    regra="hhi",
                    escopo="carteira",
                    severidade="atencao",
                    titulo="Renda variável pouco diversificada (HHI)",
                    mensagem=(
                        f"HHI de {hhi:.2f} entre as ações (limite {lim['hhi_max']:.2f}; "
                        f"1,00 = tudo em um ativo, {1 / len(acoes):.2f} = distribuição "
                        "igual entre os ativos atuais)."
                    ),
                    evidencia={"hhi": hhi, "n_ativos": len(acoes)},
                )
            )

    return recs, hhi


def regra_mix(valor_acoes, valor_rf):
    recs = []

    if valor_acoes > 0 and valor_rf == 0:
        recs.append(
            Recomendacao(
                regra="mix_renda",
                escopo="carteira",
                severidade="atencao",
                titulo="Carteira sem renda fixa",
                mensagem=(
                    "100% da carteira está em renda variável, sem reserva "
                    "de menor oscilação para amortecer quedas."
                ),
                evidencia={"pct_renda_fixa": 0.0},
            )
        )
    elif valor_rf > 0 and valor_acoes == 0:
        recs.append(
            Recomendacao(
                regra="mix_renda",
                escopo="carteira",
                severidade="info",
                titulo="Carteira apenas em renda fixa",
                mensagem=(
                    "Não há exposição a renda variável; o retorno fica limitado "
                    "ao indexador (CDI/Selic)."
                ),
                evidencia={"pct_renda_variavel": 0.0},
            )
        )

    return recs


def _fator_cdi(data_iso, cache_local, avisos):
    """Fator de CDI acumulado desde a data (memoizado por data na chamada)."""
    if data_iso not in cache_local:
        cache_local[data_iso] = 1 + rendimento_desde("CDI", data_iso, 100.0) / 100
    return cache_local[data_iso]


def comparar_com_cdi(carteira_id, acoes, posicoes_rf):
    """
    Retorno da carteira (posições em aberto) vs. o mesmo capital aplicado a
    100% do CDI nas mesmas datas.

    Aproximação para ações: cada posição é comparada usando a data média
    ponderada pelo custo das suas compras (vendas parciais não alteram o
    preço médio, então a base de custo restante é proporcional).
    """
    cache_local = {}
    investido = 0.0
    atual = 0.0
    benchmark = 0.0

    for a in acoes:
        compras = [
            op
            for op in listar_operacoes(carteira_id, a["ticker"])
            if op["tipo"] == "compra"
        ]
        base = sum(op["quantidade"] * op["preco"] for op in compras)

        if base <= 0:
            continue

        fator = (
            sum(
                op["quantidade"]
                * op["preco"]
                * _fator_cdi(op["data_operacao"], cache_local, None)
                for op in compras
            )
            / base
        )

        investido += a["custo_total"]
        atual += a["valor_atual"]
        benchmark += a["custo_total"] * fator

    for rf in posicoes_rf:
        if rf["erro"]:
            continue
        investido += rf["valor_aportado"]
        atual += rf["valor_atual"]
        benchmark += rf["valor_aportado"] * _fator_cdi(
            rf["data_operacao"], cache_local, None
        )

    if investido <= 0:
        return None

    return {
        "investido": investido,
        "retorno_carteira_pct": (atual / investido - 1) * 100,
        "retorno_cdi_pct": (benchmark / investido - 1) * 100,
    }


def regra_cdi(comp):
    if comp is None:
        return []

    carteira = comp["retorno_carteira_pct"]
    cdi = comp["retorno_cdi_pct"]

    if cdi <= 0:
        return [
            Recomendacao(
                regra="retorno_vs_cdi",
                escopo="carteira",
                severidade="info",
                titulo="Comparação com o CDI indisponível",
                mensagem=(
                    "As posições são muito recentes: ainda não há rendimento "
                    "de CDI acumulado para comparar."
                ),
                evidencia=comp,
            )
        ]

    diferenca = carteira - cdi
    abaixo = diferenca < 0

    return [
        Recomendacao(
            regra="retorno_vs_cdi",
            escopo="carteira",
            severidade="atencao" if abaixo else "info",
            titulo=f"Carteira {'abaixo' if abaixo else 'acima'} do CDI",
            mensagem=(
                f"Retorno da carteira: {carteira:+.2f}% contra {cdi:+.2f}% se o "
                f"mesmo capital estivesse a 100% do CDI nas mesmas datas "
                f"({diferenca:+.2f} p.p.). Considera apenas posições em aberto."
            ),
            evidencia=comp,
        )
    ]


# =========================
# Orquestração
# =========================


def gerar_recomendacoes(carteira_id, token, limites=None):
    """
    Analisa uma carteira e devolve:
      - recomendacoes: lista de Recomendacao ordenada por severidade
      - indicadores: {ticker: dict de indicadores | None}
      - resumo: composição, HHI e retorno vs. CDI
      - avisos: falhas parciais (ativo sem dados, CDI indisponível etc.)
    """
    lim = {**LIMITES_PADRAO, **(limites or {})}
    avisos = []
    recs = []
    indicadores = {}

    posicoes_acoes = calcular_posicoes(carteira_id)
    posicoes_rf = calcular_posicoes_rf(carteira_id)

    resumo = {
        "total_carteira": 0.0,
        "valor_acoes": 0.0,
        "valor_rf": 0.0,
        "pct_renda_variavel": 0.0,
        "pct_renda_fixa": 0.0,
        "hhi_acoes": None,
        "comparacao_cdi": None,
    }

    if not posicoes_acoes and not posicoes_rf:
        avisos.append("Nenhuma posição em aberto nesta carteira.")
        return {
            "recomendacoes": [],
            "indicadores": {},
            "resumo": resumo,
            "avisos": avisos,
        }

    # --- Cotações + históricos (cache e paralelismo já existentes) ---
    cotacoes = {}

    if posicoes_acoes:
        tickers = [p["ticker"] for p in posicoes_acoes]
        respostas = buscar_ativos_paralelo(tickers, PERIODO_ANALISE, token)

        for ticker, stock, _, erro in respostas:
            if erro:
                avisos.append(f"Erro ao buscar {ticker}: {erro}")
            elif not stock:
                avisos.append(f"Sem dados de mercado para {ticker}.")
            else:
                cotacoes[ticker] = stock

    # --- Ações: valor atual, sinais técnicos e prejuízo ---
    acoes = []

    for pos in posicoes_acoes:
        ticker = pos["ticker"]
        stock = cotacoes.get(ticker)

        preco_atual = (stock or {}).get("regularMarketPrice")
        if preco_atual is None and stock:
            fechamentos = extrair_fechamentos(stock)
            preco_atual = fechamentos[-1] if fechamentos else None

        valor_atual = (
            pos["quantidade"] * preco_atual if preco_atual else pos["custo_total"]
        )

        acoes.append(
            {
                "ticker": ticker,
                "quantidade": pos["quantidade"],
                "preco_medio": pos["preco_medio"],
                "custo_total": pos["custo_total"],
                "preco_atual": preco_atual,
                "valor_atual": valor_atual,
            }
        )

        if not stock:
            indicadores[ticker] = None
            continue

        ind = calcular_indicadores(stock, lim["janela_cruzamento"])
        indicadores[ticker] = ind

        if ind is None:
            avisos.append(
                f"Histórico insuficiente para {ticker}: sinais técnicos indisponíveis."
            )
        else:
            recs += regras_ativo(ticker, ind, lim)

        if preco_atual:
            recs += regra_prejuizo(
                ticker, pos["quantidade"], pos["preco_medio"], preco_atual, lim
            )

    # --- Composição da carteira ---
    valor_acoes = sum(a["valor_atual"] for a in acoes)
    valor_rf = sum(p["valor_atual"] for p in posicoes_rf)
    total = valor_acoes + valor_rf

    resumo.update(
        {
            "total_carteira": total,
            "valor_acoes": valor_acoes,
            "valor_rf": valor_rf,
            "pct_renda_variavel": valor_acoes / total * 100 if total else 0.0,
            "pct_renda_fixa": valor_rf / total * 100 if total else 0.0,
        }
    )

    recs_conc, hhi = regras_concentracao(acoes, total, lim)
    recs += recs_conc
    resumo["hhi_acoes"] = hhi

    recs += regra_mix(valor_acoes, valor_rf)

    # --- Retorno vs. CDI (API do BCB; falha não derruba a análise) ---
    try:
        comp = comparar_com_cdi(carteira_id, acoes, posicoes_rf)
        resumo["comparacao_cdi"] = comp
        recs += regra_cdi(comp)
    except Exception as e:
        avisos.append(f"Não foi possível comparar com o CDI agora: {e}")

    recs.sort(
        key=lambda r: (
            ORDEM_SEVERIDADE.get(r.severidade, 9),
            r.escopo != "carteira",
            r.ativo or "",
        )
    )

    return {
        "recomendacoes": recs,
        "indicadores": indicadores,
        "resumo": resumo,
        "avisos": avisos,
    }
