# Um único harness ADK + RAG + Postgres, sem Jev

Status **planejado**, aguardando as decisões abaixo antes da fase 2

Juntar `adk-rag-harness` e `adk-rag-postgres-harness` em um único harness e remover o Jev. As experiências com o Jev não foram positivas, e o `feature_planner` já decide pelo grafo ADK, com Ollama, sem Jev. A fusão não pode exigir reindexação nem recálculo de embeddings nos bancos que já existem.

Cada fase é um PR separado. Uma fase só começa depois que a anterior foi integrada na `main`.

## Decisões em aberto

| Decisão | Recomendação |
| --- | --- |
| Nome do harness único | Manter `adk-rag-harness`. O `feature_planner` e os lançadores dos pilotos já usam esse caminho, e o Postgres passa a ser o backend dele. |
| App de perguntas e respostas (`adk_app`) | Manter, sem Jev, decidindo com Ollama, ou remover e ficar só com o `feature_planner`. |
| Resultados de eval do Jev (`adk-rag-postgres-harness/evals/results/*jev*.json`) | Mover para um diretório de histórico ou apagar. Os resultados de Claude Code e agy ficam. |
| Bancos dos pilotos (`catalogo_omh11`, `catalogo_omh11_v2`) | Juntar num banco por organização (`webmotors`), copiando as linhas e os vetores como estão. |

## Modelo de dados: um banco, vários projetos

O harness não cria bancos. Um banco guarda vários projetos: `files`, `chunks`, `symbols`, `edges`, `memories` e `queries` têm `project_id`, e cada servidor MCP serve um único projeto (`--project`). A tabela `embeddings` é um cache por `(content_hash, model)` compartilhado entre projetos. Um banco separado (`--database-url`) serve para isolar uma organização, nunca um projeto.

Estado local no início do plano, no volume `adk-rag-postgres-harness_postgres_data`, porta 5433:

| Banco | Projetos | Embeddings |
| --- | --- | --- |
| `harness_rag` | `biometrik` | 2.007, `ollama:qwen3-embedding:4b` |
| `catalogo_omh11` | `catalogo-omh11` | 382, mesmo modelo |
| `catalogo_omh11_v2` | `catalogo-omh11-v2`, `-v2-ref-fipe`, `-v2-ref-fipe-harness`, `-v4-target`, `-v4-adfixus`, `-v5-target`, `-v5-adfixus` | 492, mesmo modelo |

## Invariantes que mantêm os embeddings válidos

Nenhuma fase pode mudar estes pontos. Se uma mudança for inevitável, ela vira uma fase própria, com reindexação planejada.

| Invariante | Onde está hoje | Por que importa |
| --- | --- | --- |
| Volume Docker `adk-rag-postgres-harness_postgres_data` | `adk-rag-postgres-harness/docker-compose.yml`. O Compose deriva o nome da pasta. | Se o compose mudar de pasta sem nome fixo, o Docker cria um volume vazio. |
| Chave `(content_hash, model)` | `code_chunks.py`, `ingest.py` e o chunker de docs em `rag-harness/rag_harness/chunker.py` | Mudar como o texto é dividido muda o hash e obriga a recalcular. |
| `CHUNKER_VERSION = 2` | `code_chunks.py` | Mudar a versão reindexa todos os arquivos. |
| Id do modelo `ollama:qwen3-embedding:4b` | `embedder_id` em `rag-harness/rag_harness/embeddings.py` | Identifica o espaço vetorial. |
| Instrução de consulta do Qwen3, `fit_dimension` e `EMBED_DIM = 1024` | `adk_rag_postgres_harness/embeddings.py` | Mudam o vetor das consultas e o tamanho da coluna. |
| `search_text` | `store.py` | Alimenta a coluna gerada da busca textual. |
| Nomes das migrações `001` a `004` | `migrations/` e a tabela `schema_migrations` | Uma migração renomeada roda de novo. |
| Nomes e `root` dos projetos | Tabela `projects` | Apontam para os repositórios-alvo, não para o harness. |

## Fases

### Fase 0: proteger e medir

Não muda código de produção.

