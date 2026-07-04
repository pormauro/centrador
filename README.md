# Centrador Corrugadora - Cámara USB + Python + Arduino UNO

Paquete inicial para centrar papel usando:

- Cámara USB sobre la mesa.
- Dos referencias largas fijas de alto contraste, una a cada lado.
- Detección de borde izquierdo y derecho del papel.
- Corrección por pulsos izquierda/derecha.
- Salidas por Arduino UNO hacia módulo de relés/optoacopladores.
- Pantalla de operación y calibración en Windows.
- Arranque automático opcional con Windows.

## Esquema de visión recomendado

```text
REFERENCIA FIJA IZQ        PAPEL         REFERENCIA FIJA DER
███████████████       ██████████████     ███████████████
        ↑                  ↑   ↑                ↑
        |                  |   |                |
     ref izq          borde izq borde der     ref der
```

La cámara debe mirar desde arriba, perpendicular, firme y con luz fija.

## Qué hace el software

1. Captura imagen de cámara USB.
2. Mira una franja horizontal configurable, llamada ROI.
3. Busca borde izquierdo y derecho del papel cerca de los puntos calibrados.
4. Calcula centro del papel.
5. Compara contra el centro ideal.
6. Si el error está dentro de tolerancia, no toca nada.
7. Si está corrido, manda al Arduino un pulso corto hacia el lado contrario.
8. Si no detecta papel o la visión es inválida, apaga salidas.

## Instalación en Windows

1. Instalar Python 3.10 o superior.
   - Marcar `Add python.exe to PATH`.
2. Descomprimir esta carpeta.
3. Ejecutar:

```bat
install.bat
```

4. Cargar en el Arduino UNO el sketch:

```text
arduino\centrador_arduino_uno\centrador_arduino_uno.ino
```

5. Primer arranque seguro sin Arduino:

```bat
.\run_sin_arduino.bat
```

En la pantalla principal:

1. En la sección `Cámara`, elegí el backend (`dshow`, `msmf` o `default`).
2. Tocá `Buscar cámaras`.
3. Elegí la cámara correcta en la lista, por ejemplo `0 - OK 1280x720`.
4. Tocá `Usar cámara seleccionada`.
5. Verificá que se vea la imagen correcta.
6. Tocá `Guardar configuración`.

Recién después calibrá referencias y bordes. No hace falta editar `config\config.yaml` a mano para elegir cámara.

Opcionalmente, también podés guardar capturas de diagnóstico:

```bat
probar_camaras.bat
```

Eso guarda capturas en `logs\camera_probe`. La configuración que queda guardada es:

```yaml
camera:
  index: 0
  backend: dshow
```

dentro de `config\config.yaml`.

`backend` selecciona el medio de captura de la cámara. Valores disponibles: `dshow`, `msmf` o `default`. Tanto `run_sin_arduino.bat` como `run.bat` usan este valor guardado.

6. Probar el Arduino:

```bat
probar_arduino.bat
```

## Primer arranque seguro

Para probar sin mover la máquina:

```bat
run_sin_arduino.bat
```

Para usar Arduino real:

```bat
run.bat
```

El paquete viene con:

```yaml
app:
  auto_start_enabled: false
```

Eso es intencional. Primero calibrás y probás. Recién después ponés `true` si querés que al abrir el programa ya quede trabajando.

## Calibración desde la pantalla

Con la cámara viendo las dos referencias y el papel:

1. Click en `1) Click referencia izquierda` y tocá la línea/referencia izquierda en la imagen.
2. Click en `2) Click borde izquierdo papel` y tocá el borde izquierdo del papel.
3. Click en `3) Click borde derecho papel` y tocá el borde derecho del papel.
4. Click en `4) Click referencia derecha` y tocá la referencia derecha.
5. Click en `Guardar configuración`.

El centro ideal se calcula como el promedio de los dos bordes ideales.

Si el papel en ese momento está perfectamente centrado, también podés usar:

```text
Usar centro actual como ideal
```

## Ajustes importantes

En `config\config.yaml`:

```yaml
control:
  tolerance_px: 18
  medium_error_px: 60
  pulse_small_ms: 100
  pulse_large_ms: 250
  cooldown_ms: 500
```

