"""Importação do banco do app de estações do Willian e mensagens MQTT no formato dele."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TE251_DB", str(Path(tempfile.mkdtemp()) / "teste.db"))

from te251 import enlace  # noqa: E402
from te251.importar import importar  # noqa: E402
from te251.store import Store  # noqa: E402


def banco_do_willian(caminho, linhas):
    """Mesmo esquema do te251/collector_ble.py do PROJETO-TE-251."""
    db = sqlite3.connect(caminho)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS sample(seq INTEGER PRIMARY KEY, ts REAL, pid TEXT, value REAL, unit TEXT)")
    db.executemany("INSERT INTO sample VALUES(?,?,?,?,?)",
                   [(1000 + i, ts, pid, v, u) for i, (ts, pid, v, u) in enumerate(linhas)])
    db.commit()
    db.close()


class TestImportar(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.origem = d / "willian.db"
        self.st = Store(d / "harness.db")
        banco_do_willian(self.origem, [
            (1000.0, "COOLANT_TEMP", 88.0, "degree_Celsius"),
            (1001.5, "RPM", 780.0, "revolutions_per_minute"),
            (1003.0, "CONTROL_MODULE_VOLTAGE", 14.1, "volt"),
            (1004.0, "RPM", 99999.0, "revolutions_per_minute"),   # impossível: descartada
            (1005.0, "MAF", 4.2, "gram / second"),                 # PID fora da lista da IA
            (2000.0, "COOLANT_TEMP", 91.0, "degree_Celsius"),     # 16 min depois: outra sessão
        ])

    def tearDown(self):
        self.st.db.close()

    def test_importa_em_sessoes_e_converte_unidades(self):
        r = importar(self.origem, self.st, descricao="garagem")
        self.assertEqual((r["lidas"], r["gravadas"], r["fora_da_faixa"]), (6, 5, 1))
        self.assertEqual(r["pids_novos"], ["MAF"])
        sessoes = self.st.sessoes()
        self.assertEqual([(s[4], s[1], s[2], s[6]) for s in sessoes],
                         [("importacao", 1000.0, 1005.0, 4), ("importacao", 2000.0, 2000.0, 1)])
        self.assertIn("garagem", sessoes[0][5])
        self.assertEqual(self.st.ultimo("COOLANT_TEMP")["unidade"], "°C")
        unidades = dict(self.st.db.execute("SELECT pid, unit FROM sample WHERE pid IN ('RPM','MAF')"))
        self.assertEqual(unidades, {"RPM": "rpm", "MAF": "g/s"})
        self.assertEqual(self.st.db.execute("SELECT DISTINCT fonte FROM sample").fetchall(), [("willian",)])

    def test_nao_importa_o_mesmo_arquivo_duas_vezes(self):
        importar(self.origem, self.st)
        with self.assertRaises(SystemExit):
            importar(self.origem, self.st)
        importar(self.origem, self.st, forcar=True)
        self.assertEqual(len(self.st.sessoes()), 4)


class TestMensagemDoWillian(unittest.TestCase):
    def test_replica_aceita_formato_do_app(self):
        st = Store(Path(tempfile.mkdtemp()) / "teatro.db")
        enlace.aplicar_mensagem(st, "te251/telemetry/COOLANT_TEMP",
                                {"seq": 1, "ts": 1000.0, "pid": "COOLANT_TEMP", "v": 90.0, "u": "degree_Celsius"})
        enlace.aplicar_mensagem(st, enlace.TOPICO_DTC, {"ts": 1000.0, "dtc": ["P0217"]})
        self.assertEqual(st.ultimo("COOLANT_TEMP")["unidade"], "°C")
        self.assertEqual(st.dtcs_ativos(), ["P0217"])
        st.db.close()


if __name__ == "__main__":
    unittest.main()
