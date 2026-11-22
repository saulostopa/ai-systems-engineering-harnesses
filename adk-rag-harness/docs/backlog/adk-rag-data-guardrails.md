# Guardrails de dados para o planner ADK

Status **backlog** · Prioridade **P1** · Feature **adk-rag-data-guardrails**

## Objetivo

Evitar que segredos e dados pessoais entrem em embeddings, no contexto do
modelo, em respostas ou nos artefatos do piloto. Aplicar a mesma política
às rotas locais e às chamadas externas via Databricks AI Gateway.

## Superfícies atuais

| Fronteira | Dados a verificar |
|---|---|
| Indexação Postgres | Arquivos Markdown, código, configuração e fixtures antes de gravar o chunk ou gerar o embedding |
| Entrada do ADK | Pedido do usuário, memória e referências recuperadas antes de montar o prompt |
| Saída para provedores | Texto e metadados do payload final. Repetir a checagem em cada tentativa, inclusive no fallback |
| Resposta do modelo | JSON do planner, justificativas dos revisores e mensagens de erro antes de propagar o resultado |
| Persistência e exibição | Estado do ADK, traces, Postgres, relatórios, HTML, artefatos, exportações e logs do gateway |

O texto recuperado é dado não confiável. Autorização, escopo, conta do
provedor, ferramentas e destino derivam de configuração do harness. Um
documento ou uma resposta do modelo pode sugerir ações. O código decide
quais ações a aplicação pode executar.

## Registro inicial de detecção

Cada regra terá ID, versão, classe de dado, confiança, escopos, ação padrão,
fixtures positivas e negativas e responsável. Os exemplos abaixo são
sementes para a implementação e devem ser testados com dados sintéticos.

| Regra | Sinal inicial | Verificação e ação proposta |
|---|---|---|
| cred.private-key | Delimitador PEM: «-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----» | Reconhecer blocos multilinha e detectar material PKCS/OpenSSH. Bloquear |
| cred.bearer | Header «(?i)\bAuthorization\s*:\s*(?:Bearer\|Basic)\s+[^\s"'<>]+» | Remover da entrada e bloquear saída. Reconhecer JWT e sessões estruturadas separadamente |
| cred.jwt | «\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b» | Decodificar apenas cabeçalho localmente quando necessário. Tratar caminhos de fixture explicitamente |
| cred.github | Prefixos «gh[pousr]_» e «github_pat_» seguidos de caracteres esperados | Combinar comprimento e contexto. Bloquear valores plausíveis |
| cred.provider-key | Prefixos OpenAI «sk-», Anthropic «sk-ant-», chaves Gemini «AIza», Stripe «sk_live_» e outros operadores adotados no piloto | Validar prefixo, tamanho e alfabeto por provedor. Testar credenciais falsas, exemplos e nomes de variáveis |
| cred.cloud-storage | IDs AWS «\b(?:AKIA\|ASIA)[A-Z0-9]{16}\b», campos de conta de serviço, chaves OCI/Azure/GCP e SAS | Validar campos e contexto, inclusive JSON e YAML multilinha |
| cred.databricks | Campo de token ou OAuth em headers e configuração, valores com prefixo PAT quando aplicável | Separar identificador de endpoint de autenticação. Bloquear token ou segredo |
| cred.assignment | Variáveis e campos com nome «password», «api[_-]?key», «client[_-]?secret», «access[_-]?token», «refresh[_-]?token» e similares | Fazer parsing de atribuições, exemplos e placeholders. Verificar entropia e contexto. Encaminhar ambiguidades para revisão |
| cred.uri | URI «scheme://user:password@host» ou query de URL com assinatura/token | Usar parser de URL e tratar percent encoding. Bloquear DSNs autenticadas, URLs assinadas e webhooks com segredo |
| cred.session | Headers «Cookie» e «Set-Cookie», tokens de sessão e segredos de webhook | Usar parsers do formato e contexto. Redigir inclusive nos logs de erro |
| pii.br-id | Detectar candidatos formatados ou compactos de CPF/CNPJ/RG | Aplicar validação apropriada e contexto. Mascarar ou bloquear conforme classificação |
| pii.contact | Formatos de e-mail, telefone, CEP e endereços | Validar e usar contexto do campo. Nomes e endereços em texto livre exigem sinais adicionais |
| pii.payment | Sequência de 13–19 dígitos com separadores e campos de PIX/conta | Validar Luhn quando cabível, checar contexto e reter só o mínimo permitido |
| pii.domain | Identificadores de cliente, saúde, biometria e dados sensíveis do domínio | Usar política por campo e classificação do corpus. Regex serve como sinal auxiliar |
| injection.signal | Marcadores de papel, instruções para ignorar regras, pedir segredos, mudar destino ou usar ferramenta | Delimitar como dado. Sinalizar revisão. Autorização, destinos e ferramentas continuam restritos fora do modelo |

## Cortes propostos

1. **Política e inventário.** Atribuir um perfil de sensibilidade ao corpus
   e às saídas. Definir as prioridades de bloquear, mascarar, alertar e
   permitir. Usar regras limitadas em tamanho e tempo para entradas grandes.
2. **Antes de indexar.** Checar texto antes de persistir ou chamar o modelo
   de embedding. Preservar a proveniência com identificador e hash,
   incluindo a versão da política. Planejar reindexação e saneamento de
   registros existentes quando o escopo ou a política mudarem.
3. **Antes de cada chamada.** Validar limites, proveniência e escopo.
   Checar o payload após compor o prompt e novamente antes de qualquer
   fallback. Aplicar a política também ao gateway. Autorizar destinos e
   ferramentas por configuração determinística.
4. **Antes de publicar.** Verificar resposta, mensagens auxiliares, estado e
   artefatos antes de gravar ou renderizar. Tratar texto HTML e Markdown
   conforme seu destino. Guardar categoria, ação, ID da regra e contadores
   nas evidências. Manter valores sensíveis fora de logs e traces.
5. **Avaliação e operação.** Manter corpus sintético com variantes
   multilinha, Unicode, campos serializados, fragmentação em chunks,
   valores parcialmente mascarados, exemplos legítimos e falsos positivos.
   Testar que o bloqueio impede a chamada, que o fallback reaplica a
   política e que os registros de todos os estágios permanecem limpos.
   Medir falsos positivos por regra e revisar limites por perfil.

## Aceite

- Fixtures de alta confiança ficam fora de Postgres, de embeddings, de
  chamadas, de resultados e dos logs quando configuradas para bloqueio.
- Cada evento de fiscalização identifica a etapa e a regra que decidiu.
- Chunks comuns com termos de segurança em exemplos continuam recuperáveis
  conforme o perfil e os testes.
- O inventário mostra os pontos que precisam de detecção contextual, revisão
  humana ou controle de acesso. A cobertura evolui com casos de regressão.

Os registros de uso do gateway devem guardar IDs e métricas necessários para
correlação. As tabelas opcionais de payload precisam de política e aprovação
próprias antes de receber conteúdo interno.

[Databricks AI Gateway — registro de uso](https://docs.databricks.com/aws/en/ai-gateway/usage-tracking)
