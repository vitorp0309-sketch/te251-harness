"""Servidor web do harness (só biblioteca padrão).

Uso: python -m te251.web     ->  http://localhost:8090  (na sala: http://<ip-do-notebook>:8090)
Rotas: GET /  (painel + chat) · GET /estado (JSON) · POST /ask {"pergunta": "..."}
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from te251 import config
from te251 import ferramentas as F
from te251.harness import ollama_no_ar, perguntar

PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TE-251 · harness</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}
header{padding:12px 16px;background:#1d2733;font-weight:600}
main{display:grid;grid-template-columns:minmax(260px,1fr) 2fr;gap:16px;padding:16px}
@media(max-width:800px){main{grid-template-columns:1fr}}
.card{background:#1b1b1b;border-radius:8px;padding:12px}
.pid{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #2a2a2a}
.v{font-size:1.3em;font-variant-numeric:tabular-nums}.alerta{color:#ff7a59}.ok{color:#7bd88f}
#log{height:55vh;overflow:auto}.eu{color:#9ecbff;margin:10px 0 2px}.ia{margin:2px 0 10px}
.meta{color:#888;font-size:.8em}form{display:flex;gap:8px;margin-top:8px}
input{flex:1;padding:10px;border-radius:6px;border:0;font-size:1em}button{padding:10px 16px;border:0;border-radius:6px}
</style></head><body>
<header>PROJETO TE-251 · SW4 · harness local <span id="llm" class="meta"></span></header>
<main><section class="card"><div id="pids">carregando…</div><div id="dtcs" style="margin-top:10px"></div></section>
<section class="card"><div id="log"></div>
<form id="f"><input id="q" placeholder="Pergunte sobre o carro…" autocomplete="off"><button>Enviar</button></form></section></main>
<script>
const fmt=v=>typeof v==='number'?v.toLocaleString('pt-BR',{maximumFractionDigits:1}):v;
async function estado(){try{const r=await fetch('/estado');const e=await r.json();
 document.getElementById('llm').textContent=e.llm;
 document.getElementById('pids').innerHTML=Object.entries(e.pids).map(([k,p])=>p.erro?
  `<div class="pid"><span>${k}</span><span class="meta">${p.erro}</span></div>`:
  `<div class="pid"><span>${p.descricao}</span><span class="v ${p.situacao==='normal'?'ok':'alerta'}">${fmt(p.valor)} ${p.unidade}</span></div>`).join('');
 document.getElementById('dtcs').innerHTML=e.dtcs.quantidade?e.dtcs.codigos.map(c=>`<div class="alerta">${c.codigo} · ${c.descricao}</div>`).join(''):'<span class="ok">Sem códigos de falha</span>';
}catch(_){}}
setInterval(estado,1000);estado();
const log=document.getElementById('log');
document.getElementById('f').onsubmit=async ev=>{ev.preventDefault();const q=document.getElementById('q');const p=q.value.trim();if(!p)return;q.value='';
 log.insertAdjacentHTML('beforeend',`<div class="eu">Você: ${p.replace(/</g,'&lt;')}</div>`);
 const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pergunta:p})});const j=await r.json();
 log.insertAdjacentHTML('beforeend',`<div class="ia">${j.resposta.replace(/</g,'&lt;')}<div class="meta">${j.fonte} · ${j.ferramentas.map(f=>f.ferramenta).join(', ')||'-'} · ${j.tempo_s} s</div></div>`);
 log.scrollTop=log.scrollHeight;};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        dados = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path == "/":
            dados = PAGINA.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
        elif self.path == "/estado":
            self._json({"pids": F.get_vehicle_state(None), "dtcs": F.get_dtcs(),
                        "coleta": F.get_link_status(),
                        "llm": f"{config.MODELO} " + ("no ar" if ollama_no_ar() else "indisponível (regras)")})
        else:
            self._json({"erro": "rota não encontrada"}, 404)

    def do_POST(self):
        if self.path != "/ask":
            return self._json({"erro": "rota não encontrada"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            pergunta = json.loads(self.rfile.read(n) or b"{}").get("pergunta", "").strip()
        except ValueError:
            return self._json({"erro": "JSON inválido"}, 400)
        if not pergunta:
            return self._json({"erro": "campo 'pergunta' vazio"}, 400)
        self._json(perguntar(pergunta))

    def log_message(self, *a):
        pass


def main():
    srv = ThreadingHTTPServer((config.WEB_HOST, config.WEB_PORTA), Handler)
    print(f"TE-251 web em http://localhost:{config.WEB_PORTA}  (Ctrl+C para parar)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
