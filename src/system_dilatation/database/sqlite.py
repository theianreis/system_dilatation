"""Conexão SQLite, cadastro de ensaios e persistência de medições."""

from datetime import datetime, timezone
from pathlib import Path
import os
from uuid import uuid4

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.sqlite import insert

from .models import ESTADOS, TABELAS, ensaios, metadata
from .schema import VERSAO, objetos, reconhecer
from ..validation import validar_serie

BASE_DIR = Path.cwd()
DB_PATH = Path(os.environ.get("SYSTEM_DILATATION_DB", BASE_DIR / "data" / "database" / "sensores.db"))


def criar_engine(caminho: str | Path = DB_PATH):
    """Cria um engine com integridade referencial habilitada no SQLite."""
    caminho = Path(caminho)
    novo_engine = create_engine(f"sqlite:///{caminho}", echo=False)

    @event.listens_for(novo_engine, "connect")
    def habilitar_chaves_estrangeiras(conexao, _registro):
        cursor = conexao.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return novo_engine


engine = criar_engine()


def criar_banco():
    """Cria o esquema novo; recusa bancos que exigem migração prévia."""
    if engine.url.database and engine.url.database != ':memory:':
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    with engine.begin() as conexao:
        banco = conexao.connection.driver_connection
        versao = banco.execute("PRAGMA user_version").fetchone()[0]
        if objetos(banco) or versao:
            try:
                esquema = reconhecer(banco)
            except ValueError as erro:
                raise RuntimeError(f"Esquema incompatível; execute a migração: {erro}") from erro
            if esquema != "atual":
                raise RuntimeError("Execute a migração explícita para versionar ou atualizar o banco.")
        else:
            metadata.create_all(conexao)
            conexao.exec_driver_sql(f"PRAGMA user_version={VERSAO}")


def criar_ensaio(nome: str, descricao: str | None = None, estado: str = "RASCUNHO") -> str:
    """Cadastra um ensaio e retorna seu UUID. Datas são textos ISO 8601 em UTC."""
    if not nome.strip():
        raise ValueError("O nome do ensaio não pode ser vazio.")
    if estado not in ESTADOS or estado == "LIXEIRA":
        raise ValueError("Estado inicial do ensaio inválido.")
    ensaio_id = str(uuid4())
    with engine.begin() as conexao:
        conexao.execute(ensaios.insert().values(
            id=ensaio_id,
            nome=nome.strip(),
            descricao=descricao,
            criado_em=datetime.now(timezone.utc).isoformat(),
            estado=estado,
        ))
    return ensaio_id


def consultar_ensaio(ensaio_id: str) -> dict | None:
    """Retorna os metadados do ensaio ou None quando não existe."""
    with engine.connect() as conexao:
        registro = conexao.execute(
            select(ensaios).where(ensaios.c.id == ensaio_id)
        ).mappings().first()
        return dict(registro) if registro is not None else None


def _validar_ensaio(conexao, ensaio_id: str):
    estado = conexao.execute(
        select(ensaios.c.estado).where(ensaios.c.id == ensaio_id)
    ).scalar_one_or_none()
    if estado is None:
        raise ValueError("Ensaio inexistente.")
    if estado == "LIXEIRA":
        raise ValueError("Não é permitido importar medições para um ensaio na lixeira.")


def validar_ensaio_para_importacao(ensaio_id: str):
    with engine.connect() as conexao:
        _validar_ensaio(conexao, ensaio_id)


def salvar_dados(dados, sensor: str, ensaio_id: str):
    if sensor not in TABELAS:
        raise ValueError(f"Sensor não reconhecido: {sensor}")
    if "ensaio_id" in dados.columns and not dados["ensaio_id"].eq(ensaio_id).all():
        raise ValueError("As medições possuem identificação de ensaio divergente.")

    tabela = TABELAS[sensor]
    registros = dados.assign(ensaio_id=ensaio_id).to_dict(orient="records")
    with engine.begin() as conexao:
        _validar_ensaio(conexao, ensaio_id)
        # Valida o resultado final do upsert antes de modificar qualquer registro.
        existentes = {r[0]: tuple(r) for r in conexao.execute(
            select(*[c for c in tabela.c if c.name != "ensaio_id"])
            .where(tabela.c.ensaio_id == ensaio_id)
        )}
        campos = [c.name for c in tabela.c if c.name != "ensaio_id"]
        vistos = set()
        for r in registros:
            if r["leitura"] in vistos:
                raise ValueError("Leitura duplicada no lote.")
            vistos.add(r["leitura"])
            existentes[r["leitura"]] = tuple(r[c] for c in campos)
        validar_serie(existentes.values())
        for registro in registros:
            comando = insert(tabela).values(**registro)
            atualizacao = {
                coluna.name: getattr(comando.excluded, coluna.name)
                for coluna in tabela.columns
                if not coluna.primary_key
            }
            comando = comando.on_conflict_do_update(
                index_elements=["ensaio_id", "leitura"], set_=atualizacao
            )
            conexao.execute(comando)
