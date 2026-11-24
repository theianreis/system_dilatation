"""Compatibilidade para o rascunho histórico; use a CLI estado para operar."""
from datetime import datetime, timezone
from sqlalchemy import select
from system_dilatation.database import models, sqlite
from system_dilatation.database.lifecycle import alterar

RETENCAO_DIAS = 3


def mover_para_lixeira(ensaio_id):
    alterar(ensaio_id, 'descartar')


def ensaios_expirados():
    with sqlite.engine.connect() as c:
        return list(c.execute(select(models.ensaios.c.id).where(
            models.ensaios.c.estado == 'LIXEIRA',
            models.ensaios.c.excluir_apos <= datetime.now(timezone.utc).isoformat(),
        )).scalars())
