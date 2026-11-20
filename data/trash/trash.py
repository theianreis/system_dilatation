
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from ..database.sqlite import engine

RETENCAO_DIAS = 3

def mover_para_lixeira(ensaio_id: str):
    agora = datetime.now(timezone.utc)
    excluir_apos = agora + timedelta(days=RETENCAO_DIAS)
    with engine.begin() as conexao:
        resultado = conexao.execute(
            text("""
                UPDATE ensaios
                SET
                    estado_anterior = estado,
                    estado = 'LIXEIRA',
                    excluido_em = :agora,
                    excluir_apos = :prazo
                WHERE id = :id
                  AND estado != 'LIXEIRA' """),
            {
                "id": ensaio_id,
                "agora": agora.isoformat(),
                "prazo": excluir_apos.isoformat()
            }
        )

    if resultado.rowcount == 0:
        raise ValueError("Ensaio inexistente ou já descartado.")
def ensaios_expirados():
    agora = datetime.now(timezone.utc)
    with engine.connect() as conexao:
        resultado = conexao.execute(
            text("""
                SELECT id
                FROM ensaios
                WHERE estado = 'LIXEIRA'
                  AND excluir_apos <= :agora"""),
            {"agora": agora.isoformat()}
        )

        return [ linha.id for linha in resultado]
