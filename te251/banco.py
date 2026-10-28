"""Utilitário do banco: inspecionar, exportar e medir o custo do armazenamento.

Uso:
    python -m te251.banco info                       # versão do esquema, tamanho, contagens
    python -m te251.banco sessoes                    # lista as sessões gravadas
    python -m te251.banco interacoes [--sessao N]    # perguntas feitas ao harness
    python -m te251.banco exportar --saida exports/sessao3.csv [--sessao 3]
    python -m te251.banco medir --horas 2 [--hz 5]   # simula N horas num banco temporário e mede
"""
import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from te251 import config
from te251.store import Store, data_hora


def _tamanho_mb(caminho):
    return sum(Path(str(caminho) + s).stat().st_size for s in ("", "-wal") if Path(str(caminho) + s).exists()) / 1e6


def info(st):
    db = st.db
    print(f"Banco: {config.DB_PATH}  ({_tamanho_mb(config.DB_PATH):.1f} MB)")
    print(f"Esquema: v{db.execute('PRAGMA user_version').fetchone()[0]} · modo {config.MODO}")
    for tabela in ("sessao", "sample", "dtc", "interacao"):
        print(f"  {tabela:10s} {db.execute(f'SELECT COUNT(*) FROM {tabela}').fetchone()[0]:>10,} linhas")
    ini, fim = db.execute("SELECT MIN(ts), MAX(ts) FROM sample").fetchone()
    print(f"Telemetria de {data_hora(ini)} a {data_hora(fim)}")


def sessoes(st):
    linhas = st.sessoes()
    if not linhas:
        print("Nenhuma sessão gravada.")
        return
    print(f"{'id':>4}  {'início':19s}  {'fim':19s}  {'origem':10s}  {'amostras':>9}  {'perguntas':>9}  descrição")
    for sid, ini, fim, _modo, origem, desc, n_amostras, n_perg in linhas:
        print(f"{sid:>4}  {data_hora(ini):19s}  {data_hora(fim):19s}  {origem:10s}  "
              f"{n_amostras:>9,}  {n_perg:>9}  {desc}")


def interacoes(st, sessao_id=None):
    sql = "SELECT ts, pergunta, resposta, fonte, tempo_s, idade_dado_s, ferramentas FROM interacao"
    args = ()
    if sessao_id is not None:
        sql, args = sql + " WHERE sessao_id=?", (sessao_id,)
    for ts, perg, resp, fonte, tempo, idade, ferr in st.db.execute(sql + " ORDER BY ts", args):
        nomes = ", ".join(f["ferramenta"] for f in json.loads(ferr)) or "-"
        print(f"[{data_hora(ts)}] {perg}\n    {resp}\n    ({fonte} · {nomes} · {tempo} s · dado com {idade} s)\n")


def medir(horas=2.0, hz=5.0):
    """Mede o custo de gravar `horas` de telemetria a `hz` amostras/s por PID e de consultar o banco cheio."""
    from te251.simulador import Veiculo

    pasta = tempfile.mkdtemp()
    caminho = Path(pasta) / "medicao.db"
    st = Store(caminho)
    st.abrir_sessao("simulador", f"medição {horas} h a {hz} Hz")
    v = Veiculo("estrada")
    passos = int(horas * 3600 * hz)
    t_ini = time.time() - horas * 3600
    t0 = time.perf_counter()
    for i in range(passos):
        ts = t_ini + i / hz
        for pid, val in v.passo(1 / hz).items():
            st.gravar(pid, round(val, 2), config.PIDS[pid][1], ts=ts, fonte="simulador")
        if i % 1000 == 0:
            st.commit()
    st.commit()
    gravacao_s = time.perf_counter() - t0
    st.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    linhas = st.db.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    mb = _tamanho_mb(caminho)

    def cronometrar(fn, n=20):
        t = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t) / n * 1000

    consultas = {
        "ultimo(COOLANT_TEMP)": lambda: st.ultimo("COOLANT_TEMP"),
        "historico 5 min": lambda: st.historico("COOLANT_TEMP", 300),
        "historico 1 h": lambda: st.historico("COOLANT_TEMP", 3600),
        "dtcs_ativos": st.dtcs_ativos,
        "pids_disponiveis": st.pids_disponiveis,
    }
    print(f"Medição: {horas} h de telemetria, {len(config.PIDS)} PIDs a {hz} Hz cada")
    print(f"  linhas gravadas      {linhas:,}  ({linhas / horas:,.0f} por hora)")
    print(f"  tamanho do banco     {mb:.1f} MB  ({mb / horas:.1f} MB por hora)")
    print(f"  tempo de gravação    {gravacao_s:.1f} s  ({linhas / gravacao_s:,.0f} linhas/s; "
          f"o coletor precisa de {len(config.PIDS) * hz:,.0f} linhas/s)")
    print("  consultas com o banco cheio (média de 20):")
    resultado = {"linhas": linhas, "mb": mb, "gravacao_s": gravacao_s, "consultas_ms": {}}
    for nome, fn in consultas.items():
        ms = cronometrar(fn)
        resultado["consultas_ms"][nome] = ms
        print(f"    {nome:22s} {ms:8.2f} ms")
    st.db.close()
    for s in ("", "-wal", "-shm"):
        Path(str(caminho) + s).unlink(missing_ok=True)
    os.rmdir(pasta)
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Utilitário do banco do TE-251")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    sub.add_parser("sessoes")
    p = sub.add_parser("interacoes")
    p.add_argument("--sessao", type=int)
    p = sub.add_parser("exportar")
    p.add_argument("--saida", required=True)
    p.add_argument("--sessao", type=int)
    p = sub.add_parser("medir")
    p.add_argument("--horas", type=float, default=2.0)
    p.add_argument("--hz", type=float, default=5.0)
    a = ap.parse_args()

    if a.cmd == "medir":
        medir(a.horas, a.hz)
        return
    st = Store()
    if a.cmd == "info":
        info(st)
    elif a.cmd == "sessoes":
        sessoes(st)
    elif a.cmd == "interacoes":
        interacoes(st, a.sessao)
    elif a.cmd == "exportar":
        Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
        n = st.exportar_csv(a.saida, a.sessao)
        print(f"{n:,} linhas exportadas para {a.saida}")


if __name__ == "__main__":
    main()
