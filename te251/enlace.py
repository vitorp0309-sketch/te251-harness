"""Enlace carro <-> teatro por MQTT.

No carro:   python -m te251.enlace publicar --broker <ip-do-broker>
No teatro:  python -m te251.enlace replicar --broker <ip-do-broker>

A fila é o próprio SQLite: o publicador guarda até onde já enviou (tabela `envio`)
e retoma do ponto exato quando o enlace volta. Nada se perde num corte.
A réplica ignora amostras repetidas, porque `seq` é chave primária.
"""
import argparse
import json
import time

from te251 import config
from te251.store import Store

TOPICO_TELEMETRIA = "te251/telemetry"
TOPICO_DTC = "te251/dtc"
TOPICO_HEARTBEAT = "te251/status"


def _cliente(nome, broker, porta, limpar_sessao=False):
    import paho.mqtt.client as mqtt
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=nome, clean_session=limpar_sessao)
    c.reconnect_delay_set(min_delay=1, max_delay=30)
    c.connect_async(broker, porta, keepalive=30)
    return c


def _esperar_conexao(cli, segundos=5):
    fim = time.time() + segundos
    while time.time() < fim:
        if cli.is_connected():
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- carro
def publicar(broker, porta=1883, lote=500, intervalo=1.0, store=None, ciclos=None):
    st = store or Store()
    st.db.execute("CREATE TABLE IF NOT EXISTS envio(id INTEGER PRIMARY KEY CHECK(id=1), ate_seq INTEGER)")
    st.db.execute("INSERT OR IGNORE INTO envio VALUES(1, 0)")
    st.commit()
    cli = _cliente("te251-carro", broker, porta)
    cli.loop_start()
    n = 0
    try:
        while ciclos is None or n < ciclos:
            n += 1
            if not _esperar_conexao(cli, 5):      # enlace fora do ar: tenta no próximo ciclo
                time.sleep(intervalo)
                continue
            ate = st.db.execute("SELECT ate_seq FROM envio").fetchone()[0]
            linhas = st.db.execute(
                "SELECT seq, ts, pid, value, unit FROM sample WHERE seq>? ORDER BY seq LIMIT ?",
                (ate, lote)).fetchall()
            enviadas = 0
            for seq, ts, pid, valor, unidade in linhas:
                msg = cli.publish(f"{TOPICO_TELEMETRIA}/{pid}",
                                  json.dumps({"seq": seq, "ts": ts, "pid": pid, "v": valor, "u": unidade}),
                                  qos=1)
                if msg.rc != 0:          # desconectado: para aqui e tenta de novo no próximo ciclo
                    break
                try:                     # só avança a marca depois que o broker confirmou (QoS 1)
                    msg.wait_for_publish(timeout=5)
                except (ValueError, RuntimeError):
                    break
                if not msg.is_published():
                    break
                ate, enviadas = seq, enviadas + 1
            if enviadas:
                st.db.execute("UPDATE envio SET ate_seq=?", (ate,))
                st.commit()
            dtcs = st.dtcs_ativos()
            cli.publish(TOPICO_DTC, json.dumps({"ts": time.time(), "dtcs": dtcs}), qos=1, retain=True)
            cli.publish(TOPICO_HEARTBEAT, json.dumps({"ts": time.time(), "pendentes": len(linhas) - enviadas}),
                        qos=0)
            if ciclos is None or n < ciclos:
                time.sleep(intervalo)
    except KeyboardInterrupt:
        pass
    finally:
        cli.loop_stop()
        cli.disconnect()
    return st


# ---------------------------------------------------------------- teatro
def replicar(broker, porta=1883, store=None, segundos=None):
    st = store or Store()

    def ao_conectar(cli, *_):
        cli.subscribe([(f"{TOPICO_TELEMETRIA}/#", 1), (TOPICO_DTC, 1)])

    def ao_receber(cli, _u, msg):
        try:
            d = json.loads(msg.payload)
        except ValueError:
            return
        with st._lock:
            if msg.topic == TOPICO_DTC:
                st._gravar_dtcs(d.get("dtcs", []), d.get("ts", time.time()))
            else:
                st.db.execute("INSERT OR IGNORE INTO sample VALUES(?,?,?,?,?,?)",
                              (d["seq"], d["ts"], d["pid"], d["v"], d["u"], "replica"))

    cli = _cliente("te251-teatro", broker, porta)
    cli.on_connect = ao_conectar
    cli.on_message = ao_receber
    cli.loop_start()
    _esperar_conexao(cli, 5)
    t0 = time.time()
    try:
        while segundos is None or time.time() - t0 < segundos:
            time.sleep(0.5)
            st.commit()
    except KeyboardInterrupt:
        pass
    finally:
        cli.loop_stop()
        cli.disconnect()
        st.commit()
    return st


def main():
    ap = argparse.ArgumentParser(description="Enlace MQTT do TE-251")
    ap.add_argument("papel", choices=["publicar", "replicar"])
    ap.add_argument("--broker", default="127.0.0.1", help="endereço do broker MQTT (Tailscale/LAN)")
    ap.add_argument("--porta", type=int, default=1883)
    a = ap.parse_args()
    print(f"{a.papel} · broker {a.broker}:{a.porta} · banco {config.DB_PATH}  (Ctrl+C para parar)")
    (publicar if a.papel == "publicar" else replicar)(a.broker, a.porta)


if __name__ == "__main__":
    main()
