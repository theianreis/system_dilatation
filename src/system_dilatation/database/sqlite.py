from pathlib import Path
from sqlalchemy import (create_engine,MetaData,Table,Column,Integer,Float,)
from sqlalchemy.dialects.sqlite import insert

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "database" / "sensores.db"
DB_PATH.parent.mkdir(parents=True,exist_ok=True)

# Conectar com sqlite
engine = create_engine(f"sqlite:///{DB_PATH}",echo=False)
metadata = MetaData()

## Célula + H711 -> Tabela
hx711 = Table(
    "célula",
    metadata,
    Column("leitura", Integer, primary_key=True),
    Column("tempo_s", Float, nullable=False),
    Column("bits_medido", Float, nullable=False),
    Column("deltaL_mm", Float, nullable=False),
)

## termistor -> Tabela
termistor = Table(
    "termistor",
    metadata,
    Column("leitura", Integer, primary_key=True),
    Column("tempo_s", Float, nullable=False),
    Column("bits_medido", Float, nullable=False),
    Column("temperatura_C", Float, nullable=False),
)

TABELAS = {"hx711": hx711,"termistor": termistor,}

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