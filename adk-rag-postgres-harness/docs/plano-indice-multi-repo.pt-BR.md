# Plano: indexar vários repositórios numa máquina e consultar de outra

Plano de trabalho de 2026-11-24. Este repositório é público. Nomes de repositórios,
caminhos e dados da empresa ficam no manifesto local, fora do Git.

Os scripts ficam em `adk-rag-postgres-harness/scripts/multi-repo/`. Todos os comandos
abaixo rodam a partir de `adk-rag-postgres-harness`.

## Decisões

- **Uma máquina indexa; as outras só consultam.** Hoje à noite, a indexadora é o Mac.
  Rodar `index` de outra máquina no mesmo banco falha, porque a raiz gravada no projeto
  é outra, ou troca essa raiz para todos, com `--move`.
- **O mesmo modelo de embeddings em todas as máquinas:** `qwen3-embedding:4b` no Ollama.
  Na máquina do trabalho, `ollama list` mostra o ID `df5bd2e3c74c`. O banco grava só o
  nome (`ollama:qwen3-embedding:4b`), que não distingue pesos diferentes publicados com a
  mesma tag. Por isso existe a verificação do passo 9.
- **Indexar a branch padrão do remoto, num worktree próprio.** Nunca o clone de trabalho,
  que pode estar numa branch de feature e ter alterações locais.
- **Um projeto por repositório,** com o nome da pasta em minúsculas. Pastas de documentação
  soltas viram projetos próprios.
- **Primeiro o banco local do Mac.** Um banco gerenciado, como o Supabase ou o oficial,
  entra só depois da varredura de segredos e com a aprovação de quem responde pelos dados.
  A tabela `chunks` guarda o texto do código, não só os vetores.
- **Decidido em 2026-11-24: opção A.** Até a aprovação, a máquina do trabalho usa um banco
  local restaurado do dump do Mac (passo 9). O Supabase (passo 10) fica para depois.
- **Os itens da avaliação da migration não bloqueiam hoje.** Migrations novas se aplicam
  sobre um banco já carregado (veja "Migration").

## Hoje à noite, no Mac

### 1. Preparar o ambiente

```bash
git clone git@github.com:saulostopa/ai-systems-engineering-harnesses.git
cd ai-systems-engineering-harnesses
git checkout claude/plan-multi-repo-index
cd adk-rag-postgres-harness
export UV_PYTHON=3.14
uv sync --frozen --extra postgres
docker compose up -d postgres            # pgvector/pgvector:pg17 na porta 5433
ollama pull qwen3-embedding:4b
ollama list                              # compare o ID com df5bd2e3c74c
```

Com outro ID, siga em frente: o passo 9 decide se os vetores são compatíveis. Se não
forem, copie o modelo da máquina do trabalho (`~/.ollama/models`) e reindexe.

Variáveis da sessão:

```bash
export DATABASE_URL=postgresql://harness:harness@localhost:5433/harness_rag
export OLLAMA_BASE_URL=http://localhost:11434
export HARNESS_EMBED_PROVIDER=ollama
export HARNESS_EMBED_MODEL=qwen3-embedding:4b
```

### 2. Criar os worktrees

```bash
bash scripts/multi-repo/prepare-worktrees.sh ~/PASTA_DOS_CLONES ~/harness-index/worktrees
```

O script procura clones até dois níveis abaixo da pasta e faz `git fetch`. Depois cria cada
worktree no último commit da branch padrão do remoto e grava
`~/harness-index/worktrees/manifest.tsv`. Apague do manifesto as linhas dos repositórios
que não devem entrar, como cópias, projetos de terceiros e experimentos.

### 3. Estimar o tamanho

```bash
uv run --no-sync python scripts/multi-repo/estimate.py ~/harness-index/worktrees
```

O script não grava nada. Ele mostra arquivos, trechos e tokens por repositório, além do
tamanho estimado do banco: 22 KB por trecho, medido no índice piloto. Referências da
máquina do trabalho:
- o embedding na CPU foi de 49 tokens/s;
- a pasta de repositórios de lá daria uns 33 mil trechos, 8,7 milhões de tokens e cerca de 0,7 GB.

### 4. Varrer segredos (pendência aberta)

