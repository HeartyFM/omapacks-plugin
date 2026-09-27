"""Omarchy's small, left-aligned presentation; no desktop/theme changes."""
from __future__ import annotations
import curses,os,re,shutil,subprocess,sys,termios,textwrap,tty,unicodedata
from pathlib import Path
from .util import Error,clean

_context={}
_printed_rows=0

def size(): return shutil.get_terminal_size((80,24))
def cells(text): return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)
def clip(text,width):
    text=clean(text,False)
    if cells(text)<=width: return text
    result=''
    for c in text:
        if cells(result+c)>max(0,width-1): break
        result+=c
    return result+'…' if width>0 else ''
def wrap(text,width):
    # Preserve paragraphs and indentation, including long paths and wide glyphs.
    lines=[]
    for paragraph in clean(text).split('\n'):
        for part in textwrap.wrap(paragraph,max(1,width),replace_whitespace=False,drop_whitespace=False) or ['']:
            while cells(part)>width:
                prefix=clip(part,width)[:-1]
                if not prefix: prefix=part[0]
                lines.append(prefix); part=part[len(prefix):]
            lines.append(part.rstrip())
    return lines

def light_palette():
    values=[os.environ.get('GUM_CHOOSE_ITEM_'+part,'') for part in ('FOREGROUND','BACKGROUND')]
    if not all(re.fullmatch(r'#[0-9a-fA-F]{6}',value) for value in values): return False
    # Use the inherited semantic colors, not a theme name or fixed palette.
    luminance=lambda v:sum(int(v[i:i+2],16)*weight for i,weight in ((1,.2126),(3,.7152),(5,.0722)))
    return luminance(values[1])>luminance(values[0])

def paint(text,role='text'):
    text=clean(text)
    if os.environ.get('NO_COLOR'): return text
    if role=='brand': code='32'
    elif role=='muted':
        if light_palette(): return text
        code='2'
    elif role=='strong': code='1'
    elif role=='error': code='31;1'
    elif role=='accent':
        value=os.environ.get('GUM_CHOOSE_CURSOR_FOREGROUND','2')
        if re.fullmatch(r'#[0-9a-fA-F]{6}',value): code='38;2;'+';'.join(str(int(value[i:i+2],16)) for i in (1,3,5))
        elif re.fullmatch(r'\d{1,3}',value) and int(value)<256: code='38;5;'+value
        else: code='32'
    else: return text
    return '\033['+code+'m'+text+'\033[0m'

def logo_lines(cols,rows):
    path=Path(os.environ.get('OMARCHY_PATH','/usr/share/omarchy'))/'logo.txt'
    try: lines=path.read_text().splitlines()
    except OSError: return []
    return lines if rows>=32 and lines and max(map(cells,lines))<cols else []

def context_lines(cols):
    repo=_context.get('repo',''); version=_context.get('version','ninguna')
    info='Repositorio: '+repo+'  ·  Instalada: '+version
    if cells(info)<=cols-1: return [info]
    return [clip('Repositorio: '+repo,cols-1),clip('Instalada: '+version,cols-1)]

def header(config=None,installed=None,mode='install',notice=''):
    global _context,_printed_rows
    if config is not None:
        _context={'repo':clean(config.data.get('repository','sin configurar'),False),
                  'version':clean((installed or {}).get('version','ninguna'),False),'mode':mode,'notice':clean(notice,False)}
    cols,rows=size(); logo=logo_lines(cols,rows)
    if logo and shutil.which('omarchy-show-logo'):
        subprocess.run(['omarchy-show-logo'],env={**os.environ,'OMARCHY_PATH':os.environ.get('OMARCHY_PATH','/usr/share/omarchy')})
        _printed_rows=len(logo)+3
    else:
        print('\033[2J\033[H',end=''); _printed_rows=0
    for line in wrap('OmaPacks · Configuración compartida',max(1,cols-1)):
        print(paint(line,'brand')); _printed_rows+=1
    for line in context_lines(cols): print(paint(line,'muted')); _printed_rows+=1
    if _context.get('notice'):
        for line in wrap(_context['notice'],max(1,cols-1)): print(paint(line,'muted')); _printed_rows+=1
    print(); _printed_rows+=1

