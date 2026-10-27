# TE-251 — Análise de viabilidade: LLM + OBD2 na SW4 com harness remoto

Base: diagrama "Arquitetura de Hardware" (WhatsApp Image 2026-10-16 at 20.47.42.jpeg) e a mensagem do Vitor de 16/10/2026.

## Resumo (TL;DR)

O plano é **viável**, com três ajustes que evitam falha crítica:

1. **Junte "Computador Local" e "LLM Engine" num único notebook** (ou tire a LLM do carro, ver seção 2). Duas máquinas ligadas por Ethernet dentro do carro dobram os pontos de falha sem ganho nenhum. PS5 está fora.
2. **Não use VPN tradicional.** Internet de celular (4G) fica atrás de CGNAT, então ninguém consegue "entrar" na rede do carro. Use **Tailscale** (ou ZeroTier), que atravessa CGNAT sem configurar nada, ou faça o carro só **enviar** dados para fora (MQTT/HTTP na nuvem).
3. **O núcleo é tool calling, não RAG.** Dado ao vivo do carro entra na LLM como resultado de uma ferramenta (`get_vehicle_data`), não por "treino". RAG só serve para documentos fixos (manual da SW4, tabela de códigos de falha).

Os maiores riscos não são de rede nem de LLM, são de **dado**: a SW4 pode **não informar nível de combustível pelo OBD2 padrão**, e **ocupação dos bancos não existe no OBD2** (e os bancos traseiros da SW4 nem têm sensor). Isso precisa ser testado no carro **antes** de qualquer outra coisa (script na seção 8).

---

## 1. O conector OBD2 Bluetooth dá pra ler com Python?

O link do conector não chegou junto com a mensagem nem está na pasta, então cobri os três tipos que existem no mercado. **Mande o link (ou a foto da etiqueta) que eu confirmo qual é.**

Quase todo conector barato é um **ELM327** (ou clone). A biblioteca padrão é a **python-OBD** (`pip install obd`), que fala com ELM327 por porta serial.

| Tipo de conector | Como aparece no notebook | Python funciona? |
|---|---|---|
| **Bluetooth Clássico (SPP)** — a maioria dos ELM327 azuis/pretos, pareia com PIN 1234/0000 | Depois de parear no Windows, vira uma **porta COM** (ex. COM5) | **Sim, direto.** `obd.OBD("COM5")` |
| **Bluetooth Low Energy (BLE)** — os que dizem "compatível com iPhone" (Vgate iCar Pro BLE, Veepeak BLE, etc.) | **Não** vira porta COM | **Sim, mas dá trabalho.** python-OBD não fala BLE; precisa da lib `bleak` e de um adaptador próprio. Evite se puder |
| **Wi-Fi** | Rede Wi-Fi própria (192.168.0.10:35000) | Sim, via socket TCP. Ruim porque o notebook perde a internet do celular |

Riscos do conector:
- **Clones "v2.1"** costumam ter firmware bugado (comandos faltando, travam). Se der problema, um **ELM327 v1.5** ou um **OBDLink MX+/LX** (mais caro, muito mais estável) resolvem.
- Taxa real: um ELM327 em Bluetooth lê uns **5 a 15 PIDs por segundo** no total. Para responder perguntas é mais que suficiente; para "gráfico em tempo real de 20 sensores" não.
- O conector fica alimentado pela bateria do carro mesmo desligado. Tire depois dos testes.

**Veredito:** se for Bluetooth Clássico, sim, numa boa. Se for BLE, dá, mas é a primeira coisa a resolver.

## 2. Onde rodar a LLM: embarcada, PS5 ou notebook?

