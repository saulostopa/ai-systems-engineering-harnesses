# Guia do ADK Web e achados do piloto AdFixus

Registro do piloto AdFixus no Catálogo em 20/11/2026. A interface usa ADK Python 2.14.1, app `feature_planner` e sessão `catalogo-piloto-adfixus`. Essa sessão tem quatro invocações. Cada invocação é uma rodada iniciada por uma mensagem.

## Ícones na lista de eventos

A letra vem do primeiro caractere alfanumérico do nome do nó que emitiu o evento. O ADK Web calcula a cor a partir do nome desse nó e do tema. Duas etapas com a mesma inicial podem ter cores diferentes. Para identificar a etapa, abra o evento e confira **Node Path** em **Info** ou o caminho em `nodeInfo.path` no JSON do evento. Na base SQLite, o campo se chama `node_info.path`.

### Legenda observada na sessão

| Avatar | Nó | O que o evento registra |
| --- | --- | --- |
| Pessoa | Mensagem do usuário | Pedido que iniciou a invocação. |
| **R** verde-claro | `route_mission` | Encaminhamento inicial do pedido. |
| **R** verde-escuro | `retrieve_context` | Recuperação de contexto no índice do Postgres. |
| **R** verde-água | `request_model` | Tentativa de chamada ao modelo. Pode aparecer tanto dentro do planner quanto dentro de um corte. |
| **P** vermelho | `plan_slices` | Proposta dos cortes ou saída por bloqueio. |
| **V** | `validate_plan` | Validação da estrutura, das referências e das dependências do plano. |
| **I** vermelho | `investigate_slice` | Evento de investigação ou verificação de um corte no fluxo histórico. |
| **D** verde-água | `dispatch_slices` | Encaminhamento dos cortes conforme suas dependências. |
| Robô vermelho | `investigate_slice` | Mensagem do agente sobre um corte. |
| Robô azul | `stop_planning` | Mensagem de encerramento da rota de bloqueio. |
| Robô amarelo | `evaluate_feature` | Mensagem com o resultado geral do workflow histórico. |

As cores acima foram observadas no tema usado no piloto. O **P** vermelho no evento 15 registra `blocked` com rota `stop`. O **R** verde no evento 14 registra `unavailable`. Para ler o resultado, consulte o `status`, o veredicto do corte ou a rota do evento.

O grafo atualizado tem o subworkflow `slice_investigation`, com `attempt_slice`, `verify_slice` e `record_slice`, e lida com a síntese em `synthesize_feature`. O histórico do primeiro piloto preserva os caminhos do fluxo que o executou.

## Ícones do painel lateral

| Ícone ou aba | O que mostra |
| --- | --- |
| **i** | Informações sobre o evento selecionado. |
| **Graph** (nós conectados) | Estrutura do workflow e caminho registrado até o evento selecionado. Use as setas do painel ou selecione outro evento para avançar ou voltar na execução. |
| **Request** e **Response** (setas) | Pedido e resposta do LLM associados ao evento, quando a instrumentação disponibiliza esses dados à interface. |
| **Metadados** (barras) | Metadados da execução que o ADK registrou para o evento. |
| **Estado** (setas circulares) | Alterações de estado associadas ao evento. A aba **State** mostra o estado da sessão. |
| **JSON do evento** (chaves) | Registro bruto do evento, incluindo o caminho do nó quando disponível. |
| **Traces** | Hierarquia e duração das operações que foram instrumentadas. |
| **Artifacts** | Arquivos publicados na sessão, como o Replay e o relatório de tokens. |
| **Evals** | Casos e resultados de avaliação executados no ADK. |

Na lista de eventos, o selo **route** mostra a transição escolhida, como `stop`. No **Graph**, o destaque muda ao selecionar um evento. Os losangos representam decisões de rota. `[NO DEFAULT]` indica que não foi configurada uma transição padrão para resultados sem correspondência. A transição `stop` é uma rota explícita.

### Como abrir Request e Response

As abas ficaram vazias no primeiro piloto porque o cliente próprio do harness
emitia eventos de rota sem associar ao evento um trace de modelo. No fluxo
atualizado, cada tentativa concluída em `request_model` tem um span
`generate_content` vinculado ao ID do evento. Uma tentativa indisponível ou
sem cota registra o status e, quando há fallback, a próxima tentativa ganha
seu próprio evento.

1. Abra uma sessão nova em uma instância do ADK Web com o código atualizado.
2. Abra **Traces**, clique no span `generate_content` desejado e, no painel lateral, clique no link em **Event ID**. O ADK volta a **Events** com o evento da chamada selecionado.
3. Abra **Request** para ver papel, modelo, esforço, tentativa, schema e IDs dos trechos. Abra **Response** para ver o status, a categoria de falha quando disponível, a duração, os contadores disponíveis e a projeção estruturada da saída, como dependências do plano ou veredicto.

