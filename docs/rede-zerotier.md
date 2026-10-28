# Rede do TE-251: ZeroTier, broker MQTT e teste no 4G

Situação em 28/10/2026. O grupo trocou o Tailscale pelo **ZeroTier**, numa rede administrada pelo Willian.

| | |
| --- | --- |
| Rede | `TE251-VPN`, ID `08752e18b1d7ea93` |
| PC do Vitor (Alienware, futuro notebook do carro) | `10.69.3.19` (ZeroTier address `51a1e4ffbf`) |
| Notebook do Willian (servidor de teste, telas `/sala` e `/carro`) | `10.69.3.78:8765` |

O ZeroTier faz o mesmo papel que o Tailscale faria: cada computador ganha um IP fixo na VPN e um alcança o outro mesmo com o 4G atrás de CGNAT, porque os dois só fazem conexões **de saída**. Ele só transporta dados, então continua valendo a regra de IA 100% local.

## 1. O ping serve?

Medido em 28/10, PC do Vitor até o notebook do Willian, os dois em rede fixa: **0% de perda**, normal ~30 ms, média 47 ms, picos de 141 ms.

**Serve, com muita folga.** Para comparar:

| O que | Ordem de grandeza |
| --- | --- |
| Pico medido no ping | 0,14 s |
| Coletor lê os PIDs da SW4 | a cada ~1 s |
| LLM local escreve uma resposta | alguns segundos |
| Idade máxima que a sala aceita antes de avisar "dado desatualizado" (`TE251_IDADE_MAX_S`) | 15 s |

O atraso da rede é cerca de 100 vezes menor do que a folga que o harness já dá. Mesmo que o 4G triplique esses números (300 a 500 ms é comum), continua bom. **O que pode atrapalhar no 4G não é a latência, é a queda**: o celular perde sinal, troca de antena ou a VPN demora a reconectar. Isso o enlace já trata (o carro guarda tudo no SQLite e reenvia do ponto exato), mas precisa ser medido. Ver seção 4.

A variação entre 30 e 141 ms é normal em Wi-Fi doméstico. Vale conferir se a conexão do ZeroTier está **direta** ou passando por **relay** (servidor intermediário, mais lento):

```
zerotier-cli peers          # Windows: abrir o PowerShell como administrador
```

Na linha do outro computador, `DIRECT` é o ideal; `RELAY` funciona, mas com mais atraso.

## 2. Como o PC do Vitor vira a máquina do carro

Hoje o servidor de teste do Willian trata o PC do Vitor como "Estação da Sala". Há dois caminhos:

| | A. Willian só troca os papéis | B. O servidor passa a rodar no PC do Vitor (**recomendado**) |
| --- | --- | --- |
| O que muda | No servidor dele, o IP `10.69.3.19` passa a ser o "carro" | O PC do Vitor roda o servidor/harness; a sala abre `http://10.69.3.19:<porta>/sala` |
| Se a VPN cair | o carro fica sem servidor | o carro continua funcionando sozinho |
| Bate com a arquitetura A5? | Não: o dado do carro dependeria da internet para ser gravado | Sim: o carro é o dono do banco, a sala recebe a réplica |
| Bom para | um teste rápido de tela | o projeto de verdade |

Não conheço o código do servidor do Willian (porta 8765), então quem confirma como trocar os papéis é ele. Para o harness deste repositório, a máquina do carro é só configurar `TE251_MODO=carro` (o padrão).

**O que pedir ao Willian:**

1. Manter o IP `10.69.3.19` fixo para o PC do Vitor no ZeroTier Central e dar um nome a ele (ex.: `carro-sw4`).
2. Dizer qual é a faixa da rede (ex.: `10.69.0.0/16`), para a regra do firewall.
3. Escolher A ou B. Se for B, mandar o servidor de teste para rodar no PC do Vitor, ou combinar que a parte "carro" passa a ser o harness deste repositório.
4. Dizer qual computador fica na sala e qual o IP dele na VPN (é onde fica o broker, seção 3).

**No PC do Vitor (máquina do carro):**

```
cd "C:\Users\Vitor Pinheiro\te251-harness"
set TE251_BROKER=<ip-da-sala-na-vpn>
python -m te251.coletor --porta COM5            # ou: python -m te251.simulador --cenario estrada
python -m te251.enlace publicar                 # em outro terminal, com o mesmo TE251_BROKER
python -m te251.web                             # equipe no carro: http://localhost:8090
```

O Windows costuma tratar a rede do ZeroTier como "rede pública" e bloquear conexões de entrada. Se a sala precisar abrir alguma página do carro (porta 8090 do harness, ou 8765 do servidor do Willian), libere a porta só para a faixa da VPN, no PowerShell como administrador:

```
New-NetFirewallRule -DisplayName "TE251 web (VPN)" -Direction Inbound -Protocol TCP -LocalPort 8090 -RemoteAddress 10.69.0.0/16 -Action Allow
```

(Troque `10.69.0.0/16` pela faixa que o Willian informar e `8090` pela porta que for usada.)

## 3. Onde fica o broker MQTT

O broker é o "correio" do MQTT: o carro entrega as leituras nele e a sala retira de lá. As três opções:

