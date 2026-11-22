# Evals e relatório de resultados para o feature planner

Status **primeiro corte disponível para o Piloto 3**

O primeiro conjunto deve usar uma missão AdFixus com dados sintéticos e referências sanitizadas, fixadas por commit. Inclua casos positivos com paridade suficiente, casos sem a evidência da API de Consentimento e um corpus com documentação Adobe concorrendo pela busca. O primeiro corte oferece o conjunto sintético versionado `catalogo-adfixus-v1` e o relatório de planejamento sobre a evidência real. As verificações de integração do executor, segurança de ações e produto em ambiente autorizado continuam em backlog. [Como rodar no Piloto 3](../catalogo-adfixus-pilot3.pt-BR.md) [Evals do ADK](https://adk.dev/evaluate/) · [Critérios do ADK](https://adk.dev/evaluate/criteria/)

## Casos iniciais

| Área | Cobertura mínima |
| --- | --- |
| Planejamento | Schema e limites do `WorkflowSpec`, cobertura dos requisitos técnicos e de negócio, dependências válidas, pedido de esclarecimento ou bloqueio quando faltar evidência. Use uma rubrica de aderência à missão para a resposta final e valide o schema em código. |
| RAG | Recuperação de fontes esperadas por corpus (`recall@k`), resolução de projeto, caminho, linhas e hash, citações sustentadas pelo trecho e rejeição de fontes fora do escopo. |
| Grafo e ferramentas | Valide ordem parcial de dependências, retry limitado por corte, retomada, fallback em falta de quota ou timeout, resultado dos cortes e efeitos persistidos. Use `tool_trajectory_avg_score` em casos com sequência estável de chamadas. |
| Produto | Teste preservar filtros e higienizar a URL, ciclo de consentimento e revogação, identidade entre visitas e persistência da API. Associe resultados de CI, contratos de backend e Playwright ao ambiente e à revisão exatos. Use registros de teste no ambiente aprovado. |
| Segurança | Prove que instruções recuperadas e saídas de ferramentas não ampliam privilégios. Teste vazamento de dados sintéticos e segregação de corpus, escrita fora da worktree, acesso indevido à rede e tentativa de publicar ou promover sem autorização. |
| Eficiência | Registre tentativas, wall time, latência por etapa, uso de entrada, cache e saída e custo. Com amostra suficiente, calcule p50 e p95. Compare com orçamento e versão de referência. |

Para os requisitos de segurança, use verificações determinísticas de autorização e de efeitos observáveis. Avaliações por modelo podem complementar a análise de fundamentação e aderência à rubrica. Configure critérios e limiares antes da execução e revise o conjunto quando o contrato de produto mudar. [Guardrails de dados](adk-rag-data-guardrails.md)

## Skill Eval Results

Proposta de skill que recebe o resultado dos Evals e das suítes de teste e produz `eval-results.json` para automação e `eval-summary.md` para a revisão e a apresentação. Atribua a cada caso um ID, cenário, categoria, limite, resultado, severidade, referências e ação de correção. O cabeçalho deve registrar versão do conjunto, ID e data da rodada, commit e diff, manifesto do RAG, política de guardrails, ambiente, identidade do modelo e esforço. Para critérios por modelo, inclua versão da rubrica e do juiz. Quando existir seed configurável, registre-a.

A visão gerencial deve mostrar cobertura e denominador, estados `passed`, `failed`, `blocked`, `skipped` e `not_run` e divergências frente à baseline. Casos sem execução e condições sem telemetria devem permanecer identificados. Qualquer falha crítica de segurança bloqueia a entrega. Publique somente evidências sanitizadas. Ligue a linha da tabela à invocação do ADK e ao identificador do teste ou recibo que a sustenta.

## Aceite

- Conjunto versionado reproduzível no ADK Web e em CI com um caso aprovado, um caso de evidência insuficiente e um caso de tentativa de quebra de escopo.
- Os dois artefatos reproduzem os mesmos totais e preservam o resultado individual e o controle de acesso de cada evidência.
- O fluxo de CI falha em violações críticas. O resumo mantém visível toda validação de produto exigida e sua situação no ambiente correto.
