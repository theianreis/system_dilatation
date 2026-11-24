"""Estados, lixeira e exclusão explícita com integridade transacional."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from . import sqlite, models

TRANSICOES = {
    'RASCUNHO': {'EM_ANDAMENTO', 'CONCLUIDO', 'INTERROMPIDO'},
    'EM_ANDAMENTO': {'CONCLUIDO', 'INTERROMPIDO'},
    'CONCLUIDO': set(), 'INTERROMPIDO': {'EM_ANDAMENTO'},
}


def alterar(ensaio_id, acao):
    now = datetime.now(timezone.utc)
    with sqlite.engine.begin() as c:
        record = c.execute(select(models.ensaios).where(models.ensaios.c.id == ensaio_id)).mappings().first()
        if record is None:
            raise ValueError('Ensaio inexistente.')
        state = record['estado']
        values = {}
        if acao == 'descartar':
            if state in ('EM_ANDAMENTO', 'LIXEIRA'):
                raise ValueError('Encerre o ensaio antes de descartar; ensaio já descartado não pode ser descartado novamente.')
            values = dict(estado='LIXEIRA', estado_anterior=state, excluido_em=now.isoformat(),
                          excluir_apos=(now + timedelta(days=3)).isoformat())
        elif acao == 'restaurar':
            if state != 'LIXEIRA' or record['estado_anterior'] not in TRANSICOES:
                raise ValueError('Estado de restauração inválido.')
            values = dict(estado=record['estado_anterior'], estado_anterior=None,
                          excluido_em=None, excluir_apos=None)
        elif acao == 'excluir':
            if state != 'LIXEIRA' or not record['excluir_apos'] or datetime.fromisoformat(record['excluir_apos']) > now:
                raise ValueError('Exclusão só é permitida após o prazo de retenção na lixeira.')
            ids = select(models.sessoes.c.id).where(models.sessoes.c.ensaio_id == ensaio_id)
            for table in (models.eventos, models.ciclos):
                c.execute(table.delete().where(table.c.sessao_id.in_(ids)))
            c.execute(models.sessoes.delete().where(models.sessoes.c.ensaio_id == ensaio_id))
            for table in models.TABELAS.values():
                c.execute(table.delete().where(table.c.ensaio_id == ensaio_id))
            c.execute(models.ensaios.delete().where(models.ensaios.c.id == ensaio_id))
            return
        else:
            if acao not in TRANSICOES.get(state, set()):
                raise ValueError(f'Transição inválida: {state} → {acao}.')
            values['estado'] = acao
            if acao == 'EM_ANDAMENTO':
                values['iniciado_em'] = record['iniciado_em'] or now.isoformat()
                values['finalizado_em'] = None
            elif state == 'EM_ANDAMENTO':
                values['finalizado_em'] = now.isoformat()
        c.execute(models.ensaios.update().where(models.ensaios.c.id == ensaio_id).values(**values))
