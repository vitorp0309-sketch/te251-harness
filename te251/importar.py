"""Importa para o te251.db o banco gravado pelo app de estações do Willian (PROJETO-TE-251).

O app dele grava SQLite com a mesma tabela `sample(seq, ts, pid, value, unit)` e os mesmos
nomes de PID do python-OBD; só as unidades vêm escritas de outro jeito ("degree_Celsius").
Cada trecho contínuo de gravação vira uma sessão de origem 'importacao'.

Uso:
    python -m te251.importar caminho/do/te251.db                       # do app do Willian
    python -m te251.importar caminho/do/te251.db --descricao "garagem, 27/10"
    python -m te251.importar caminho/do/te251.db --pausa-s 600         # pausa que separa sessões
"""
import argparse
import hashlib
import sqlite3
from pathlib import Path

from te251 import config
from te251.store import Store, data_hora, unidade_padrao

PAUSA_S = 300   # mais de 5 min sem leitura = outra gravação


def _sha1(caminho):
    h = hashlib.sha1()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()[:12]


def importar(origem, store=None, descricao="", pausa_s=PAUSA_S, forcar=False):
    """Copia as amostras de `origem` para o banco do harness. Devolve um resumo (dict)."""
    origem = Path(origem)
    st = store or Store()
    marca = f"{origem.name} sha1:{_sha1(origem)}"
    ja = st.db.execute("SELECT id FROM sessao WHERE origem='importacao' AND descricao LIKE ?",
                       (f"%[{marca}]%",)).fetchone()
    if ja and not forcar:
        raise SystemExit(f"Este arquivo já foi importado (sessão {ja[0]}). Use --forcar para importar de novo.")

    fonte = sqlite3.connect(f"file:{origem.as_posix()}?mode=ro", uri=True)
    linhas = fonte.execute("SELECT ts, pid, value, unit FROM sample ORDER BY ts").fetchall()
    fonte.close()

    resumo = {"lidas": len(linhas), "gravadas": 0, "fora_da_faixa": 0, "sessoes": [], "pids_novos": set()}
    ultimo_ts = None
    for ts, pid, valor, unidade in linhas:
        if valor is None or ts is None:
            resumo["fora_da_faixa"] += 1
            continue
        if pid in config.PIDS:
            lo, hi = config.PIDS[pid][2]
            if not lo <= valor <= hi:     # mesma regra do coletor: descarta leitura impossível
                resumo["fora_da_faixa"] += 1
                continue
        else:
            resumo["pids_novos"].add(pid)  # gravado, mas as ferramentas da IA ainda não o usam
        if ultimo_ts is None or ts - ultimo_ts > pausa_s:
            if st.sessao_id is not None:
                st.fechar_sessao(fim=ultimo_ts)
            n = len(resumo["sessoes"]) + 1
            texto = f"{descricao + ' · ' if descricao else ''}app do Willian, trecho {n} [{marca}]"
            resumo["sessoes"].append(st.abrir_sessao("importacao", texto, inicio=ts))
        st.gravar(pid, valor, unidade_padrao(unidade), ts=ts, fonte="willian")
        resumo["gravadas"] += 1
        ultimo_ts = ts
    st.commit()
    if st.sessao_id is not None:
        st.fechar_sessao(fim=ultimo_ts)
    resumo["pids_novos"] = sorted(resumo["pids_novos"])
    return resumo


def main():
    ap = argparse.ArgumentParser(description="Importa o banco do app de estações do Willian")
    ap.add_argument("arquivo", help="te251.db gravado pelo app (não use o te251-simulacao.db)")
    ap.add_argument("--descricao", default="", help='nota das sessões, ex.: "garagem, 27/10"')
    ap.add_argument("--pausa-s", type=float, default=PAUSA_S, help="pausa (s) que separa duas sessões")
    ap.add_argument("--forcar", action="store_true", help="importa mesmo que o arquivo já tenha sido importado")
    a = ap.parse_args()
    st = Store()
    r = importar(a.arquivo, st, a.descricao, a.pausa_s, a.forcar)
    print(f"{r['gravadas']:,} de {r['lidas']:,} leituras importadas para {config.DB_PATH}")
    if r["fora_da_faixa"]:
        print(f"{r['fora_da_faixa']:,} leituras descartadas (vazias ou fora da faixa física)")
    if r["pids_novos"]:
        print("PIDs gravados que a IA ainda não usa:", ", ".join(r["pids_novos"]))
    for sid, ini, fim, _m, _o, desc, n, _p in st.sessoes():
        if sid in r["sessoes"]:
            print(f"  sessão {sid}: {data_hora(ini)} a {data_hora(fim)} · {n:,} leituras · {desc}")


if __name__ == "__main__":
    main()
