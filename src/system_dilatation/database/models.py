"""Definições dos ensaios, das medições e de seus relacionamentos."""

from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Integer, MetaData, String, Table

metadata = MetaData()

ESTADOS = ("RASCUNHO", "EM_ANDAMENTO", "CONCLUIDO", "INTERROMPIDO", "LIXEIRA")

ensaios = Table(
    "ensaios",
    metadata,
    Column("id", String, primary_key=True),
    Column("nome", String, nullable=False),
    Column("descricao", String),
    Column("criado_em", String, nullable=False),
    Column("iniciado_em", String),
    Column("finalizado_em", String),
    Column("estado", String, nullable=False),
    Column("estado_anterior", String),
    Column("excluido_em", String),
    Column("excluir_apos", String),
    CheckConstraint("length(trim(nome)) > 0", name="ensaio_nome_preenchido"),
    CheckConstraint(
        "estado IN ('RASCUNHO', 'EM_ANDAMENTO', 'CONCLUIDO', 'INTERROMPIDO', 'LIXEIRA')",
        name="ensaio_estado_valido",
    ),
)

hx711 = Table(
    "célula",
    metadata,
    Column("ensaio_id", String, ForeignKey("ensaios.id", ondelete="RESTRICT"), primary_key=True),
    Column("leitura", Integer, primary_key=True),
    Column("tempo_s", Float, nullable=False),
    Column("bits_medido", Float, nullable=False),
    Column("deltaL_mm", Float, nullable=False),
    CheckConstraint("leitura > 0", name="celula_leitura_positiva"),
    CheckConstraint("tempo_s >= 0", name="celula_tempo_nao_negativo"),
)

termistor = Table(
    "termistor",
    metadata,
    Column("ensaio_id", String, ForeignKey("ensaios.id", ondelete="RESTRICT"), primary_key=True),
    Column("leitura", Integer, primary_key=True),
    Column("tempo_s", Float, nullable=False),
    Column("bits_medido", Float, nullable=False),
    Column("temperatura_C", Float, nullable=False),
    CheckConstraint("leitura > 0", name="termistor_leitura_positiva"),
    CheckConstraint("tempo_s >= 0", name="termistor_tempo_nao_negativo"),
)

TABELAS = {"celula": hx711, "termistor": termistor}

# Aquisição bruta: identidade independente da numeração histórica de leituras.
sessoes = Table(
    'sessoes', metadata,
    Column('id', String, primary_key=True),
    Column('ensaio_id', String, ForeignKey('ensaios.id', ondelete='RESTRICT'), nullable=False),
    Column('fonte_sha256', String, nullable=False),
    Column('indice', Integer, nullable=False),
    Column('criado_em', String, nullable=False),
    Column('metadados_json', String, nullable=False),
)
eventos = Table(
    'eventos', metadata,
    Column('sessao_id', String, ForeignKey('sessoes.id', ondelete='RESTRICT'), primary_key=True),
    Column('linha', Integer, primary_key=True),
    Column('texto', String, nullable=False),
)
ciclos = Table(
    'ciclos', metadata,
    Column('sessao_id', String, ForeignKey('sessoes.id', ondelete='RESTRICT'), primary_key=True),
    Column('cycle', Integer, primary_key=True),
    Column('linha', Integer, nullable=False),
    Column('dados_json', String, nullable=False),
)
calibracoes = Table(
    'calibracoes', metadata,
    Column('id', String, primary_key=True),
    Column('criado_em', String, nullable=False),
    Column('parametros_json', String, nullable=False),
)
