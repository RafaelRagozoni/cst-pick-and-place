# Guia dos slides semanais (APR-01)

Para o agente que gera slides. Origem: vault, `Rafael/Specs/APR-01 Apresentações semanais.md`.
Exemplo completo e aprovado: `mudancas/2026-10-27-cre-01/` e a reunião `reunioes/2026-11-11.qmd`.

## Quando gerar slides

| Momento | Gatilho | Slides | Pasta |
|---|---|---|---|
| **Spec escrita** | uma spec nova aprovada (como CRE-01, MAC-01) | problema, alternativas, um "como funciona" por escolhida | `mudancas/<data>-<id>/` |
| **Resultado** | uma bateria (protocolo) ou exploratórias com conclusão | previsto × aconteceu; comparação se houver 2+ abordagens | a mesma pasta |
| **Reunião** | antes de cada reunião | manchete, ponto de partida, fechamento | `reunioes/<data>.qmd` e `reunioes/<data>/` |

Entradas de infraestrutura, renomeação, quiz ou ferramenta **não** geram slide: viram uma linha
"também nestas semanas" no fechamento. **Semana sem o ciclo completo** (só infraestrutura ou um bug):
um slide "o que mudou / por quê / o que aprendi" — copie `tema/modelos/semana-curta.qmd` para
`mudancas/<data>-<id>/_01-semana.qmd`, troque os «…» e crie o `fatos.json`.

## Estrutura da reunião (~10 min, ordem fixa)

| # | Slide | Tempo | O que tem |
|---|---|---|---|
| 1 | Manchete | ~45 s | a semana numa frase, **com a parte ruim**; 2–3 números antes → depois com ✓/✗ contra a previsão; imagem real; faixa dos WPs |
| 2 | Ponto de partida | ~1 min | o fechamento da reunião anterior (vídeo) + números agregados |
| 3 | Problema | ~1 min | tira de imagens reais da falha + o número + as causas em palavras simples, sem nomes de pessoas |
| 4 | Alternativas | ~1,5 min | todas num slide, da mais simples à mais elaborada; as descartadas riscadas **uma por clique**, com o motivo; o plano por último |
| 5–6 | Como funciona | ~1 min cada | antes × depois que se entenda sem ler; termos do agente traduzidos no slide |
| 7 | Previsto × aconteceu | ~2 min | a previsão escrita antes de rodar (da spec), o que aconteceu, ✓/✗; legenda de toda métrica; vídeo escolhido por regra |
| 8 | Comparação | ~1 min | só com 2+ abordagens; base em cinza, rótulo direto |
| 9 | Fechamento | ~1 min | estado final, próximo passo, **"Para discutir"** neutro; vira o slide 2 da próxima |

Uma reunião com várias specs repete 3–8 para cada uma; o **corte** decide o que fica nos 10 min.

## Regras de escrita

1. **O título é uma afirmação completa**; o corpo é a prova. Nada de "Resultados".
2. **Palavras simples.** Sigla e métrica por extenso na primeira vez em cada slide; termos do agente
   (bin, Task, UCB, goal, tick, macro) traduzidos. **A definição de uma métrica vem da fonte**
   (`bench/P1.json`, docstring de `tools/bench.py`), nunca de memória. M2 = taxa de sucesso nos
   últimos 100 episódios da Fase 2 (os 500 depois do 1º acerto), média dos seeds; seed sem 1º acerto
   conta 0.
3. **Sem chamadas diretas e sem o nome do orientador.** Perguntas vão para "Para discutir".
4. **Nenhum número digitado.** Todo número entra por `{{< fato chave >}}`. O rodapé (`fonte="..."`)
   traz entrada, commit, pasta do run.
5. **Vídeo é exemplo, número é prova.** Ao lado do vídeo, o número agregado; na legenda, a **regra de
   escolha** do episódio (`episode_pick.py` a escreve).
