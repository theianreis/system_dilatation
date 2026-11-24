"""Reconhecimento conservador dos esquemas SQLite suportados."""

import re

from sqlalchemy import create_engine

from .models import metadata

VERSAO = 2
COLUNAS = {
    "célula": ("leitura", "tempo_s", "bits_medido", "deltaL_mm"),
    "termistor": ("leitura", "tempo_s", "bits_medido", "temperatura_C"),
}


def normalizar(sql):
    partes = re.split(r"('(?:''|[^'])*')", sql)
    return "".join(parte if indice % 2 else re.sub(r'[\s"`\[\]]', '', parte).lower()
                   for indice, parte in enumerate(partes))


def objetos(conexao):
    return conexao.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()


def ddl_atual():
    engine = create_engine("sqlite://")
    try:
        metadata.create_all(engine)
        with engine.connect() as conexao:
            return conexao.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
            ).scalars().all()
    finally:
        engine.dispose()


def verificar_integridade(conexao):
    if conexao.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("Banco com falha de integridade SQLite.")
    if conexao.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Banco com referências inválidas.")


def reconhecer(conexao):
    versao = conexao.execute("PRAGMA user_version").fetchone()[0]
    if versao not in (0, 1, VERSAO):
        raise ValueError(f"Versão de esquema incompatível: {versao}.")
    encontrados = objetos(conexao)
    esperado = sorted(normalizar(sql) for sql in ddl_atual())
    if (all(tipo == "table" for tipo, *_ in encontrados)
            and sorted(normalizar(sql) for _, _, _, sql in encontrados) == esperado):
        return "atual" if versao == VERSAO else "sem_versao"
    anteriores = sorted(normalizar(sql) for sql in ddl_atual()
                        if any(normalizar(sql).startswith('createtable' + nome + '(')
                               for nome in ('ensaios', 'célula', 'termistor')))
    if (all(tipo == 'table' for tipo, *_ in encontrados)
            and sorted(normalizar(sql) for _, _, _, sql in encontrados) == anteriores
            and versao in (0, 1)):
        return 'versao_1'
    if versao != 0 or {nome for _, nome, _, _ in encontrados} != set(COLUNAS):
        raise ValueError("Esquema desconhecido ou incompleto; execute uma migração compatível.")
    for tipo, nome, _, sql in encontrados:
        if tipo != "table" or re.search(
            r'\b(CHECK|UNIQUE|DEFAULT|COLLATE|REFERENCES|GENERATED|WITHOUT|STRICT|AUTOINCREMENT)\b', sql, re.I
        ):
            raise ValueError("Objetos ou restrições desconhecidos no banco legado.")
        colunas = conexao.execute(f'PRAGMA table_info("{nome}")').fetchall()
        if len(colunas) != 4:
            raise ValueError("Colunas inesperadas no banco legado.")
        for indice, (_, campo, tipo_coluna, obrigatorio, padrao, pk) in enumerate(colunas):
            if (campo != COLUNAS[nome][indice]
                    or tipo_coluna.upper() not in (("INTEGER",) if indice == 0 else ("FLOAT", "REAL"))
                    or pk != (1 if indice == 0 else 0)
                    or (indice != 0 and not obrigatorio) or padrao is not None):
                raise ValueError(f"Estrutura legada incompatível: {nome}.{campo}.")
        if conexao.execute(f'PRAGMA foreign_key_list("{nome}")').fetchall():
            raise ValueError("Referências inesperadas no banco legado.")
    return "legado"


def criar_esquema(conexao):
    for sql in ddl_atual():
        conexao.execute(sql)
