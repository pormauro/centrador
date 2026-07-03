# Protocolo serial PC -> Arduino UNO

Configuración:

```text
115200 baudios, 8N1, salto de línea \n
```

Comandos:

```text
PING
ENABLE 1
ENABLE 0
HB
STOP
PULSE L 100
PULSE R 250
```

Respuestas típicas:

```text
READY CENTRADOR UNO
PONG
OK ENABLED
OK DISABLED
OK HB
OK STOP
OK PULSE L 100
OK PULSE_DONE
FAULT WATCHDOG
ERR NOT_ENABLED
ERR BAD_DIRECTION
ERR BAD_PULSE_FORMAT
```

## Watchdog

Cuando está habilitado, el Arduino espera `HB` periódicos. Si pasan más de 3 segundos sin heartbeat:

1. deshabilita el sistema;
2. apaga salidas;
3. emite `FAULT WATCHDOG`.

## Enclavamiento

El sketch apaga ambas salidas antes de activar una. No permite que izquierda y derecha queden energizadas juntas.
