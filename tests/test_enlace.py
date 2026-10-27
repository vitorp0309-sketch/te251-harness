"""Enlace carro -> teatro, inclusive com corte.

Precisa de um broker MQTT local e do paho-mqtt. Sem isso, o teste é pulado:
    pip install paho-mqtt
    docker run -p 1883:1883 eclipse-mosquitto   (ou mosquitto -p 1883)
Aponte outro endereço com TE251_BROKER_TESTE=host:porta
"""
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("TE251_DB", str(Path(tempfile.mkdtemp()) / "carro.db"))

from te251.store import Store  # noqa: E402

BROKER, PORTA = (os.environ.get("TE251_BROKER_TESTE", "127.0.0.1:1883").split(":") + ["1883"])[:2]
PORTA = int(PORTA)


def _broker_no_ar():
    try:
        with socket.create_connection((BROKER, PORTA), timeout=1):
            return True
    except OSError:
        return False


try:
    import paho.mqtt.client  # noqa: F401
    TEM_PAHO = True
except ImportError:
    TEM_PAHO = False


@unittest.skipUnless(TEM_PAHO and _broker_no_ar(), f"sem paho-mqtt ou sem broker em {BROKER}:{PORTA}")
class TestEnlace(unittest.TestCase):
    def setUp(self):
        from te251 import enlace, simulador
        self.enlace, self.simulador = enlace, simulador
        d = Path(tempfile.mkdtemp())
        self.carro = Store(d / "carro.db")
        self.teatro = Store(d / "teatro.db")

    def tearDown(self):
        self.carro.db.close()
        self.teatro.db.close()

    def _replicar_em_segundo_plano(self, segundos):
        t = threading.Thread(target=self.enlace.replicar,
                             kwargs=dict(broker=BROKER, porta=PORTA, store=self.teatro, segundos=segundos),
                             daemon=True)
        t.start()
        time.sleep(1)   # deixa assinar os tópicos antes de o carro publicar
        return t

    def _contar(self, store):
        return store.db.execute("SELECT COUNT(*) FROM sample").fetchone()[0]

    def test_replica_recebe_tudo_e_sem_duplicatas(self):
        t = self._replicar_em_segundo_plano(12)
        self.simulador.rodar("estrada", segundos=2, hz=10, aquecer_s=0, store=self.carro, sleep=False)
        self.enlace.publicar(BROKER, PORTA, store=self.carro, ciclos=2, intervalo=0.5)
        self.enlace.publicar(BROKER, PORTA, store=self.carro, ciclos=2, intervalo=0.5)  # reenvio: nada novo
        time.sleep(2)
        self.assertEqual(self._contar(self.teatro), self._contar(self.carro))
        self.assertEqual(self.teatro.dtcs_ativos(), self.carro.dtcs_ativos())
        t.join(timeout=15)

    def test_corte_de_enlace_nao_perde_amostra(self):
        # 1ª rodada com a réplica no ar
        t = self._replicar_em_segundo_plano(8)
        self.simulador.rodar("estrada", segundos=1, hz=10, aquecer_s=0, store=self.carro, sleep=False)
        self.enlace.publicar(BROKER, PORTA, store=self.carro, ciclos=2, intervalo=0.5)
        time.sleep(1.5)
        recebidas_antes = self._contar(self.teatro)
        self.assertGreater(recebidas_antes, 0)
        t.join(timeout=12)   # teatro sai do ar = enlace cortado

        # carro continua coletando sozinho (modo tandem)
        self.simulador.rodar("superaquecimento", segundos=2, hz=10, aquecer_s=0, store=self.carro, sleep=False)
        self.assertGreater(self._contar(self.carro), recebidas_antes)

        # enlace volta: o publicador retoma do ponto exato
        t2 = self._replicar_em_segundo_plano(12)
        self.enlace.publicar(BROKER, PORTA, store=self.carro, ciclos=3, intervalo=0.5)
        time.sleep(2.5)
        self.assertEqual(self._contar(self.teatro), self._contar(self.carro))
        self.assertIn("P0217", self.teatro.dtcs_ativos())
        t2.join(timeout=15)


if __name__ == "__main__":
    unittest.main()
