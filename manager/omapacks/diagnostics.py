"""Small, serializable diagnostics. Never infer a machine repair from a failure."""
import os,re
from .util import Error,clean

def safe(value):
    text=clean(value)
    for name in ('OMAPACKS_GITHUB_TOKEN','GITHUB_TOKEN','GH_TOKEN'):
        secret=os.environ.get(name)
        if secret: text=text.replace(secret,'[oculto]')
    text=re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer|token)\s+)\S+',r'\1[oculto]',text)
    text=re.sub(r'(https?://)[^/\s@]+@',r'\1[oculto]@',text)
    text=re.sub(r'(?i)([?&](?:token|access_token|password|key|signature)=)[^&\s]+',r'\1[oculto]',text)
    return text

def issue(error,resource,phase='preflight'):
    kind=getattr(error,'kind','unknown')
    category={'package_missing':'receta o repositorios del equipo','provider_mismatch':'receta',
              'query':'consulta fallida; causa externa o del equipo por determinar',
              'system_update':'estado del equipo','locked':'estado del equipo',
              'requirements':'estado del equipo','incompatible':'compatibilidad',
              'changed':'estado cambiado','validation':'receta o recurso local'}.get(kind,'causa por determinar')
    return {'phase':phase,'resource':safe(resource),'kind':kind,'category':category,
            'cause':safe(str(error)) or type(error).__name__,
            'next':'Revisar el diagnóstico y calcular un plan nuevo; no repetir la aplicación anterior.'}

class Blocked(Error):
    def __init__(self,issues):
        self.issues=issues
        kinds={i['kind'] for i in issues}
        super().__init__('Bloqueos detectados antes de aplicar:\n\n'+'\n\n'.join(
            i['resource']+' · '+i['category']+'\n'+i['cause'] for i in issues)+
            '\n\nNo se iniciaron cambios en este intento. Revisa los bloqueos antes de continuar.',
            next(iter(kinds)) if len(kinds)==1 else 'blocked')

def operation_summary(journal):
    status={'complete':'Completado','partial':'Parcial','applying':'Interrumpido',
            'recovering':'Recuperación incompleta','restored':'Archivos restaurados',
            'prepared':'Preparación terminada'}.get(journal['status'],journal['status'])
    failure=journal.get('failure',{})
    lines=[status, 'Fase: '+journal.get('phase','no registrada')]
    if failure:
        lines+=['Recurso: '+failure['resource'],'Diagnóstico: '+failure['category'],'Causa: '+failure['cause']]
    elif journal.get('error'): lines+=['Causa: '+safe(journal['error'])]
    done=sum(f['phase']=='done' for f in journal.get('files',[]))
    lines+=['Archivos escritos registrados: '+str(done),
            'Paquetes confirmados registrados: '+str(len(journal.get('packages',[]))),
            'Una fase iniciada puede haber tenido efectos aún no confirmados.',
            '', 'Siguiente paso: revisar la operación y restaurar archivos si corresponde; después crear otro plan.',
            'Restaurar archivos no revierte paquetes, servicios ni compilaciones.',
            'Instalar una release anterior es una operación distinta, con su propio plan.']
    return '\n'.join(lines)