6. **Ilustração não é dado:** selo "ilustrativa" (no rodapé ou no desenho).
7. **Vídeos da parte principal com 30–45 s.** Os longos vão para o apêndice.
8. **Apêndice:** código, logs, alternativas em detalhe, vídeos longos.
9. **Notas do apresentador** (`::: notes`) em todo slide: 1–3 perguntas prováveis, resposta curta e
   onde está (entrada, spec, seção).
10. **Pronto = o Rafael consegue defender cada slide.** Entregue montado, aberto no Firefox.
11. Português nos slides; identificadores de código em inglês.

**Visual:** uma cor por seção (classe no título: `.ctx` violeta, `.prob` laranja, `.sol` azul,
`.res` magenta; `.ctx .proximos` acende "Próximos"); ✓ verde e ✗ vermelho só em previsto ×
aconteceu; nada de tela só de texto. O tema (`tema/apr.scss`) desenha faixa, seções, rodapé e "n / N".

## Uma mudança, passo a passo

```
mudancas/<data>-<id>/
  midia.sh        # comandos video.py que geram media/ (commitado; media/ fica fora do git)
  fatos.py        # gera fatos.json: calculados das ferramentas, manuais com citação
  fatos.json      # commitado
  slides.qmd      # só includes, na ordem
  _01-problema.qmd, _02-alternativas.qmd, ...   # um arquivo por slide
```

1. `bash slides/mudancas/<pasta>/midia.sh` — os vídeos e as tiras, do log, sem física.
2. `python3 slides/mudancas/<pasta>/fatos.py` — lê os sidecars `.json` da mídia (episódio, regra,
   passos), então roda **depois** do `midia.sh`.
3. Escreva os slides (`_NN-nome.qmd`) e o `slides.qmd` com
   `{{< include /mudancas/<pasta>/_01-problema.qmd >}}` (caminho **a partir da raiz** `slides/`).
4. `python3 tools/slides.py review slides/mudancas/<pasta>` — avisa número digitado, monta em
   `_saida/revisao/` e abre no Firefox (`--no-open` para não abrir).
5. `python3 tools/slides.py capture slides/_saida/revisao/<pasta>.html ~/slides-capturas/<pasta>` —
   um PNG por slide, mais `slideNN_cliques.png` com todos os cliques. **Olhe cada um**: nada pode
   passar do rodapé (título em 2 linhas + muito texto estoura).
6. Commit da pasta (sem `media/`), em inglês, no estilo do `git log`.

## A reunião

1. `reunioes/<data>.qmd`: cabeçalho com `pagetitle:` (não `title:`, que cria um slide de título) e
   `fatos:` listando os `fatos.json` das mudanças e o da reunião; manchete, ponto de partida e
   fechamento escritos ali; os slides das mudanças por include, um por um.
2. `reunioes/<data>/midia.sh` e `fatos.py`: o vídeo de ponto de partida (`video.py learning`; escolha
   `--every` e `--stride` com `--estimate` até dar 30–45 s) e as chaves `reuniao.*`.
3. **Proposta de corte** em `reunioes/<data>-corte.md`: `slide | tempo | entra / apêndice | motivo`,
   parte principal ≤ 10 min 30 s; critérios: o que mais mudou o rumo, o que tem resultado, o que
   gera pergunta. O apêndice vem depois de um slide `## Apêndice`.
4. `python3 tools/slides.py build slides/reunioes/<data>.qmd`, depois `capture`.
5. `python3 tools/slides.py send slides/reunioes/<data>.qmd [--max-video-mb N]` — zip **sem as
   notas** em `Rafael/Meetings/<data> para enviar.zip` no vault.
6. Depois da reunião: `python3 tools/slides.py archive slides/reunioes/<data>.qmd` — zip com as notas
   em `Rafael/Meetings/<data> apresentação.zip`.

## Ferramentas

