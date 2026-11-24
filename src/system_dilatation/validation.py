"""Regras compartilhadas para séries físicas já convertidas."""
import math


def validar_serie(linhas):
    tempos = set()
    for linha in linhas:
        leitura, tempo, *valores = linha
        if type(leitura) is not int or leitura <= 0:
            raise ValueError('Identificador de leitura deve ser inteiro positivo.')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (tempo, *valores)):
            raise ValueError('Medições físicas devem conter somente números finitos.')
        if tempo < 0 or tempo in tempos:
            raise ValueError('Tempos devem ser não negativos e estritamente crescentes, sem repetições.')
        tempos.add(tempo)
