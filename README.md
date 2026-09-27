# OmaPacks · Configuración compartida

Plugin para instalar el gestor de configuraciones compartidas de Diego y Rafa.
Es independiente del actualizador oficial de Omarchy.

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

Para retirar el gestor, ejecuta `~/.local/share/omapacks-manager/uninstall.sh` en
una terminal y confirma. Después retira el plugin desde Omarchy. Tus aplicaciones,
configuraciones instaladas, origen y respaldos se conservan.

Una entrega sin `manager/bundle.json` o `manager/publisher.pub` es de desarrollo:
el instalador la rechaza. La compatibilidad de cada pack se comprueba por separado.
