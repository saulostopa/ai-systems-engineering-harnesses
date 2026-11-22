# Testes de carga do ADK RAG Harness

Status **backlog** · Feature **adk-load-testing**

Medir quantas missões produzem um resultado aceitável dentro do prazo quando
vários usuários ou jobs executam o harness ao mesmo tempo. Usar essa medição
para definir a capacidade do piloto e os limites da futura janela noturna.

## Cenários

- Comece com o AdFixus em dados sintéticos e a mesma base, manifesto do corpus,
  política de roteamento e conjunto de Evals em todas as rodadas. Rode uma
  missão isolada como referência. Depois faça uma rampa de concorrência, um
  pico curto e uma rodada sustentada. Registre carga, duração, número de
  missões emitidas e orçamento antes do teste.
- Exercite recuperação no Postgres, planejamento, fan-out de cortes
  independentes, verificação e geração de evidências. Use worktrees
  descartáveis e serviços simulados no perfil local. Em ambiente autorizado,
  repita o perfil com o gateway para medir latência, cotas e custo reais
  das chamadas de modelo.
- Simule espera ou indisponibilidade no Postgres, timeout e quota no
  provedor, saturação da fila, cancelamento e retomada. Verifique que cada
  sessão mantém seus próprios dados e recibos, que o número de tentativas
  respeita o limite e que o mesmo patch só é aplicado uma vez.

## Medição

Métrica principal: **missões aceitáveis dentro do prazo ÷ todas as missões
emitidas no perfil**, incluindo a espera em fila. Uma missão positiva é
aceitável quando cumpre a rubrica, preserva o escopo autorizado e entrega
os artefatos exigidos. Nas missões desenhadas para testar bloqueios,
o resultado esperado é o bloqueio com o recibo correspondente. Reporte
esses testes separadamente das missões de entrega.

Registre throughput, p50/p95/p99 de latência quando houver amostra suficiente,
tempo em fila e por nó, erros e timeouts, retries e fallbacks, tokens de entrada,
cache e saída, custo por missão aceitável, saturação de Postgres e lacunas de
telemetria. Correlacione as medições por invocação, corte e rota de modelo.
Fixe o prazo, a rubrica e o limite de carga e custo em configuração versionada
antes do teste.

## Aceite

- Um comando reproduz o perfil local com corpus sintético, parâmetros
  versionados e modelo e serviço simulados. O relatório registra qual
  perfil foi usado.
- A evidência consolida baseline isolada, rampa, pico, execução sustentada
  e falhas. Traz o denominador, os percentis com amostra registrada,
  a primeira carga em que o objetivo deixa de ser cumprido e o principal
  gargalo observado.
- Os cenários de segurança demonstram isolamento entre sessões,
  respeito ao escopo de escrita e ausência de duplicação na retomada.
  O relatório registra os resultados e associa as falhas aos traces.
- A recomendação de concorrência e orçamento da execução noturna usa a
  medição no ambiente autorizado e registra explicitamente os limites
  ainda desconhecidos.

[Guardrails](adk-rag-data-guardrails.md) · [Evals e relatório](adk-evals-results.md) · [Execução na nuvem](adk-databricks-cloud-execution.md)
