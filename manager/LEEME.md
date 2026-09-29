# Rafa: actualizar OmaPacks y probar el pack

Entrega preparada: **gestor 0.3.3 / pack de prueba 1.1.2**. El flujo de la interfaz
está aprobado por Diego. **Espera su aviso de publicación verificada**: mientras
GitHub siga ofreciendo 0.2.1 / 1.0.0, Update no puede descargar estas versiones.

## 1. Comprobar tu punto de partida

En una terminal, sin sudo:

```sh
~/.local/bin/omapacks --version
~/.local/bin/omapacks doctor
~/.local/bin/omapacks status
```

Guarda el resultado para compararlo después. Si `status` muestra operaciones
pendientes, revísalas con Diego antes de actualizar o aplicar otro pack. No borres
diarios ni respaldos. Si el comando no existe, comunica eso: no es una actualización
normal de una instalación existente.

## 2. Retirar el gestor anterior y volver a añadir el plugin

Este es el recorrido elegido con Diego. **Quitar el plugin no quita por sí solo el
gestor instalado.** Primero comprueba el estado del paso 1. Si no hay operaciones
pendientes, ejecuta como usuario normal:

```sh
~/.local/share/omapacks-manager/uninstall.sh
```

Lee el mensaje y confirma. Retira gestor, comando y sus entradas del menú; conserva
packs instalados, aplicaciones, configuración, confianza, registros y respaldos.
No borres `.config/omapacks` ni `.local/state/omapacks`. Si el gestor no existe,
comunícalo a Diego y pasa a añadir el plugin; no necesitas borrar otras carpetas.

Después abre **Setup → Plugin → Remove**, elige **OmaPacks** (`heartyfm.omapacks`)
y confirma. Si habías editado su código, conserva esa copia antes de retirarlo.
Abre **Setup → Plugin → Add** y pega:

```text
https://github.com/HeartyFM/omapacks-plugin
```

Acepta el código del plugin y actívalo. La oferta debe indicar **gestor 0.3.3**.
Si no aparece o la cerraste, abre una terminal y ejecuta:

```sh
python3 ~/.config/omarchy/plugins/heartyfm.omapacks/bootstrap.py --interactive
```

Revisa origen y clave, y confirma la instalación del gestor. No necesita sudo ni
cuenta de GitHub. El origen esperado es `HeartyFM/omapacks-config` y la huella:
`SHA256:Y3eeDXbuQIbHZ4TYaWGMSQRV+Gg9yKqpjcXuyMlO6G0`.
Si la entrega no coincide con el origen/confianza conservados, comunica el aviso;
no los borres ni reconfigures para saltarlo.

Comprueba:

```sh
~/.local/bin/omapacks --version
~/.local/bin/omapacks status
```

Debe mostrar **OmaPacks gestor 0.3.3** y la versión de contenido que tenías antes.
Instalar el gestor no aplica el pack. También se mantiene la actualización sin
retirar desde **Setup → Plugin → Update**, seguida de la oferta del bootstrap,
si prefieres conservar el plugin instalado.

### En futuras versiones: actualización solicitada por un pack

Desde 0.3.3, si una release necesita un gestor más nuevo, su reporte mostrará
**Actualización necesaria de OmaPacks**, versión actual/destino y origen verificado.
**Actualizar gestor** autoriza solo ese paso. **Volver** cancela sin reemplazarlo.
El gestor exige una release estable firmada por la clave ya confiada; el pack no
puede escoger otro origen ni ejecutar su propio instalador. Si no existe una
entrega compatible o falla la firma, se detiene y explica el motivo.

Tras actualizar, se reabre el mismo pack, se comprueban sus archivos otra vez y
se calcula un plan nuevo que tendrás que aprobar. Cancelarlo deja el gestor nuevo
instalado. Este mecanismo no actualiza el plugin ni el sistema Omarchy. El pack
1.1.2 requiere 0.3.3: después de esta reinstalación ya cumples el requisito y no
verás una actualización artificial o repetida.

## 3. Elegir el pack de prueba

