"""Chat no terminal.  Uso: python -m te251.chat   (sair: 'sair' ou Ctrl+C)"""
from te251 import config
from te251.harness import ollama_no_ar, perguntar


def main():
    print(f"TE-251 · harness local · banco {config.DB_PATH}")
    print(f"LLM: {config.MODELO} em {config.OLLAMA_URL} -> "
          + ("no ar" if ollama_no_ar() else "INDISPONÍVEL (respostas por regras)"))
    historico = []
    while True:
        try:
            p = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if p.lower() in {"sair", "exit", "quit"}:
            break
        if not p:
            continue
        r = perguntar(p, historico=historico[-6:])
        print(f"TE-251: {r['resposta']}")
        nomes = ", ".join(u["ferramenta"] for u in r["ferramentas"]) or "-"
        print(f"   [{r['fonte']} · ferramentas: {nomes} · {r['tempo_s']} s]")
        historico += [{"role": "user", "content": p}, {"role": "assistant", "content": r["resposta"]}]


if __name__ == "__main__":
    main()
