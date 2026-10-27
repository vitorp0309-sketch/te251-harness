"""Simulador de OBD2: grava no mesmo banco que o coletor real.

Uso:
    python -m te251.simulador                      # cenário 'estrada', roda até Ctrl+C
    python -m te251.simulador --cenario superaquecimento
    python -m te251.simulador --cenario marcha_lenta --segundos 120
    python -m te251.simulador --listar
"""
import argparse
import math
import random
import time

from te251 import config
from te251.store import Store

# alvo de cada grandeza por cenário + DTCs ativos
CENARIOS = {
    "marcha_lenta":     dict(vel=0,   temp=90,  volt=14.1, boost=0,   comb=68, dtcs=[]),
    "estrada":          dict(vel=100, temp=92,  volt=14.2, boost=1.0, comb=68, dtcs=[]),
    "superaquecimento": dict(vel=60,  temp=112, volt=14.0, boost=0.6, comb=60, dtcs=["P0217"]),
    "bateria_fraca":    dict(vel=0,   temp=88,  volt=11.8, boost=0,   comb=55, dtcs=["P0562"]),
    "turbo_fraco":      dict(vel=80,  temp=91,  volt=14.1, boost=0.2, comb=50, dtcs=["P0299"]),
    "tanque_reserva":   dict(vel=90,  temp=91,  volt=14.2, boost=0.9, comb=8,  dtcs=[]),
}


class Veiculo:
    """Modelo simples: as grandezas perseguem o alvo do cenário com ruído."""

    def __init__(self, cenario):
        self.c = CENARIOS[cenario]
        self.vel = 0.0
        self.temp = 70.0
        self.volt = 12.6
        self.comb = float(self.c["comb"])
        self.t = 0.0

    def passo(self, dt):
        c = self.c
        self.t += dt
        alvo_vel = c["vel"] + (8 * math.sin(self.t / 15) if c["vel"] else 0)
        self.vel += (alvo_vel - self.vel) * min(1, dt / 4)
        self.temp += (c["temp"] - self.temp) * min(1, dt / 30)
        self.volt += (c["volt"] - self.volt) * min(1, dt / 3)
        self.comb = max(0.0, self.comb - dt * self.vel / 3.6e5)   # gasto lento
        marcha = max(1, min(6, int(self.vel / 22) + 1))
        rpm = 750 if self.vel < 2 else 900 + self.vel / marcha * 40
        carga = 18 if self.vel < 2 else 30 + c["boost"] * 35
        mapa = 100 + c["boost"] * 90 * (self.vel / 100)
        r = random.gauss
        return {
            "RPM": max(0, rpm + r(0, 25)),
            "SPEED": max(0, self.vel + r(0, 0.6)),
            "COOLANT_TEMP": self.temp + r(0, 0.3),
            "ENGINE_LOAD": min(100, max(0, carga + r(0, 2))),
            "INTAKE_PRESSURE": mapa + r(0, 2),
            "CONTROL_MODULE_VOLTAGE": self.volt + r(0, 0.03),
            "FUEL_LEVEL": self.comb,
        }


def rodar(cenario="estrada", segundos=None, hz=5.0, aquecer_s=600, store=None, sleep=True):
    """Grava amostras simuladas. `aquecer_s` gera um histórico passado antes de começar."""
    st = store or Store()
    v = Veiculo(cenario)
    dt = 1.0 / hz
    agora = time.time()
    # histórico recente (para get_history e médias funcionarem logo de cara)
    passos = int(aquecer_s * hz / 5)
    for i in range(passos):
        ts = agora - aquecer_s + i * dt * 5
        for pid, val in v.passo(dt * 5).items():
            st.gravar(pid, round(val, 2), config.PIDS[pid][1], ts=ts, fonte="simulador")
    st.gravar_dtcs(CENARIOS[cenario]["dtcs"])
    st.commit()
    if segundos == 0:
        return st
    inicio = time.time()
    n = 0
    limite = None if segundos is None else int(segundos * hz)   # sem sleep: conta passos, não relógio
    while (limite is None or n < limite) if not sleep else (segundos is None or time.time() - inicio < segundos):
        for pid, val in v.passo(dt).items():
            st.gravar(pid, round(val, 2), config.PIDS[pid][1], fonte="simulador")
        n += 1
        if n % int(hz) == 0:
            st.gravar_dtcs(CENARIOS[cenario]["dtcs"])
            st.commit()
        if sleep:
            time.sleep(dt)
    st.commit()
    return st


def main():
    ap = argparse.ArgumentParser(description="Simulador OBD2 do TE-251")
    ap.add_argument("--cenario", default="estrada", choices=sorted(CENARIOS))
    ap.add_argument("--segundos", type=float, default=None, help="duração (padrão: até Ctrl+C)")
    ap.add_argument("--hz", type=float, default=5.0, help="amostras por segundo por PID")
    ap.add_argument("--listar", action="store_true", help="lista os cenários e sai")
    a = ap.parse_args()
    if a.listar:
        for nome, c in CENARIOS.items():
            print(f"{nome:18s} vel={c['vel']} km/h temp={c['temp']} °C volt={c['volt']} V "
                  f"comb={c['comb']}% dtcs={c['dtcs'] or '-'}")
        return
    print(f"Simulando '{a.cenario}' em {config.DB_PATH} a {a.hz} Hz por PID. Ctrl+C para parar.")
    try:
        rodar(a.cenario, a.segundos, a.hz)
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    main()
