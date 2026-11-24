"""Importação atômica e idempotente; o arquivo original é preservado pelo chamador."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import select
from ..database import sqlite, models
from .protocol import parse


def importar(caminho, ensaio_id):
    data = Path(caminho).read_bytes()
    digest, sessions = parse(data)
    sqlite.criar_banco()
    archive = Path(sqlite.engine.url.database).resolve().parent / 'capturas' / (digest + '.csv')
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with archive.open('xb') as f:
            f.write(data)
    except FileExistsError:
        if archive.read_bytes() != data:
            raise ValueError('Arquivo de captura arquivado diverge de seu hash.')
    ids = []
    with sqlite.engine.begin() as connection:
        sqlite._validar_ensaio(connection, ensaio_id)
        for index, session in enumerate(sessions):
            sid = str(uuid5(NAMESPACE_URL, f'system-dilatation:{ensaio_id}:{digest}:{index}'))
            ids.append(sid)
            if connection.execute(select(models.sessoes.c.id).where(models.sessoes.c.id == sid)).first():
                continue
            connection.execute(models.sessoes.insert().values(
                id=sid, ensaio_id=ensaio_id, fonte_sha256=digest, indice=index,
                criado_em=datetime.now(timezone.utc).isoformat(),
                metadados_json=json.dumps(session['metadata'], ensure_ascii=False)))
            connection.execute(models.eventos.insert(), [
                {'sessao_id': sid, 'linha': line, 'texto': text} for line, text in session['events']])
            connection.execute(models.ciclos.insert(), [
                {'sessao_id': sid, 'cycle': row['cycle'], 'linha': line,
                 'dados_json': json.dumps(row, allow_nan=False)} for line, row in session['rows']])
    return {'ensaio_id': ensaio_id, 'sha256': digest, 'sessoes': ids,
            'arquivo_preservado': str(archive), 'ciclos': sum(len(s['rows']) for s in sessions)}
