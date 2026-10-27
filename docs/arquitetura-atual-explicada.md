# TE-251 — A arquitetura atual, explicada do zero

Base: resumo do Vitor de 26/10/2026 e o documento `PROJETO_TE-251_CONTEXTO_COMPLETO.md` (v3, 24/10, do Guilherme), que corresponde à **arquitetura A5** da simulação. Comparado com `analise-viabilidade-te251.md` e `paralelo-rag-ripeam.md`.

## Em uma frase

Dentro da SW4 existe uma **rede própria** (criada por um roteador pequeno), onde o notebook e os óculos HMT-1 conversam entre si e com uma **IA que roda no próprio notebook**. O celular só serve de "cano" para a internet, e por esse cano, protegido por uma VPN, os dados do carro são copiados para o computador do auditório, que tem **outra IA local** para a plateia.

## As peças, uma por uma

| Peça | O que é, em termos simples | Papel no projeto |
|---|---|---|
| **Roteador de viagem (OpenWrt)** | Um roteador do tamanho de um maço de cartas (tipo GL.iNet). OpenWrt é o sistema dele, um Linux para roteadores que deixa instalar coisas como VPN | Cria a **LAN** do carro: a "rede de casa" dentro da SW4 |
| **LAN** | Rede local. Os aparelhos ligados nela se enxergam direto, sem passar pela internet | Notebook e HMT-1 conversam mesmo sem sinal de celular |
| **Ethernet → notebook** | Cabo de rede | Ligação mais estável e rápida para a peça mais importante |
| **Wi-Fi 5 GHz → HMT-1** | O HMT-1 é um tablet que fica preso na cabeça (RealWear), controlado por voz. 5 GHz é a faixa do Wi-Fi mais rápida e com menos interferência (e não briga com Bluetooth, que usa 2,4 GHz) | Interface do operador no carro: ele fala, o HMT-1 manda para a IA do notebook e mostra/fala a resposta |
| **Celular como WAN por USB tethering** | WAN é "a saída para a internet". Tethering USB é o celular emprestando a internet 4G pelo cabo | Único caminho para fora do carro. Cabo é mais estável que hotspot e ainda carrega o celular |
| **VPN no roteador** | Um túnel criptografado entre o carro e o auditório, como se os dois estivessem na mesma rede | Toda a LAN do carro fica acessível de forma segura, configurada **uma vez só**, no roteador |
| **LLM local fine-tunado no notebook** | Um modelo de linguagem rodando no notebook (ex. via Ollama), ajustado pelo grupo com exemplos próprios | Responde aos operadores **sem depender de internet** (o "stand-alone") |
| **Réplica da telemetria** | Uma cópia, no auditório, do banco de dados que o notebook grava | O auditório consulta a cópia, não o carro ao vivo |
| **LLM local no PC do auditório (GPU)** | Outra IA, num PC mais forte com placa de vídeo | Responde à plateia/banca sobre os dados replicados |
| **"Nenhuma IA em nuvem"** | Nada de OpenAI, Claude, Gemini etc. | Internet só transporta dado, não pensa |

## O caminho do dado

```
ECU da SW4 → OBD2 → OBDLink EX ─USB→ NOTEBOOK (Legion 5i)
                                         ├─ coletor Python grava em SQLite e publica no MQTT local
                                         └─ LLM local ← pergunta do operador (HMT-1, Wi-Fi 5 GHz)
                                         │
                                 (cabo Ethernet)
                                         │
                                ROTEADOR OpenWrt ── VPN ── USB ── celular 4G ── internet
                                                                                  │
                                                                     PC DO AUDITÓRIO
                                                                       ├─ réplica (bridge MQTT)
                                                                       └─ LLM local (GPU) ← perguntas da plateia
```

Dois "mundos" independentes:
- **No carro:** tudo funciona sem internet. Se o 4G cair, o operador nem percebe.
- **No auditório:** funciona com a cópia mais recente que chegou. Se o 4G cair, a IA da sala continua respondendo com o último dado (e deve dizer que ele está velho).

## O que mudou em relação às análises anteriores

