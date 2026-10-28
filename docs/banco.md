# Banco de dados do TE-251 (esquema v1)

Um arquivo SQLite (`te251.db`, modo WAL) em cada lado. No carro, o coletor é o dono do banco; no teatro, o banco é uma réplica que chega por MQTT. A versão do esquema fica em `PRAGMA user_version`. Um banco antigo (v0) é migrado sozinho na primeira vez que o harness abre, sem perder dados: o que já existia vira uma sessão de origem `legado`.

## Tabelas

```
sessao 1 ──< sample          telemetria (uma linha por leitura de PID)
       1 ──< dtc             mudanças nos códigos de falha
       1 ──< interacao       perguntas ao harness e respostas
```

### `sessao`: cada rodagem ou teste

| Coluna | Tipo | Conteúdo |
| --- | --- | --- |
| `id` | inteiro | chave |
| `inicio`, `fim` | real (epoch s) | `fim` fica vazio enquanto a sessão está aberta ou se o programa caiu |
| `modo` | texto | `carro` ou `teatro` |
| `origem` | texto | `obd` (coletor), `simulador`, `importacao` (dados de fora, ex.: Will), `replica`, `legado` |
| `descricao` | texto | nota livre: `--descricao "first trial"` no coletor, cenário no simulador |

### `sample`: telemetria

| Coluna | Tipo | Conteúdo |
| --- | --- | --- |
| `seq` | inteiro | chave, crescente; é o que o enlace usa para retomar o envio |
| `ts` | real (epoch s) | hora da leitura |
| `pid` | texto | nome do python-OBD (`RPM`, `SPEED`, `COOLANT_TEMP`...; lista em `config.PIDS`) |
| `value`, `unit` | real, texto | valor já convertido e unidade |
| `fonte` | texto | `obd`, `simulador`, `replica`... |
| `sessao_id` | inteiro | sessão |

### `dtc`: códigos de falha

Só grava quando o conjunto muda: `(ts, codigo, status, sessao_id)`, com `status` `ativo` ou `limpo`.

### `interacao`: o que a IA respondeu

Cada pergunta feita pelo terminal ou pela web: pergunta, resposta, `fonte` (`LLM <modelo>` ou `regras (...)`), `aprovada` (1 se a resposta do LLM passou na checagem de números), ferramentas chamadas (JSON), tempo de resposta, idade do dado no momento da pergunta, e a resposta reprovada quando houve. É a base para medir a precisão no first trial. Fica no lado onde a pergunta foi feita (não é replicada).

### Visão `telemetria`

Junta `sample` e `sessao` com data e hora legíveis. É o jeito mais simples de abrir os dados no Excel, no pandas ou no DB Browser for SQLite:

```sql
SELECT data_hora, pid, valor, unidade FROM telemetria WHERE sessao_id = 3 AND pid = 'COOLANT_TEMP';
```

## Utilitário `te251.banco`

```
python -m te251.banco info                        # versão, tamanho e contagens
python -m te251.banco sessoes                     # lista as sessões
python -m te251.banco interacoes --sessao 3       # perguntas e respostas da sessão 3
python -m te251.banco exportar --saida exports/sessao3.csv --sessao 3
python -m te251.banco medir --horas 2 --hz 5      # mede o custo do armazenamento (banco temporário)
```

## Impacto do armazenamento (medido em 28/10/2026)

Medido com `python -m te251.banco medir` na máquina de desenvolvimento, com os 7 PIDs atuais. Repetir no notebook do carro.

| Cenário | Linhas por hora | Banco por hora | Gravação |
| --- | --- | --- | --- |
| 5 Hz por PID, 2 h | 126.000 | 16,6 MB | cerca de 100 mil linhas/s; o coletor precisa de 35 |
| 2 Hz por PID, 8 h | 50.400 | 6,6 MB | cerca de 100 mil linhas/s; o coletor precisa de 14 |

Um adaptador ELM327/OBDLink lê na prática de 10 a 20 PIDs por segundo no total, então o caso real fica perto do segundo cenário ou abaixo: um dia inteiro de coleta cabe em menos de 100 MB. Gravar não pesa para o notebook.

Consultas das ferramentas com o banco cheio: o último valor de um PID e os DTCs levam menos de 0,1 ms; o histórico de 5 min, de 0,5 a 2 ms; o de 1 h, de 9 a 25 ms.

A medição achou um gargalo no v0: buscar o último valor de um PID varria todo o histórico e chegava a 32 ms com 2 h de dados e 68 ms com 8 h, crescendo sem parar. O v1 criou o índice `ix_sample_pid` e o problema sumiu (0,01 ms). O custo é cerca de 25% a mais de espaço em disco.

## Integração com os dados do Willian (Will)

O Willian coleta o OBD2 da SW4 com o app de estações dele (repositório `PROJETO-TE-251`: ELM327 por Bluetooth, painel web, SQLite e MQTT). O banco dele usa a mesma tabela `sample(seq, ts, pid, value, unit)` e os mesmos nomes de PID do python-OBD, então o arquivo entra direto, sem CSV:

```
python -m te251.importar "caminho/do/te251.db" --descricao "garagem, 27/10"
```

- Cada trecho contínuo de gravação vira uma sessão de origem `importacao` (mais de 5 min sem leitura abre outra; ajuste com `--pausa-s`). As amostras ficam com `fonte = 'willian'`.
- As unidades são convertidas para as do harness (`degree_Celsius` → `°C`, `revolutions_per_minute` → `rpm` etc.; tabela `UNIDADES` em `store.py`).
- Leituras fisicamente impossíveis são descartadas, com a mesma regra do coletor. PIDs que a IA ainda não usa (o app grava até 30 com "todos os dados") são guardados mesmo assim.
- O mesmo arquivo não é importado duas vezes (o nome e o hash vão na descrição da sessão); `--forcar` importa de novo.
- Use o `te251.db` do app. O `te251-simulacao.db` dele é dado falso.

O MQTT do app dele também é compatível com a réplica do teatro (`te251/telemetry/<PID>` com `seq, ts, pid, v, u`). A réplica aceita as falhas no campo `dtc`, como o app manda, e converte as unidades.

## Limitações conhecidas

- No teatro, a réplica reaproveita o id da sessão do carro. Se o banco do teatro tiver uma sessão local com o mesmo id (por exemplo, `legado` vinda da migração), as amostras replicadas entram nela. Para evitar, comece a réplica com um banco novo.
- A tabela `interacao` não vai para o teatro, e as perguntas feitas no teatro ficam só no banco do teatro.
