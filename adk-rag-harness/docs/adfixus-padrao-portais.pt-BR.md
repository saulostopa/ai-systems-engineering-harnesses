# Padrão AdFixus para portais com consentimento compartilhado

Use o portal de referência em homologação para conferir a integração com o fornecedor. Fixe a revisão usada na comparação. O comportamento do botão **Entendi** definido abaixo vale para o portal de referência, o Catálogo e os próximos portais.

## Contrato do componente

| Cenário | Resultado esperado |
| --- | --- |
| Primeira visita, sem clicar em **Entendi** | O aviso continua fixo durante a navegação. O SDK pode carregar após a higienização da URL. O componente aguarda o clique para iniciar a identificação. |
| **Entendi**, com todos os opcionais desligados | Grava a decisão com os quatro opcionais desligados e inicia a identidade AdFixus. Com o SDK pronto, a chamada parte do próprio gesto. |
| **Entendi**, com uma seleção de opcionais | Grava exatamente a seleção e inicia a identidade da mesma forma. |
| SDK ainda indisponível quando o usuário clica | A tentativa iniciada pelo clique aguarda a prontidão do SDK por tempo limitado. |
| Retorno com uma decisão salva | Mantém o banner fechado e reaproveita a identidade existente. O carregamento da página fica sem nova chamada de login. |
| Alteração das preferências pelo rodapé | Atualiza a decisão e as preferências. Desligar Marketing não desativa a identidade mínima nem dispara uma nova criação. |
| Sincronização com a API habilitada | Envia a decisão pelo backend do portal. O vínculo do identificador `acid` à decisão requer um recibo válido do próprio visitante e uma identidade válida. A seleção de Marketing é registrada na decisão. |

**Entendi** mantém a seleção. Quando a pessoa marca os quatro opcionais e
confirma, o cookie registra a ação `i` e `p/s/m/e=1`, e a API recebe
`accept_all`. Nas demais seleções, inclusive com tudo desligado, o cookie
registra `c` com os valores selecionados e a API recebe `save_preferences`
com o valor real de Marketing. O contrato atual da API recebe o estado de
Marketing, enquanto o cookie guarda as quatro categorias.

A integração existente do Adobe segue seu próprio ciclo. O trabalho do Catálogo preserva a montagem atual, sem adicionar uma dependência do evento AdFixus ao Adobe.

## Preferências entre portais

Os portais usam `portal_cookie_consent` com o mesmo schema e o mesmo escopo
`Domain=.example.com; Path=/` em HTTPS. O Catálogo lê a decisão gravada
pelo portal de referência e mantém o banner fechado quando o mesmo perfil do navegador chega
com um cookie válido e vigente. O repositório e o ambiente do frontend
podem ser diferentes. A regra depende dos domínios efetivamente abertos no
navegador e da disponibilidade do cookie nesse perfil.

## Como reaproveitar em outro portal

- Reutilize o componente de banner e preferências, o bootstrap do SDK e a lógica de recibo no módulo `src/components/adfixus` do Catálogo. O módulo serve como fonte do componente comum até a publicação em um pacote compartilhado.
- Configure o nome público, a origem do portal no cookie e a versão da política. Preserve o formato versionado de `portal_cookie_consent` e a leitura de decisões de outros portais válidas para o domínio compartilhado.
- Monte o guard antes dos scripts que podem ler a URL. Preserve os filtros, parâmetros repetidos e fragmentos necessários a cada portal. Teste os casos de navegação específicos antes da adesão.
- Use as rotas de consentimento de mesma origem. Configure a URL HTTPS do SDK por ambiente e mantenha a URL e o papel AWS da API exclusivamente no servidor. Valide o roteamento das duas rotas no proxy do portal.
- Rode testes de primeira visita, navegação sem clique, **Entendi** com opcionais desligados e ligados, retorno, edição no rodapé e vínculo do `acid`. No ambiente autorizado, confirme o GET do SDK, a criação de `afx_profile`, a chamada de decisão, o vínculo com Marketing ligado e desligado e a persistência no backend.

## Evidências para a comparação do Catálogo

Valide primeiro a implementação local. Rode a nova sessão do ADK com a mesma revisão da `main`, o mesmo contrato e os mesmos testes da rodada direta no Claude Code. Mantenha worktrees separadas. Registre as rotas de modelo e tentativas, intervenções manuais, Evals, testes, tempo, tokens observados e custos estimados. Identifique o que foi verificado com respostas simuladas e o que foi observado no ambiente autorizado.
