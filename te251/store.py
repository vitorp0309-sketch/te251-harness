"""Banco local (SQLite em modo WAL): fonte da verdade dentro do carro."""
import sqlite3
import threading
import time
from te251 import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sample(
    seq   INTEGER PRIMARY KEY,
    ts    REAL NOT NULL,
    pid   TEXT NOT NULL,
    value REAL NOT NULL,
    unit  TEXT NOT NULL,
    fonte TEXT NOT NULL DEFAULT 'obd'
);
CREATE INDEX IF NOT EXISTS ix_sample_pid_ts ON sample(pid, ts);
CREATE TABLE IF NOT EXISTS dtc(
    ts     REAL NOT NULL,
    codigo TEXT NOT NULL,
    status TEXT NOT NULL            -- 'ativo' | 'limpo'
);
"""


def conectar(caminho=None):
    db = sqlite3.connect(str(caminho or config.DB_PATH), check_same_thread=False, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(ESQUEMA)
    return db


class Store:
    def __init__(self, caminho=None):
        self.db = conectar(caminho)
        self._lock = threading.RLock()   # coletor grava numa thread e faz commit em outra
        ultimo = self.db.execute("SELECT MAX(seq) FROM sample").fetchone()[0]
        self._seq = max(int(time.time() * 1000), (ultimo or 0) + 1)

    # ---------- escrita (coletor / simulador) ----------
    def gravar(self, pid, valor, unidade, ts=None, fonte="obd"):
        with self._lock:
            self._seq += 1
            self.db.execute("INSERT INTO sample VALUES(?,?,?,?,?,?)",
                            (self._seq, ts or time.time(), pid, float(valor), unidade, fonte))
            return self._seq

    def gravar_dtcs(self, codigos, ts=None):
        """Registra o conjunto atual de DTCs ativos (só grava quando muda)."""
        with self._lock:
            self._gravar_dtcs(codigos, ts or time.time())

    def _gravar_dtcs(self, codigos, ts):
        atuais = set(self.dtcs_ativos())
        novos = set(codigos)
        for c in novos - atuais:
            self.db.execute("INSERT INTO dtc VALUES(?,?,?)", (ts, c, "ativo"))
        for c in atuais - novos:
            self.db.execute("INSERT INTO dtc VALUES(?,?,?)", (ts, c, "limpo"))

    def commit(self):
        with self._lock:
            self.db.commit()

    # ---------- leitura (ferramentas do harness) ----------
    def ultimo(self, pid):
        row = self.db.execute(
            "SELECT value, unit, ts, fonte FROM sample WHERE pid=? ORDER BY seq DESC LIMIT 1",
            (pid,)).fetchone()
        if not row:
            return None
        return {"valor": row[0], "unidade": row[1], "ts": row[2], "fonte": row[3]}

    def historico(self, pid, janela_s):
        desde = time.time() - janela_s
        return self.db.execute(
            "SELECT ts, value FROM sample WHERE pid=? AND ts>=? ORDER BY ts", (pid, desde)).fetchall()

    def dtcs_ativos(self):
        rows = self.db.execute(
            "SELECT codigo, status FROM dtc d WHERE ts = (SELECT MAX(ts) FROM dtc WHERE codigo=d.codigo)"
        ).fetchall()
        return sorted(c for c, s in rows if s == "ativo")

    def ultima_amostra_ts(self):
        return self.db.execute("SELECT MAX(ts) FROM sample").fetchone()[0]

    def pids_disponiveis(self):
        return [r[0] for r in self.db.execute("SELECT DISTINCT pid FROM sample ORDER BY pid")]
