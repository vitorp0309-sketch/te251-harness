# Rede do TE-251: Tailscale, broker MQTT e teste no 4G

Situação em 29/10/2026. O grupo voltou ao **Tailscale** (o ZeroTier `TE251-VPN` foi usado só nos testes de 28/10). O app das estações do Willian já usa Tailscale, então os dois lados ficam na mesma VPN.

O Tailscale dá a cada computador um IP fixo `100.x.y.z` e um nome (MagicDNS). Um alcança o outro mesmo com o 4G atrás de CGNAT, porque os dois só fazem conexões **de saída**: quando não dá para ligar direto, o tráfego passa por um relay criptografado do Tailscale (DERP; há um em São Paulo). Ele só transporta dados, então continua valendo a regra de IA 100% local.

| Máquina | Nome no tailnet | Papel |
| --- | --- | --- |
| PC do Vitor (Alienware m16, Win 11) | `carro-sw4` | coletor OBD2 + SQLite + harness + Ollama; sobe por 4G |
| Notebook da sala | `sala-te251` | broker MQTT + réplica + harness + Ollama; rede fixa |
| Notebooks do grupo (Willian, etc.) | o nome de cada um | desenvolvimento e testes |

Os IPs `100.x.y.z` só aparecem depois que cada máquina entra; anote-os aqui quando estiverem prontos. Nos comandos, prefira os nomes: eles não mudam se a máquina for reinstalada.

## 1. Criar o tailnet (uma pessoa, uma vez)

**Quem administra:** se o Willian já tem um tailnet rodando para o app das estações, use o dele e pule para o passo 2 (ele só precisa convidar os outros). Se não, quem cria vira o administrador; o natural é o dono deste repositório (Vitor). O plano gratuito Personal basta para o grupo (limites atuais em tailscale.com/pricing).

1. Entrar em <https://login.tailscale.com/start> e fazer login com uma conta Google, Microsoft ou GitHub. Esse login vira o dono do tailnet.
2. **Admin console → Users → Invite users**: convidar o e-mail de cada membro do grupo. Cada um entra com a própria conta.
3. **Admin console → DNS**: conferir que **MagicDNS** está ligado (vem ligado em tailnets novos).
4. **Admin console → Access controls**: colar a política da seção 4 e salvar.

## 2. Instalar nas máquinas

Em cada computador (Windows):

1. Baixar em <https://tailscale.com/download/windows> e instalar.
2. Clicar no ícone do Tailscale na bandeja → **Log in** → entrar com a conta convidada.
3. Renomear a máquina no **Admin console → Machines → ⋯ → Edit machine name** (`carro-sw4`, `sala-te251`).

Nas duas máquinas fixas do projeto (`carro-sw4` e `sala-te251`), no **Admin console → Machines → ⋯**:

- **Disable key expiry.** Sem isso o login expira (180 dias por padrão) e a máquina sai da VPN no meio de uma apresentação.
- **Edit ACL tags** → `tag:carro` ou `tag:sala`. A máquina passa a pertencer ao projeto, não à conta pessoal de quem fez login, e continua no tailnet mesmo que essa pessoa saia.

Conferir, no PowerShell:

```
tailscale status        # máquinas vistas, IP e se estão online
tailscale ip -4         # meu IP 100.x.y.z
```

Se o Windows bloquear conexões de entrada vindas da VPN (o ping responde, mas a porta não abre), libere a porta só para a faixa do Tailscale, no PowerShell como administrador:

```
New-NetFirewallRule -DisplayName "TE251 MQTT (Tailscale)" -Direction Inbound -Protocol TCP -LocalPort 1883 -RemoteAddress 100.64.0.0/10 -Action Allow
```

(Troque `1883` por `8090` para o telão do harness, ou pela porta que for usada.)

## 3. Onde fica o broker MQTT

O broker é o "correio" do MQTT: o carro entrega as leituras nele e a sala retira de lá.

| | No carro | **Na sala** (recomendado) | Numa base fixa (3º computador) |
| --- | --- | --- | --- |
| Quem abre a conexão pelo 4G | a sala precisa "entrar" no carro | o carro "sai" até a sala | os dois saem até a base |
| Confirmação de entrega | o broker local confirma até sem internet, então a marca de envio avança mesmo sem a sala ter recebido | a confirmação só chega quando o dado está na sala: a marca de envio do SQLite fica certa | confirma quando chega na base, não na sala |
| Se o 4G cair por muito tempo | o broker do carro segura a fila na memória (limite padrão de 1000 mensagens ≈ 2 min) e pode descartar o excesso | o carro guarda tudo no SQLite e reenvia do ponto exato | a base segura a fila para a sala; precisa configurar fila sem limite |
| Máquinas a manter ligadas | carro | carro + sala | carro + sala + base |
| Mudança no harness | sim, a fila teria que mudar de lugar | **nenhuma**, é como o enlace foi feito | pequena (configurar o broker da base) |

**Recomendação: broker no computador da sala.** O carro só considera uma leitura enviada quando o broker da sala confirma, então a fila de verdade é o SQLite do carro e nada se perde num corte de 4G.

### Instalar o broker na sala

