"""Ferramentas do harness: a ÚNICA fonte de números para o LLM.

Contrato único (o mesmo para terminal, web e, no futuro, MCP/Open WebUI):
    get_vehicle_state(pids)       último valor + idade
    get_history(pid, janela_s)    mín/máx/média/tendência
    get_dtcs()                    códigos de falha ativos + descrição
    fuel_range()                  combustível, alcance e ponto de não retorno
    search_kb(consulta)           trechos da base de conhecimento (manuais, DTCs, limites)
    get_link_status()             se o coletor está gravando e a idade do último dado
"""
import csv
import re
import threading
import time
import unicodedata

from te251 import config
from te251.store import Store

_local = threading.local()   # uma conexão SQLite por thread (servidor web atende em paralelo)


def store():
    if getattr(_local, "store", None) is None:
        _local.store = Store()
    return _local.store


def _arred(v):
    return round(v, 1) if abs(v) < 100 else round(v)


def _situacao(pid, v):
    lo, hi = config.PIDS[pid][3]
    return "abaixo do normal" if v < lo else "acima do normal" if v > hi else "normal"


# ----------------------------------------------------------------------------
def get_vehicle_state(pids=None):
    pids = [p.upper() for p in (pids or list(config.PIDS))]
    out, agora = {}, time.time()
    for p in pids:
        if p not in config.PIDS:
            out[p] = {"erro": f"PID desconhecido. Válidos: {', '.join(config.PIDS)}"}
            continue
        u = store().ultimo(p)
        if u is None:
            out[p] = {"erro": "sem leitura (ECU não suporta ou coletor parado)"}
            continue
        idade = agora - u["ts"]
        out[p] = {"descricao": config.PIDS[p][0], "valor": _arred(u["valor"]), "unidade": u["unidade"],
                  "idade_s": round(idade, 1), "situacao": _situacao(p, u["valor"]),
                  "faixa_normal": list(config.PIDS[p][3])}
        if idade > config.IDADE_MAX_S:
            out[p]["aviso"] = "dado desatualizado"
    return out


def get_history(pid, janela_s=300):
    pid = pid.upper()
    if pid not in config.PIDS:
        return {"erro": f"PID desconhecido. Válidos: {', '.join(config.PIDS)}"}
    janela_s = max(5, min(int(janela_s), 24 * 3600))
    serie = store().historico(pid, janela_s)
    if not serie:
        return {"pid": pid, "erro": "sem dados na janela"}
    vals = [v for _, v in serie]
    t0, t1 = serie[0][0], serie[-1][0]
    terco = (t1 - t0) / 3                     # compara o 1º e o último terço do TEMPO, não das amostras
    ini = [v for t, v in serie if t <= t0 + terco] or vals[:1]
    fim = [v for t, v in serie if t >= t1 - terco] or vals[-1:]
    delta = sum(fim) / len(fim) - sum(ini) / len(ini)
    lim = 0.02 * (config.PIDS[pid][2][1] - config.PIDS[pid][2][0])
    tend = "subindo" if delta > lim else "caindo" if delta < -lim else "estável"
    return {"pid": pid, "descricao": config.PIDS[pid][0], "unidade": config.PIDS[pid][1],
            "janela_s": janela_s, "amostras": len(vals), "minimo": _arred(min(vals)),
            "maximo": _arred(max(vals)), "media": _arred(sum(vals) / len(vals)),
            "tendencia": tend, "variacao": _arred(delta)}