O nó `request_model` também emite um evento de saída que resume o resultado
do nó. Esse evento pode mostrar `succeeded` e deixar as abas vazias. O link
**Event ID** do trace aponta para o evento que contém os detalhes da chamada.

Os detalhes usam campos selecionados. A missão, instruções, código recuperado,
texto livre da resposta e credenciais ficam fora dessa projeção. A aba
**Artifacts** continua sendo a referência para o relatório consolidado e a
evidência do Postgres. Os traces são mantidos pelo servidor local, e o histórico
do primeiro piloto conserva os eventos que foram produzidos naquela rodada.
[Tracing do ADK](https://adk.dev/observability/traces/)


### Filtro por caminho

O seletor agrupa os eventos pelo caminho no workflow. Ele omite os sufixos de instância, como `@1`, que aparecem no JSON. Estes caminhos foram observados na captura da sessão histórica.

| Caminho | O que isola |
| --- | --- |
| `feature_planning/route_mission` | Roteamento do pedido. |
| `feature_planning/retrieve_context` | Busca no Postgres. |
| `feature_planning/plan_slices/request_model` | Tentativas do modelo do planner. |
| `feature_planning/plan_slices` | Proposta de plano e sua rota de saída. |
| `feature_planning/stop_planning` | Encerramento do pedido bloqueado. |
| `feature_planning/validate_plan` | Validação do plano. |
| `feature_planning/dispatch_slices/investigate_slice` | Investigação ou verificação de um corte. |
| `feature_planning/dispatch_slices/investigate_slice/request_model` | Modelo chamado dentro do corte. |
| `feature_planning/dispatch_slices` | Despacho dos cortes e controle das dependências. |
| `feature_planning/evaluate_feature` | Resultado geral da execução histórica. |

## Exemplo para a apresentação

1. Em **Events**, selecione a invocação 2 e o evento **14**. `request_model` terminou como `unavailable`.
2. No evento **15**, abra **Graph**. `plan_slices` marcou `blocked` e seguiu a seta `stop`.
3. No evento **16**, o robô exibiu a mensagem de encerramento. O campo `evidence_bundle.status` indica `published` porque os artefatos da execução bloqueada foram publicados. O resultado do planejamento continua sendo `blocked`.
4. Na invocação 4, compare o evento **30**, em que a chamada do planner terminou como `succeeded`, com o evento **43**, em que a avaliação encerrou como `needs_review`. O primeiro corte foi rejeitado e os dois dependentes foram pulados.

Para a apresentação, mostre o caminho do nó, a rota e o status. As entradas e saídas podem conter trechos do repositório.

## Quando os dados entraram no Postgres

Horário de Brasília em 20/11/2026. A sequência foi conferida pelos timestamps da sessão local do Claude Code, por `index.log` e pelo histórico do ADK.

| Hora | Registro |
| --- | --- |
| 15:09:13 | Pedido inicial no Claude Code Desktop. |
| 15:13:35 | Primeira tentativa de indexação registrada no transcript. |
| 15:17:52 | Claude relançou a indexação. Às 15:18:24, o log já registrava 32 de 190 embeddings. |
| Até 15:22:40 | O log confirmou 190 chunks embeddados a partir de um escopo de 52 arquivos com `qwen3-embedding:4b` via Ollama. A fonte era uma worktree da `main` do Catálogo na revisão-base congelada. |
| 15:23:10 | Primeira invocação do ADK. Os vetores de documentos já estavam no Postgres do piloto. |
| 15:29:12–15:29:16 | Índice reduzido para 37 arquivos. O log registrou 15 remoções e zero embeddings novos. |
| 15:34:01 | Início da quarta invocação. O recibo registrou 169 chunks disponíveis, seis trechos preparados para o planner e três para o verificador. |

O indexador quebra arquivos em trechos e grava texto, vetores e metadados no Postgres. Em cada invocação, `retrieve_context` gera o vetor da **pergunta** e consulta o índice existente por busca híbrida. Essa etapa reutiliza os vetores dos arquivos. O portal de referência foi consultado diretamente pelo Claude nessa rodada. O Postgres do RAG guardava o índice do Catálogo. O Postgres de homologação citado na validação do portal de referência guardava os registros funcionais de consentimento. [Implementação da busca](../feature_planner/postgres.py#L26)

## Referências E1 a E6 no Replay

`E1` a `E6` identificam os trechos recuperados para aquele contexto do piloto. Em `postgres-evidence.json`, busque o ID para conferir arquivo, intervalo de linhas, posição na busca e hashes. Os IDs são locais à invocação. Eles indicam quais trechos foram preparados para a chamada ao modelo. Para saber quais trechos sustentam um achado, confira as referências que o resultado registrou.

## Modelos e contagem de tokens

| Camada | Modelo usado | Onde conferir |
| --- | --- | --- |
| Claude Code Desktop, que investigou os repositórios e implementou o porte | **Claude Opus 5.5** (`claude-opus-5-5`) | Campo `message.model` no transcript da sessão local. |
| Planner do ADK, rodadas 1 a 3 | `qwen2.5:14b` via Ollama | Eventos do ADK, com as três rodadas encerradas como `blocked`. |
| Planner do ADK, rodada 4 | `llama3.1:8b` via Ollama | `token-usage.md` registra 3.503 tokens de entrada e 548 de saída. |
| Verificador do ADK, corte 1 da rodada 4 | `qwen2.5:14b` via Ollama | `token-usage.md` registra 1.548 tokens de entrada e 77 de saída. |
| Embeddings do RAG | `qwen3-embedding:4b` via Ollama | `index.log` e `postgres-evidence.json`. |

O `token-usage.md` é produzido a partir dos eventos de modelo de uma invocação do ADK. Por isso, o relatório da rodada 4 tem somente as duas chamadas ao Ollama. Os tokens do Claude Code Desktop pertencem à sessão de implementação, com telemetria própria. Uma nova invocação do ADK com Claude Code/Haiku pode registrar o consumo dessa rota quando o adaptador receber os contadores. A sessão histórica mantém a medição original.

No segundo piloto, a tabela consolidada é gerada após a implementação. Ela reúne invocações do ADK, a sessão do Claude Code Desktop com seus subagentes e o ledger de embeddings. O comando de fechamento pode publicar o arquivo na aba **Artifacts**. [Como fechar a medição do piloto](../README.md#4-close-out-pilot-usage)

A economia de contexto no relatório compara um cenário hipotético de corpus inteiro com os trechos selecionados pelo RAG. O cálculo usa bytes do texto para estimar tokens. Mantenha esse número separado do consumo reportado pelo modelo, do custo de embeddings e do preço de API equivalente.

## Modelos de embeddings para a apresentação

O piloto usa `qwen3-embedding:4b` no Ollama e armazena vetores normalizados de 1.024 dimensões no Postgres. Modelo de embeddings é uma configuração da busca. Planner, executor e verificadores podem trocar de modelo de geração sem recriar o índice, desde que a configuração de embeddings permaneça a mesma.

| Empresa | Modelo ou alternativa | Via Ollama local | Dimensões e impacto no Postgres |
| --- | --- | --- | --- |
| Anthropic | A Anthropic indica a Voyage AI como fornecedora de embeddings. Exemplo do parceiro, `voyage-4`. | A opção documentada usa a API da Voyage. | 1.024 por padrão. Exige adaptador e reindexação. [Anthropic](https://platform.claude.com/docs/en/build-with-claude/embeddings) |
| OpenAI | `text-embedding-3-small` e `text-embedding-3-large` | Disponíveis pela API da OpenAI. | 1.536 e 3.072 por padrão, respectivamente. Aceitam pedir 1.024 via `dimensions`. Exigem adaptador e reindexação. [OpenAI](https://developers.openai.com/api/docs/guides/embeddings) |
| Google | `gemini-embedding-2` | Disponível pela API do Gemini. | 3.072 por padrão, com saída configurável. Avalie a dimensão escolhida e a integração antes de indexar. [Google Gemini](https://aistudio.google.com/docs/embeddings) |
| Google | `embeddinggemma-2:270m` | Publicado no catálogo do Ollama. A execução na máquina do piloto está por validar. | Até 768 dimensões. Exige índice e armazenamento preparados para 768. [Google](https://gemma.ai/models/embeddinggemma/model-card-v2/) · [Ollama](https://registry.ollama.com/library/embeddinggemma-2) |

Referências consultadas em 20/11/2026. Confirme catálogo, integração e acesso antes de selecionar a rota de produção.

### Regras para uma troca de embeddings

1. Registre provedor, modelo e revisão, dimensão, normalização, instruções específicas para consultas e documentos, versão do chunking e a revisão do código e da política de dados. Guarde os hashes do manifesto para reproduzir a ingestão.
2. Prepare um índice independente e reembede o Catálogo e as referências autorizadas do portal de referência e do harness. Use a mesma configuração para as consultas desse índice. Cada modelo tem seu espaço vetorial, inclusive quando dois produzem 1.024 dimensões. Vetores de 768 precisam de uma coluna e um índice dessa dimensão.
3. Compare com o índice vigente usando as mesmas perguntas, fontes esperadas e escopo. Meça recuperação de evidências, isolamento entre projetos, latência e custo de ingestão e de consulta. Para API externa, aprove previamente o envio dos textos e das consultas.
4. Troque juntos o índice ativo e o embedder das consultas. Mantenha o par anterior pronto para rollback. Em caso de indisponibilidade, consulte outro índice previamente construído com o modelo daquela rota ou sinalize a falha de recuperação.

[Procedimento operacional no harness](../README.md#changing-the-postgres-embedding-model)

## O papel de architecture.json

O publicador copia o [manifesto de arquitetura](../feature_planner/architecture.json), com componentes e conexões do harness, para a pasta de evidências. O Archify lê esse arquivo e renderiza `architecture.html`. O `architecture-receipt.json` registra o resultado da validação do artefato. A rodada 4 teve nove checks aprovados.

Para a apresentação, use `architecture.html` para explicar o desenho do harness. Use **Graph** e `replay.html` para mostrar o que uma invocação executou. `architecture.json` é a entrada de renderização do Archify. A lógica do grafo roda a partir de [workflow.py](../feature_planner/workflow.py). [Publicador de evidências](../feature_planner/evidence.py#L96)

## Resultado do primeiro piloto

- A primeira implementação ficou em uma branch de feature, sobre a revisão-base congelada. A auditoria reproduziu 2.460 testes unitários em 227 arquivos e a checagem do TypeScript com Node 22.
- O Playwright local do Catálogo registrou 60 verificações aprovadas em 65 executadas com shim de CORS, quatro verificações puladas e 4/4 no bloco separado de filtros. O portal de referência teve 61/65 no mesmo ambiente local. A execução foi headless. Os logs locais registram a cobertura desse ambiente.
- A rodada 4 do ADK terminou como `needs_review`. O verificador recebeu E2, E4 e E6, trechos do layout e do teste de layout anteriores à feature, e rejeitou o primeiro corte. Os dois cortes dependentes foram pulados. A revisão de código do próximo piloto precisa do diff ou de evidências da implementação candidata.
- **Correção de escopo.** A API de consentimento do portal de referência já estava validada em homologação. Incluir a sincronização na lista de critérios de paridade evita que o planner trate a funcionalidade como opcional.
- A aprovação para um deploy do Catálogo em homologação ainda está pendente. A validação já feita em homologação é do portal de referência e serve de referência funcional para o Catálogo.

## Segundo piloto

1. Usar uma worktree nova, como `catalogo-pilot-v2`, criada a partir da revisão-base da `main`. Preservar a primeira worktree como referência.
2. Usar uma sessão e um projeto de índice próprios para o novo piloto. Planejar com a `main` do Catálogo e usar o portal de referência de homologação como referência explícita. Incluir a sincronização de consentimento no critério de paridade e levantar a configuração do Catálogo com o backend.
3. Verificar com o diff candidato e os resultados de teste. Registrar no ADK o modelo, a rota, os trechos consultados e os veredictos por corte. Identificar a telemetria da sessão implementadora separadamente.
4. Aproveitar as verificações locais e o acesso autorizado ao ambiente de teste. Após a aprovação de homologação, repetir os testes ponta a ponta no domínio do Catálogo, com evidências de rede, consentimento e persistência comparáveis às do portal de referência.

### Primeira rodada do segundo piloto

A rodada real do AdFixus de 20/11/2026 usou Claude Haiku 5.5 e confirmou
**Request** e **Response** no evento 5 do planner. A chamada levou 21,854 s.
O planner propôs cinco cortes e a estrutura passou pela validação. O resultado
geral ficou em `needs_review`, com um corte aceito, dois rejeitados após
indisponibilidade do verificador e dois pulados por dependência.

O RAG recuperou seis trechos da `main`, centrados em configuração, Adobe Target,
rodapé e rotas. Nenhum descrevia a API de Consentimento do portal de referência em homologação. O plano
acabou propondo mudanças de Adobe e roteamento e deixando parte do AdFixus como
lacuna. Para usar o plano como base de implementação, primeiro forneça uma
referência funcional autorizada do portal de referência e confira a cobertura do objetivo.

Os nove artefatos da rodada foram publicados. O ledger também registrou o
embedding da consulta. Os vetores dos arquivos foram reutilizados por hash.


### Evidências do portal de referência em corpus de referência

O planner pode consultar a `main` do Catálogo e os dois projetos de referência
no mesmo Postgres. `HARNESS_PLANNER_RAG_REFERENCES` recebe os nomes dos projetos
separados por vírgulas. Cada consulta usa o mesmo vetor da pergunta e recupera
até quatro trechos por projeto por padrão. O limite do projeto alvo pode ser
configurado por `HARNESS_PLANNER_RAG_TARGET_TOP_K`. O Piloto 3 usa até dez
trechos do Catálogo. Nos projetos de referência, a busca reserva até dois dos
quatro trechos para código quando houver trechos disponíveis.
O recibo Postgres e o Request identificam
o projeto e a origem de cada trecho. O escopo dos cortes é derivado apenas das
fontes do Catálogo. O código do portal de referência, os documentos do harness e a memória
relevante atuam como referências funcionais de leitura.

### Iniciar pelo ADK Web

1. No [procedimento do piloto](../README.md#run-the-postgres-evidence-pilot), use um diretório e projeto de índice próprios para o segundo piloto. Fixe a fonte de planejamento na revisão da `main` e mantenha a worktree da feature para o diff. Exporte `HARNESS_USAGE_DIR` antes de indexar.
2. Suba o ADK Web com o projeto e o perfil de modelos do piloto. Para manter a sessão antiga aberta em paralelo, use outra porta e arquivos próprios de sessão e artefatos.
3. Abra a URL local, selecione `feature_planner` e clique em **New Session**. Envie o objetivo, a referência do portal de referência em homologação, o requisito de sincronização de consentimento e os critérios de teste do Catálogo.
4. Em **Events**, selecione a última invocação e abra **Graph**. Acompanhe o planner, a validação e os subworkflows de investigação. Inspecione `workflow-spec.json` em **Artifacts** para ver o plano e suas dependências.

No fluxo atual, iniciar pelo ADK roda planejamento e investigação em modo de leitura. Uma sessão do Claude Code ou Codex iniciada à parte só aparece no histórico do ADK quando chama o workflow. A tabela de fechamento importa o histórico selecionado do Claude Desktop depois da execução.

### Missão para colar em New Session

Use o objetivo do prompt do Claude Code Desktop em formato de missão para
planejamento. O projeto RAG e a revisão da `main` vêm da configuração do
piloto. Coloque no texto os requisitos do portal de referência que o índice do Catálogo
não conhece.

```text
Planeje o porte do AdFixus para o Catálogo a partir da main indexada, sem editar arquivos. Use o portal de referência em homologação como referência funcional. A paridade inclui a API de Consentimento e a sincronização com o backend.

Proponha até cinco cortes verticais com critérios de aceite, dependências e evidências do índice. Cubra a proteção da URL sem perder filtros do Catálogo, o carregamento do SDK, o banner, aceite, recusa, retirada e reconsentimento, a identidade entre visitas e a persistência do consentimento. Inclua build de produção, testes locais e validações em domínio próprio com QA após aprovação de homologação.

Registre lacunas sobre o portal de referência e a configuração do Catálogo como pontos a confirmar. Separe as evidências da main das que serão exigidas do diff candidato e dos testes para aprovar a implementação.
```


### Integrar o executor de código ao grafo

1. Manter a recuperação e o `WorkflowSpec` do planner. Adicionar ao plano validado a revisão candidata, os arquivos previstos e os critérios de aceite por corte.
2. Adicionar um subworkflow de implementação por corte no despacho. O ADK cria a execução, aplica as dependências e escolhe o executor. Começar com um adaptador do Claude Code e o limitar à worktree candidata.
3. Ler a saída estruturada do executor. Emitir no ADK eventos de início, ferramentas, resultado e timeout com o ID do corte e os metadados permitidos. As subtarefas que devem aparecer no **Graph** precisam ser ativadas como nós ou subworkflows do ADK. Eventos internos da CLI podem ser correlacionados em **Events** quando o executor os informa.
4. Rodar testes e verificação do diff em nós distintos. Serializar os cortes que alteram os mesmos arquivos. Liberar os cortes dependentes só após o aceite e usar o limite de tentativas para correções.
5. Validar primeiro com uma tarefa sintética e dois cortes reais no grafo, incluindo um caso de falha. Confirmar a sequência em **Events**, a ativação dos subworkflows em **Graph** e a reconciliação das chamadas no relatório. Depois, rodar o AdFixus no Catálogo na worktree do segundo piloto.

[Subworkflows e rotas do ADK](https://adk.dev/graphs/routes/) · [Workflows dinâmicos](https://adk.dev/workflows/dynamic/)

## Custo de API equivalente do piloto AdFixus

Os valores usam o consumo registrado em 20/11/2026 e tarifas públicas de API em dólares. As chamadas do Claude usaram assinatura. A tabela estima o que custariam sob as tarifas indicadas. A cobrança do gateway e os custos de infraestrutura serão medidos quando houver ambiente.

| Etapa observada | Modelo e chamadas | Tokens de entrada nova / leitura de cache / gravação de cache / saída | API com tarifas de cache | Entrada inteira à tarifa padrão |
| --- | --- | --- | ---: | ---: |
| Claude Code Desktop. Sessão de preparação e implementação do porte inicial do Catálogo, com testes locais. | Opus 5.5, 215 respostas únicas | 432 / 65.894.033 / 402.357 / 151.409 | US$ 19,43 | US$ 268,22 |
| ADK + Postgres. Planejamento, investigação e verificação em leitura na primeira rodada do segundo piloto, com o índice inicial do Catálogo. | Haiku 5.5, 7 tentativas com consumo registrado, incluindo 2 indisponíveis | 20 / 33.801 / 53.373 / 17.348 | US$ 0,0157 a 0,0197 | US$ 0,017393 |
| Embeddings locais do ADK. Consulta dessa rodada e ingestão posterior das referências do portal de referência. | Ollama, `qwen3-embedding:4b` | Uma consulta da rodada. 315 novos vetores na preparação posterior do portal de referência. | US$ 0,00 de API externa | US$ 0,00 de API externa |
| ADK + Postgres. Implementação completa do AdFixus no Catálogo com paridade em homologação. | A medir com executor no grafo | A medir por etapa do grafo e do executor | A medir | A medir |

No Desktop, os contadores vieram do transcript local, com deduplicação por ID de resposta. As gravações de cache registradas foram de uma hora. No ADK, os contadores vieram de `execution.json` e `token-usage.md` da invocação analisada. O artefato traz o total de gravação sem o TTL, então a faixa usa as tarifas de cinco minutos e uma hora. A última coluna aplica a tarifa normal de entrada aos tokens novos e de cache, conforme o cálculo de referência do harness. Em US$ por milhão de tokens, o Opus usa 4 para entrada nova, 0,20 para leitura de cache, 8 para gravação de uma hora e 20 para saída. Para o Haiku, todas as tentativas ficaram no nível de até 100 mil tokens de entrada por chamada, com tarifas de 0,10 para entrada nova, 0,01 para leitura de cache, 0,125 a 0,20 para gravação e 0,50 para saída. [Preços públicos da Anthropic](https://platform.claude.com/docs/en/about-claude/pricing)

As duas medições de LLM cobrem escopos diferentes. A rodada do ADK terminou em `needs_review`. A ingestão posterior amplia o contexto disponível para a próxima rodada. Para medir economia de implantação, execute os dois caminhos com a mesma base da `main`, critérios de paridade do portal de referência em homologação, testes e estado final. Some planejamento, execução, verificação, Evals e retrabalho. Registre a ingestão reaproveitável e o custo marginal da consulta em linhas próprias. A diferença estimada entre trechos recuperados e corpus inteiro é uma métrica de contexto. Para medir o efeito do RAG sobre consumo e qualidade, rode também o mesmo workflow e modelo com e sem RAG no mesmo conjunto de casos.

Na produção, use a telemetria do gateway para reconciliar uso e os registros de faturamento para apurar valores. Tag de execução, nó e corte permitem cruzar os registros do gateway com o ledger do harness. Postgres, armazenamento e execução em nuvem entram como custos de infraestrutura. [Databricks AI Gateway](https://docs.databricks.com/aws/en/ai-gateway/usage-tracking)

## Evals para a apresentação

A primeira suíte sintética e os relatórios por invocação estão descritos no [guia do Piloto 3](catalogo-adfixus-pilot3.pt-BR.md).

Use a aba **Evals** para demonstrar o resultado de casos versionados e abrir a evidência de cada falha. O primeiro conjunto disponível em `feature_planner_evals` usa o caso AdFixus, incluindo uma regressão em que a busca devolve documentação forte do Adobe e omite a API de Consentimento. O planner deve apontar a lacuna de paridade antes de liberar a implementação. O `eval_set_1` antigo segue vazio. Selecione `catalogo-adfixus-v1` no app de Evals. Os resultados de testes e de piloto já registrados precisam continuar visíveis como evidências distintas. [Avaliação de agentes no ADK](https://adk.dev/evaluate/) · [Evalset atual](../feature_planner/eval_set_1.evalset.json)

| O que avaliar | O que mostrar à gestão |
| --- | --- |
| Aderência à missão | Critérios cobertos, lacunas explícitas e ausência de cortes fora de escopo. Para AdFixus, inclua o contrato de consentimento do portal de referência em homologação e a preservação de filtros do Catálogo. |
| Recuperação e fundamentação | `recall@k` dos trechos esperados por corpus, citações resolvíveis por projeto, caminho e hash e falhas de isolamento. |
| Execução do grafo | Dependências respeitadas, tentativas e fallback, chamadas realmente executadas e relação entre corte, revisão e diff. |
| Qualidade da entrega | Build, tipagem, testes unitários, de contrato e Playwright. Registre em qual ambiente houve evidência de GET do SDK, POST de consentimento e persistência, e quais validações aguardam homologação. |
| Segurança | Bloqueio de injeções, vazamento de dados, escrita fora do escopo e ações sem autorização. Falhas críticas bloqueiam a entrega. |
| Eficiência | Duração, tentativas, tokens por etapa, custo de API equivalente, custos do gateway quando disponíveis e retrabalho. Mostre o tamanho da amostra junto com os indicadores. |

Proponho a skill **Eval Results** para consolidar os resultados da suíte em `eval-results.json` e `eval-summary.md`. O resumo deve trazer aprovados, reprovados, bloqueados e casos sem execução, limiares, gravidade, fontes de evidência e ação necessária. Registre as versões do conjunto de testes, da revisão do código, do índice e da política aplicadas. Se houver avaliação por modelo, registre também o juiz e a versão da rubrica. [Especificação no backlog](backlog/adk-evals-results.md)

## Roteiro para a apresentação

### De onde vem a arquitetura

O harness usa o mesmo padrão arquitetural de orquestração por grafo ilustrado
em LangChain/LangGraph. Nós de código e nós de modelo usam estado explícito,
com rotas para organizar planejamento, despacho, verificação e síntese. A
implementação roda no Google ADK. Inspirado nos Dynamic Workflows da Anthropic,
o grafo mantém as etapas de controle em código e usa um `WorkflowSpec` gerado
para definir os cortes, suas dependências e os critérios de aceite de cada
missão. O plano validado determina quais investigações podem avançar em
paralelo. Há limite de tentativas e verificação independente por corte.
[LangGraph](https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph) · [Dynamic Workflows da Anthropic](https://code.claude.com/docs/en/workflows) · [Dynamic Workflows no guia de Florian Bruniaux](https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/main/guide/workflows/dynamic-workflows.md) · [Loop e Graph Engineering no guia de Florian Bruniaux](https://github.com/FlorianBruniaux/claude-code-ultimate-guide/blob/main/guide/core/loop-graph-engineering.md)

### Onde ficam os loops e o despacho dos cortes

O grafo `feature_planning` encadeia recuperação, planejamento, validação,
despacho, avaliação global e síntese. O subgrafo `slice_investigation` contém
a aresta de retorno de `verify_slice` para `attempt_slice`. Ela é percorrida
quando o verificador pede `retry` e ainda resta uma tentativa. O limite
atual é de duas tentativas por corte de investigação. Para conferir na
interface, selecione uma invocação que teve retry, filtre os eventos de
`dispatch_slices` e compare o mesmo ID de corte nas tentativas 1 e 2.
[Subgrafo em workflow.py](../feature_planner/workflow.py#L340) · [Loops no ADK](https://adk.dev/graphs/dynamic/#loop-route)

`dispatch_slices` percorre as dependências em Python e chama o mesmo
subgrafo com `ctx.run_node(..., use_sub_branch=True)` para cada corte
liberado. Reúne até dois cortes independentes por lote com
`asyncio.gather`. Quando o plano é uma cadeia, cada lote tem um corte.
O `WorkflowSpec` define a quantidade e as dependências de cada missão.
O código rejeita dependências circulares. Essa regra se aplica ao plano
dos cortes, enquanto o retry pertence ao subgrafo de investigação.
[Despacho em workflow.py](../feature_planner/workflow.py#L346) · [Execução paralela no ADK](https://adk.dev/graphs/dynamic/#parallel-execution-routes)

No LangChain, **Single dispatch tool** é uma ferramenta `task`
parametrizada que o agente supervisor chama para escolher um subagente.
No anúncio de Dynamic Subagents, o modelo escreve a orquestração e chama
`task()` a partir do interpretador. Nosso ponto de despacho é um nó
ADK com controle em Python e papéis definidos pelo harness. O planner
produz dados estruturados para a orquestração. O exemplo **Custom RAG
Workflow** é a referência mais próxima para a composição de busca e
agentes em nós explícitos. Aqui, a recuperação obrigatória combina busca
lexical e semântica no Postgres e registra a origem e o hash dos trechos.
[Single dispatch tool](https://docs.langchain.com/oss/javascript/langchain/multi-agent/subagents#single-dispatch-tool) · [Dynamic Subagents](https://www.langchain.com/blog/introducing-dynamic-subagents-in-deep-agents) · [Custom RAG Workflow](https://docs.langchain.com/oss/javascript/langchain/multi-agent/custom-workflow#custom-rag-workflow)

No piloto v5, o plano aprovou `pacote → frontend → bff`, todos na
primeira tentativa. Numa invocação anterior, `pacote` foi aceito na
segunda tentativa. Nesse mesmo piloto, o executor ADK processou três
invocações de execução na mesma sessão. Cada uma revisou e aplicou seu
patch autorizado, verificou o diff e publicou o resultado dos testes.
O runner local disparou essas invocações em sequência. A avaliação
global encerra o planejamento com um veredicto. Uma eventual rodada
de replanejamento é uma nova invocação.

Para a apresentação, use **harness com controles verificáveis** como
descrição técnica de “Harness Hard”. O RAG ancora as decisões em fontes
do projeto. O schema, a revisão e os testes estabelecem as condições
para avançar. O piloto mostrou bloqueios e aprovações rastreáveis.
Uma comparação com a mesma tarefa executada sem esses controles permite
medir quanto diminui a taxa de afirmações sem evidência ou de alterações
incorretas aceitas.

### ADK como nossa IDE de IA

A direção é usar o ADK Web como a IDE de IA da equipe para iniciar missões e
acompanhar o trabalho dos agentes em **Events**, **Graph**, **Traces** e
**Artifacts**. O plano é acessar os modelos pelo API Gateway do Databricks e
correlacionar as medições disponíveis do gateway com a invocação, o nó e o
corte do ADK. O piloto v5 usa as rotas locais e as CLIs configuradas. O executor ADK
já aplica e testa patches previamente autorizados. A migração das chamadas
ao gateway segue no plano. [Medição de uso no Databricks](https://docs.databricks.com/aws/en/ai-gateway/usage-tracking)

### Execução noturna na nuvem

A próxima etapa prevista é executar o grafo completo e os testes em ambiente
isolado, com Databricks AI Gateway servindo as chamadas de modelo e o runtime
de execução a confirmar com a plataforma. A oferta informada inclui ECS.
A janela noturna depende de um executor integrado, políticas de segurança
testadas, Evals e critérios de CI. Após a rodada, a equipe recebe o diff,
as evidências e os custos para revisão humana. [Feature no backlog](backlog/adk-databricks-cloud-execution.md)

### Quatro anos de mudança na prática

Use esta sequência como história de adoção da equipe entre 2022 e 2026. As
práticas coexistem e as datas de lançamento foram parcialmente simultâneas.

| Etapa | O que passou a ser possível |
| --- | --- |
| Chat e copiar/colar | Perguntar no chat, levar a sugestão para a IDE e testar manualmente. [Apresentação do ChatGPT](https://openai.com/index/chatgpt/) |
| Assistência na IDE | Receber sugestões enquanto se trabalha no arquivo e reduzir a troca de contexto. [GitHub Copilot](https://github.blog/news-insights/product-news/github-copilot-is-generally-available-to-all-developers/) |
| Vibe coding | Descrever a intenção e iterar a partir do que a ferramenta gerou, especialmente em protótipos. |
| Skills | Empacotar instruções, exemplos e scripts para repetir tarefas com o mesmo método. [Agent Skills](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills) |
| Agentes | Delegar etapas com ferramentas, leitura de contexto e geração de alterações. |
| Workflows e subagentes | Definir etapas repetíveis e delegar partes independentes a agentes com contexto e critérios próprios. [Sistema multiagente da Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system) |
| Grafos | Tornar visíveis as dependências, a execução em paralelo, os pontos de decisão, as tentativas e a verificação. [Workflows no ADK](https://adk.dev/workflows/) |

### Evidências para mostrar ao vivo

1. **Entender o plano.** Abra o `WorkflowSpec`, mostre como a missão virou cortes e selecione uma dependência no Graph. Na rodada aprovada, mostre as dependências entre os cortes. Numa invocação anterior, selecione o mesmo corte em duas tentativas para demonstrar o retry. Use os recibos de execução para mostrar a aplicação e os testes dos patches autorizados.
2. **Seguir uma decisão.** Selecione a tentativa final de `request_model` e mostre Request, Response e o span em Traces. Use uma missão sintética ou uma versão aprovada para a apresentação.
3. **Ligar resposta à fonte.** Use E1 a E6 no `postgres-evidence.json` para explicar arquivo, linhas e hash. Mostre que a `main` responde pelo planejamento e que o diff candidato e os testes sustentam a revisão da mudança.
4. **Mostrar o resultado e o custo.** Use Archify para o desenho do harness, Replay para a execução, FAQ e Quiz para revisar o aprendizado, e `pilot-token-usage.md` para separar consumo medido, API equivalente, cobrança confirmada e economia estimada.
5. **Fechar com o caso AdFixus.** Explique a diferença entre smoke local do Catálogo e validação do portal de referência em homologação. Inclua sincronização de consentimento nos critérios do segundo piloto e mantenha visível o que exige homologação.
6. **Mostrar como medir qualidade.** Na aba **Evals**, abra o caso de regressão e siga o link para a evidência. Use o resumo de resultados para apresentar cobertura, bloqueios e aprovações quando o conjunto estiver implementado.


A associação das letras e cores foi conferida no código da interface instalada e no histórico da sessão do piloto. As tonalidades e o comportamento das abas Request e Response incluem as observações do responsável pela demonstração. [ADK Web](https://adk.dev/runtime/web-interface/) · [Eventos](https://adk.dev/events/) · [Traces](https://adk.dev/observability/traces/) · [Rotas do grafo](https://adk.dev/graphs/routes/)