- Fazer `pg_dump` dos três bancos para um diretório fora do repositório, com a data no nome.
- Fixar o nome do volume no compose: `volumes: postgres_data: name: adk-rag-postgres-harness_postgres_data`. Confirmar com `docker compose config` e `docker volume ls` que nenhum volume novo foi criado.
- Criar um script de impressão digital, só de leitura, que grave por banco: linhas por tabela, sha256 da lista ordenada de `(content_hash, model)` e sha256 da lista ordenada de `(projeto, path, content_hash, chunker_version)`. Guardar o resultado como linha de base.
- Rodar `evals/run_retrieval.py` com `evals/biometrik_questions.json` e guardar o hit@5 atual.

Aceite: dumps restauráveis num banco temporário, impressão digital gravada e hit@5 registrado.

### Fase 1: testes de referência no código atual

- Testes que fixam, para arquivos de exemplo versionados, os hashes de chunk de código e de docs, o `search_text`, o texto da consulta enviado ao modelo e o `embedder_id`.
- Comando `verify-index --project <nome>`, só de leitura: refaz os chunks dos arquivos cujo hash em disco ainda é igual ao do banco e confere os `content_hash` com os do banco. Não grava e não chama o Ollama.

Aceite: os testes passam no código atual e `verify-index` não mostra diferenças em nenhum projeto.

### Fase 2: juntar sem mudar comportamento

- Mover com `git mv` o pacote `adk_rag_postgres_harness`, `migrations/`, `docker-compose.yml`, `scripts/`, `.githooks/`, `evals/` e `tests/` para dentro do harness único, mantendo por enquanto o nome do pacote.
- Unir os dois `pyproject.toml` e os extras. Regenerar um único `uv.lock`.
- Ajustar os `sys.path` que apontam para pastas irmãs (`feature_planner/postgres.py`, `adk_app/agent.py`, `adapter.py`, `embeddings.py`).
- Nenhuma lógica muda.

Aceite: todos os testes dos dois harnesses passam, a fase 1 passa e a impressão digital é idêntica à da fase 0.

### Fase 3: remover o Jev

- Apagar `adk_rag_harness/jev.py`, `adk_rag_harness/jev_sdk.py`, o extra `jev-sdk`, `evals/run_jev_evals.py`, `evals/run_jev.py`, os testes de Jev e as partes de Jev do `adapter.py`.
- Remover o guardrail via Jev (`HARNESS_GUARDRAIL`) e o modelo `typesafe/jev-router` dos padrões.
- Se o `adk_app` ficar, o provedor de decisão padrão passa a ser Ollama.
- Manter `TripartitePolicy` e os contratos tipados, que são do harness.
- Tratar os resultados de eval do Jev conforme a decisão acima.

Aceite: nenhuma referência a Jev ou TypeSafe fora do histórico, testes passando e `adk web` iniciando o `feature_planner` e, se mantido, o `adk_app`.

### Fase 4: renomear e limpar

- Dar o nome final ao pacote. Trocar `sys.path` por dependências declaradas onde der.
- Atualizar o README do harness, o README raiz e o `.env.example`, incluindo a seção "One server per project".
- Registrar de novo os servidores MCP existentes com o caminho novo. O do `biometrik` já está quebrado: aponta para uma pasta antiga do harness.

Aceite: o comando `mcp` sobe a partir do caminho novo para cada projeto, e o README não cita caminhos antigos.

### Fase 5: verificação final

- Impressão digital idêntica à da fase 0.
- `verify-index` sem diferenças em todos os projetos.
- hit@5 igual ou maior que o da fase 0.
- Uma rodada do `feature_planner` com `catalogo-omh11-v5-target` e a referência `catalogo-omh11-v5-adfixus`.
- A contagem da tabela `embeddings` não sobe. Se subir, algo foi recalculado.

### Fase opcional: um banco por organização

- Criar o banco `webmotors`, rodar `migrate` e copiar as linhas dos projetos de `catalogo_omh11` e `catalogo_omh11_v2`, inclusive os vetores, sem recalcular. Os nomes de projeto já são distintos.
- Conferir a impressão digital por projeto contra a linha de base.
- Atualizar o `DATABASE_URL` dos lançadores dos pilotos. Apagar os bancos antigos só depois da confirmação do responsável.

## Fora do escopo

- O repositório do curso, que cita estes harnesses e as tarefas de Jev em `docs/tasks/`. Ele recebe um PR próprio depois da fase 4.
- A worktree do piloto `codex/adk-rag-provider-routing` e os lançadores em `~/harness-pilots`, que usam um commit antigo e continuam funcionando.
