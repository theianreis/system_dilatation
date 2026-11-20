"""Conexão SQLite, cadastro de ensaios e persistência de medições."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.dialects.sqlite import insert

from .models import ESTADOS, TABELAS, ensaios, metadata

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "database" / "sensores.db"


def criar_engine(caminho: str | Path = DB_PATH):
    """Cria um engine com integridade referencial habilitada no SQLite."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
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
    with engine.begin() as conexao:
        inspetor = inspect(conexao)
        existentes = set(inspetor.get_table_names())
        if existentes:
            compativel = existentes == set(metadata.tables)
            if compativel:
                for nome, tabela in metadata.tables.items():
                    colunas = {coluna["name"] for coluna in inspetor.get_columns(nome)}
                    chave = inspetor.get_pk_constraint(nome)["constrained_columns"]
                    if colunas != set(tabela.c.keys()) or chave != [
                        coluna.name for coluna in tabela.primary_key
                    ]:
                        compativel = False
                        break
                for tabela in TABELAS.values():
                    referencias = inspetor.get_foreign_keys(tabela.name)
                    if not any(
                        fk["constrained_columns"] == ["ensaio_id"]
                        and fk["referred_table"] == "ensaios"
                        and fk["referred_columns"] == ["id"]
                        and fk.get("options", {}).get("ondelete", "").upper() == "RESTRICT"
                        for fk in referencias
                    ):
                        compativel = False
            if not compativel:
                raise RuntimeError(
                    "Esquema de banco incompatível. Preserve os dados e execute "
                    "uma migração antes de usar esta versão."
                )
        metadata.create_all(conexao)


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
