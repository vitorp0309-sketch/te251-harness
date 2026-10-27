# Paralelo: chatbot RAG RIPEAM → projeto TE-251

Material analisado: `Código artigo RAG RIPEAM.rar` (pasta do projeto). Dentro dele há só 3 arquivos de código úteis (~400 linhas), o PDF do RIPEAM, um índice Chroma já gerado e um `venv` de Windows com ~50 mil arquivos.

| Arquivo | O que faz |
|---|---|
| `Script RAG RIPEAM.py` | Rascunho em células (Spyder): PDF → chunks → embeddings OpenAI → Chroma → laço de perguntas no terminal. API antiga do LangChain (`LLMChain`, `RetrievalQA`) |
| `chat_ripeam.py` | Versão "limpa": mesmo RAG, agora dentro de um grafo **LangGraph** (`StateGraph` + `MessagesState`) com um nó só, `gpt-4o-mini` |
| `app.py` | Interface **Streamlit** de chat (porta 8503), histórico em `st.session_state`, saudação conforme o horário |
| `chroma_db/` | Índice vetorial do RIPEAM |
| `venv/` | LangChain 0.3.24, LangGraph 0.3.34, langchain-openai, **langchain-ollama + ollama**, chromadb 1.0.7, Streamlit |

## ⚠️ Antes de tudo: a chave da OpenAI está exposta

`Script RAG RIPEAM.py` e `chat_ripeam.py` têm uma chave `sk-proj-...` escrita no código, e o `.rar` agora está na pasta do projeto. **Revogue essa chave em platform.openai.com → API keys** e gere outra. No TE-251, a chave vai num arquivo `.env` (fora do git) lido com `python-dotenv`.

## Mapa rápido

| Peça do RIPEAM | Serve para o TE-251? | Onde entra |
|---|---|---|
| Pipeline RAG (PyPDFLoader → RecursiveCharacterTextSplitter 1000/50 → embeddings → Chroma → `similarity_search(k=3)`) | **Sim, quase direto** | O "RAG pequeno" do manual da SW4 (seção 7 da análise). Troca `Ripeam.pdf` pelo manual |
| Prompt de grounding ("responda estritamente com base no contexto; se não souber, diga…") | **Sim** | Vira a regra do agente: responder só com o que veio das ferramentas, e dizer quando o dado está velho ou ausente |
| Grafo LangGraph com `MessagesState` | **Sim, como esqueleto** | Base do harness. Precisa virar um agente com tool calling (ver abaixo) |
| App Streamlit | **Sim** | Interface do harness na sala. Dá para pôr um painel lateral com a telemetria ao vivo |
| `langchain-ollama` já instalado | **Sim** | O caminho da LLM local (Ollama) já foi usado pelo grupo, trocar a LLM é uma linha |
| SystemMessage com data/hora atual | **Sim, a ideia** | No TE-251 o importante é o horário **da leitura** do carro (`lido_em`, `idade_s`), não só o horário atual |
| `chroma_db/` existente | Não | São embeddings do RIPEAM |
| `venv/` | Não | É de Windows e pesa muito. Gere um `requirements.txt` com as versões acima |
| `Script RAG RIPEAM.py` | Não | API depreciada; o `chat_ripeam.py` já faz o mesmo de forma melhor |

## O que precisa mudar ao reaproveitar

1. **RAG passa a ser uma ferramenta, não um passo fixo.** Hoje toda pergunta busca 3 trechos no PDF e cola no prompt. No TE-251, "quanto combustível tenho?" não deve consultar o manual. O LLM decide: `get_vehicle_data`, `get_dtc` ou `buscar_manual`.
2. **O histórico não pode virar uma string só.** `build_messages_string` junta toda a conversa num único texto de usuário. Isso quebra tool calling, que depende da lista de mensagens de verdade (`AIMessage` com `tool_calls`, `ToolMessage` com o resultado). Use as mensagens direto.
3. **Grafo de um nó → agente com ferramentas.** O mais curto é `create_react_agent` do `langgraph.prebuilt` (já instalado no venv), ou o par `ToolNode` + `tools_condition`.
4. **Índice persistido de verdade.** O código atual recria os embeddings a cada vez que o app sobe (`Chroma.from_documents` sem `persist_directory`), pagando a API e atrasando o início. Indexe uma vez com `persist_directory` e só carregue depois.
5. **Tabela de códigos de falha não vai para o vetor.** Busca semântica é ruim para código exato ("P0299" acha "P0229"). Guarde a tabela DTC como CSV/dicionário e faça lookup direto dentro de `get_dtc()`. RAG fica só para o texto do manual.
6. **`temperature=0.7` → 0 a 0,2.** Para responder com dado do carro, criatividade atrapalha.
7. **Contas no Python.** Autonomia e rota são calculadas na ferramenta, como já diz a análise; o RIPEAM não tinha esse problema.
8. **Manual da SW4 em PDF** costuma ter tabelas e figuras que o `PyPDFLoader` lê mal. Vale conferir uns chunks (como o script fazia com `chunks[9]`) antes de confiar.

## Esboço do `chat_ripeam.py` adaptado

```python
# chat_te251.py
import os, requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings      # ou langchain_ollama.ChatOllama
from langchain_community.vectorstores import Chroma
from langgraph.prebuilt import create_react_agent

load_dotenv()                                   # OPENAI_API_KEY no .env
API_CARRO = os.getenv("API_CARRO", "http://100.x.y.z:8000")   # IP Tailscale do notebook do carro

manual = Chroma(persist_directory="chroma_sw4", embedding_function=OpenAIEmbeddings())

@tool
def get_vehicle_data(campos: list[str]) -> dict:
    """Leituras atuais do OBD2 (rpm, velocidade, temp_motor, combustivel...). Cada valor vem com lido_em e idade_s."""
    return requests.get(f"{API_CARRO}/telemetria", params={"campos": campos}, timeout=5).json()

@tool
def get_dtc() -> dict:
    """Códigos de falha ativos, já com a descrição da tabela DTC."""
    return requests.get(f"{API_CARRO}/dtc", timeout=5).json()

@tool
def buscar_manual(pergunta: str) -> str:
    """Trechos do manual do proprietário da SW4. Use para dúvidas sobre o carro que não dependem de leitura ao vivo."""
    return "\n\n".join(d.page_content for d in manual.similarity_search(pergunta, k=3))

system = (
    "Você é o assistente da SW4. Responda só com base no que as ferramentas devolveram. "
    "Sempre diga há quanto tempo o dado foi lido. Se uma ferramenta falhar ou o dado não existir, diga isso."
)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
app = create_react_agent(llm, [get_vehicle_data, get_dtc, buscar_manual], prompt=system)
```

O `app.py` do Streamlit continua quase igual: ele já chama `app.invoke({'messages': historico})` e mostra a última mensagem. Só precisa ignorar `ToolMessage` na hora de desenhar o histórico.

## Conclusão

Dá para aproveitar bastante: o pipeline de RAG, o padrão de prompt com grounding, a estrutura LangGraph e a interface Streamlit cobrem a parte "sala de aula" do projeto (harness + RAG do manual). O que o material **não** tem é justamente o núcleo do TE-251: tool calling com dado ao vivo, o coletor OBD2 e a API do carro. Isso continua sendo trabalho novo, conforme as seções 6 e 10 da análise de viabilidade.
