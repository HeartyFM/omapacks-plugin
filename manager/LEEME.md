# Rafa: usar OmaPacks

1. En **Setup → Plugin → Add Plugin** de Omarchy pega
   **https://github.com/HeartyFM/omapacks-plugin**, revisa la advertencia nativa
   y acepta añadirlo y habilitarlo. El repo de contenido no sirve en Add Plugin.
2. Se abre el instalador de OmaPacks. Revisa gestor, origen y huella de la clave
   pública, pulsa Continuar y confirma Instalar gestor.
   El plugin y las releases son públicos: no necesitas cuenta ni token de GitHub.
3. En la lista de releases, elige con las flechas y Enter. Lee «Qué hay de nuevo
   en esta configuración» y elige **Instalar** o **Retroceder** abajo. La más reciente
   está coloreada; «Prueba» no significa recomendada ni compatible con tu equipo.
4. Revisa el plan, las aplicaciones predeterminadas, conflictos y permisos. Confirma
   para instalar. Se conservan las confirmaciones del proveedor; al terminar se
   comprueban defaults, menú y recarga de Hyprland. Si falla, consulta el registro
   y la recuperación que ofrece la herramienta.
5. Para otra versión usa **Install/Update → Configuración compartida**, incluidas
   las anteriores. Esc retrocede; al salir o cancelar con Ctrl+C aparece
   **«Pulse cualquier tecla para salir»** y, al pulsarla, se cierra la ventana.

Si cancelaste la instalación inicial, abre `Instalar.sh` dentro de
`~/.config/omarchy/plugins/heartyfm.omapacks/` para reintentar. Para retirar el gestor,
abre `~/.local/share/omapacks-manager/uninstall.sh` en una terminal. Remove Plugin
retira su entrada de Omarchy por separado. Los packs, aplicaciones y respaldos se conservan.
La compatibilidad del Lenovo se confirma probando allí, no se presupone.
