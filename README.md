# TE-251 · harness local da SW4 (v0.2)

Projeto da disciplina TE-251 (ITA): um LLM **local** responde, em tempo real, perguntas sobre uma Toyota SW4 a partir da telemetria OBD2, com uma réplica no Teatro Weiss para a turma. Arquitetura idealizada por Guilherme Thiago de Souza.

## Arquitetura adotada: A5 (tandem stand-alone)

| | Notebook do carro (GPU) | Computador do teatro (GPU, banda larga) |
| --- | --- | --- |
| Dados | coletor OBD2 grava no SQLite (dono do banco) | réplica do SQLite recebida por MQTT |
| IA | harness + Ollama (mesmo GGUF) | harness + Ollama (mesmo GGUF) |
| Quem usa | equipe no carro (o motorista não usa a IA) | turma na sala, pelo telão/navegador |
| Se o enlace cair | segue respondendo ao vivo | responde com o último estado e **sempre informa a idade do dado** |

- Enlace: carro sobe por 4G; VPN **ZeroTier** (rede `TE251-VPN`, administrada pelo Willian), que atravessa o CGNAT da operadora. O broker MQTT fica no computador da sala. A internet só transporta dados. Detalhes, IPs e roteiro de teste no 4G em [`docs/rede-zerotier.md`](docs/rede-zerotier.md).
- Restrições: IA 100% local (nada de nuvem), barramento OBD2 **somente leitura**, SQLite como banco (CSV só para exportação).
- Documentos de análise em [`docs/`](docs/): viabilidade, arquitetura explicada, paralelo com o RAG RIPEAM, comparativo e simulador (HTML).

## Fluxo de trabalho

Todo o desenvolvimento passa por este repositório: cada mudança entra por um branch e um pull request na `main`.

---

Harness da SW4 com **um harness completo de cada lado**: no notebook do carro e no computador do teatro. Cada lado tem banco, ferramentas, LLM local (Ollama) e página web próprios, e continua respondendo quando o enlace cai. Nada de IA em nuvem: a internet só transporta a telemetria.

Esta versão funciona **sem o carro**: um simulador grava dados realistas no mesmo banco que o coletor OBD2 real vai usar. Também funciona **sem LLM**: se o Ollama não estiver no ar, as respostas saem por regras fixas.

## Como funciona

```
         CARRO (TE251_MODO=carro)                 │            TEATRO (TE251_MODO=teatro)
                                                  │
coletor.py (OBD2) ─┐                              │
                   ├─> te251.db ─> enlace.py ──── MQTT ────> enlace.py ─> te251.db (réplica)
simulador.py ──────┘      │        (publicar)     │          (replicar)        │
                          │                       │                            │
                    ferramentas.py                │                      ferramentas.py
                          │                       │                            │
                   harness.py <─> Ollama          │               harness.py <─> Ollama
                          │                       │                            │
                   chat.py · web.py               │                    chat.py · web.py (telão)
```

Os dois lados rodam **o mesmo código**. A variável `TE251_MODO` diz de onde vêm os dados:

| | `carro` | `teatro` |
| --- | --- | --- |
| Banco | escrito pelo coletor (ao vivo) | réplica recebida por MQTT |
| Idade aceitável do dado | 5 s | 15 s |
| Resposta | fala do estado atual | sempre diz há quanto tempo o dado foi lido |
| Enlace cai | segue respondendo ao vivo | responde com o último estado recebido, avisando |

1. O **coletor** (ou o simulador) grava cada leitura no `te251.db` com hora e número de sequência.
1b. O **enlace** (`enlace.py`) publica essas leituras por MQTT e guarda até onde já enviou. Se o 4G cair, o carro continua gravando; quando o enlace volta, o envio retoma do ponto exato. No teatro, a réplica ignora o que já recebeu.
2. As **ferramentas** são funções Python que consultam o banco. São a única fonte de números.
3. O **harness** manda a pergunta ao LLM junto com a lista de ferramentas. O LLM pede as ferramentas, o harness executa e devolve os resultados, e o LLM escreve a resposta.
4. A **checagem** (`guardrails.py`) confere se todo número da resposta veio de uma ferramenta. Se o LLM inventar um número, a resposta é descartada e entra a resposta por regras (`regras.py`).

| Ferramenta | Devolve |
| --- | --- |
| `get_vehicle_state(pids)` | último valor, unidade, idade em segundos e situação (normal / acima / abaixo) |
| `get_history(pid, janela_s)` | mínimo, máximo, média e tendência |
| `get_dtcs()` | códigos de falha ativos com descrição e orientação |
| `fuel_range()` | nível, alcance estimado e ponto de não retorno |
| `search_kb(consulta)` | trechos da pasta `kb/` (manuais, DTCs, limites) |
| `get_link_status()` | se o coletor está gravando e a idade do último dado |

## Instalação (Windows ou Linux)

Requer Python 3.10 ou mais novo. O núcleo usa só a biblioteca padrão, então não há `pip install` para começar.

```
cd te251-harness
python -m unittest discover tests          # 12 testes; os 2 do enlace são pulados sem broker MQTT
```