def message(text,role='text'):
    global _printed_rows
    for line in wrap(text,max(1,size().columns-1)):
        print(paint(line,role),flush=True); _printed_rows+=1

def footer_lines(cols,confirming=False):
    first='←→ elegir   Enter confirmar   Esc volver' if confirming else '↑↓ elegir   Enter abrir   Esc volver'
    full=first+'   Ctrl+C salir'
    return [full] if cells(full)<cols else [first,'Ctrl+C salir']

def reserve_footer(height,confirming=False):
    footer=footer_lines(size().columns,confirming)
    # Gum owns header+rows. Leave a blank line, then small native-style key help.
    print('\n'*(height+2)+ '\n'.join(paint(line,'muted') for line in footer),end='',flush=True)
    print(f'\033[{height+1+len(footer)}A\r',end='',flush=True)

def choose(options,title,default=None,highlights=()):
    cols,rows=size(); labels=[]
    for i,value in enumerate(options):
        label=clip(clean(value,False).replace('|','│'),max(8,cols-4))
        if label in labels: label=clip(label,max(3,cols-11))+f' [{i+1}]'
        labels.append(label)
    # A common row width keeps the native theme's background from forming
    # ragged rectangles around labels of different lengths.
    width=max(map(cells,labels))
    labels=[label+' '*(width-cells(label)) for label in labels]
    # Only local index metadata may add ANSI, after all remote text is sanitized.
    labels=[paint(label,'accent') if i in highlights else label for i,label in enumerate(labels)]
    height=max(1,min(len(labels),8,rows-_printed_rows-len(footer_lines(cols))-4))
    argv=['gum','choose','--header',clip(title,cols-1),'--height',str(height),'--no-show-help','--no-strip-ansi','--label-delimiter','|','--padding','0 0','--header.background','']
    # The focused release uses the same selection roles as native gum confirm.
    for component in ('FOREGROUND','BACKGROUND'):
        value=os.environ.get('GUM_CHOOSE_SELECTED_'+component)
        if value and (re.fullmatch(r'#[0-9a-fA-F]{6}',value) or value.isdecimal() and int(value)<256):
            argv+=['--cursor.'+component.lower(),value]
    if default is not None: argv+=['--selected',labels[default]]
    reserve_footer(height)
    result=subprocess.run(argv,input='\n'.join(label+'|'+str(i) for i,label in enumerate(labels)),text=True,stdout=subprocess.PIPE)
    if result.returncode==130: raise KeyboardInterrupt
    if result.returncode:
        header() # Remove gum's English cancellation message from the finished screen.
        return None
    try: return int(result.stdout.strip())
    except ValueError: raise Error('Respuesta inesperada de gum')

def confirm(message_text,affirmative='Instalar'):
    cols=size().columns
    prompt='\n'.join(wrap(message_text,max(1,cols-1)))
    reserve_footer(len(prompt.splitlines())+2,True)
    result=subprocess.run(['gum','confirm',prompt,'--affirmative',affirmative,'--negative','Volver','--default=false','--no-show-help','--padding','0 0'])
    if result.returncode==130: raise KeyboardInterrupt
    return result.returncode==0