| Tema | Antes | Agora | Avaliação |
|---|---|---|---|
| Rede no carro | Notebook ligado direto no celular | Roteador dedicado criando uma LAN | **Melhor.** Resolve o "Ethernet até o celular" do diagrama antigo e permite incluir o HMT-1 |
| VPN | Tailscale instalado em cada computador | VPN no roteador | **Melhor**, desde que seja do tipo que atravessa CGNAT (ver riscos) |
| Onde fica a IA | Recomendação: um só lugar, com nuvem de plano B | Duas IAs locais, uma em cada ponta | **Mais robusto**, mas são dois modelos para manter |
| Nuvem | Plano B | Proibida | Exige trocar as peças de nuvem do código do RIPEAM (abaixo) |
| Fine-tuning | "Não é necessário" | No resumo, faz parte; no documento, é opcional | Ok, mas só ensina **comportamento**, não dado ao vivo (abaixo) |
| Como o auditório lê o carro | Consultava a API do carro ao vivo | Lê uma réplica local | **Melhor.** Já é o "modo replay" que a análise pedia como seguro |
| Interface do operador | Não definida | HMT-1 por voz | Novo. Útil e seguro: quem está no carro não precisa mexer no notebook |

## Três conceitos que costumam confundir

**1. Fine-tuning não coloca o dado do carro na IA.** Ele ensina o *jeito* de responder: o vocabulário, o formato, quando chamar cada ferramenta (`get_vehicle_data`, `get_dtc`). O valor de RPM ou combustível continua chegando na hora da pergunta, pela ferramenta. Uma IA fine-tunada que responde "de memória" vai inventar números.

**2. Réplica não é tempo real.** A cópia no auditório sempre está alguns segundos (ou minutos, se o 4G cair) atrás do carro. Por isso cada leitura precisa ter horário (`lido_em`), e o notebook precisa guardar o que não conseguiu enviar e mandar depois (o nome técnico é *store-and-forward*).

**3. VPN tradicional não funciona com 4G.** A operadora esconde o celular atrás de um CGNAT (vários clientes dividem um IP), então ninguém de fora consegue "ligar" para o carro. Quem inicia a conexão tem que ser o carro. Funciona com: **Tailscale** no roteador (os GL.iNet já trazem pronto) ou **WireGuard** apontando para um servidor com IP público (um VPS barato serve; é só rede, não é IA).

## Pontos de atenção (revisados com o documento de contexto)

O documento do Guilherme já responde várias dúvidas que eu tinha levantado. Elas ficam marcadas como resolvidas.

| # | Ponto | Situação |
|---|---|---|
| 1 | Qual VPN atravessa o CGNAT? | **Resolvido:** Tailscale (WireGuard próprio como alternativa). Falta só testar a rede do ITA e o sinal dentro do Teatro Weiss (item crítico 1) |
| 2 | Como a réplica chega ao auditório? | **Resolvido:** MQTT com broker local nas duas pontas, bridge persistente, buffer em SQLite e reenvio quando o enlace volta (máquina de estados ONLINE → DEGRADADO → TANDEM → RESSINCRONIZAÇÃO) |
| 3 | O notebook aguenta? | **Quase:** é um Legion 5i com 32 GB de RAM. Falta confirmar a GPU (RTX 4060 8 GB ou 4050 6 GB), que define se o modelo é 7–8B ou 3B |
| 4 | Conector OBD2 | **Resolvido:** OBDLink EX por USB (~45 leituras/s), evitando clone ELM327 Bluetooth (~7/s). Isso substitui o ELM327 da minha primeira análise |
| 5 | As duas IAs falam a mesma língua? | **Resolvido:** o mesmo arquivo de modelo (GGUF `te251`) nas duas pontas, mesmas 8 ferramentas e mesmos guardrails |
| 6 | Fine-tuning | **Resolvido:** QLoRA em 7–8B com 1–3 mil exemplos, e **só se as métricas exigirem**. Ou seja, não é obrigatório; o resumo de 26/10 dá a impressão de que é |
| 7 | Código do RIPEAM usa nuvem | **Continua valendo.** O documento já escolhe embeddings `bge-m3` e Ollama; o código herdado (`gpt-4o-mini`, `OpenAIEmbeddings`) precisa ser trocado antes de reaproveitar |
| 8 | Combustível e ocupação dos bancos | **Encaminhado:** PID 2F marcado como "pode não ser suportado", com plano B por integração de consumo; ocupação por sensores FSR + ESP32. Ainda depende da varredura de PIDs no carro |
| 9 | USB tethering no OpenWrt | **Continua valendo:** Android usa `kmod-usb-net-rndis`, iPhone `kmod-usb-net-ipheth`. Testar com o celular real |
| 10 | Interface do HMT-1 | **Resolvido no conceito:** página leve própria (854×480) + voz (faster-whisper → harness → Piper TTS). Ainda não existe implementada |

