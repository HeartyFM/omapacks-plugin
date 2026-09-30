"""Bounded Steam dependency policy. Read hardware, never configure it.

pacman --print picks the first provider of an unsatisfied virtual dependency.
For Vulkan this may be NVIDIA even on an AMD machine. Resolve Mesa libraries
explicitly on the target machine before asking pacman for the complete plan.
"""
import re
from pathlib import Path
from .util import Error

VIRTUAL = ('vulkan-driver', 'lib32-vulkan-driver')
MESA = {'0x1002': ('AMD Radeon', 'radeon'), '0x8086': ('Intel', 'intel')}


def display_vendors(root):
    """Read the kernel's PCI display class/vendor attributes, including 3D GPUs."""
    vendors = set()
    try:
        for device in sorted(Path(root).iterdir()):
            category = (device / 'class').read_text().strip().lower()
            if not re.fullmatch(r'0x[0-9a-f]{6}', category):
                raise ValueError('invalid PCI class')
            if not category.startswith('0x03'):
                continue
            vendor = (device / 'vendor').read_text().strip().lower()
            if not re.fullmatch(r'0x[0-9a-f]{4}', vendor):
                raise ValueError('invalid PCI vendor')
            vendors.add(vendor)
    except (OSError, ValueError) as exc:
        raise Error('Steam: no se pudo leer la GPU mediante PCI/sysfs. '
                    'No se elegirá un proveedor Vulkan por defecto. Revisa el diagnóstico del equipo.', 'gpu') from exc
    return vendors


def dependencies(providers, packages):
    steam = next((p for p in packages if p['provider'] == 'arch' and p['name'] == 'steam'), None)
    if not steam:
        return []
    current = providers.installed('steam')
    if current and providers.compare(current, steam['version']) >= 0:
        return []
    query = providers.runner.run(['pacman', '-T', '--', *VIRTUAL], check=False)
    missing = query.stdout.splitlines()
    if query.stderr.strip() or not (
        query.returncode == 0 and not missing or
        query.returncode == 127 and missing and set(missing) <= set(VIRTUAL)
    ):
        raise Error('No se pudo comprobar la disponibilidad de Vulkan para Steam (pacman -T).', 'query')
    if not missing:
        return []  # Existing providers (including NVIDIA/custom ones) remain untouched.
    vendors = display_vendors(providers.pci_root)
    supported = sorted(vendors & MESA.keys())
    if not supported:
        raise Error('Steam necesita proveedores Vulkan de 64 y 32 bits. '
                    'No se detectó una GPU AMD Radeon o Intel para completar las bibliotecas Mesa. '
                    'Revisa los proveedores adecuados del equipo antes de continuar; '
                    'OmaPacks no instalará NVIDIA ni sustituirá controladores o el kernel.', 'gpu')
    selected = {}
    labels = ', '.join(MESA[v][0] for v in supported)
    for vendor in supported:
        label, suffix = MESA[vendor]
        for prefix, bits in (('', '64'), ('lib32-', '32')):
            selected[prefix + 'vulkan-' + suffix] = f'Steam: Vulkan de {bits} bits para {label}, detectada en este equipo.'
    # Steam also uses OpenGL; libglvnd alone does not supply Mesa's implementation.
    for name, bits in (('mesa', '64'), ('lib32-mesa', '32')):
        selected[name] = f'Steam: bibliotecas gráficas Mesa de {bits} bits para {labels}.'
    result = []
    for name, reason in selected.items():
        current = providers.installed(name)
        result.append({'provider': 'arch', 'name': name,
                       'version': current or providers.repository_info(name),
                       'module': steam.get('module'),
                       'reason': reason + ' Se conserva la configuración de GPU, kernel y arranque.'})
    return result