| Ferramenta | Para quê |
|---|---|
| `tools/slide_facts.py` | formato pt-BR (`fmt_percent`, `fmt_number_range`…), `FactSheet`, leitores do ledger, scorecard, `carry_ranges` (linhas "all" do `carry_report`), `success_after_first` |
| `tools/episode_pick.py` | escolhe o episódio por regra: `every:N`, `first-success`, `last-with-stage:STAGE`, `min-energy-success`, `first-drop-away:START` |
| `tools/video.py episode` | vídeo legendado de um episódio + quadros: `--stills grasp-40,drop+40,last` (âncoras, nada de número de passo digitado) |
| `tools/video.py learning` | um episódio a cada N com as taxas do bloco ao lado; `--epilogue first-success`; `--estimate` |
| `tools/slides.py` | `review`, `build`, `capture`, `send`, `archive` |
| `tools/slide_lint.py` | acusa número digitado; uma linha com `<!-- número digitado: motivo -->` passa, com o motivo à vista |

## Componentes (exemplos prontos para copiar)

| Componente | Onde ver |
|---|---|
| quadro antes → depois (`.kv` com `.what/.from/.to/.mark`) | `reunioes/2026-11-11.qmd`, manchete |
| tira de quadros (`.strip`, legenda `[1]{.n}texto`) | `mudancas/2026-10-27-cre-01/_01-problema.qmd` |
| causas (`.cause` com `<b class="k">1</b>`) | o mesmo |
| cartões de alternativa (`.alts`, `.alt.pick`, `.alt.fragment.riscar` com `.why`, `.plan.fragment`) | `mudancas/2026-10-27-cre-01/_02-alternativas.qmd` |
| trilho de etapas animado (`.row`, `.tr`) | `mudancas/2026-10-27-cre-01/_03-como-a.qmd` |
| grade de situações (`.gwrap`, `.g`, `.q`) | `mudancas/2026-10-27-cre-01/_04-como-b.qmd` |
| tabela previsto × aconteceu + legenda da métrica (`table`, `.legend`) | `mudancas/2026-10-27-cre-01/_05-previsto.qmd` |
| barras de comparação (`.chart`, `.bars`, alturas por fato) | `mudancas/2026-10-27-cre-01/_06-comparacao.qmd` |
| passos como chips (`.chipj`, `.chipg`) | `mudancas/2026-11-03-mac-01/_03-como-funciona.qmd` |
| barra horizontal por fato, "Para discutir" (`.disc`) | `mudancas/2026-11-03-mac-01/_06-causas.qmd` |

## Armadilhas já encontradas

- **Pasta com `_` no começo fica fora do projeto Quarto:** o deck monta sozinho, sem a extensão
  `fato`. Por isso a revisão é `revisao/`, não `_revisao/`.
- **Include aninhado resolve a partir do documento de cima:** use sempre `/mudancas/...`.
- **`<video>` em HTML cru:** o Quarto não reescreve nem copia o caminho. Use
  `src="../mudancas/<pasta>/media/x.mp4"` (todo deck fica um nível abaixo de `slides/`) — os `.mp4` de
  `media/` estão em `resources:` no `_quarto.yml`. Imagem em markdown pode usar `/mudancas/...`.
- **Texto antes do primeiro `##`** (até um comentário HTML) vira um slide vazio.
- **Fato usado como valor de CSS** (altura, largura) precisa de ponto decimal ou inteiro: `"18%"`,
  `"85.9%"`, nunca `"1,1%"`.
- **Um `.qmd` quebrado em `revisao/` ou `reunioes/` derruba todas as montagens:** o Quarto lê a lista
  de render inteira a cada `render`.
- **Firefox snap** só lê dentro de `$HOME`, fora de pastas ocultas no topo (`~/.cache`): saídas e
  capturas ficam em `slides/_saida/` e `~/slides-capturas/`.
- **CoppeliaSim headless** (`video.py`) roda fora da sandbox do Claude Code.

## Commits

Em inglês, no estilo do `git log --oneline`; terminando com a linha `Co-Authored-By` da sessão. A
pasta da mudança vai no mesmo commit dos ajustes que o Rafael pedir na revisão.