- **PS5: descartado.** É um console fechado, não roda código próprio (nem Python, nem servidor de LLM). Não existe caminho legítimo para isso.
- **Notebook no carro (LLM local):** funciona com **Ollama** + modelo pequeno com suporte a tool calling (ex. Qwen 2.5 3B/7B, Llama 3.2 3B, quantizados). Limites:
  - Sem GPU dedicada, um modelo 3B roda a uns 5–15 tokens/s em CPU; um 7B precisa de ~8 GB de RAM livres e fica lento. **Quais são as specs do notebook "sobrando"?** Isso decide se a LLM local é viável.
  - Modelos pequenos erram mais em tool calling e em contas (autonomia, rota).
  - Alimentação: notebook + LLM puxando CPU no talo drena bateria rápido. Precisa de inversor 12V ou carregador USB-C PD veicular.
- **LLM fora do carro (recomendado se o enunciado permitir):** o carro só roda um coletor Python leve que expõe os dados; a LLM roda **na sala** (num PC melhor, com Ollama) **ou numa API na nuvem** (Claude, GPT, Gemini). Fica mais rápido, mais inteligente e o carro só precisa mandar alguns KB de telemetria.

**Recomendação:**
- Se o trabalho **exige LLM embarcada** (edge AI é o ponto da disciplina): **um notebook só no carro** fazendo coleta OBD2 + Ollama, e uma API na nuvem como plano B se o modelo local ficar ruim.
- Se **não exige**: notebook no carro só como coletor; LLM e harness na sala. É a arquitetura com menor risco de falha na apresentação.

## 3. Internet roteando o celular funciona?

**Sim**, a telemetria é minúscula (KB/s) e a latência do 4G (50–150 ms) é irrelevante perto do tempo de resposta da LLM. Cuidados:

- **CGNAT:** a operadora não dá IP público ao celular, então **nenhuma conexão de fora consegue entrar** no carro. Isso derruba VPN tradicional e "abrir porta" (ver seção 4). A solução é sempre o carro iniciar a conexão.
- **Prefira ancoragem USB** em vez do hotspot Wi-Fi: mais estável, não depende do Wi-Fi do notebook (que pode estar ocupado/brigar com o Bluetooth) e carrega o celular. Obs.: o diagrama mostra "Ethernet" até o roteador celular; celular não tem Ethernet, vai ser USB ou Wi-Fi.
- Android/iOS desligam o hotspot sozinhos quando acham que ninguém está usando, e o celular esquenta no painel. Desative a economia de energia do hotspot.
- **Cobertura:** em estrada o 4G cai. O sistema tem que lidar com isso (seção 5).
- Alternativa mais robusta: um modem 4G USB ou roteador MiFi com chip dedicado.

## 4. VPN entre a sala e a rede do carro funciona?

- **VPN tradicional (OpenVPN/WireGuard puro): não, do jeito que está no diagrama.** Precisa de um lado com IP público e porta aberta. O 4G não tem (CGNAT) e a rede da faculdade provavelmente também não deixa.
- **Tailscale (ou ZeroTier): sim, e é o caminho recomendado.** É WireGuard em malha, gratuito para uso pessoal, instala nos dois computadores, faz login com a mesma conta e pronto: o notebook do carro ganha um IP fixo tipo `100.x.y.z` que o PC da sala acessa direto, mesmo atrás de CGNAT. Se a rede bloquear UDP, ele cai para relay via HTTPS (porta 443), mais lento mas funciona.
- **Risco:** firewall da rede da faculdade. Mitigação: testar da sala antes; o diagrama já prevê 4G na GCS, então o PC da sala pode usar outro celular.
- **Alternativa sem VPN:** o carro publica telemetria num broker **MQTT** na nuvem (HiveMQ Cloud ou EMQX, têm plano grátis) e a sala assina. Ou expor a API do carro com **Cloudflare Tunnel**. Ambos funcionam porque o carro só faz conexão de saída.

## 5. O harness falando com a LLM pela internet dá certo?

**Dá.** A rede adiciona centenas de milissegundos; a LLM leva segundos. O que precisa ser projetado:

- **Toda leitura com timestamp.** A ferramenta devolve `{"valor": ..., "lido_em": "...", "idade_s": 3}` para a LLM poder dizer "há 3 segundos o tanque estava em X" ou "estou sem dado novo há 2 minutos".
- **Queda de conexão:** guardar o último valor conhecido e responder com ele + aviso, em vez de travar.
- **Demo com plano B:** gravar uma sessão de dados reais num SQLite durante um teste e ter um modo "replay" para a apresentação, caso o 4G caia na hora. Isso é o seguro mais barato contra falha crítica.

