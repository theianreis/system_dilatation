# Entrega das etapas 14–21 — 24/11/2026

Este registro distingue implementação, teste simulado e validação física. A revisão
original permanece como histórico em `estudos/Projeto/planejamento/`.

| Etapa | Entrega | Situação |
|---|---|---|
| 14 | Valores finitos, validação do resultado do upsert, migração com validação comum, pré-validação das entradas e recuperação de CSV | Implementada e testada |
| 15 | Esquema 2 com sessões, eventos, ciclos e calibrações; migração de versão 1 | Implementada e testada |
| 16 | Importador offline, validação do protocolo, arquivo original arquivado e idempotência | Implementado e testado |
| 17 | Captura serial durável, recibos UTC, início/pausa e estados do ensaio | Implementada e testada com I/O simulado; validação na porta real pendente |
| 18 | Procedimento de bancada e critérios de aceitação | Preparado; identificação do NTC/circuito e execução física pendentes |
| 19 | Ajuste beta e de deflexão, parâmetros/proveniência, registro de calibrações | Ferramentas implementadas; obtenção dos parâmetros reais e validação física pendentes |
| 20 | Análise por temperatura medida, fases independentes do pico de deslocamento, resíduos, material explícito e versão corrigida da análise histórica | Implementada/testada com dados de teste; reanálise real depende dos TXT originais |
| 21 | CLI, caminho de dados independente da instalação, lixeira, backup, CI, pacote e configuração Docker | Implementada; CI preparada sem execução remota; Docker sem execução por falta de acesso ao daemon |

## Evidência de verificação

- 43 testes Python aprovados, incluindo regressões da revisão, migração v1→v2, recuperação,
  sessões, lixeira, captura serial, calibração, ciência e análise histórica corrigida.
- Integração do parser com saída do firmware real compilado para simulação nativa.
- Trinta cenários do firmware e seus testes numéricos.
- Compilação PlatformIO para Uno; configuração padrão sem NTC/calibração inventados.
- Construção de sdist e wheel; instalação das dependências do lock em ambiente novo
  e instalação do wheel construído. O cache local foi copiado para `/tmp`, permitindo
  instalar offline sem modificar o cache global do usuário.
- Sintaxe/configuração Compose validada. O daemon Docker recusou acesso ao socket;
  a imagem não foi construída nem executada.
- Nenhum banco experimental foi criado, migrado ou excluído; as gravações de
  verificação usaram arquivos temporários. Nenhum firmware foi enviado à placa.

## Limites operacionais explícitos

1. O intervalo, a janela e a tolerância no firmware continuam provisórios.
2. O NTC precisa de circuito/modelo identificados; o display não tem interface definida.
3. Os ajustes matemáticos começam com `validada_experimentalmente=false`.
4. Os coeficientes de dilatação permanecem aparentes. O efeito da montagem e a
   equivalência deflexão da célula/dilatação da amostra não foram comprovados.
5. Captura serial não reconecta automaticamente. Após desconexão, retomar o ensaio
   com um novo arquivo; os fragmentos anteriores permanecem preservados.
6. Reimportação é idempotente por ensaio, hash do arquivo e sessão. Arquivos alterados
   ou sobrepostos são fontes diferentes; não há deduplicação por semelhança dos dados.
7. O banco confirma dados antes da exportação CSV; uma falha de exportação informa
   que o banco já foi atualizado. O comando `exportar` recupera a série completa.
8. As capturas originais arquivadas não são apagadas pela exclusão de um ensaio.
9. A análise histórica corrigida preserva os arrays informados pelo usuário. Os TXT
   dos ensaios e as anotações originais ainda precisam ser fornecidos para auditoria.
10. Mudanças estão no workspace; não houve publicação, execução remota de CI ou commit.

Os procedimentos completos estão em [operação](operacao.md) e
[bancada e calibração](bancada_e_calibracao.md).
