# Piloto 3 do AdFixus no Catálogo

Use duas worktrees limpas da mesma revisão da `main`, a mesma referência funcional do portal de referência em homologação e a mesma lista de critérios de aceite. No ADK, a sessão do planner produz plano, evidências e avaliações da invocação. A investigação e a verificação do plano rodam em leitura. Os cortes de configuração, montagem do SDK e banner seguem pelo executor local autorizado na sessão do Piloto 3.

No caminho direto, abra o Claude Code Desktop na segunda worktree. Acesso Git e dependências locais, o acesso autorizado ao ambiente de desenvolvimento valem para os dois caminhos. Os testes que dependem do domínio ou ambiente autorizado precisam ser registrados com ambiente e resultado.

O [padrão AdFixus para os portais](adfixus-padrao-portais.pt-BR.md) fixa o contrato usado nas duas rodadas.

## Missão para o ADK Web

> Planeje a integração do AdFixus ao Catálogo, com paridade funcional com o portal de referência em homologação. Use a main congelada do Catálogo como escopo de implementação. Consulte o código, QA e harness do portal de referência como referências de leitura. Priorize evidência do SDK, guard de URL que preserve os filtros, banner fixo antes da decisão, identidade disparada por Entendi com qualquer combinação de opcionais e API de Consentimento. Verifique o vínculo do acid a um recibo válido do próprio visitante com qualquer seleção de Marketing, e o compartilhamento do cookie do portal de referência com o Catálogo no mesmo navegador. Cite os trechos por corte e defina critérios de aceite para o comportamento e os testes. Identifique lacunas de configuração e de validação em ambiente autorizado. Se faltar evidência do contrato de consentimento, sinalize revisão antes da implementação. Ignore integrações alheias à missão, inclusive Adobe Target. Proponha apenas planejamento e verificação em leitura.
>
> Em cada corte, cite ao menos um ID de origem target que sustente a integração proposta no Catálogo. Use o layout do Catálogo como ponto de montagem do SDK, banner e identidade quando sustentado pelos trechos. Consulte o rodapé para a entrada de preferências e a configuração do Catálogo para o endpoint, flags e testes. Para sincronização, combine evidência do ponto de integração ou configuração do Catálogo com o contrato do portal de referência em homologação. Trate a superfície candidata como proposta de implementação. Quando os trechos não mostrarem uma suíte, chamada, execução em homologação ou contrato no Catálogo, registre 'não verificado no Catálogo' e formule o teste necessário. Separe o comportamento verificado no portal de referência de qualquer hipótese para o Catálogo. Quando não for possível sustentar um mapeamento, sinalize a lacuna para revisão.

## Evals no ADK Web

Selecione o app `feature_planner_evals` e abra **Evals → catalogo-adfixus-v1**. Execute os três casos com `response_match_score` em `1.0`. Eles rodam o grafo real com busca e respostas de modelo sintéticas. São uma regressão de orquestração e escopo. A ausência da referência de consentimento deve levar a `needs_review`, e uma citação a um ID inexistente deve bloquear o plano.

Use a mesma suíte em CI a partir da pasta `adk-rag-harness`.

```sh
uv sync --locked --extra adk --extra postgres
uv pip install --python .venv/bin/python "google-adk[eval]==2.14.1"
uv run --no-sync adk eval feature_planner_evals feature_planner_evals/catalogo-adfixus-v1.evalset.json --config_file_path feature_planner_evals/test_config.json
```

## Avaliação da invocação real

Configure `HARNESS_PILOT_EVAL_POLICY` junto de `HARNESS_PILOT_EVIDENCE_DIR`. O arquivo local tem `version: 1` e a lista `required_sources`. Cada entrada tem `id`, `corpus` (`target` ou `reference`), `project` com o nome no Postgres e `paths` com caminhos relativos aceitos para aquela evidência. Use um ID por expectativa e as revisões fixadas no piloto.

