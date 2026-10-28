"""Harness TE-251: pergunta -> LLM local (Ollama) <-> ferramentas -> resposta checada.

Só usa a biblioteca padrão do Python para falar com o Ollama (HTTP local).
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request

from te251 import config, guardrails, regras
from te251 import ferramentas as F

_ORIGEM = ("Você roda no notebook DENTRO do carro: os dados são ao vivo. "
           if config.MODO == "carro" else
           "Você roda no computador do teatro, sobre uma RÉPLICA da telemetria que chega do carro pela rede. "
           "O dado nunca é do instante atual: SEMPRE diga há quanto tempo foi lido. "
           "Se get_link_status disser que o enlace parou, avise que o carro pode estar em outro estado agora. ")

SISTEMA = (_ORIGEM +
    "Você é o assistente técnico da Toyota SW4 do PROJETO TE-251 (ITA). "
    "Responda em português do Brasil, em no máximo 4 frases curtas. "
    "Para qualquer valor do veículo (temperatura, tensão, rotação, combustível, falhas), "
    "CHAME AS FERRAMENTAS; nunca invente nem estime números. "
    "Use somente números devolvidos pelas ferramentas e diga há quantos segundos o dado foi lido. "
    "Se uma ferramenta devolver erro ou 'dado desatualizado', diga isso claramente. "
    "Autonomia e viagem são sempre estimativas: diga isso. "
    "O sistema é somente leitura: nunca sugira enviar comandos ao veículo."
)


def _post(caminho, corpo, timeout):
    req = urllib.request.Request(config.OLLAMA_URL + caminho, data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ollama_no_ar():
    try:
        with urllib.request.urlopen(config.OLLAMA_URL + "/api/tags", timeout=1) as r:
            nomes = [m["name"] for m in json.loads(r.read())["models"]]
        return any(n == config.MODELO or n.startswith(config.MODELO + ":") for n in nomes)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return False


def chat_ollama(mensagens):
    """Uma chamada ao LLM local. Retorna a mensagem do assistente (dict)."""
    r = _post("/api/chat", {"model": config.MODELO, "messages": mensagens, "tools": F.ESQUEMAS,
                            "stream": False, "options": {"temperature": config.TEMPERATURA}}, timeout=120)
    return r["message"]


def perguntar(pergunta, chat=None, historico=None):
    """Responde uma pergunta. Retorna dict com resposta, fonte, ferramentas usadas e tempo.

    `chat` permite trocar o LLM (nos testes, um falso); padrão = Ollama local.
    `historico` = mensagens anteriores (usuário/assistente) da mesma conversa.
    Cada pergunta fica registrada na tabela `interacao` do banco.
    """
    r = _responder(pergunta, chat, historico)
    try:
        F.store().registrar_interacao(pergunta, r)
    except sqlite3.Error:
        pass                     # falha no registro nunca impede a resposta
    return r


def _responder(pergunta, chat, historico):
    t0 = time.time()
    usadas, saidas = [], []
    if chat is None:
        if not ollama_no_ar():
            return {"resposta": regras.responder(pergunta), "fonte": "regras (LLM indisponível)",
                    "ferramentas": [], "tempo_s": round(time.time() - t0, 2)}
        chat = chat_ollama

    msgs = [{"role": "system", "content": SISTEMA}] + (historico or []) + [{"role": "user", "content": pergunta}]
    resposta = None
    try:
        for _ in range(config.MAX_RODADAS):
            m = chat(msgs)
            chamadas = m.get("tool_calls") or []
            if not chamadas:
                resposta = (m.get("content") or "").strip()
                break
            msgs.append(m)
            for c in chamadas:
                nome = c["function"]["name"]
                args = c["function"].get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args or "{}")
                saida = F.executar(nome, args)
                usadas.append({"ferramenta": nome, "args": args})
                saidas.append(saida)
                msgs.append({"role": "tool", "tool_name": nome, "content": json.dumps(saida, ensure_ascii=False)})
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        return {"resposta": regras.responder(pergunta), "fonte": f"regras (erro no LLM: {e})",
                "ferramentas": usadas, "tempo_s": round(time.time() - t0, 2)}

    if not resposta:
        return {"resposta": regras.responder(pergunta), "fonte": "regras (LLM não concluiu)",
                "ferramentas": usadas, "tempo_s": round(time.time() - t0, 2)}

    ok, soltos = guardrails.checar(resposta, saidas, pergunta)
    if not ok:
        return {"resposta": regras.responder(pergunta),
                "fonte": f"regras (resposta do LLM reprovada: números sem fonte {soltos})",
                "resposta_llm_reprovada": resposta, "ferramentas": usadas,
                "tempo_s": round(time.time() - t0, 2)}
    return {"resposta": resposta, "fonte": f"LLM {config.MODELO}", "ferramentas": usadas,
            "tempo_s": round(time.time() - t0, 2)}