## 6. Como o dado do carro chega na LLM?

Sim, é obrigatório ter um PC (o notebook) no carro: é ele que faz a ponte. O fluxo:

```
ECU da SW4 ──CAN (ISO 15765-4, 500 kbps)──> Porta OBD2
   └─> ELM327 ──Bluetooth SPP──> Notebook (porta COM)
         └─> Coletor Python (python-OBD, modo async: lê PIDs em loop)
               ├─> Estado atual em memória + log em SQLite
               └─> API local (FastAPI): GET /telemetria, GET /dtc
                     └─(Tailscale / 4G)─> Harness na sala
                           └─> LLM com tool calling:
                                 usuário pergunta → LLM chama get_vehicle_data(["combustivel"])
                                 → harness consulta a API do carro → devolve JSON
                                 → LLM responde em texto, com base no dado
```

Pontos importantes:
- **A LLM nunca lê o OBD2 diretamente**, e não é "treinada" com os dados. Ela recebe o JSON da ferramenta no momento da pergunta. Isso é o grounding.
- Ferramentas sugeridas:
  - `get_vehicle_data(campos)` → RPM, velocidade, temperatura do motor, carga, combustível (se existir), tensão da bateria…
  - `get_dtc()` → códigos de falha ativos (Modo 03) + descrição
  - `plan_route(destino)` → chama uma API de rotas (OSRM é grátis; Google/Mapbox também) para distância, e o código calcula autonomia = litros restantes × consumo médio. **Faça a conta no Python, não peça para a LLM fazer conta.**
- **Só leitura.** Não exponha comando de apagar falhas (Modo 04) nem nada que escreva na ECU como ferramenta da LLM.
- Onde a LLM roda muda só onde fica o harness/tool calling; o coletor e a API do carro são iguais nos dois cenários da seção 2.

## 7. RAG é necessário? ("treinar a RAG")

- **RAG não se treina**: você indexa documentos (gera embeddings) e busca trechos na hora da pergunta. Fine-tuning também **não** é necessário.
- **Para dado ao vivo, RAG é a ferramenta errada.** Indexar telemetria em vetor gera respostas com dado velho. Tool calling resolve melhor e é mais simples.
- **RAG faz sentido para conteúdo fixo**: manual do proprietário da SW4, tabela de códigos DTC, ficha técnica (tanque de 80 L, consumo de referência, pressão de pneus). Exemplo: "a luz de injeção acendeu, o que é P0299?" → `get_dtc()` + RAG no manual/tabela.
- **Recomendação:** tool calling é o núcleo obrigatório; um RAG pequeno com o manual é um bônus barato que enriquece a apresentação. Se o tempo apertar, corte o RAG, não o tool calling.

## 8. Riscos de falha crítica

| # | Risco | Gravidade | O que fazer |
|---|---|---|---|
| 1 | **Nível de combustível não sai no OBD2 padrão.** O PID 0x2F (Fuel Tank Level) é opcional e várias Toyotas, incluindo Hilux/SW4 diesel, frequentemente não o informam | **Alta** (é o exemplo principal do trabalho) | Rodar o script abaixo no carro já. Se não tiver: tentar PIDs proprietários Toyota (Modo 21/22 no módulo do painel; a comunidade do app Torque tem listas), ou estimar pelo consumo, ou informar manualmente o nível inicial |
| 2 | **"Quantas pessoas no carro" pelos sensores dos bancos não é viável pelo OBD2.** Não existe PID padrão para isso. A SW4 tem no máximo detecção de passageiro dianteiro (airbag) e status de cinto, que ficam em módulos de carroceria/airbag acessíveis só por PIDs proprietários (se acessíveis). Bancos traseiros não têm sensor de presença | **Alta** | Tirar do escopo, **ou** substituir por status dos cintos via PID proprietário (experimental), **ou** uma webcam no notebook com detecção de pessoas (YOLO). A webcam é a alternativa mais demonstrável |
| 3 | Conector BLE ou clone bugado | Média | Identificar o modelo (mande o link); ter um ELM327 v1.5 ou OBDLink de reserva |
| 4 | Sem conexão de entrada no carro (CGNAT) | Alta se usar VPN tradicional | Tailscale ou MQTT na nuvem (seção 4) |
| 5 | 4G cai durante a demo | Média | Modo replay com dados gravados + último valor conhecido |
| 6 | Notebook sem bateria/superaquecendo | Média | Inversor ou carregador veicular; LLM fora do carro se o notebook for fraco |
| 7 | Consumo/autonomia imprecisos no diesel | Baixa | O OBD2 padrão não dá vazão de combustível em muitos diesel; usar consumo médio de referência e deixar claro que é estimativa |
| 8 | Segurança no trânsito | — | Quem dirige não mexe no notebook; dados só de leitura |

