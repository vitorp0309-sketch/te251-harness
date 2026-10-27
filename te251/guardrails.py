"""Checagem pós-geração: todo número da resposta tem de vir de uma ferramenta
(ou da própria pergunta). Um número inventado reprova a resposta."""
import json
import re

_CODIGO_DTC = re.compile(r"\b[PCBU]\d{4}\b")
# O sinal de menos só vale quando não vem colado em outro número ou palavra:
# "-5 °C" é negativo, mas em "80-105" o hífen separa a faixa.
_NUM = re.compile(r"(?:(?<![\w.,])-)?\d+(?:[.,]\d+)?")


def _numeros(texto):
    texto = _CODIGO_DTC.sub(" ", texto)
    out = []
    for m in _NUM.findall(texto):
        s = m
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        elif s.count(".") == 1 and len(s.split(".")[1]) == 3:   # 1.674 (milhar pt-BR)
            s = s.replace(".", "")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def _valores(obj, acc):
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _valores(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _valores(v, acc)
    elif isinstance(obj, str):
        acc.extend(_numeros(obj))
    return acc


def _bate(n, fontes):
    for f in fontes:
        tol = max(0.06, abs(f) * 0.01)       # aceita arredondamento (92,37 -> 92)
        if abs(n - f) <= tol or abs(n - round(f)) < 1e-9:
            return True
    return False


def checar(resposta, saidas_ferramentas, pergunta=""):
    """Retorna (ok, numeros_sem_fonte)."""
    fontes = []
    for s in saidas_ferramentas:
        _valores(s if not isinstance(s, str) else json.loads(s), fontes)
    fontes += _numeros(pergunta)
    soltos = [n for n in _numeros(resposta) if not _bate(n, fontes)]
    return (not soltos, soltos)
