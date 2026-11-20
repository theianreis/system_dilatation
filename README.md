# Sistema de dilatação

Aplicação Python para importar e tratar medições de célula/HX711 e termistor,
armazenando os resultados por ensaio em CSV e SQLite.

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

Esta entrega não implementa migração, restauração ou exclusão pela lixeira.
A gravação no SQLite e a escrita do CSV são operações separadas: uma falha na
escrita do CSV pode ocorrer depois de o banco já ter sido atualizado. A importação
dos dois sensores também ocorre em operações separadas.

## Testes

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Os testes utilizam arquivos e bancos temporários e verificam o isolamento entre
ensaios, a atualização de valores, a CLI e a integridade referencial.