## Veredito

A arquitetura do resumo é a **A5** do documento, e ela está bem pensada: o carro funciona sozinho, a sala tem a própria cópia, a rede fica centralizada no roteador e tudo é local. O que falta não é desenho, é **decisão e prova**: confirmar a GPU do Legion, varrer os PIDs da SW4, testar o 4G no teatro e escolher formalmente A5 (alvo) com A6 (MVP).

---

## Complemento: temos PRD, specs e docs? (pergunta de 24/10)

**Resposta do idealizador:** "Não. Temos a arquitetura e conceito. Temos que sentar e definir."

Depois de ler o `PROJETO_TE-251_CONTEXTO_COMPLETO.md` e a simulação v3, a resposta mais justa é: **as specs existem em boa parte; o que não existe é a decisão do grupo, um PRD curto e o código.**

### O que cada documento é, em termos simples

| Documento | Pergunta que responde |
|---|---|
| **PRD** (Product Requirements Document) | **O quê e por quê:** o que a banca vai ver, quem usa, o que entra e o que fica fora, como saber que deu certo |
| **Specs** (especificação técnica) | **Como:** peças, modelos, protocolos, formato do dado, portas |
| **ADR** (registro de decisão) | **Por que esta opção e não aquela:** meia página por decisão |
| **Plano de testes / demo** | Como provar que funciona e o que fazer se algo falhar |

### O que já existe no material do Guilherme

| Item | Onde está | Estado |
|---|---|---|
| Requisitos (R1–R10) e restrições inegociáveis | Seção 2 | **Pronto.** É o núcleo de um PRD |
| Comparação de arquiteturas A1–A6 com veredito, prazo e dificuldade | Seção 4 e simulação | **Pronto.** Recomenda A5 como alvo e A6/A1 como MVP |
| Hardware (SW4, Legion, HMT-1, OBDLink, PC da base, energia) | Seções 3 e 11 | **Quase pronto.** Faltam GPU do Legion e GPU do PC da base |
| Rede, MQTT, tópicos, máquina de estados do tandem | Seção 5 | **Pronto** como spec |
| Pilha de IA: 8 ferramentas, modelo, RAG, fine-tuning, guardrails, portas dos serviços | Seção 6 | **Pronto** como spec de alto nível |
| PIDs, fórmulas, ocupação, cenários de missão e cálculos | Seções 8 a 10 | **Pronto** |
| Riscos (14 itens críticos), cronograma (16 etapas), testes (T01–T13) e marcos (M1–M5) | Seção 12 | **Pronto.** Já é um plano de testes, com critérios como "50 perguntas, 100% dos números corretos" |
| Simulação 3D + relatório de 17 capítulos | `TE-251_Simulacao_v3.html` | **Pronto.** O HTML está ofuscado; analisei pelo documento de contexto, não pelo código |

### O que de fato falta

1. **A decisão do grupo.** O documento *recomenda* A5 com MVP em A6, mas ninguém assinou embaixo. Isso é exatamente o "temos que sentar e definir". Sai da reunião como o primeiro ADR: "Arquitetura-alvo A5, MVP A6, porque…".
2. **PRD curto, de uma página, acordado pelo grupo.** O material é um relatório técnico escrito para apresentar opções (e para orientar uma IA a continuar o trabalho), não um acordo do grupo. O PRD tira dele:
   - **Objetivo da demo em uma frase** (o que a banca vê funcionando no dia).
   - **Escopo mínimo × extensões.** O cronograma já marca ocupação, missão/OSRM, vídeo Jitsi e fine-tuning como extensão ou opcional. O grupo precisa confirmar que o mínimo é: coletor OBD + réplica na base + chat com ferramentas + tandem.
   - **Data da apresentação.** Está em aberto; sem ela o Gantt de 6 a 10 semanas não vira calendário.