| | No carro | **Na sala** (recomendado) | Numa base fixa (3º computador) |
| --- | --- | --- | --- |
| Quem abre a conexão pelo 4G | a sala precisa "entrar" no carro | o carro "sai" até a sala | os dois saem até a base |
| Confirmação de entrega | o broker local confirma até sem internet, então a marca de envio avança mesmo sem a sala ter recebido | a confirmação só chega quando o dado está na sala: a marca de envio do SQLite fica certa | confirma quando chega na base, não na sala |
| Se o 4G cair por muito tempo | o broker do carro segura a fila na memória (limite padrão de 1000 mensagens ≈ 2 min) e pode descartar o excesso | o carro guarda tudo no SQLite e reenvia do ponto exato | a base segura a fila para a sala; precisa configurar fila sem limite |
| Máquinas a manter ligadas | carro | carro + sala | carro + sala + base |
| Mudança no harness | sim, a fila teria que mudar de lugar | **nenhuma**, é como o enlace foi feito | pequena (configurar o broker da base) |

**Recomendação: broker no computador da sala.** É o desenho que o enlace já usa: o carro só considera uma leitura enviada quando o broker da sala confirma, então a fila de verdade é o SQLite do carro e nada se perde num corte de 4G. A sala está em rede fixa e ligada durante a aula, e o carro só precisa fazer conexão de saída, que é o que funciona melhor com CGNAT.

A base fixa só vale a pena se mais de um computador (várias salas, painel do Willian etc.) for receber os dados ao mesmo tempo, ou se a sala não puder ficar ligada. Nesse caso, use a configuração de fila sem limite de [`mosquitto-sala.conf`](mosquitto-sala.conf) também na base.

### Instalar o broker na sala

1. Instalar o Mosquitto (mosquitto.org/download, versão Windows). Ele vira o serviço "Mosquitto Broker".
2. Criar a pasta `C:\mosquitto\dados\`.
3. Copiar [`docs/mosquitto-sala.conf`](mosquitto-sala.conf) por cima de `C:\Program Files\mosquitto\mosquitto.conf` e reiniciar o serviço.
4. Liberar a porta 1883 para a VPN (PowerShell como administrador):

   ```
   New-NetFirewallRule -DisplayName "TE251 MQTT (VPN)" -Direction Inbound -Protocol TCP -LocalPort 1883 -RemoteAddress 10.69.0.0/16 -Action Allow
   ```

5. Na sala, rodar a réplica e o telão:

   ```
   set TE251_MODO=teatro & set TE251_DB=teatro.db & set TE251_BROKER=127.0.0.1
   python -m te251.enlace replicar
   python -m te251.web
   ```

A rede ZeroTier é privada (só entra quem o Willian autoriza), por isso o broker começa sem senha. Para exigir senha, siga os comentários do `.conf` e defina `TE251_MQTT_USUARIO` e `TE251_MQTT_SENHA` nos dois computadores.

## 4. O que testar no 4G

Todos com o PC do Vitor ligado no 4G do celular (roteador ou USB) e a sala na rede fixa. Anote operadora, local e horário.

| # | Teste | Como | Passa se |
| --- | --- | --- | --- |
| 1 | Latência e perda | `ping -n 600 <ip-da-sala>` (10 minutos), parado e depois com o carro andando | perda < 2%, média < 300 ms |
| 2 | Direto ou relay | `zerotier-cli peers` no 4G | anotar `DIRECT`/`RELAY`; `RELAY` não reprova, mas explica latência alta |
| 3 | Corte e volta | com o enlace rodando, pôr o celular em modo avião por 30 s e por 5 min | o ping volta sozinho em menos de ~30 s e a sala volta a receber dados sem ninguém mexer |
| 4 | Nada se perde | simulador + enlace por 30 min com 2 ou 3 cortes; depois contar linhas da tabela `sample` nos dois bancos | mesma quantidade nos dois lados, sem duplicadas |
| 5 | Idade do dado na sala | durante um corte, perguntar à IA da sala "O motor está esquentando?" | a resposta avisa há quanto tempo o dado foi lido |
| 6 | Consumo de dados | ver o contador do celular antes e depois de 1 h | estimativa: poucos MB por hora (7 PIDs por segundo, cada mensagem com ~100 bytes) |
| 7 | Rede do ITA e Teatro Weiss | repetir o teste 1 com a sala na rede do ITA e o celular dentro/perto do Teatro | a rede do ITA pode bloquear UDP; se o ZeroTier não conectar, pedir liberação da porta UDP 9993 |
| 8 | Duas operadoras | repetir 1 e 3 com um chip de outra operadora | escolher a que cair menos |

Para contar as linhas (teste 4), nos dois computadores:

```
python -c "import sqlite3; print(sqlite3.connect('te251.db').execute('select count(*), max(seq) from sample').fetchone())"
```

(Na sala, troque `te251.db` por `teatro.db`.)

## Comandos úteis do ZeroTier

```
zerotier-cli info            # meu endereço e se o serviço está ONLINE
zerotier-cli listnetworks    # redes em que estou, status e IP
zerotier-cli peers           # computadores vistos e se a ligação é DIRECT ou RELAY
```

No Windows, abra o PowerShell como administrador. Se o comando não for encontrado, use o caminho completo: `"C:\Program Files (x86)\ZeroTier\One\zerotier-cli.bat"`.
