# Sistema de dilatação

Aplicação Python para importar e tratar medições de célula/HX711 e termistor,
armazenando os resultados por ensaio em CSV e SQLite.

## Operação integrada

O comando `uv run system-dilatation --help` disponibiliza cadastro, consulta, captura,
importação do protocolo, exportação, backup, estados, lixeira e processamento.

- [Manual de operação e recuperação](docs/operacao.md).
- [Estado das entregas e validações das etapas 14–21](docs/entrega_etapas_14_21.md).
- [Procedimento de bancada e calibração](docs/bancada_e_calibracao.md).
- [Análise corrigida dos ensaios históricos](analysis/ensaios_historicos.py).

O esquema atual do banco é **2**. A migração preserva o original e produz candidato.
O banco padrão fica em `data/database/sensores.db` no diretório de trabalho;
`--db` na CLI ou `SYSTEM_DILATATION_DB` selecionam outro caminho.
Os resultados científicos permanecem aparentes até validação experimental.

## Firmware Arduino

A aquisição conjunta HX711/NTC está preparada em [`firmware/`](firmware/README.md),
com comandos seriais, dados brutos, janelas de aquisição e indicadores de falha.
O NTC e as conversões físicas precisam de configuração e calibração. A serial usa
115200 baud e protocolo CSV próprio, com receptor/importador Python dedicado.

## Importação por ensaio

Os exemplos pressupõem o ambiente `.venv` com as dependências do projeto instaladas.
Os arquivos de entrada precisam existir; seus nomes abaixo são exemplos.

Criar um ensaio e importar os dois sensores:

```bash
PYTHONPATH=src .venv/bin/python -m system_dilatation.etl.loading \
  --novo-ensaio "Ensaio A" \
  --celula data/raw/celula.csv \
  --termistor data/raw/termistor.csv
```

O comando exibe o UUID do ensaio criado. Para importar ou reimportar dados nesse
mesmo ensaio, substituir `UUID_DO_ENSAIO` pelo identificador exibido:

```bash
PYTHONPATH=src .venv/bin/python -m system_dilatation.etl.loading \
  --ensaio-id UUID_DO_ENSAIO \
  --celula data/raw/celula.csv \
  --termistor data/raw/termistor.csv
```

É possível informar apenas um sensor. Usar `--novo-ensaio` novamente cria outro
ensaio, mesmo que o nome seja igual. O cadastro começa em `RASCUNHO`; importar
arquivos não declara que a execução experimental foi concluída.

As entradas da célula devem conter `leitura`, `tempo_s`, `bits_media` e
`deltaL_mm`. O termistor aceita as colunas padronizadas `leitura`, `tempo_s`,
`bits_medido` e `temperatura_C`, além das variantes previstas em `transform.py`.
Os valores físicos já devem estar presentes nos arquivos; calibração não é
calculada por essa importação.

Os resultados incluem `ensaio_id` e ficam em:

```text
data/processed/<UUID_DO_ENSAIO>/celula_limpo.csv
data/processed/<UUID_DO_ENSAIO>/termistor_limpo.csv
data/database/sensores.db
```

`--out` altera o diretório base dos CSVs. Reimportar o mesmo sensor atualiza as
leituras presentes no arquivo pela chave `(ensaio_id, leitura)`; não remove do
banco leituras ausentes na nova entrada. O CSV de saída desse sensor é substituído
pelo lote processado, portanto pode não representar toda a série armazenada.

## Cadastro e consulta em Python

```python
from system_dilatation.database.sqlite import criar_banco, criar_ensaio, consultar_ensaio

criar_banco()
ensaio_id = criar_ensaio("Ensaio A", descricao="Observações da execução")
ensaio = consultar_ensaio(ensaio_id)
```

Os horários cadastrados são textos ISO 8601 em UTC. Datas da execução física
permanecem ausentes quando desconhecidas. A consulta retorna `None` se não
encontrar o ensaio. Importações para ensaios inexistentes ou na lixeira são rejeitadas.

## Compatibilidade do banco

A aplicação cria o novo esquema quando o banco não possui tabelas. Bancos no
formato anterior, sem vínculo de ensaio, são rejeitados e precisam de migração
separada. Não apagar um banco antigo para contornar essa verificação.

Estados, restauração e exclusão após retenção estão disponíveis pela CLI; veja o manual de operação.
A gravação no SQLite e a escrita do CSV são operações separadas: uma falha na
escrita do CSV pode ocorrer depois de o banco já ter sido atualizado. A importação
dos dois sensores também ocorre em operações separadas.

## Criação e migração explícitas

A ferramenta gera um **candidato separado**, backup consistente pela API SQLite
quando existe origem e relatório JSON ao lado do candidato. Não substitui o banco
original. Interrompa ETL, aquisição e qualquer outro gravador antes de começar;
mantenha-os parados até concluir a ativação ou cancelar a operação.

