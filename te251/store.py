"""Banco local (SQLite em modo WAL): fonte da verdade dentro do carro.

Esquema v1 (detalhes em docs/banco.md):
    sessao     cada rodagem/teste (coletor, simulador, importação, réplica)
    sample     telemetria: uma linha por leitura de PID, ligada à sessão
    dtc        mudanças no conjunto de códigos de falha ativos
    interacao  cada pergunta feita ao harness, com resposta, fonte e ferramentas
A versão fica em PRAGMA user_version; bancos antigos (v0) são migrados ao abrir.
"""
import csv
import datetime as dt
import json
import sqlite3
import threading
import time
from te251 import config

VERSAO = 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sessao(
    id        INTEGER PRIMARY KEY,
    inicio    REAL NOT NULL,
    fim       REAL,
    modo      TEXT NOT NULL,              -- 'carro' | 'teatro'
    origem    TEXT NOT NULL,              -- 'obd' | 'simulador' | 'importacao' | 'replica' | 'legado'
    descricao TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sample(
    seq       INTEGER PRIMARY KEY,
    ts        REAL NOT NULL,
    pid       TEXT NOT NULL,
    value     REAL NOT NULL,
    unit      TEXT NOT NULL,
    fonte     TEXT NOT NULL DEFAULT 'obd',
    sessao_id INTEGER REFERENCES sessao(id)
);
CREATE INDEX IF NOT EXISTS ix_sample_pid_ts ON sample(pid, ts);
-- (pid) carrega o seq junto (é o rowid): "último valor do PID" sem varrer o histórico
CREATE INDEX IF NOT EXISTS ix_sample_pid ON sample(pid);
CREATE TABLE IF NOT EXISTS dtc(
    ts        REAL NOT NULL,
    codigo    TEXT NOT NULL,
    status    TEXT NOT NULL,              -- 'ativo' | 'limpo'
    sessao_id INTEGER REFERENCES sessao(id)
);
CREATE TABLE IF NOT EXISTS interacao(
    id           INTEGER PRIMARY KEY,
    ts           REAL NOT NULL,
    sessao_id    INTEGER REFERENCES sessao(id),   -- sessão do dado mais recente no momento da pergunta
    modo         TEXT NOT NULL,
    pergunta     TEXT NOT NULL,
    resposta     TEXT NOT NULL,
    fonte        TEXT NOT NULL,                   -- 'LLM <modelo>' ou 'regras (...)'
    aprovada     INTEGER NOT NULL,                -- 1 = resposta do LLM passou na checagem
    ferramentas  TEXT NOT NULL,                   -- JSON: [{"ferramenta":..., "args":...}]
    tempo_s      REAL NOT NULL,
    idade_dado_s REAL,                            -- idade da última amostra quando a pergunta chegou
    resposta_llm_reprovada TEXT
);
"""

# Índices e visão que dependem de sessao_id: criados depois da migração de bancos v0.
POS_MIGRACAO = """
CREATE INDEX IF NOT EXISTS ix_sample_sessao ON sample(sessao_id);
CREATE VIEW IF NOT EXISTS telemetria AS
    SELECT s.sessao_id, ss.origem, ss.descricao AS sessao,
           strftime('%Y-%m-%d %H:%M:%f', s.ts, 'unixepoch', 'localtime') AS data_hora,
           s.ts, s.pid, s.value AS valor, s.unit AS unidade, s.fonte
    FROM sample s LEFT JOIN sessao ss ON ss.id = s.sessao_id;
"""


def _colunas(db, tabela):
    return {r[1] for r in db.execute(f"PRAGMA table_info({tabela})")}


def _migrar(db):
    """Leva o banco até VERSAO sem perder dados. Idempotente."""
    versao = db.execute("PRAGMA user_version").fetchone()[0]
    if versao >= VERSAO:
        return
    with db:
        for tabela in ("sample", "dtc"):
            if "sessao_id" not in _colunas(db, tabela):
                db.execute(f"ALTER TABLE {tabela} ADD COLUMN sessao_id INTEGER REFERENCES sessao(id)")
        # dados de antes do v1 ficam numa sessão 'legado'
        ini, fim = db.execute("SELECT MIN(ts), MAX(ts) FROM sample WHERE sessao_id IS NULL").fetchone()
        if ini is not None:
            cur = db.execute("INSERT INTO sessao(inicio, fim, modo, origem, descricao) VALUES(?,?,?,?,?)",
                             (ini, fim, config.MODO, "legado", "dados gravados antes do esquema v1"))
            db.execute("UPDATE sample SET sessao_id=? WHERE sessao_id IS NULL", (cur.lastrowid,))
            db.execute("UPDATE dtc SET sessao_id=? WHERE sessao_id IS NULL", (cur.lastrowid,))
        db.execute(f"PRAGMA user_version={VERSAO}")


def conectar(caminho=None):
    db = sqlite3.connect(str(caminho or config.DB_PATH), check_same_thread=False, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(ESQUEMA)
    _migrar(db)
    db.executescript(POS_MIGRACAO)
    return db


class Store:
    def __init__(self, caminho=None):
        self.db = conectar(caminho)
        self._lock = threading.RLock()   # coletor grava numa thread e faz commit em outra
        ultimo = self.db.execute("SELECT MAX(seq) FROM sample").fetchone()[0]
        self._seq = max(int(time.time() * 1000), (ultimo or 0) + 1)
        self.sessao_id = None

    # ---------- sessões ----------
    def abrir_sessao(self, origem, descricao="", inicio=None):
        """Começa uma sessão; as próximas gravações deste Store ficam ligadas a ela."""
        with self._lock:
            cur = self.db.execute("INSERT INTO sessao(inicio, modo, origem, descricao) VALUES(?,?,?,?)",
                                  (inicio or time.time(), config.MODO, origem, descricao))
            self.db.commit()
            self.sessao_id = cur.lastrowid
            return self.sessao_id

    def fechar_sessao(self, fim=None):
        with self._lock:
            if self.sessao_id is not None:
                self.db.execute("UPDATE sessao SET fim=? WHERE id=?", (fim or time.time(), self.sessao_id))
                self.db.commit()
                self.sessao_id = None

    def sessoes(self):
        return self.db.execute(
            "SELECT ss.id, ss.inicio, ss.fim, ss.modo, ss.origem, ss.descricao, "
            "(SELECT COUNT(*) FROM sample WHERE sessao_id=ss.id), "
            "(SELECT COUNT(*) FROM interacao WHERE sessao_id=ss.id) "
            "FROM sessao ss ORDER BY ss.id").fetchall()

    # ---------- escrita (coletor / simulador) ----------
    def gravar(self, pid, valor, unidade, ts=None, fonte="obd"):
        with self._lock:
            self._seq += 1
            self.db.execute("INSERT INTO sample(seq, ts, pid, value, unit, fonte, sessao_id) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (self._seq, ts or time.time(), pid, float(valor), unidade, fonte, self.sessao_id))
            return self._seq

    def gravar_dtcs(self, codigos, ts=None):
        """Registra o conjunto atual de DTCs ativos (só grava quando muda)."""
        with self._lock:
            self._gravar_dtcs(codigos, ts or time.time())

    def _gravar_dtcs(self, codigos, ts, sessao_id=None):
        atuais = set(self.dtcs_ativos())
        novos = set(codigos)
        sid = sessao_id if sessao_id is not None else self.sessao_id
        for c in novos - atuais:
            self.db.execute("INSERT INTO dtc VALUES(?,?,?,?)", (ts, c, "ativo", sid))
        for c in atuais - novos:
            self.db.execute("INSERT INTO dtc VALUES(?,?,?,?)", (ts, c, "limpo", sid))

    def registrar_interacao(self, pergunta, r):
        """Guarda uma pergunta e o dict devolvido por harness.perguntar."""
        with self._lock:
            ult = self.db.execute("SELECT ts, sessao_id FROM sample ORDER BY seq DESC LIMIT 1").fetchone()
            agora = time.time()
            self.db.execute(
                "INSERT INTO interacao(ts, sessao_id, modo, pergunta, resposta, fonte, aprovada, ferramentas, "
                "tempo_s, idade_dado_s, resposta_llm_reprovada) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (agora, ult[1] if ult else None, config.MODO, pergunta, r["resposta"], r["fonte"],
                 int(r["fonte"].startswith("LLM")), json.dumps(r["ferramentas"], ensure_ascii=False),
                 r["tempo_s"], round(agora - ult[0], 1) if ult else None, r.get("resposta_llm_reprovada")))
            self.db.commit()

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
        # pula de PID em PID pelo índice em vez de varrer todas as amostras (DISTINCT)
        return [r[0] for r in self.db.execute(
            "WITH RECURSIVE p(pid) AS (SELECT MIN(pid) FROM sample UNION ALL "
            "SELECT (SELECT MIN(pid) FROM sample WHERE pid > p.pid) FROM p WHERE p.pid IS NOT NULL) "
            "SELECT pid FROM p WHERE pid IS NOT NULL")]

    # ---------- exportação ----------
    def exportar_csv(self, destino, sessao_id=None):
        """Telemetria em CSV, uma linha por leitura (todas as sessões ou uma). Devolve o nº de linhas."""
        sql = "SELECT sessao_id, data_hora, ts, pid, valor, unidade, fonte FROM telemetria"
        args = ()
        if sessao_id is not None:
            sql += " WHERE sessao_id=?"
            args = (sessao_id,)
        n = 0
        with open(destino, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sessao_id", "data_hora", "ts", "pid", "valor", "unidade", "fonte"])
            for row in self.db.execute(sql + " ORDER BY ts", args):
                w.writerow(row)
                n += 1
        return n


def data_hora(ts):
    return "-" if ts is None else dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")
