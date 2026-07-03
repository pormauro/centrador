# Seguridad mínima para usar en máquina real

No conectar este sistema directo a una máquina productiva sin validar lo siguiente:

## Obligatorio

- Selector físico Manual/Auto.
- Parada de emergencia independiente del software.
- Relés/contactos secos u optoaislación.
- Fusible o protección de la fuente de mando.
- Nunca conectar 5V del Arduino a la botonera industrial.
- Watchdog activo.
- Máximo tiempo de pulso limitado.
- Nunca izquierda y derecha al mismo tiempo.
- Falla de cámara = salidas apagadas.
- Falta de papel = salidas apagadas.
- Sin Arduino/serie = no auto, salvo prueba dry-run.

## Puesta en marcha recomendada

1. Cámara y software en dry-run.
2. Arduino conectado, relés desconectados de máquina.
3. Verificar LED de relés: derecha/izquierda correctas.
4. Conectar contactos en paralelo a botones, con máquina en condiciones seguras.
5. Pulsos muy chicos: 50 a 100 ms.
6. Subir de a poco.
7. Validar que la corrección no oscile.
8. Recién ahí habilitar autostart.