```bash
brew install gitleaks
bash scripts/multi-repo/scan-secrets.sh ~/harness-index/worktrees ~/harness-index/secret-reports
```

Leia os relatórios, que já saem mascarados. Para tirar do índice os arquivos com achados:

```bash
python3 scripts/multi-repo/findings-to-ragignore.py ~/harness-index/worktrees ~/harness-index/secret-reports
```

O script acrescenta `/caminho` ao `.ragignore` de cada worktree. Esse arquivo não é
versionado, então os repositórios não mudam. O gitleaks não lê o `.ragignore`, então uma
nova varredura continua listando esses arquivos. Para conferir a exclusão, rode o passo 3 de
novo e veja os arquivos caírem.

Uma credencial real também precisa ser trocada pelos donos do repositório: tirar o arquivo
do índice não resolve o vazamento. A varredura cobre o que o gitleaks reconhece, não
qualquer dado sensível.

### 5. Calibrar a velocidade

Indexe primeiro um repositório médio e divida os tokens dele (passo 3) pelos segundos
que o script mostrar:

```bash
bash scripts/multi-repo/index-all.sh ~/harness-index/worktrees NOME_DO_PROJETO
```

### 6. Indexar o resto

Deixe o Mac na tomada e com a tampa aberta:

```bash
caffeinate -is bash scripts/multi-repo/index-all.sh ~/harness-index/worktrees PROJETO_1 PROJETO_2 ...
```

Sem nomes, o script indexa o manifesto inteiro, na ordem dele. Uma falha fica registrada
em `~/harness-index/worktrees/index-logs/` e o próximo projeto segue. A indexação retoma de
onde parou, então basta repetir o comando. Um trecho idêntico em dois repositórios é
calculado uma vez só.

### 7. Conferir

```bash
uv run --no-sync python -m adk_rag_postgres_harness.cli search "PERGUNTA CONHECIDA" --project NOME
uv run --no-sync python scripts/multi-repo/check-embeddings.py --sample 20
```

### 8. Exportar

```bash
mkdir -p ~/harness-index/dumps
docker compose exec -T postgres pg_dump -U harness -d harness_rag -Fc > ~/harness-index/dumps/index-$(date +%F).dump
```

O dump contém o código indexado. Trate-o como o próprio código-fonte: nada de pasta
pública nem nuvem pessoal. Para levá-lo à máquina do trabalho, use um meio aprovado pela
empresa, como o OneDrive corporativo ou um disco externo criptografado. Os vetores
comprimem pouco, então o arquivo deve ficar na casa das centenas de MB. Confira o tamanho
com `ls -lh` e anote o resumo do `index-all.sh` (projetos, trechos e falhas) para a conferência
de amanhã.

## Amanhã, na máquina do trabalho

### 9. Opção A, escolhida até a aprovação: banco local novo

1. Restaurar o dump num banco novo, `harness_rag_multi`, no contêiner que já existe. O
   `harness_rag` atual continua intacto.
2. Apontar `DATABASE_URL` em `~/.config/ai-harness-local/harness.env` para esse banco.
3. Rodar `check-embeddings.py`. Um cosseno mínimo abaixo de 0,99 indica que o Ollama da
   máquina do trabalho não gera os mesmos vetores do Mac.
4. Configurar o projeto alvo e as referências do planner
   (`HARNESS_PLANNER_RAG_PROJECT`, `HARNESS_PLANNER_RAG_REFERENCES`). O launcher local
   ainda não repassa as referências.

Limite desta opção: `search`, `read` e o MCP leem os arquivos do disco a partir da raiz
gravada, que são caminhos do Mac. Até existirem os mesmos repositórios, nos mesmos commits,
nesta máquina, só o planner funciona aqui, porque ele usa o texto guardado no banco. Com os
worktrees criados aqui, `index --move` acerta as raízes, mas só no banco local.

### 10. Opção B, depois da aprovação e da varredura: Supabase

**Plano e tamanho:**
- O plano Free permite 500 MB por projeto. Acima disso, o banco fica só de leitura.
- No Free, um projeto sem uso por uma semana é pausado.
- O conjunto completo deve passar de 0,7 GB. Isso exige o plano Pro (US$ 25 por mês, com
  8 GB) ou um subconjunto de até uns 20 mil trechos.