Dados que o OBD2 padrão normalmente entrega bem (confirmar com o script): RPM, velocidade, temperatura do líquido de arrefecimento, temperatura do ar de admissão, pressão do coletor (MAP), carga do motor, posição do acelerador, pressão do rail (diesel), códigos de falha, distância desde que as falhas foram apagadas, tensão da bateria (comando `ATRV` do ELM327).

### Primeiro teste (fazer antes de tudo, com o carro ligado e parado)

```python
# pip install obd
import obd

conn = obd.OBD("COM5")  # troque pela porta COM do conector pareado; obd.OBD() tenta achar sozinho
print("Status:", conn.status(), "| Protocolo:", conn.protocol_name())

suportados = sorted(c.name for c in conn.supported_commands)
print(f"{len(suportados)} comandos suportados:")
for nome in suportados:
    print(" ", nome)

for cmd in ["FUEL_LEVEL", "RPM", "SPEED", "COOLANT_TEMP", "ENGINE_LOAD"]:
    r = conn.query(obd.commands[cmd])
    print(cmd, "->", r.value)

print("Bateria:", conn.query(obd.commands.ELM_VOLTAGE).value)
print("Falhas:", conn.query(obd.commands.GET_DTC).value)
```

Se `FUEL_LEVEL` aparecer na lista e retornar um valor, o risco #1 some. Salve a saída e mande aqui.

## 9. Arquitetura revisada sugerida

```
SW4                                         Sala de aula (GCS)
┌─────────────────────────────────┐         ┌──────────────────────────────┐
│ ECU ─OBD2─> ELM327 ─BT─┐        │         │ PC da sala                   │
│                        v        │         │  Harness (CLI/web)           │
│  Notebook único                 │         │   └─ LLM com tool calling    │
│   ├ Coletor Python + SQLite     │ Tailscale│      (local, nuvem ou       │
│   ├ API FastAPI (/telemetria)   │<───────>│       chamando a do carro)   │
│   └ [opcional] Ollama (LLM)     │  4G     │  RAG pequeno: manual SW4     │
│        │ USB tethering          │         └──────────────────────────────┘
│     Celular 4G                  │
└─────────────────────────────────┘
```

## 10. Ordem sugerida de execução

1. Identificar o conector e rodar o script do item 8 no carro (decide o escopo real).
2. Coletor Python + API local, testado com o notebook no carro.
3. Tailscale nos dois PCs, acessar a API do carro a partir da sala via 4G.
4. Harness com tool calling (começar com uma LLM na nuvem, que é mais fácil; migrar para local se for requisito).
5. Gravação + modo replay.
6. Bônus: RAG com o manual, rota com OSRM, webcam para contar pessoas.

## Pendências para fechar a análise

- Link/modelo do conector OBD2.
- Specs do notebook (CPU, RAM, GPU).
- Ano/motor da SW4 (2.8 diesel ou 2.7 flex muda o que o OBD2 entrega).
- O enunciado de TE-251 exige que a LLM rode embarcada no carro?