O publicador grava `eval-results.json` e `eval-summary.md` na aba **Artifacts**. O relatório confere recuperação de fontes esperadas, citações do plano, integridade dos hashes do contexto e escopo derivado do Catálogo. A presença do documento esperado e sua citação medem cobertura documental. A validade de cada afirmação e a paridade funcional exigem revisão do conteúdo e testes de produto.

Para recalcular o relatório de uma invocação guardada, rode na pasta `adk-rag-harness`.

```sh
uv run --no-sync python -m feature_planner.pilot_evals --bundle "$BUNDLE" --policy "$POLICY" --output "$RESULTS"
```

O comando retorna código 1 quando o planejamento exige revisão. Build, Playwright, API de consentimento no ambiente autorizado e segurança do executor ficam explicitamente sem execução até a coleta dessas evidências. Use o relatório de tokens da mesma invocação para consumo e custos estimados.

### Falhas de verificação e abertura de artefatos

Em **Events**, abra o `request_model` do corte e veja a categoria em
**Response**. O campo `provider_attempt` diferencia as tentativas do mesmo
provedor. Em falha recuperável, o verificador pode usar a mesma investigação
mais uma vez. O verificador e o avaliador global usam Claude Haiku com
limite de quatro turnos. Se ocorrerem duas falhas recuperáveis de
transporte, serviço ou limite de turnos na mesma rota, podem avançar
para o Codex `gpt-6-sol`, a segunda rota configurada. Uma rejeição por
cota confirmada avança imediatamente. Problemas de autenticação e recusas
encerram a chamada.

O planner recupera até 10 trechos do índice do Catálogo nesta configuração.
Os dois corpora de referência mantêm quatro trechos cada. Isso oferece mais
contexto do layout e do rodapé para mapear a integração do SDK e do banner.

O Eval de escopo exige que todo corte cite fontes do Catálogo e tenha ao menos
um caminho correspondente. As referências do portal de referência sustentam a paridade.

Se a URL do artefato aparecer com `/sessions//artifacts/`, selecione
de novo a sessão pelo painel **Sessions** e abra **Artifacts**. O trecho
vazio indica que a interface montou a URL sem o ID da sessão.

## Primeiro corte no executor do ADK

Na sessão autorizada do `feature_planner`, o comando exato
`Executar corte aprovado` abre o subgrafo `approved_slice_execution`.
A autorização local associa uma invocação de planejamento aprovada, o corte, a sessão, a revisão e a
branch do Catálogo com os hashes
do patch e dos arquivos resultantes. O comando e os dados recuperados
permanecem sem acesso para definir permissões, arquivos ou comandos.

Em **Graph**, acompanhe a autorização, a revisão do subagente Codex, a
aplicação do patch, a verificação do diff e os checks. O subagente recebe
apenas o patch revisado e os critérios deste corte. A operação de escrita
usa o patch fixado na autorização local e valida novamente escopo e base.
Cada autorização se aplica uma vez. O primeiro corte exige worktree limpa.
Para o segundo, o executor confere o recibo aprovado do primeiro corte e
aceita somente seu diff registrado na mesma worktree. O terceiro autoriza mudanças sobrepostas no layout e dois arquivos novos
do componente. O executor confere os recibos dos cortes anteriores, os
hashes do conteúdo antes e depois e a lista exata de novos arquivos.
Os checks conferem novamente o conteúdo depois dos testes.

Em **Artifacts**, abra `slice-execution.diff` e `slice-execution.json`. O
recibo identifica a invocação que aprovou o plano, os arquivos alterados e os
resultados de Vitest e TypeScript. Para reproduzir a preparação, use Node 22,
dependências com o mesmo lockfile e uma cópia isolada para os testes. Os
controles deste piloto local cobrem a aplicação do patch autorizado. Os
Evals de ponta a ponta e o executor geral em múltiplos cortes seguem como
entregas posteriores.

### Guard de URL e montagem do SDK