Interpretación:

- `tolerance_px`: banda muerta. Si el error es menor, no corrige.
- `medium_error_px`: desde este error usa pulso grande.
- `pulse_small_ms`: pulso chico.
- `pulse_large_ms`: pulso grande.
- `cooldown_ms`: espera después de cada pulso antes de volver a corregir.

Si corrige al revés:

```yaml
control:
  invert_correction: true
```

## Falta de papel

El sistema declara falla si:

- no encuentra uno de los bordes;
- la confianza de borde es baja;
- el ancho detectado es absurdo;
- hay demasiados frames inválidos seguidos.

Ajustes:

```yaml
vision:
  edge_search_window_px: 90
  edge_min_confidence: 4.0
  min_paper_width_px: 150
  no_paper_confirm_frames: 8
```

## Arranque automático con Windows

Cuando ya esté calibrado y probado, usá la sección `Inicio automático` dentro de la pantalla principal.

Para iniciar la aplicación con Windows:

1. Abrí la app.
2. En `Inicio automático`, activá `Iniciar esta aplicación automáticamente con Windows`.
3. Verificá que el estado diga `Inicio con Windows: Activado`.

La app intenta usar primero el Programador de tareas de Windows con una tarea `At logon` del usuario actual. Si eso falla, crea un acceso directo en la carpeta Startup del usuario. No activa autologin, no guarda contraseñas y no necesita administrador si Windows permite crear la tarea por usuario.

Para desactivarlo, destildá la misma opción. La app elimina la tarea programada y el acceso directo de Startup si existen, sin crear duplicados.

### Encendido automático al volver la corriente

Que la PC encienda sola cuando vuelve la alimentación eléctrica no depende de Windows. Se configura en el BIOS/UEFI de la computadora.

En la app, sección `Encendido automático al volver la corriente`, podés tocar `Abrir BIOS/UEFI`. Windows pedirá permisos de administrador y ejecutará:

```bat
shutdown /r /fw /t 0
```

Si el equipo no soporta esa opción, reiniciá manualmente y entrá al BIOS/UEFI presionando `DEL`, `F2`, `F10`, `F12` o `ESC` según el fabricante.

Buscá una opción con alguno de estos nombres:

- `Restore on AC Power Loss`
- `AC Power Recovery`
- `Power On After Power Fail`
- `After Power Loss`
- `State After Power Loss`
- `AC Back`

Configurala en `Power On`.

No intentes cambiar valores de BIOS desde Windows salvo que el fabricante tenga una herramienta oficial específica y documentada para ese modelo.

Alternativa anterior por scripts:

1. Editar `config\config.yaml`:

```yaml
app:
  auto_start_enabled: true
  fullscreen: true
```

2. Ejecutar como administrador:

```bat
instalar_autostart.bat
```

Para quitarlo:

```bat
quitar_autostart.bat
```

## Conexión de salidas

El Arduino manda salidas a un módulo de relés u optoacopladores.

Por defecto:

```text
Pin 7 = izquierda
Pin 8 = derecha
```

Usar contactos secos NA en paralelo a los botones existentes.

```text
Botón izquierda original ───── entrada máquina
         │
         └── contacto NA relé izquierda ───┘

Botón derecha original ─────── entrada máquina
         │
         └── contacto NA relé derecha ─────┘
```

No metas 5V del Arduino a la máquina. No unas masas por deporte. No alimentes la botonera desde el Arduino.

## Teclas rápidas

- `A`: activar/desactivar automático.
- `S`: guardar configuración.
- `F`: pantalla completa.
- `ESC`: salir.

## Logs

Los logs quedan en:

```text
logs\centrador.log
```

## Límites honestos

Este paquete es una base funcional lista para instalar y calibrar, pero no reemplaza una puesta en marcha industrial. Antes de conectarlo a movimiento real:

- probar con `run_sin_arduino.bat`;
- probar Arduino con relés desconectados;
- probar relés con la máquina parada;
- verificar que izquierda y derecha no estén invertidas;
- verificar que emergencia y seguridad de máquina sigan mandando;
- dejar un selector Manual/Auto físico.

La regla correcta es: si la imagen no es confiable, no mueve.
