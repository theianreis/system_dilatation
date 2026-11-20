"""Conexão com o SQLite e persistência das medições."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert

from .models import TABELAS, metadata

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "database" / "sensores.db"
DB_PATH.parent.mkdir(parents=True,exist_ok=True)

# Conectar com sqlite
engine = create_engine(f"sqlite:///{DB_PATH}",echo=False)

def criar_banco():
     metadata.create_all(engine)

def salvar_dados(dados, sensor: str):
    if sensor not in TABELAS:
        raise ValueError(f"Sensor não reconhecido: {sensor}")

    tabela = TABELAS[sensor]
    registros = dados.to_dict(orient="records")
    if not registros:
        return
    with engine.begin() as conexao:
        for registro in registros:
            comando = insert(tabela).values(**registro)
            atualizacao = {coluna.name: getattr(comando.excluded,coluna.name)
                for coluna in tabela.columns
                if coluna.name != "leitura"
            }
            comando = comando.on_conflict_do_update(index_elements=["leitura"],set_=atualizacao)    
            conexao.execute(comando)
