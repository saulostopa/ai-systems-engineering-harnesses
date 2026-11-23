# Execução de features na nuvem com Databricks

Status **backlog**

Permitir que um projeto autorizado execute o grafo completo de uma feature em uma janela de madrugada. O ADK orquestra planejamento, execução por corte, verificação e consolidação de evidências. O Databricks AI Gateway é a rota planejada para as chamadas de modelo. O responsável informou uma oferta de execução em ECS. Confirme com a equipe de plataforma quem provisiona e opera o ECS, qual identidade executa o job e quais redes e projetos podem ser acessados. Valide se o runtime será ECS com EventBridge Scheduler, Lakeflow Jobs ou uma integração entre os dois. [ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/tasks-scheduled-eventbridge-scheduler.html) · [Databricks Jobs](https://docs.databricks.com/aws/en/jobs/configure-job) · [Databricks AI Gateway](https://docs.databricks.com/aws/en/ai-gateway/usage-tracking)

## Fluxo e recuperação

1. Comece com execução manual e revisão do diff em um repositório de teste. Habilite a janela noturna por projeto depois do aceite de segurança, definindo fuso, concorrência e política de cancelamento.
2. Receba missão autorizada, repositório, SHA da base, escopo de escrita e critérios de aceite. Fixe a revisão e os manifestos de índice para planejar. Crie uma worktree descartável por invocação para alterações e testes.
3. Valide o plano e execute os cortes autorizados com um executor integrado ao grafo. Registre modelo, rota, tentativas e efeitos por corte. Use limites de tempo, tokens, custo e concorrência. Retome por checkpoint com operações idempotentes e bloqueio por projeto e invocação.
4. Rode build, análise estática, testes unitários, de contrato, E2E e Evals conforme o projeto. Valide o diff antes de publicar evidências sanitizadas. A abertura de PR em rascunho pode ser habilitada por política. Merge e deploy permanecem etapas com aprovação humana.
5. Preserve os IDs do gateway, do job, do ADK, do corte e dos artefatos. Registre o estado final, as falhas e a recuperação. Separe custo de modelos, Postgres, armazenamento e computação. Aplique retenção e limpeza às worktrees e aos artefatos.

## Controles exigidos para o piloto

- Identidade de serviço com menor privilégio, credenciais temporárias em gerenciador de segredos, branch protection, permissões separadas para leitura e publicação e trilha auditável.
- Imagem fixada por digest, processo sem root, dependências verificáveis e varredura de vulnerabilidades. Workspace descartável com controle efetivo de escrita, acesso de rede privado e destinos externos autorizados.
- Escopo de projeto no Postgres e em cada busca de referência. Classificação e mascaramento de dados antes da ingestão e do envio a modelos. Aplique esquemas e políticas no limite de cada ferramenta. Use padrões de detecção, incluindo regex, em conjunto com controles de autorização. Trate entrada do usuário, documentos, logs e respostas de ferramentas como dados não confiáveis.
- Rotas de modelo permitidas por classificação dos dados. Um fallback deve respeitar a mesma política de egress. Mascare dados sensíveis em respostas, traces, logs e artefatos antes de armazenar. Controle acesso, criptografia e retenção.
- Conjunto inicial de ameaças exercitado com dados sintéticos, incluindo instruções vindas do RAG, tentativa de vazar credenciais ou modificar outro projeto, execução de ferramenta ou rede sem autorização, orçamento excedido e falha seguida de retomada.
- Pré-requisitos de entrega vinculados ao [backlog de guardrails](adk-rag-data-guardrails.md) e ao [backlog de Evals](adk-evals-results.md). Bloqueie execução de escrita sem escopo autorizado e promoção com testes críticos reprovados ou sem execução.

## Aceite

- Uma execução de teste em ambiente isolado produz um diff, testes e evidências rastreáveis, com autorização por projeto, revisão humana e custo reconciliável.
- Testes de integração comprovam bloqueios de escrita e saída de dados, isolamento entre execuções, falha segura quando acaba a quota e retomada sem duplicar efeitos.
- A janela noturna é habilitada somente após o ensaio supervisionado e aprovação dos responsáveis por plataforma e segurança. A equipe consegue cancelar a rodada, revogar o acesso e recuperar as evidências.
