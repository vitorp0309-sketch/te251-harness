"""Configuração do TE-251. Tudo pode ser trocado por variável de ambiente."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# "carro" = banco escrito pelo coletor (dado ao vivo); "teatro" = réplica recebida por MQTT
MODO = os.environ.get("TE251_MODO", "carro").lower()

DB_PATH = Path(os.environ.get("TE251_DB", RAIZ / "te251.db"))
KB_DIR = Path(os.environ.get("TE251_KB", RAIZ / "kb"))

# LLM local (Ollama). Nada de nuvem: o endereço padrão é a própria máquina.
OLLAMA_URL = os.environ.get("TE251_OLLAMA_URL", "http://127.0.0.1:11434")
MODELO = os.environ.get("TE251_MODELO", "qwen2.5:7b")   # GPU de 6 GB: qwen2.5:3b
TEMPERATURA = 0.2
MAX_RODADAS = 6           # máximo de idas e vindas LLM <-> ferramentas por pergunta

# Enlace MQTT. O broker fica no computador da sala (ver docs/rede-tailscale.md);
# o carro o alcança pelo nome/IP dele na VPN Tailscale.
BROKER = os.environ.get("TE251_BROKER", "127.0.0.1")
BROKER_PORTA = int(os.environ.get("TE251_BROKER_PORTA", "1883"))
MQTT_USUARIO = os.environ.get("TE251_MQTT_USUARIO") or None   # vazio = broker sem senha
MQTT_SENHA = os.environ.get("TE251_MQTT_SENHA") or None

WEB_HOST = os.environ.get("TE251_HOST", "0.0.0.0")
WEB_PORTA = int(os.environ.get("TE251_PORTA", "8090"))

# Veículo
TANQUE_L = 80.0           # SW4 — confirmar no manual da unidade
KM_L_PADRAO = 9.5         # consumo médio inicial; calibrar com rodagens reais
RESERVA_PCT = 10.0

# Dado mais velho que isso é tratado como "desatualizado".
# No teatro a folga é maior: a réplica atravessa o 4G do carro.
IDADE_MAX_S = float(os.environ.get("TE251_IDADE_MAX_S", 5.0 if MODO == "carro" else 15.0))

# PIDs: nome do python-OBD -> (descrição, unidade, faixa física, faixa normal)
PIDS = {
    "RPM":                    ("Rotação do motor",          "rpm", (0, 5000),  (600, 4000)),
    "SPEED":                  ("Velocidade",                "km/h", (0, 200),  (0, 120)),
    "COOLANT_TEMP":           ("Temperatura do líquido de arrefecimento", "°C", (-40, 130), (80, 105)),
    "ENGINE_LOAD":            ("Carga calculada do motor",  "%",   (0, 100),   (0, 90)),
    "INTAKE_PRESSURE":        ("Pressão no coletor (MAP)",  "kPa", (0, 255),   (90, 230)),
    "CONTROL_MODULE_VOLTAGE": ("Tensão do módulo/bateria",  "V",   (9, 16),    (12.4, 14.8)),
    "FUEL_LEVEL":             ("Nível de combustível",      "%",   (0, 100),   (15, 100)),
}
