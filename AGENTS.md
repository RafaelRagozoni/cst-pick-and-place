# Instruções para agentes: Simulation

Repositório do agente CST (Java, `agent/`), do bridge com o CoppeliaSim (Python,
`coppelia_environment/`) e das ferramentas de bateria (`tools/`, `bench/`). A arquitetura do agente
está em `agent/README.md`.

## Nomes

Nomes descritivos são o padrão, mesmo que fiquem longos. O código deve se explicar sem a tese aberta,
e um nome precisa ser achável com Ctrl+F ou grep. Vale para Java e Python.

- **Nada de nomes de uma ou duas letras** para variáveis que vivem mais que poucas linhas ou que
  aparecem em vários métodos: `observation`, não `o`; `characterizationVector`, não `b`;
  `yieldFactor`, não `y`.
- **Exceções:** índices de laço curtos (`i`, `j`) e contas de poucas linhas que seguem uma equação,
  com um comentário apontando para ela.
- **Não repita o contexto** que a classe ou o tipo já dão: dentro de `Observation`, `cubeY`, e não
  `observationCubeY`.
- **Símbolo da tese:** use o nome descritivo e ponha o símbolo num comentário, por exemplo
  `double[] characterizationVector = ...; // b, cap4 4.3.1`.
- **O nome diz o quê; o porquê continua num comentário:** de onde vem um valor, por que essa escolha.
- **Código antigo com nomes curtos** se renomeia numa passada própria (um commit só de nomes, com o
  comportamento igual), nunca misturado com mudança de lógica.

Esta regra ainda não é checada no build. Um Checkstyle que reprove nomes de uma letra está na fila
(suspeita 4 de `code_notes/Tour pelo código.md`, no vault).
