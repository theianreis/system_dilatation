# Operação do sistema integrado

## Instalação e banco

```bash
uv sync --locked --python 3.13
uv run system-dilatation --help
uv run system-dilatation --db data/database/sensores.db criar-ensaio "Ensaio A"
```

`--db` vem antes do subcomando. Sem ele, usa-se `SYSTEM_DILATATION_DB` ou
`data/database/sensores.db` no diretório atual, independentemente de onde o pacote
foi instalado. O comando de criação exibe o UUID; substitua `UUID` nos exemplos.

O esquema atual é **2**. Bancos da versão 1 e esquemas sem versão precisam de
migração explícita para um candidato novo:

```bash
uv run python -m system_dilatation.database.migration \
  --origem data/database/sensores.db \
  --destino data/database/sensores.v2.db --backups data/backups
```

Para o formato legado sem ensaios, fornecer também `--mapeamento` conforme o README.
A origem não é substituída. Confira relatório/backup e passe a usar o candidato
pelo `--db` ou variável de ambiente. Todas as gravações devem permanecer paradas
até a ativação/cancelamento. Não há migração inversa automática.

## Coleta e importação

```bash
uv run system-dilatation capturar --porta /dev/ttyACM0 \
  --destino data/raw/captura-001.csv --duracao 120 --iniciar --ensaio-id UUID
uv run system-dilatation importar-captura data/raw/captura-001.csv --ensaio-id UUID
```

A porta é um exemplo. O arquivo de destino deve ser novo. A coleta preserva cada
fragmento recebido antes do processamento e grava horário UTC/quantidade de bytes
no arquivo `.recepcao.jsonl`. `--iniciar` aguarda o cabeçalho do firmware antes de
enviar `s`. O firmware permanece sujeito à configuração e aos comandos de seu manual.

O comando envia `p` ao encerrar; desconexão pode impedir sua entrega. O estado do
ensaio fica `INTERROMPIDO`, pois terminar a captura não comprova conclusão física.
Após reconectar, é possível retomar um ensaio interrompido; use outro arquivo de
captura para a nova conexão. Não existe reconexão automática durante a captura.

Na falha de comunicação, os bytes já recebidos continuam no arquivo. Linhas truncadas
são diagnosticadas pelo importador; preserve a fonte e faça eventual reparação em
uma cópia rastreável. O importador exige boot/cabeçalho e ciclos em cada sessão.
Uma sessão vazia final é recusada; ela não é descartada silenciosamente.

A importação valida o arquivo inteiro antes de gravar sessões/eventos/ciclos em
transação. Reinícios separam sessões. Capturas byte a byte iguais reimportadas para
o mesmo ensaio são idempotentes; arquivos alterados são fontes distintas. Não
importe versões sobrepostas do mesmo arquivo como se fossem capturas independentes.

O original também é arquivado em `<pasta_do_banco>/capturas/<sha256>.csv`. Preserve
captura, recibos e banco nos backups. Excluir um ensaio não apaga esses arquivos.

## Recuperar exportação, estados e backup

```bash
uv run system-dilatation exportar UUID --sensor celula --destino data/processed/recuperado.csv
uv run system-dilatation estado UUID CONCLUIDO
uv run system-dilatation estado UUID descartar
uv run system-dilatation estado UUID restaurar
uv run system-dilatation backup --destino data/backups/operacional-001.db
```

`exportar` recupera toda a série física armazenada, não somente o lote que falhou.
O banco é o registro principal: a gravação CSV ocorre depois do commit, de forma
atômica por arquivo, e falha gera diagnóstico explícito de exportação pendente.
A importação histórica de dois sensores continua com commits separados.

Descartar é bloqueado durante aquisição. A restauração recupera o estado anterior.
`estado UUID excluir` remove fisicamente o ensaio e seus registros associados só
após três dias na lixeira; é um comando explícito e não há limpeza automática.
Backups nunca sobrescrevem o destino. Para restaurar, copie o backup consistente
para um caminho novo com todos os gravadores parados e selecione esse caminho.
Se houver dados novos no banco atual, preserve ambos e reconcilie antes de retornar.

## Calibração e processamento

```bash
uv run system-dilatation calibrar referencias.csv --tipo deslocamento \
  --referencia "Instrumento e procedimento utilizados" --destino ajuste.json
uv run system-dilatation processar-captura data/raw/captura-001.csv \
  --parametros parametros-reais.json --destino pares-processados.json
uv run system-dilatation analisar-serie pares-medidos.csv \
  --comprimento-mm 545 --material "Alumínio" --destino analise.json
```

Os formatos das referências estão em [bancada e calibração](bancada_e_calibracao.md).
Ajustes ficam no JSON e no cadastro `calibracoes`, com identificador imutável. O
campo `validada_experimentalmente` começa falso: ajuste matemático não é validação.

O JSON de processamento exige `series_ohms`, `beta_K`, `r0_ohms`, `t0_C`,
`ntc_to_ground` e `mm_per_count`. Use valores reais documentados. O relatório guarda
o snapshot desses parâmetros e o hash da captura. Ele preserva motivos de exclusão
por qualidade. A saída é separada por sessão, com pares e registros excluídos.
Converta os `pares` da sessão desejada para CSV com as colunas `tempo_s`,
`temperatura_C`, `deslocamento_mm` para analisar. Não misture sessões automaticamente.

A análise usa o primeiro máximo de temperatura medida para separar as fases; não
exige coincidência com o máximo de deslocamento. Confirme se esse critério representa
o ensaio; múltiplos ciclos térmicos precisam ser separados previamente. Material é
informado explicitamente; não é inferido por cor ou coeficiente. Os coeficientes são
sempre aparentes até que a validação experimental seja documentada.

O notebook histórico anexado permanece como fonte original. A versão corrigida em
`analysis/ensaios_historicos.py` substitui seu cálculo sem alterar o anexo: não gera temperaturas, não obriga coincidência dos
máximos e não troca automaticamente materiais/fases. Reanalisar os ensaios históricos
exige fornecer seus TXT e arrays medidos originais, ainda ausentes no repositório.

## Testes e container

```bash
uv run python -m unittest discover -s tests -v
python firmware/test/native/run.py
pio run -d firmware
uv build
docker compose config --quiet
docker compose run --rm app --help
```

CI executa Python, build do pacote, testes C++ e compilação Uno em jobs separados.
Docker é opcional para aplicação Python, com `data/` persistente; não executa firmware.
Não há acesso USB configurado no container. Faça coleta no host inicialmente.
A construção/execução Docker depende de acesso ao daemon; não foi possível executá-la
neste ambiente. A configuração Compose foi validada.


### Reanalisar os três ensaios históricos

Os arrays anexados foram extraídos sem alteração para
`analysis/temperaturas_informadas.csv`, com hash/proveniência em
`analysis/origem_temperaturas.json`. São tratados como medidos conforme a declaração
do usuário; a validação das anotações originais ainda depende dos arquivos reais.
Copie `analysis/metadados.exemplo.json`, ajuste os caminhos e identifique os materiais
quando houver confirmação. Os nomes escura/clara não são associados a cobre/latão.

```bash
uv run python analysis/ensaios_historicos.py --metadados metadados-reais.json \
  --temperaturas analysis/temperaturas_informadas.csv --out data/processed/historicos
```

A versão corrigida exporta relatório por material/fase, resíduos e dados associados,
sem a tabela estática com coeficientes e fases trocados. Os TXT ainda precisam ser
fornecidos para executar a análise real.