3. **Divisão de responsabilidades.** O cronograma tem 16 etapas e nenhum dono. Uma tabela "etapa → pessoa" resolve.
4. **Contratos de interface detalhados**, para que pessoas diferentes trabalhem em paralelo sem se quebrar:
   - formato JSON de cada mensagem MQTT (`te251/telemetry/<pid>`, `te251/dtc`, `te251/seats`, `te251/status`);
   - entrada e saída exatas de cada uma das 8 ferramentas do harness;
   - a API do te251-api (porta 8090) que o HMT-1 e o Open WebUI consomem.
   O documento lista os nomes; faltam os campos.
5. **Respostas às questões abertas** (seção 16): GPU do Legion, ano/motor da SW4 e PIDs suportados, GPU do PC do auditório e uso da rede cabeada do ITA, cobertura 4G no teatro.
6. **Código real.** Coletor OBD, harness e página do HMT-1 ainda não existem fora dos "códigos de referência" do relatório. O próprio documento coloca o protótipo Python como melhoria da v4.
7. **Repositório compartilhado.** O material vive numa pasta local do Guilherme com site protegido por senha. Para o grupo construir junto, falta um repositório (Git) com o código e esses documentos.

### Proposta de ordem

1. **Reunião curta** com três saídas: aprovar A5 + MVP A6, fechar o escopo mínimo e marcar a data da apresentação.
2. **PRD de uma página** e o **ADR da arquitetura**, escritos a partir das seções 1, 2, 4 e 12 do documento do Guilherme.
3. **Semana 1 do cronograma (S01)**: varredura de PIDs na SW4 e site survey no Teatro Weiss, mais confirmar a GPU do Legion. Esses três resultados podem mudar o escopo.
4. **Contratos de interface** (MQTT e ferramentas) e divisão das etapas por pessoa, para começar o código em paralelo.

---

## Complemento 2: o plano de passos do Guilherme (24/10)

Resumo das mensagens: (1) fazer o RealWear conversar com o computador por comandos de voz; (2) tirar os dados do OBD2 e gravar num banco no próprio computador, que pode ser uma planilha para simplificar; (3) criar uma LLM com guardrail no mesmo computador, que use o que foi treinado e os dados da planilha. O segredo é o harness, que junta o conhecimento do carro com o status atual e manda tudo **no contexto, em tempo real**, em vez de colocar os dados dentro da LLM de tempos em tempos.

**Avaliação geral: a sequência é boa e a ideia central está certa.** Cada passo entrega algo que funciona sozinho, e nenhum depende ainda do 4G, da VPN ou do auditório. É o MVP "A6" do próprio documento: tudo num computador só. Abaixo, o que observar em cada passo.

### Passo 1: RealWear ↔ computador por voz

- **Bom primeiro passo**: não precisa do carro, só do HMT-1, do notebook e da rede. Prova que "tudo está se falando".
- **Não precisa de app Android no começo.** O HMT-1 tem navegador e o sistema de voz dele (WearHF) aciona sozinho qualquer botão cujo texto apareça na tela: um botão "COMBUSTÍVEL" vira o comando de voz "combustível". Basta o notebook servir uma página web simples (FastAPI) e o HMT-1 abri-la. App nativo fica para depois, se for preciso.
- **Comando fixo é fácil; pergunta livre é outra coisa.** "Mostrar temperatura" funciona com botões. "Dá para chegar em Taubaté?" precisa transformar fala em texto. O ditado do Android pode usar serviço do Google (nuvem, proibido pela regra do projeto). O caminho local é gravar o áudio no HMT-1 e transcrever no notebook com faster-whisper, como já prevê o documento.
- **Sugestão de entrega do passo 1:** página no HMT-1 com 3 a 6 valores grandes e 3 botões de voz, lendo dados **falsos** do notebook. Assim o passo 1 não espera o passo 2.

### Passo 2: OBD2 → "banco de dados" no computador

