# OmaPacks · Configuración compartida

Plugin para instalar el gestor de configuraciones compartidas de Diego y Rafa.
Es independiente del actualizador oficial de Omarchy.

## Si ya tienes OmaPacks

Actualiza `heartyfm.omapacks` desde **Setup → Plugin → Update**. Después acepta
la oferta **Actualizar gestor → 0.3.3**. Si la cerraste, ejecuta en una terminal:

```sh
python3 ~/.config/omarchy/plugins/heartyfm.omapacks/bootstrap.py --interactive
~/.local/bin/omapacks --version
```

Actualizar el plugin y actualizar el gestor son pasos distintos. El contenido
instalado y los respaldos permanecen; el pack se elige después desde
**Update → Configuración compartida**. La guía completa está incluida en
`manager/LEEME.md`. Si una actualización de Git avisa de cambios locales,
consérvalos y comunica el error, sin borrar la carpeta ni usar reset.

## Retirar y reinstalar (recorrido elegido para Rafa)

Comprueba primero `~/.local/bin/omapacks status`. Si no hay operaciones pendientes,
ejecuta `~/.local/share/omapacks-manager/uninstall.sh` y confirma. Conserva contenido,
origen, confianza y respaldos. Después usa **Setup → Plugin → Remove → OmaPacks**
y vuelve a añadir esta URL desde **Setup → Plugin → Add**. No borres el estado ni
la configuración de OmaPacks. La guía completa está en `manager/LEEME.md`.

## Primera instalación

1. En Omarchy abre **Setup → Plugin → Add Plugin**, introduce
   `https://github.com/HeartyFM/omapacks-plugin` y acepta añadirlo y habilitarlo
   después de revisar su procedencia.
2. Se abrirá el instalador en una terminal. Revisa el origen y la clave pública;
   confirma la instalación del gestor y de sus dos entradas del menú.
3. Elige una release, lee sus novedades y selecciona **Instalar**.
4. Revisa cambios, permisos y conflictos; confirma el plan y espera su verificación.
5. Para futuras instalaciones usa **Install/Update → Configuración compartida**.
   Esc retrocede; Ctrl+C cancela y una tecla cierra la ventana final.

Requiere Omarchy con plugins, Python ≥3.11, gum y OpenSSH. El instalador comprueba
sus requisitos y no instala paquetes en ese primer paso. El código del gestor
viene incluido: no necesitas pip, herramientas de desarrollo ni rutas de Diego.
La configuración del equipo y sus aplicaciones se instalan solo al aprobar un pack.

Origen configurado: [HeartyFM/omapacks-config](https://github.com/HeartyFM/omapacks-config).
Ambos repositorios son públicos; no necesitas cuenta ni token de GitHub.
Huella de la clave pública de releases:
`SHA256:Y3eeDXbuQIbHZ4TYaWGMSQRV+Gg9yKqpjcXuyMlO6G0`.

Si cancelas la preparación inicial, abre `Instalar.sh` dentro de
`~/.config/omarchy/plugins/heartyfm.omapacks/` para reintentar.
Actualizar el plugin no sustituye silenciosamente el gestor ya instalado.
Desde 0.3.0, si hay un gestor anterior, el plugin ofrece actualizarlo con una
confirmación separada. Conserva su origen, confianza y respaldos; la instalación
del pack sigue requiriendo revisar y confirmar su propio plan.

Para retirar el gestor, ejecuta `~/.local/share/omapacks-manager/uninstall.sh` en
una terminal y confirma. Después retira el plugin desde Omarchy. Tus aplicaciones,
configuraciones instaladas, origen y respaldos se conservan.

Una entrega sin `manager/bundle.json` o `manager/publisher.pub` es de desarrollo:
el instalador la rechaza. La compatibilidad de cada pack se comprueba por separado.

Desde 0.3.3, si un pack exige un gestor posterior, su reporte ofrece una actualización
estable y firmada del gestor. Requiere autorización; conserva contenido y respaldos,
y vuelve a abrir el pack con un plan nuevo. No actualiza el checkout del plugin ni
Omarchy. El pack declara únicamente `manager_min`, no una URL o instalador propio.
