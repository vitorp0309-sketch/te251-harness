"""Testes do esquema v1 do banco.  Uso: python -m unittest discover tests"""
import csv
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("TE251_DB", str(Path(tempfile.mkdtemp()) / "teste.db"))
os.environ.setdefault("TE251_OLLAMA_URL", "http://127.0.0.1:9")

from te251 import banco, harness, simulador  # noqa: E402
from te251 import ferramentas as F  # noqa: E402
from te251.store import VERSAO, Store  # noqa: E402

ESQUEMA_V0 = """
CREATE TABLE sample(seq INTEGER PRIMARY KEY, ts REAL NOT NULL, pid TEXT NOT NULL,
                    value REAL NOT NULL, unit TEXT NOT NULL, fonte TEXT NOT NULL DEFAULT 'obd');
CREATE INDEX ix_sample_pid_ts ON sample(pid, ts);
CREATE TABLE dtc(ts REAL NOT NULL, codigo TEXT NOT NULL, status TEXT NOT NULL);
"""


class TestEsquema(unittest.TestCase):
    def setUp(self):
        self.caminho = Path(tempfile.mkdtemp()) / "b.db"

    def test_banco_novo_ja_nasce_na_versao_atual(self):
        st = Store(self.caminho)
        self.assertEqual(st.db.execute("PRAGMA user_version").fetchone()[0], VERSAO)

    def test_migra_banco_v0_sem_perder_dados(self):
        db = sqlite3.connect(self.caminho)
        db.executescript(ESQUEMA_V0)
        db.execute("INSERT INTO sample VALUES(1, 100.0, 'RPM', 800, 'rpm', 'obd')")
        db.execute("INSERT INTO sample VALUES(2, 101.0, 'RPM', 850, 'rpm', 'obd')")
        db.execute("INSERT INTO dtc VALUES(100.0, 'P0217', 'ativo')")
        db.commit()
        db.close()

        st = Store(self.caminho)
        self.assertEqual(st.db.execute("PRAGMA user_version").fetchone()[0], VERSAO)
        (sid, ini, fim, _m, origem, _d, n_amostras, _n), = st.sessoes()
        self.assertEqual((origem, ini, fim, n_amostras), ("legado", 100.0, 101.0, 2))
        self.assertEqual(st.db.execute("SELECT sessao_id FROM dtc").fetchone()[0], sid)
        self.assertEqual(st.dtcs_ativos(), ["P0217"])
        st.db.close()
        Store(self.caminho)   # abrir de novo não migra duas vezes
        self.assertEqual(len(Store(self.caminho).sessoes()), 1)

    def test_sessao_liga_amostras_e_dtcs(self):
        st = Store(self.caminho)
        sid = st.abrir_sessao("obd", "garagem")
        st.gravar("RPM", 800, "rpm")
        st.gravar_dtcs(["P0562"])
        st.fechar_sessao()
        st.gravar("RPM", 900, "rpm")             # fora de sessão
        st.commit()
        self.assertEqual(st.db.execute("SELECT COUNT(*) FROM sample WHERE sessao_id=?", (sid,)).fetchone()[0], 1)
        self.assertEqual(st.db.execute("SELECT sessao_id FROM dtc").fetchone()[0], sid)
        self.assertIsNotNone(st.sessoes()[0][2])  # fim preenchido

    def test_simulador_abre_e_fecha_sessao(self):
        st = Store(self.caminho)
        simulador.rodar("estrada", segundos=1, hz=5, aquecer_s=10, store=st, sleep=False)
        (_sid, _ini, fim, _m, origem, desc, n, _p), = st.sessoes()
        self.assertEqual((origem, desc), ("simulador", "cenário estrada"))
        self.assertIsNotNone(fim)
        self.assertGreater(n, 0)

    def test_exportar_csv(self):
        st = Store(self.caminho)
        sid = st.abrir_sessao("obd")
        st.gravar("SPEED", 42, "km/h", ts=time.time())
        st.commit()
        saida = self.caminho.with_suffix(".csv")
        self.assertEqual(st.exportar_csv(saida, sid), 1)
        with open(saida, encoding="utf-8") as f:
            linha = next(csv.DictReader(f))
        self.assertEqual((linha["pid"], float(linha["valor"]), linha["sessao_id"]), ("SPEED", 42.0, str(sid)))


class TestInteracao(unittest.TestCase):
    def test_pergunta_fica_registrada(self):
        if getattr(F._local, "store", None):
            F._local.store.db.close()
        F._local.store = None
        for s in ("", "-wal", "-shm"):
            Path(os.environ["TE251_DB"] + s).unlink(missing_ok=True)
        simulador.rodar("bateria_fraca", segundos=1, hz=5, aquecer_s=30, sleep=False)
        r = harness.perguntar("Como está a bateria?")
        row = F.store().db.execute(
            "SELECT pergunta, resposta, aprovada, sessao_id, idade_dado_s FROM interacao").fetchone()
        self.assertEqual(row[:3], ("Como está a bateria?", r["resposta"], 0))   # sem LLM: regras
        self.assertIsNotNone(row[3])
        self.assertLess(row[4], 60)


class TestMedicao(unittest.TestCase):
    def test_medir_roda_e_devolve_numeros(self):
        r = banco.medir(horas=0.01, hz=2)
        self.assertEqual(r["linhas"], int(0.01 * 3600 * 2) * 7)
        self.assertIn("historico 1 h", r["consultas_ms"])


if __name__ == "__main__":
    unittest.main()