- **Planilha funciona, com um cuidado.** Um arquivo Excel (.xlsx) não é bom para isso: o Excel trava o arquivo enquanto está aberto, e regravar o .xlsx a cada leitura é lento e pode corromper.
- **Melhor caminho simples: CSV.** É uma planilha em texto, uma linha por leitura (`horario, pid, valor, unidade`). O coletor só acrescenta linhas no fim, o Excel abre normalmente para conferir e o harness lê as últimas linhas. Resolve o desejo de "fugir de SQL" sem os problemas do .xlsx.
- Se depois for preciso, trocar CSV por SQLite (o que o documento prevê para o tandem e a réplica) é mexer numa função só, desde que o resto do código leia o dado por uma função como `ultimo_valor(pid)` e não direto do arquivo.
- **Começar com o simulador**: sem o carro, o coletor pode gravar valores gerados (os presets da aba "Parâmetros ECU" servem de roteiro). Com o carro, o primeiro teste é a varredura de PIDs (seção 8 da análise de viabilidade).

### Passo 3: LLM com guardrail + harness

O ponto principal do Guilherme, "não é colocar os dados de tempos em tempos dentro da LLM", está **correto** e bate com tudo o que analisamos: o dado ao vivo nunca vai para o treino, ele entra na conversa na hora da pergunta.

Existem dois jeitos de o harness fazer isso. Os dois são válidos e podem conviver:

| Jeito | Como funciona | Quando usar |
|---|---|---|
| **Injeção de contexto** (o que o Guilherme descreveu) | A cada pergunta, o harness lê as últimas leituras da planilha e cola um bloco no prompt: "Estado atual (lido às 14:03:12, há 2 s): RPM 820, combustível 63%…" | **Começar por aqui.** É simples, funciona com modelos pequenos e quase não erra |
| **Tool calling** (o que o documento de contexto especifica) | A LLM decide pedir um dado: chama `fuel_range()` ou `get_history("COOLANT_TEMP", "10 min")`, e o harness devolve | Quando a pergunta precisa de algo grande ou calculado: histórico, rota, autonomia. Não dá para colar tudo isso em todo prompt |

Cuidados:

- **"Acessar o que for treinado" é o ponto mais frágil.** Fine-tuning é bom para ensinar o *jeito* de responder (tom, formato, quando usar cada dado). Ele **não é confiável para guardar fatos** (capacidade do tanque, pressão dos pneus, o que significa P0299): o modelo mistura e inventa. Para fatos do carro, o caminho seguro é o RAG (manual e tabela de códigos) e o harness colar o trecho no contexto, igual faz com os dados. O próprio documento põe o fine-tuning como opcional.
- **Contas fora da LLM.** Autonomia e "dá para chegar em X" devem ser calculados no Python e entregues prontos no contexto. Modelo pequeno erra conta.
- **Guardrail na prática** são três regras no harness: só citar números que vieram do contexto, sempre dizer a idade do dado, e dizer "não tenho esse dado" quando ele não existe. O teste T04 do documento (50 perguntas, 100% dos números corretos) mede exatamente isso.

### Como isso conversa com o resto

| Passo do Guilherme | Etapas do cronograma do documento | Marco |
|---|---|---|
| 1. RealWear ↔ computador | S09 (harness móvel + voz), S07 (dashboards) | parte do M3 |
| 2. OBD2 → planilha | S01 (varredura de PIDs), S04 (coletor OBD) | M1 |
| 3. LLM + harness | S08 (Open WebUI), S09, S14 (fine-tuning, opcional) | M3 |
| Depois | S06 (rede/VPN/bridge), S10 (base), S13 (tandem) | M2, M4 |

### Sugestão de ajuste na ordem

Os passos 1 e 2 **podem andar em paralelo**, com pessoas diferentes, se os dois combinarem só o formato da planilha (as colunas do CSV). O passo 1 usa dados falsos até o passo 2 ficar pronto. O passo 3 começa assim que existir a planilha, mesmo com dados simulados. Isso encurta o caminho até a "grande vitória" de ver tudo se falando.

---

## Complemento 3: harness em Python local e treino no hardware que temos

Ideia do Vitor (26/10): fazer o harness em Python, local, e treinar o modelo que o hardware disponível permitir, seguindo os "exercícios webUI". Não encontrei o material desses exercícios na pasta do projeto nem na pasta do computador; se mandar, eu ajusto esta seção a ele.

### O harness em Python