def pager(text,title='Detalles',kind='normal',actions=()):
    safe=clean(text)
    def view(screen):
        try: curses.use_default_colors(); curses.curs_set(0)
        except curses.error: pass
        screen.keypad(True); top=0; selected=0
        colors=not os.environ.get('NO_COLOR') and curses.has_colors()
        if colors:
            for n,c in ((1,2),(2,1)):
                try: curses.init_pair(n,c,-1)
                except curses.error: pass
        button=curses.A_REVERSE
        if colors and curses.COLORS>=256:
            def ansi_color(value):
                if value.isdecimal() and int(value)<256: return int(value)
                if not re.fullmatch(r'#[0-9a-fA-F]{6}',value): raise ValueError
                rgb=[int(value[i:i+2],16) for i in (1,3,5)]
                levels=(0,95,135,175,215,255)
                cube=[min(range(6),key=lambda n:abs(levels[n]-v)) for v in rgb]
                shade=min(range(24),key=lambda n:sum((8+n*10-v)**2 for v in rgb))
                return 232+shade if sum((8+shade*10-v)**2 for v in rgb)<sum((levels[n]-v)**2 for n,v in zip(cube,rgb)) else 16+36*cube[0]+6*cube[1]+cube[2]
            try:
                curses.init_pair(3,ansi_color(os.environ.get('GUM_CHOOSE_SELECTED_FOREGROUND','')),ansi_color(os.environ.get('GUM_CHOOSE_SELECTED_BACKGROUND','')))
                button=curses.color_pair(3)
            except (ValueError,curses.error): pass
        brand=curses.color_pair(1) if colors else 0
        heading=(curses.color_pair(2) if colors and kind=='error' else brand)|curses.A_BOLD
        secondary=0 if light_palette() else curses.A_DIM
        while True:
            rows,cols=screen.getmaxyx(); width=max(1,min(86,cols-1)); screen.erase()
            def put(y,value,style=0):
                if 0<=y<rows:
                    try: screen.addstr(y,0,clip(value,cols-1),style)
                    except curses.error: pass
            logo=logo_lines(cols,rows); y=0
            if logo:
                y=1
                for line in logo: put(y,line,brand); y+=1
                y+=2
            for line in wrap('OmaPacks · Configuración compartida',max(1,cols-1)): put(y,line,brand); y+=1
            # The release/topic takes the place of repository metadata inside the reader.
            put(y,clip(title,cols-1),heading); y+=2
            height=max(1,rows-y-(6 if actions else 4))
            lines=wrap(safe,width)
            top=max(0,min(top,max(0,len(lines)-height)))
            for i,line in enumerate(lines[top:top+height]):
                section=bool(line and len(line)<55 and (line.endswith(':') or line.isupper()))
                put(y+i,line,curses.A_BOLD if section else 0)
            end=min(len(lines),top+height)
            progress=f'{top+1}–{end} de {len(lines)}' if len(lines)>height else ''
            put(rows-(5 if actions else 3),progress,secondary)
            if actions:
                x=0
                for index,action in enumerate(actions):
                    label=' '+clean(action,False)+' '
                    try: screen.addstr(rows-3,x,label,button|curses.A_BOLD if selected==index else secondary)
                    except curses.error: pass
                    x+=cells(label)+3
            helptext='↑↓ desplazar   PgUp/PgDn página   Inicio/Fin   Esc volver' if cols>=66 else '↑↓ mover   Inicio/Fin   Esc volver'
            if actions:
                helptext='↑↓ desplazar   ←→ elegir   Enter continuar'
            put(rows-2,helptext,secondary); put(rows-1,'Esc retroceder   Ctrl+C salir' if actions else 'q volver   Ctrl+C salir',secondary)
            screen.refresh(); pressed=screen.getch()
            if pressed in (27,ord('q')): return
            if pressed==3: raise KeyboardInterrupt
            if actions:
                if pressed in (10,13,curses.KEY_ENTER): return selected
                if pressed in (9,curses.KEY_RIGHT): selected=(selected+1)%len(actions)
                elif pressed in (curses.KEY_BTAB,curses.KEY_LEFT): selected=(selected-1)%len(actions)
            if pressed in (curses.KEY_DOWN,ord('j')): top+=1
            elif pressed in (curses.KEY_UP,ord('k')): top-=1
            elif pressed in (curses.KEY_NPAGE,ord(' ')): top+=height
            elif pressed==curses.KEY_PPAGE: top-=height
            elif pressed in (curses.KEY_HOME,ord('g')): top=0
            elif pressed in (curses.KEY_END,ord('G')): top=max(0,len(lines)-height)
    return curses.wrapper(view)


def exit_prompt(cancelled=False):
    """Read one literal key, restoring terminal state even after interruption."""
    header()
    message('Operación cancelada.' if cancelled else 'OmaPacks cerrado.','muted')
    message('Pulse cualquier tecla para salir','strong')
    fd=sys.stdin.fileno(); previous=termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        os.read(fd,1)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd,termios.TCSADRAIN,previous)
    print()