1. Instalar o Mosquitto (mosquitto.org/download, versão Windows). Ele vira o serviço "Mosquitto Broker".
2. Criar a pasta `C:\mosquitto\dados\`.
3. Copiar [`docs/mosquitto-sala.conf`](mosquitto-sala.conf) por cima de `C:\Program Files\mosquitto\mosquitto.conf` e reiniciar o serviço.
4. Se preciso, liberar a porta 1883 para o Tailscale (comando da seção 2).
5. Na sala, rodar a réplica e o telão:

   ```
   set TE251_MODO=teatro & set TE251_DB=teatro.db & set TE251_BROKER=127.0.0.1
   python -m te251.enlace replicar
   python -m te251.web
   ```

### No PC do Vitor (máquina do carro)

```
cd "C:\Users\Vitor Pinheiro\te251-harness-git"
set TE251_BROKER=sala-te251
python -m te251.coletor --porta COM5            # ou: python -m te251.simulador --cenario estrada
python -m te251.enlace publicar                 # em outro terminal, com o mesmo TE251_BROKER
python -m te251.web                             # equipe no carro: http://localhost:8090
```

Se o nome `sala-te251` não resolver, use o IP `100.x.y.z` da sala (`tailscale status` mostra).

## 4. Política de acesso (ACL)

O tailnet é privado: só entra quem o administrador convida. A política abaixo deixa os membros do grupo alcançarem tudo e as duas máquinas do projeto se alcançarem entre si. Colar em **Admin console → Access controls**:

```json
{
  "tagOwners": {
    "tag:carro": ["autogroup:admin"],
    "tag:sala":  ["autogroup:admin"]
  },
  "grants": [
    {"src": ["autogroup:member"], "dst": ["*"], "ip": ["*"]},
    {"src": ["tag:carro"], "dst": ["tag:sala"], "ip": ["*"]},
    {"src": ["tag:sala"], "dst": ["tag:carro"], "ip": ["*"]}
  ]
}
```

Os `tagOwners` precisam existir antes de aplicar as tags da seção 2. Quando tudo estiver estável, dá para apertar: trocar o `"*"` de `tag:carro → tag:sala` por `"tcp:1883"` (só MQTT) e o de `tag:sala → tag:carro` por `"tcp:8090"` (só o telão). Com regras por porta, o `ping` entre as duas deixa de responder; use `tailscale ping`, que funciona sempre.

## 5. O que testar

O ping pelo ZeroTier em rede fixa (28/10) deu 0% de perda e média de 47 ms, muito abaixo da folga do harness (`TE251_IDADE_MAX_S` = 15 s). Refazer no Tailscale e, principalmente, no 4G. O que pode atrapalhar no 4G não é a latência, é a queda.

Todos com o PC do Vitor no 4G do celular (roteador ou USB) e a sala na rede fixa. Anote operadora, local e horário.

| # | Teste | Como | Passa se |
| --- | --- | --- | --- |
| 0 | Rede fixa | `tailscale ping sala-te251` e `ping -n 100 sala-te251` com os dois em rede fixa | perda 0%, média < 100 ms |
| 1 | Latência e perda no 4G | `ping -n 600 sala-te251` (10 minutos), parado e depois com o carro andando | perda < 2%, média < 300 ms |
| 2 | Direto ou relay | `tailscale ping sala-te251` no 4G | anotar `via <ip>` (direto) ou `via DERP(sao)` (relay); relay não reprova, mas explica latência mais alta |
| 3 | Corte e volta | com o enlace rodando, pôr o celular em modo avião por 30 s e por 5 min | o ping volta sozinho em menos de ~30 s e a sala volta a receber dados sem ninguém mexer |
| 4 | Nada se perde | simulador + enlace por 30 min com 2 ou 3 cortes; depois contar linhas da tabela `sample` nos dois bancos | mesma quantidade nos dois lados, sem duplicadas |
| 5 | Idade do dado na sala | durante um corte, perguntar à IA da sala "O motor está esquentando?" | a resposta avisa há quanto tempo o dado foi lido |
| 6 | Consumo de dados | contador do celular antes e depois de 1 h | poucos MB por hora (7 PIDs por segundo, ~100 bytes cada) |
| 7 | Rede do ITA e Teatro Weiss | repetir o teste 1 com a sala na rede do ITA e o celular dentro/perto do Teatro; rodar `tailscale netcheck` na sala | conecta; se a rede do ITA bloquear UDP, o Tailscale cai para relay por HTTPS (443) e continua funcionando, só mais lento |
| 8 | Duas operadoras | repetir 1 e 3 com um chip de outra operadora | escolher a que cair menos |

Para contar as linhas (teste 4), nos dois computadores:

```
python -c "import sqlite3; print(sqlite3.connect('te251.db').execute('select count(*), max(seq) from sample').fetchone())"
```

(Na sala, troque `te251.db` por `teatro.db`.)

## Comandos úteis do Tailscale

```
tailscale status              # máquinas do tailnet, IPs e quem está online
tailscale ip -4               # meu IP na VPN
tailscale ping sala-te251     # latência pela VPN e se a ligação é direta ou via relay (DERP)
tailscale netcheck            # diagnóstico da rede local: UDP liberado? relay mais próximo?
tailscale up / tailscale down # liga / desliga a VPN nesta máquina
```

No Windows, os comandos funcionam no PowerShell ou no Prompt; se `tailscale` não for encontrado, use `"C:\Program Files\Tailscale\tailscale.exe"`.
