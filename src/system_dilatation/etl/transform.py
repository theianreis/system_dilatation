import pandas as pd
import numpy as np

def validar_dados(dados: pd.DataFrame,colunas: list[str]) -> pd.DataFrame:
    faltantes = [
        coluna
        for coluna in colunas
        if coluna not in dados.columns
    ]
    if faltantes:
        raise ValueError(
            f"Colunas ausentes: {faltantes}"
        )
    resultado = dados.loc[:, colunas].copy()
    # Converte os valores para tipos numéricos.
    for coluna in colunas:
        resultado[coluna] = pd.to_numeric(
            resultado[coluna],
            errors="raise")
    if resultado.isna().any().any():
        raise ValueError("Foram encontrados valores ausentes")
    if not np.isfinite(resultado.to_numpy()).all():
        raise ValueError("Os valores devem ser finitos.")
    # A leitura deve ser um índice inteiro positivo.
    leitura = resultado["leitura"]
    if ((leitura < 1).any()or (leitura % 1 != 0).any()):
        raise ValueError( "A coluna leitura deve conter inteiros positivos")
    resultado["leitura"] = leitura.astype("int64")
    if resultado["leitura"].duplicated().any():
        raise ValueError(
            "Foram encontrados identificadores duplicados."
        )
    if (resultado["tempo_s"] < 0).any():raise ValueError("O tempo não pode ser negativo.")
    resultado = resultado.sort_values("tempo_s").reset_index(drop=True)
    if (resultado["tempo_s"].diff().dropna() <= 0).any():
        raise ValueError("Os tempos devem ser estritamente crescentes.")
    return resultado



def transform_celula(dados: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "leitura",
        "tempo_s",
        "bits_media",
        "deltaL_mm"
    ]
    resultado = validar_dados(dados,colunas)
    resultado = resultado.rename(
        columns={"bits_media": "bits_medido"})
    return resultado



def transform_termistor(dados: pd.DataFrame) -> pd.DataFrame:
    resultado = dados.copy()
    resultado = resultado.rename(
        columns={
            "Leitura": "leitura",
            "tempo": "tempo_s",
            "Tempo": "tempo_s",
            "bits": "bits_medido",
            "Bits": "bits_medido",
            "temperatura": "temperatura_C",
            "Temperatura": "temperatura_C"
        }
    )
    colunas = [
        "leitura",
        "tempo_s",
        "bits_medido",
        "temperatura_C"
    ]
    resultado = validar_dados(resultado,colunas)
    return resultado