**Criação** (feita por você):
- região de São Paulo;
- Postgres 17, se houver a opção;
- senha guardada no gerenciador de senhas.

**Antes de carregar dados:**
- **pgvector:** `create extension if not exists vector;` e depois
  `select extversion from pg_extension where extname = 'vector';`. A versão precisa ser
  0.8.0 ou maior, por causa da varredura iterativa que a busca usa.
- **Data API:** desative-a ou tire o schema `public` dos schemas expostos. Sem isso, as
  tabelas ficam acessíveis pela API REST com a chave anônima do projeto.
- **Conexão:** use a URI do *session pooler* (IPv4, porta 5432) com `sslmode=require`. Não
  use o *transaction pooler* (porta 6543).

**Carga.** O caminho abaixo evita os problemas de schema do `pg_restore` em banco gerenciado
e grava as raízes certas:

```bash
export TARGET_URL='URI do session pooler'   # digitada por você; não vai para o Git
DATABASE_URL="$TARGET_URL" uv run --no-sync python -m adk_rag_postgres_harness.cli migrate
```

Ative o RLS em todas as tabelas como segunda barreira. O harness conecta como dono das
tabelas e não é afetado. Repita depois de cada migration nova:

```sql
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;
```

Copie os vetores. O CSV não tem texto de código, só hashes e vetores:

```bash
docker compose exec -T postgres psql -U harness -d harness_rag \
  -c "COPY (SELECT content_hash, model, embedding::text FROM embeddings) TO STDOUT WITH (FORMAT csv)" \
  > ~/harness-index/dumps/embeddings.csv
docker run --rm -i pgvector/pgvector:pg17 psql "$TARGET_URL" \
  -c "COPY embeddings (content_hash, model, embedding) FROM STDIN WITH (FORMAT csv)" \
  < ~/harness-index/dumps/embeddings.csv
```

Reindexe a partir do Mac. Cada projeto deve mostrar "0 chunks embedded", e o texto do código
entra nesta etapa:

```bash
DATABASE_URL="$TARGET_URL" bash scripts/multi-repo/index-all.sh ~/harness-index/worktrees
```

Na máquina do trabalho, aponte `DATABASE_URL` para a mesma URI (a senha você digita) e rode
`check-embeddings.py`. Nunca rode `index` de lá nesse banco. O banco oficial, mais tarde,
segue os mesmos quatro passos.

## Migration: os três itens da avaliação

Vão num PR separado, numa `005_*.sql` nova. A `001_initial.sql` já aplicada não roda de novo.

| Item | Decisão |
|---|---|
| Varredura iterativa na busca por projeto | Já existe (`store.py`, `_prepare_vector_scan`, `strict_order`). Só exige pgvector 0.8.0 ou maior. |
| Vetores órfãos | Fazer: um comando de limpeza que apague vetores sem trecho e sem memória (`memories` usa a mesma tabela), com prazo de carência. O `last_seen_at` via `ON CONFLICT` não funcionaria, porque o indexador só insere vetores que faltam. |
| `vector` sem dimensão e índice HNSW por modelo | Só quando um segundo modelo rodar junto. A consulta teria que repetir a expressão do índice e o nome do modelo. |
| `CHECK (start_line >= 1 AND end_line >= start_line)` | Fazer, com `NOT VALID` e validação depois. |
| `halfvec` no índice HNSW | Avaliar no servidor compartilhado; corta pela metade a memória do índice. |

## Depois

- Fazer o merge do PR #2 (busca do planner separada por coleção) antes de usar o planner no
  índice grande. A indexação não depende dele.
- Suporte a C# e PHP no indexador.
- Servidor MCP com vários projetos e ordenação única entre repositórios.
- Perguntas de avaliação por repositório, com o arquivo esperado.

## Riscos

- **Segredos:** a varredura reduz o risco, mas não o elimina. O índice e o dump guardam o código.
- **Terceiros:** o Supabase guardaria uma cópia do código da empresa. É uma decisão de quem
  responde pelos dados, não só técnica.
- **Modelo:** mesma tag com pesos diferentes passa despercebida sem o `check-embeddings.py`.
- **Raízes:** só a máquina indexadora deve rodar `index` num banco compartilhado.