Para criar um candidato vazio quando não há banco:

```bash
PYTHONPATH=src .venv/bin/python -m system_dilatation.database.migration \
  --criar --destino data/database/sensores.candidato.db
```

Para migrar um banco legado existente:

```bash
PYTHONPATH=src .venv/bin/python -m system_dilatation.database.migration \
  --origem data/database/sensores.db \
  --destino data/database/sensores.candidato.db \
  --mapeamento /caminho/mapeamento.json \
  --backups data/backups
```

Origem ausente, candidato existente, esquema desconhecido, versão incompatível,
objetos adicionais e dados inválidos são recusados. Bancos legados vazios dispensam
`--mapeamento`. Um banco já atualizado é validado e reportado sem copiar novamente.
Bancos com o esquema da etapa 11 e versão `0` são copiados e versionados preservando
os cadastros, sem receber mapeamento legado. A versão de destino é `user_version=2`, incluindo sessões, eventos, ciclos brutos e calibrações. Bancos da versão 1 também são migrados explicitamente.
A aplicação recusa esquemas existentes sem versão ou incompatíveis; a atualização
ocorre somente pelo comando explícito.

O JSON associa **cada leitura de cada sensor exatamente uma vez**. Use UUIDs reais
e nomes e estados correspondentes aos ensaios conhecidos. Exemplo para um legado
que contém somente a leitura 1 de cada sensor:

```json
{
  "ensaios": [
    {
      "id": "b939a3d3-f42b-420e-a0ab-90bd23def1c5",
      "nome": "Ensaio A",
      "estado": "CONCLUIDO",
      "descricao": "Origem confirmada nos registros do experimento"
    }
  ],
  "medicoes": [
    {"sensor": "celula", "leitura": 1, "ensaio_id": "b939a3d3-f42b-420e-a0ab-90bd23def1c5"},
    {"sensor": "termistor", "leitura": 1, "ensaio_id": "b939a3d3-f42b-420e-a0ab-90bd23def1c5"}
  ]
}
```

O cadastro aceita `RASCUNHO`, `EM_ANDAMENTO`, `CONCLUIDO` e `INTERROMPIDO`.
Datas físicas desconhecidas permanecem ausentes; o momento de cadastro usa UTC.
Sem conhecer a origem dos dados, interrompa a migração até determinar a associação.
A ferramenta não recupera valores anteriormente sobrescritos pelo esquema antigo.

O relatório registra caminhos, versões, mapeamento, hash SHA-256 do backup,
contagens por sensor e, no destino, por ensaio, verificações e resultado. Em falhas,
o candidato incompleto é removido; o backup e o diagnóstico são preservados.
A migração compara todas as tuplas das medições e verifica `integrity_check` e
`foreign_key_check` antes de confirmar e novamente após reabrir o candidato.
O reconhecimento do esquema é conservador: definições diferentes das suportadas
exigem avaliação, mesmo que pareçam equivalentes.

### Aceitação, ativação e recuperação

Confira `resultado: candidato_validado`, os caminhos, as contagens e as verificações
no relatório. Preserve o backup e a origem. Para testes que escrevem, use uma cópia
descartável do candidato; não altere o candidato já validado.

A aplicação aceita selecionar outro banco pela variável `SYSTEM_DILATATION_DB`.
Com todos os gravadores ainda parados, valide a abertura em leitura:

```bash
SYSTEM_DILATATION_DB=data/database/sensores.candidato.db PYTHONPATH=src \
  .venv/bin/python - <<'PYTHON'
from contextlib import closing
from system_dilatation.database.migration import abrir_leitura
from system_dilatation.database.sqlite import DB_PATH
from system_dilatation.database.schema import reconhecer, verificar_integridade

with closing(abrir_leitura(DB_PATH)) as banco:
    verificar_integridade(banco)
    print(reconhecer(banco))
PYTHON
```

Para ativar, configure `SYSTEM_DILATATION_DB` com o caminho absoluto do candidato
em todos os processos da aplicação e só então libere gravações. Esse procedimento
mantém o arquivo anterior e seus arquivos WAL/journal separados do banco novo.
Nenhuma troca automática de arquivos é executada pela ferramenta.

Se for preciso recuperar antes de haver novas gravações, encerre as conexões,
preserve o candidato para diagnóstico e use o banco anterior com a versão anterior
da aplicação. O backup também pode ser restaurado para um caminho novo pela API
SQLite. Depois de novas gravações, preserve ambos os bancos e reconcilie as novas
medições antes de retornar: substituir pelo backup antigo perderia essas medições.

## Testes

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Os testes utilizam arquivos e bancos temporários e verificam o isolamento entre
ensaios, a atualização de valores, a CLI e a integridade referencial.
