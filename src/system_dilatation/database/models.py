"""Definições das tabelas de medições e seus metadados."""

from sqlalchemy import Column, Float, Integer, MetaData, Table

metadata = MetaData()

hx711 = Table(
    "célula",
    metadata,
    Column("leitura", Integer, primary_key=True),
    Column("tempo_s", Float, nullable=False),
    Column("bits_medido", Float, nullable=False),
    Column("deltaL_mm", Float, nullable=False),
)

termistor = Table(
    "termistor",
    metadata,
    Column("leitura", Integer, primary_key=True),
    Column("tempo_s", Float, nullable=False),
    Column("bits_medido", Float, nullable=False),
    Column("temperatura_C", Float, nullable=False),
)

TABELAS = {"hx711": hx711, "termistor": termistor}