- **É a peça certa para ser nossa.** O harness é o programa que fica entre a pergunta e o modelo: lê a planilha/CSV, monta o contexto, chama o Ollama, aplica os guardrails e devolve a resposta. Tudo isso cabe em Python com poucas bibliotecas (`fastapi`, `requests` ou `ollama`, `pandas` para o CSV).
- **Um harness só, várias telas.** Recomendo que ele seja um serviço próprio (FastAPI na porta 8090, como no documento), e não código dentro do Open WebUI. Assim a página do HMT-1, o Open WebUI do notebook e o telão da base usam **o mesmo** harness e dão a mesma resposta.
- **Ligação com o Open WebUI:** o Open WebUI aceita "servidores de ferramentas" no formato OpenAPI, que o FastAPI gera sozinho. Ou seja, as ferramentas do harness aparecem no chat do Open WebUI sem código extra (o `mcpo` do documento é o outro caminho para o mesmo resultado).
- **Esqueleto mínimo** (injeção de contexto, como o Guilherme descreveu):

```python
# harness.py — mínimo para o passo 3
import time, pandas as pd, ollama

def estado_atual(csv="leituras.csv"):
    df = pd.read_csv(csv).groupby("pid").tail(1)          # última leitura de cada PID
    agora = time.time()
    return "\n".join(f"{r.pid}: {r.valor} {r.unidade} (há {agora - r.horario:.0f} s)"
                     for r in df.itertuples())

REGRAS = ("Você é o assistente da SW4. Use só os números do bloco ESTADO ATUAL. "
          "Sempre diga há quanto tempo o dado foi lido. Se o dado não estiver lá, diga que não tem.")

def perguntar(pergunta, modelo="te251"):
    msgs = [{"role": "system", "content": REGRAS},
            {"role": "user", "content": f"ESTADO ATUAL:\n{estado_atual()}\n\nPERGUNTA: {pergunta}"}]
    return ollama.chat(model=modelo, messages=msgs, options={"temperature": 0.1})["message"]["content"]
```

### Que modelo dá para treinar com o hardware que temos

Treinar aqui quer dizer **fine-tuning com QLoRA**: não se treina um modelo do zero, ajusta-se um modelo pronto (Qwen2.5, Llama 3.x) com poucas camadas extras, e o modelo base fica em 4 bits para caber na placa de vídeo. Os números abaixo são **estimativas**.

| Máquina | Placa | Treinar (QLoRA) | Rodar (Ollama, Q4) |
|---|---|---|---|
| Legion 5i com RTX 4060 | 8 GB | 3–4B com folga; 7–8B no limite (Unsloth, textos curtos de até ~1.000 tokens, lote 1) | 7–8B cabe (~5 GB) |
| Legion 5i com RTX 4050 | 6 GB | 1,5–3B | 3–4B; 7–8B fica apertado |
| PC da base (≥ 16 GB, ex. 4060 Ti 16 GB) | 16 GB | 7–8B com folga | 7–14B |

Recomendações:

1. **Confirmar a GPU do Legion primeiro.** É ela que decide entre 3B e 7–8B (já é a questão aberta nº 1 do documento).
2. **Treinar onde couber melhor e rodar no carro.** Se o PC da base tiver 16 GB, treine lá e copie o arquivo GGUF para o Legion. O modelo é o mesmo nas duas pontas.
3. **Treino tem que ser local também.** Google Colab ou serviços de GPU alugada contam como nuvem, o que a restrição do projeto proíbe.
4. **No Windows, use WSL2** (Linux dentro do Windows) para Unsloth/PEFT. Funciona melhor e evita brigas com CUDA. O Ollama roda nativo no Windows.
5. **Medir antes de treinar.** Rode o teste T04 (50 perguntas, números 100% corretos) com o modelo base + harness. Se já passar, o fine-tuning vira refinamento de estilo, não necessidade. O documento diz o mesmo: "fazer só se as métricas exigirem".
6. **Os dados de treino saem do próprio harness.** Cada pergunta, contexto e resposta boa que o harness gerar (com dados simulados ou reais) vira um exemplo. Com 1 a 3 mil exemplos revisados, o fine-tuning ensina o tom, o formato e a disciplina de citar a idade do dado.
7. **Fluxo do treino até o carro:** QLoRA → juntar o adaptador ao modelo → converter para GGUF → `ollama create te251` → o harness passa a usar `modelo="te251"` sem outra mudança.