def _tabela_dtc():
    tab = {}
    arq = config.KB_DIR / "dtc.csv"
    if arq.exists():
        with open(arq, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                tab[r["codigo"]] = r
    return tab


def get_dtcs():
    tab = _tabela_dtc()
    ativos = store().dtcs_ativos()
    return {"quantidade": len(ativos),
            "codigos": [{"codigo": c,
                         "descricao": tab.get(c, {}).get("descricao", "sem descrição na base"),
                         "gravidade": tab.get(c, {}).get("gravidade", "?"),
                         "orientacao": tab.get(c, {}).get("orientacao", "consultar manual")}
                        for c in ativos]}


def fuel_range(km_l=None):
    u = store().ultimo("FUEL_LEVEL")
    if u is None:
        return {"erro": "nível de combustível indisponível (PID 2F não suportado ou sem leitura)"}
    km_l = float(km_l or config.KM_L_PADRAO)
    util_l = max(0.0, config.TANQUE_L * (u["valor"] - config.RESERVA_PCT) / 100)
    alcance = util_l * km_l
    return {"nivel_pct": _arred(u["valor"]), "litros_totais": _arred(config.TANQUE_L * u["valor"] / 100),
            "litros_uteis_acima_da_reserva": _arred(util_l), "km_l_usado": km_l,
            "alcance_km": round(alcance), "ponto_de_nao_retorno_km": round(alcance / 2),
            "idade_s": round(time.time() - u["ts"], 1),
            "aviso": f"estimativa com consumo fixo de {km_l} km/L e reserva de {config.RESERVA_PCT:.0f}%"}


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def search_kb(consulta, k=3):
    """Busca por palavras-chave (v0). Trocar por embeddings locais (bge-m3) depois."""
    termos = {t for t in re.findall(r"\w{3,}", _norm(consulta))}
    trechos = []
    for arq in sorted(config.KB_DIR.glob("*")):
        if arq.suffix not in {".md", ".txt", ".csv"}:
            continue
        texto = arq.read_text(encoding="utf-8")
        blocos = texto.splitlines() if arq.suffix == ".csv" else re.split(r"\n\s*\n", texto)
        for b in blocos:
            nb = _norm(b)
            score = sum(1 for t in termos if t in nb)
            if score:
                trechos.append((score, arq.name, b.strip()))
    trechos.sort(key=lambda x: -x[0])
    return {"consulta": consulta, "trechos": [{"fonte": f, "texto": t[:600]} for _, f, t in trechos[:k]]}


def get_link_status():
    no_carro = config.MODO == "carro"
    ts = store().ultima_amostra_ts()
    if ts is None:
        return {"modo": config.MODO, "dado_ao_vivo": False,
                "aviso": "banco vazio: rode o simulador/coletor (carro) ou a réplica (teatro)"}
    idade = time.time() - ts
    ao_vivo = idade <= config.IDADE_MAX_S
    r = {"modo": config.MODO, "dado_ao_vivo": ao_vivo, "idade_ultimo_dado_s": round(idade, 1),
         "pids_disponiveis": store().pids_disponiveis()}
    if not ao_vivo:
        r["aviso"] = ("coletor parado: o último dado tem "
                      if no_carro else
                      "enlace com o carro interrompido: a réplica parou há ") + f"{idade:.0f} s"
    elif not no_carro:
        r["aviso"] = "réplica do carro; o dado chega com alguns segundos de atraso"
    return r


# ----------------------------------------------------------------------------
def _fn(nome, desc, props=None, obrig=None):
    return {"type": "function", "function": {"name": nome, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": obrig or []}}}


PIDS_TXT = ", ".join(config.PIDS)

ESQUEMAS = [
    _fn("get_vehicle_state",
        f"Último valor de cada PID com unidade, idade em segundos e situação (normal/acima/abaixo). PIDs: {PIDS_TXT}.",
        {"pids": {"type": "array", "items": {"type": "string"}, "description": "lista de PIDs; vazio = todos"}}),
    _fn("get_history", "Mínimo, máximo, média e tendência de um PID numa janela de tempo.",
        {"pid": {"type": "string"}, "janela_s": {"type": "integer", "description": "segundos (padrão 300)"}},
        ["pid"]),
    _fn("get_dtcs", "Códigos de falha (DTC) ativos com descrição, gravidade e orientação."),
    _fn("fuel_range", "Nível de combustível, alcance estimado (só ida) e ponto de não retorno."),
    _fn("search_kb", "Busca trechos de manuais, tabela de DTCs e limites de operação.",
        {"consulta": {"type": "string"}}, ["consulta"]),
    _fn("get_link_status", "Diz se o dado é ao vivo ou vem da réplica, e a idade do último dado."),
]

IMPL = {"get_vehicle_state": get_vehicle_state, "get_history": get_history, "get_dtcs": get_dtcs,
        "fuel_range": fuel_range, "search_kb": search_kb, "get_link_status": get_link_status}


def executar(nome, args):
    if nome not in IMPL:
        return {"erro": f"ferramenta desconhecida: {nome}"}
    try:
        return IMPL[nome](**(args or {}))
    except TypeError as e:
        return {"erro": f"argumentos inválidos: {e}"}
