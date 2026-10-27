"""Coletor OBD2 real: adaptador -> SQLite. Somente leitura no barramento.

Requer: pip install obd
Uso:
    python -m te251.coletor --porta COM5          # Windows
    python -m te251.coletor --porta /dev/ttyUSB0  # Linux
    python -m te251.coletor --varrer              # só lista os PIDs que a ECU suporta
"""
import argparse
import time

from te251 import config
from te251.store import Store


def main():
    import obd   # import aqui para o resto do projeto rodar sem o pacote

    ap = argparse.ArgumentParser(description="Coletor OBD2 do TE-251")
    ap.add_argument("--porta", default=None, help="porta serial do adaptador (padrão: autodetectar)")
    ap.add_argument("--varrer", action="store_true", help="lista os PIDs suportados e sai")
    a = ap.parse_args()

    conn = obd.Async(a.porta, fast=False, timeout=0.5)
    if not conn.is_connected():
        raise SystemExit("Adaptador não conectado. Confira a porta e a ignição.")

    if a.varrer:
        for c in sorted(conn.supported_commands, key=lambda c: c.name):
            print(c.name, "-", c.desc)
        return

    st = Store()
    comandos = [obd.commands[p] for p in config.PIDS if conn.supports(obd.commands[p])]
    faltando = [p for p in config.PIDS if p not in {c.name for c in comandos}]
    print("PIDs suportados:", [c.name for c in comandos])
    if faltando:
        print("Não suportados pela ECU:", faltando)   # ex.: FUEL_LEVEL em algumas Toyota

    faixas = {p: v[2] for p, v in config.PIDS.items()}

    def ao_ler(r):
        if r.is_null():
            return
        nome = r.command.name
        valor = float(r.value.magnitude)
        lo, hi = faixas[nome]
        if not lo <= valor <= hi:          # rejeita leitura fisicamente impossível
            return
        st.gravar(nome, valor, config.PIDS[nome][1])

    for c in comandos:
        conn.watch(c, callback=ao_ler)
    conn.watch(obd.commands.GET_DTC,
               callback=lambda r: None if r.is_null() else st.gravar_dtcs([d[0] for d in r.value]))
    conn.start()
    print(f"Coletando em {config.DB_PATH}. Ctrl+C para parar.")
    try:
        while True:
            time.sleep(1)
            st.commit()
    except KeyboardInterrupt:
        conn.stop()
        st.commit()


if __name__ == "__main__":
    main()