Abre **Update → Configuración compartida** o ejecuta `~/.local/bin/omapacks tui`.
Selecciona **v1.1.2**, marcada **Prueba**, y lee el reporte. Es una release completa:
incluye apariencia Hyprland, menú, barra y aplicaciones predeterminadas compartidas,
además de **OmaSettings** y **Super+Shift+S para guardar una captura completa**.
Si vienes de 1.0.0 también recibirás los cambios de escritorio de 1.1.0.

El pack está acotado a x86_64, Omarchy **4.0.4**, Hyprland **0.56.2** y configuración
Lua. `doctor` comprueba tu equipo; no se da por hecho que el Lenovo cumpla esto.
Un bloqueo de compatibilidad se revisa antes de instalar. La actualización del
sistema se hace por el actualizador oficial de Omarchy, en una decisión separada.

Revisa los paquetes realmente pendientes, permisos y conflictos. Prueba primero
**Volver** y vuelve a abrir la misma versión: cancelar la revisión no instala nada.
Después elige **Instalar**. Conserva o reemplaza cada recurso conscientemente:
no tienes por qué tener el mismo atajo o las mismas asociaciones MIME que Diego.
Reemplazar preferencias modifica solo lo administrado y crea respaldo. Conservar
un recurso requerido puede dejar la instalación parcial; eso no cuenta como éxito.

Tras las decisiones, confirma **¿Deseas proceder con la instalación?**. Detalles
permite revisar código y recursos. OmaSettings es código externo que se ejecutará
con tus permisos, sin aislamiento. Durante la operación verás fases, y las preguntas
nativas de permisos necesarias. No interrumpas procesos de paquetes por probar errores.

## 4. Comprobar el resultado en el Lenovo

Solo un resultado correcto muestra **Instalación completada correctamente.**
Esc vuelve al menú; cualquier otra tecla cierra esa pantalla. Comprueba:

- `~/.local/bin/omapacks status` indica contenido **1.1.2** y no hay pendientes.
- La lista marca esa versión como instalada. Vuelve a abrirla y revisa que no haya
  duplicados ni cambios inesperados; reinstalarla requiere el mismo consentimiento.
- OmaSettings aparece en el lanzador y abre su panel. Para esta prueba basta abrir
  y cerrar: no cambies ajustes del equipo desde el panel.
- Super+Shift+S guarda una captura completa sin pedir selección de región. Hazla
  sobre una pantalla sin información privada; no hace falta enviar la imagen.
- Menú, Apps y barra se abren; la terminal y los atajos esenciales siguen accesibles.
- Monitores, escala, idiomas, ratón/touchpad y preferencias ajenas siguen como antes.
  Revisa las asociaciones MIME que decidiste conservar o reemplazar.

Comunica a Diego la versión inicial/final, cada comprobación y cualquier fallo con
su fase y recurso. Revisa los registros antes de compartirlos; no envíes perfiles,
cookies, claves, tokens ni capturas con información personal.

## 5. Si algo falla o necesitas recuperar

No empieces varias instalaciones ni borres la evidencia. La pantalla explica la
fase, cambios realizados y siguiente paso. Usa `~/.local/bin/omapacks status` para
identificar la transacción. El recorrido permite revisar **Restaurar archivos**;
confirma únicamente tras leer qué recuperará y si hay cambios personales posteriores.

Restaurar archivos no revierte paquetes ni los ajustes que posteriormente hagas
desde OmaSettings. Instalar una release anterior es otra operación, con plan nuevo
y comprobación de compatibilidad. No desinstales ni bajes paquetes para simular una
recuperación. Los fallos artificiales de firma/hash, plan obsoleto y operación parcial
ya se prueban en fixtures aislados; no hay que provocarlos en tu escritorio.

Si el gestor nuevo no arranca, conserva el mensaje y su carpeta. No reemplaces a
ciegas binarios o claves ni desinstales el gestor: se revisa su estado por separado
del contenido. Una prueba en este equipo es lo que permitirá confirmar su
compatibilidad; las pruebas locales de Diego no la sustituyen.