O segundo corte adiciona um guard inline antes dos scripts do head. Ele
remove `afxAppID` da consulta da página e da cópia de `document.referrer`,
preservando os demais parâmetros, os filtros repetidos e o fragmento. A montagem assíncrona solicita o SDK após a higienização. A identidade
é iniciada ao clicar em **Entendi**. O script envia ao fornecedor o
referrer no nível da origem. A flag desligada mantém o guard e a
solicitação do SDK ausentes. A URL do Catálogo em
`https://catalogo.example.com/catalogo` é a página de entrada. A URL
HTTPS de identificação do SDK continua em `NEXT_PUBLIC_ADFIXUS_URL`.

### Banner, identidade e sincronização

O terceiro corte do piloto original condicionava a montagem do SDK a
Marketing. Para as próximas rodadas vale o [contrato comum](adfixus-padrao-portais.pt-BR.md).
O banner fica fixo até **Entendi**. O clique confirma a seleção e inicia a
identidade com qualquer combinação de opcionais. **Serviços** e
`#gerenciar-cookies` abrem as preferências. A API vincula o `acid` a um recibo válido do mesmo
visitante com qualquer seleção de Marketing.

### Evidência local da correção

No Catálogo, 2.493 testes Vitest passaram. No portal de referência, 257 testes passaram
nas suítes de cookies e consentimento. A checagem de TypeScript passou
nos dois projetos. O Playwright com SDK e API simulados confirmou
o gesto, os filtros, o cookie com todos os opcionais desligados ou
ligados. A revisão seguinte corrige o vínculo para qualquer seleção.

O plano da sessão anterior foi aprovado com o requisito antigo de
Marketing para o SDK. Gere um novo plano para o contrato comum antes de
reutilizar autorizações de corte. O SDK e a API reais do Catálogo e os
registros no backend continuam pendentes de validação no ambiente autorizado.
Na primeira verificação local, o build com Webpack falhou no export principal de
uma biblioteca de mídia. A mesma falha ocorreu na cópia limpa da
`main` congelada com as mesmas dependências. O build padrão com Turbopack
foi interrompido durante a compilação.

### Revisão do vínculo e teste entre portais

O Playwright executou os componentes do portal de referência e do Catálogo em subdomínios
diferentes, com SDK e API simulados. Confirmou o vínculo com todos os
opcionais desligados nos dois portais. Na navegação direta do portal de referência para
o Catálogo, o mesmo perfil reaproveitou o cookie e o banner ficou fechado.
Em um perfil novo, o Catálogo mostrou **Entendi**.

Os testes de integração do endpoint de vínculo usam um banco local de teste.
Após a aprovação do ambiente de homologação, confirme com o SDK real o vínculo
de recibos com Marketing desligado. Reproduza a instalação com o lockfile
fixado para distinguir uma falha da base de uma regressão da feature.

## Prompt para o Claude Code Desktop

Cole o texto abaixo no Claude Code Desktop aberto na worktree destinada à rodada direta.

> Implemente o SDK no Catálogo a partir desta worktree. Use o portal de referência em homologação para conferir o comportamento da API de Consentimento e siga o contrato deste guia para o clique em **Entendi**. Fixe a revisão do checkout de referência e consulte as evidências do harness como material de leitura. Confirme a origem do material antes de adotá-lo como contrato.
>
> Mapeie primeiro o carregamento do SDK, a higienização de URL e preservação de filtros, banner, aceite e revogação, identidade entre visitas e sincronização de consentimento. Compare cada item com o portal de referência. Preserve os comportamentos próprios do Catálogo. Registre configuração e credenciais ainda pendentes para o backend do Catálogo. Confirme qualquer lacuna que mude o requisito com o responsável.
>
> Implemente em cortes nesta worktree. Rode build, tipagem, testes unitários, contrato e Playwright conforme o ambiente permitir. Registre comandos, resultados, ambiente e evidências de rede e persistência disponíveis. Distingua mocks locais, SDK real em teste local e verificações que exigem homologação aprovada. Use dados sintéticos nos testes e preserve segredos fora de logs e artefatos. Entregue o diff, o checklist de paridade do portal de referência com resultados ou pendências, os testes e o ID da sessão para consolidar tokens. Pare antes de publicar, abrir PR ou fazer deploy.