Para o LLM local, instale o [Ollama](https://ollama.com) e baixe um modelo uma vez:

```
ollama pull qwen2.5:7b        # GPU de 8 GB
ollama pull qwen2.5:3b        # GPU de 6 GB ou só CPU
```

Para usar outro modelo: `set TE251_MODELO=qwen2.5:3b` (Windows) ou `export TE251_MODELO=qwen2.5:3b` (Linux).

## Uso com dados simulados

Abra dois terminais na pasta `te251-harness`:

```
# terminal 1: gera dados (Ctrl+C para parar)
python -m te251.simulador --cenario estrada

# terminal 2: chat no terminal...
python -m te251.chat
# ...ou a página web
python -m te251.web          # abra http://localhost:8090
```

Cenários: `marcha_lenta`, `estrada`, `superaquecimento`, `bateria_fraca`, `turbo_fraco`, `tanque_reserva` (`--listar` mostra os detalhes). Troque o cenário e faça a mesma pergunta para ver a resposta mudar.

Perguntas para testar: "O motor está esquentando?", "Há algum código de falha?", "Como está a bateria?", "Quanto de autonomia temos?", "A temperatura subiu nos últimos 5 minutos?", "Qual o estado geral do carro?".

**Na sala de aula:** com o `web.py` rodando no notebook, qualquer computador na mesma rede abre `http://<ip-do-notebook>:8090`. O Firewall do Windows vai pedir permissão na primeira vez.

## Uso com os dois lados (carro + teatro)

Precisa de um broker MQTT alcançável pelos dois. Em laboratório, basta rodar na mesma rede:

```
docker run -p 1883:1883 eclipse-mosquitto          # ou instalar o mosquitto
pip install paho-mqtt
```

No carro:

```
python -m te251.simulador --cenario estrada        # ou o coletor real
python -m te251.enlace publicar --broker <ip-do-broker>
```

No teatro:

```
set TE251_MODO=teatro & set TE251_DB=teatro.db     # Linux: export TE251_MODO=teatro TE251_DB=teatro.db
python -m te251.enlace replicar --broker <ip-do-broker>
python -m te251.web                                # telão: http://localhost:8090
```

Em campo, o broker fica no computador da sala e o carro o alcança pelo IP dele na VPN ZeroTier, que atravessa o CGNAT da operadora. Em vez de `--broker` em todo comando, dá para definir `TE251_BROKER=<ip-da-sala>` uma vez (senha opcional em `TE251_MQTT_USUARIO`/`TE251_MQTT_SENHA`). Configuração do broker: [`docs/mosquitto-sala.conf`](docs/mosquitto-sala.conf). Use o mesmo modelo nos dois Ollama, ou as respostas vão divergir na frente da plateia.

Para ver o modo tandem: desligue a réplica do teatro por um minuto com o simulador rodando, depois ligue de novo. Nenhuma amostra se perde, e durante o corte o teatro responde avisando a idade do dado.

## Uso no carro (OBD2 real)

```
pip install obd
python -m te251.coletor --varrer             # lista os PIDs que a ECU da SW4 suporta (anote se FUEL_LEVEL aparece)
python -m te251.coletor --porta COM5         # grava no mesmo te251.db (Linux: /dev/ttyUSB0)
```

O coletor é somente leitura: usa os modos 01 e 03 do OBD2 e nunca escreve na ECU. Ele descarta leituras fora da faixa física. Com o coletor rodando, o chat e o web funcionam do mesmo jeito que com o simulador.

## O que é provisório nesta v0

- `kb/limites.md` tem valores de referência genéricos que eu escrevi. Precisam ser conferidos no manual da SW4 de vocês.
- Consumo fixo de 9,5 km/L e tanque de 80 L em `config.py`. Calibrar com rodagens reais.
- `search_kb` busca por palavras-chave. A troca por embeddings locais (bge-m3 + Chroma) fica para a próxima versão.
- Ainda não tem ocupação dos bancos, distância de viagem (OSRM), voz do HMT-1 nem integração com o Open WebUI (`mcp_server.py` + `mcpo`).
- O enlace foi testado contra um broker local, não contra 4G real com CGNAT e VPN. Pela VPN ZeroTier em rede fixa, o ping deu 0% de perda e média de 47 ms (28/10); o roteiro do teste no 4G está em [`docs/rede-zerotier.md`](docs/rede-zerotier.md).
- Não foi testado com um Ollama de verdade: os testes usam um LLM falso que imita a API do Ollama. O primeiro teste real é rodar `python -m te251.chat` com o Ollama no ar.

## Arquivos

| Arquivo | Função |
| --- | --- |
| `te251/config.py` | caminhos, modelo, PIDs e faixas normais (tudo ajustável por variável de ambiente) |
| `te251/store.py` | banco SQLite em modo WAL |
| `te251/simulador.py` | gera dados realistas por cenário |
| `te251/coletor.py` | OBD2 real via python-OBD |
| `te251/ferramentas.py` | as 6 ferramentas e seus esquemas para o LLM |
| `te251/harness.py` | laço pergunta → LLM ↔ ferramentas → resposta checada |
| `te251/guardrails.py` | checagem de números |
| `te251/regras.py` | respostas sem LLM |
| `te251/enlace.py` | envio por MQTT (carro) e réplica (teatro), com fila que sobrevive a cortes |
| `te251/chat.py` · `te251/web.py` | interfaces de terminal e navegador |
| `kb/` | base de conhecimento (tabela de DTCs e limites) |
| `tests/` | testes automáticos |
