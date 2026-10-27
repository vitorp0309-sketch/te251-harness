"""Respostas determinísticas, sem LLM. Usadas quando o Ollama não está no ar
ou quando a resposta do LLM reprova na checagem de números."""
from te251 import ferramentas as F
from te251.ferramentas import _norm


def _fmt(v):
    return f"{v:.1f}".replace(".", ",") if isinstance(v, float) and not v.is_integer() else f"{v:.0f}"


def _linha(pid, e):
    if "erro" in e:
        return f"{pid}: {e['erro']}."
    txt = f"{e['descricao']}: {_fmt(e['valor'])} {e['unidade']} ({e['situacao']}, há {_fmt(e['idade_s'])} s)"
    return txt + (" — dado desatualizado" if e.get("aviso") else "") + "."


def _estado(pids):
    est = F.get_vehicle_state(pids)
    return " ".join(_linha(p, e) for p, e in est.items())


def _dtcs():
    d = F.get_dtcs()
    if not d["quantidade"]:
        return "Nenhum código de falha ativo."
    return " ".join(f"{c['codigo']}: {c['descricao']} (gravidade {c['gravidade']}). {c['orientacao']}."
                    for c in d["codigos"])


def _autonomia():
    r = F.fuel_range()
    if "erro" in r:
        return r["erro"].capitalize() + "."
    return (f"Combustível em {_fmt(r['nivel_pct'])}% ({_fmt(r['litros_totais'])} L). Alcance estimado de "
            f"{r['alcance_km']} km só ida; ponto de não retorno em {r['ponto_de_nao_retorno_km']} km. "
            f"Estimativa com {_fmt(r['km_l_usado'])} km/L e reserva de 10%.")


REGRAS = [
    (("esquent", "temperatura", "superaquec", "arrefec"), lambda: _estado(["COOLANT_TEMP"])),
    (("bateria", "tensao", "voltagem", "alternador"), lambda: _estado(["CONTROL_MODULE_VOLTAGE"])),
    (("turbo", "pressao", "map"), lambda: _estado(["INTAKE_PRESSURE", "ENGINE_LOAD"])),
    (("falha", "dtc", "codigo", "erro", "defeito"), _dtcs),
    (("combust", "autonomia", "alcance", "tanque", "diesel", "viagem"), _autonomia),
    (("rotacao", "rpm", "giro"), lambda: _estado(["RPM"])),
    (("velocidade", "rapido", "km/h"), lambda: _estado(["SPEED"])),
    (("carga",), lambda: _estado(["ENGINE_LOAD"])),
]


def _aviso_enlace():
    e = F.get_link_status()
    return e.get("aviso", "") if not e.get("dado_ao_vivo", True) or e["modo"] == "teatro" else ""


def responder(pergunta):
    p = _norm(pergunta)
    partes = [f() for chaves, f in REGRAS if any(k in p for k in chaves)]
    if not partes:   # "estado geral", "posso continuar rodando?" e afins
        partes = [_estado(None), _dtcs()]
    aviso = _aviso_enlace()
    if aviso:
        partes.append(f"Atenção: {aviso}.")
    return " ".join(dict.fromkeys(partes))   # sem repetir trechos
