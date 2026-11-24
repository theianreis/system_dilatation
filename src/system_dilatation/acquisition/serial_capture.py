"""Captura durável antes do processamento; uma conexão por arquivo exclusivo."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time


def capturar(porta, destino, duracao_s, *, serial_factory=None, iniciar=False):
    if not math.isfinite(duracao_s) or duracao_s <= 0:
        raise ValueError('Duração deve ser positiva.')
    if serial_factory is None:
        import serial
        serial_factory = serial.Serial
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    received = destino.with_name(destino.name + '.recepcao.jsonl')
    count = 0
    # Exige caminhos novos: captura anterior nunca é truncada.
    with destino.open('xb') as raw, received.open('x', encoding='utf-8') as receipt:
        with serial_factory(porta, baudrate=115200, timeout=0.2) as device:
            deadline = time.monotonic() + duracao_s
            started = False
            pending = b''
            try:
                while time.monotonic() < deadline:
                    line = device.readline()
                    if line:
                        raw.write(line)
                        raw.flush()
                        os.fsync(raw.fileno())
                        count += 1
                        receipt.write(json.dumps({'sequencia': count,
                            'recebido_em': datetime.now(timezone.utc).isoformat(),
                            'bytes': len(line)}) + '\n')
                        receipt.flush()
                        # Aguarda o boot/cabeçalho; abrir a serial do Uno pode reiniciá-lo.
                        pending += line
                        while b'\n' in pending:
                            complete, pending = pending.split(b'\n', 1)
                            if iniciar and not started and complete.startswith(b'schema,cycle,'):
                                device.write(b's\n')
                                started = True
                        if len(pending) > 65536:
                            raise ValueError('Linha serial excede o limite; bytes já preservados.')
            finally:
                try:
                    device.write(b'p\n')
                except OSError:
                    pass  # Desconectado: captura preservada, pausa não confirmada.
    return {'arquivo': str(destino), 'recepcao': str(received), 'fragmentos': count}
