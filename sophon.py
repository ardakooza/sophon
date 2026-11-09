#!/usr/bin/env python3
import sys, re, json, os, select, time, ast, math, random as _random
from pathlib import Path
from datetime import datetime, date
from collections import namedtuple

LOG_LEVELS = ("compact", "normal", "detailed", "debug")
LOG_LEVEL_RANK = {name: rank for rank, name in enumerate(LOG_LEVELS)}
ACTIONS = ("read", "write", "modify", "remove", "create", "reorder")
# Observation logs record resource reads; "write" is a policy action, not an event type.
OBSERVE_ACTIONS = ("read", "modify", "create", "remove", "reorder")
ASK_TYPES = ("text", "number")
# Capability grants that live in a policy access block without a nested name list.
MODULES = ("database", "observer", "multi-observer", "agent", "component", "file", "execute", "datetime", "random")
PLANNED_MODULES = {"math", "system", "sys", "multi-agent"}
# Local standard-library modules do not require XAF capabilities.
LOCAL_MODULES = ("datetime", "random")
XAF_MODULES = tuple(module for module in MODULES if module not in LOCAL_MODULES)
GLOBAL_ACCESS = ("surface", "ask", "input")
ASK_RETRIES = 3

SphProgram = namedtuple('SphProgram', (
    'states', 'groups', 'observers', 'observer_groups', 'connect',
    'databases', 'agent_connects', 'uses', 'imports',
    'agent_calls', 'asks', 'renders', 'files', 'executes', 'functions',
    'decl_lines'))

class SophonWarning(Exception):
    """A condition the runtime recovered from. Never fatal, always visible on stderr."""
    def __init__(self, code, message, file=None):
        self.code, self.message, self.file = code, message, file
    def __str__(self):
        s = f"SophonWarning [{self.code}] {self.message}"
        if self.file: s += f"\n  --> {self.file}"
        return s

def _quarantine(fp, code, message):
    """Move an unreadable derived file aside, so nothing is silently discarded."""
    moved=None
    if fp.exists():
        bad=fp.with_name(fp.name+'.corrupt')
        try:
            if bad.exists(): bad.unlink()
            fp.rename(bad); moved=str(bad)
        except OSError: moved=None
    text=f'{message} Quarantined as {moved}.' if moved else f'{message} Could not quarantine it.'
    print(SophonWarning(code,text,str(fp)), file=sys.stderr)

class SophonError(Exception):
    def __init__(self, code, message, file=None, line=None, column=None, source=None, hint=None):
        self.code, self.message = code, message
        self.file, self.line, self.column = file, line, column
        self.source, self.hint = source, hint
    def __str__(self):
        s = f"SophonError [{self.code}] {self.message}"
        if self.file and self.line:
            s += f"\n  --> {self.file}:{self.line}:{self.column or 1}"
            if self.source:
                s += f"\n   | {self.source}\n   | " + " " * ((self.column or 1)-1) + "^"
        if self.hint: s += f"\n  hint: {self.hint}"
        return s

def strip_comment(line):
    """Drop a // comment, respecting quoted strings. One pass, no per-character copies."""
    n=len(line); i=0; cut=n; in_str=False
    while i<n:
        c=line[i]
        if c=='"' and (i==0 or line[i-1]!='\\'): in_str=not in_str
        elif not in_str and c=='/' and i+1<n and line[i+1]=='/': cut=i; break
        i+=1
    return line[:cut].rstrip()

def _list_tokens(text, name, line, raw, code='S210'):
    """Split a list body into element tokens. Commas are optional separators."""
    name=getattr(name,'name',name) or ''
    toks=[]; buf=''; in_str=False; i=0
    while i<len(text):
        c=text[i]
        if c=='"' and (i==0 or text[i-1]!='\\'): in_str=not in_str; buf+=c
        elif in_str: buf+=c
        elif c==',':
            if buf: toks.append(buf); buf=''
        elif c.isspace():
            if buf: toks.append(buf); buf=''
        else: buf+=c
        i+=1
    if in_str: raise SophonError(code,'Unterminated string in list.',name,line,1,raw,'Close the quote before the closing bracket.')
    if buf: toks.append(buf)
    return toks

def _local_timezone_name(now=None):
    """Return the local IANA timezone name when the host exposes one."""
    now = now or datetime.now().astimezone()
    env_name = os.environ.get('TZ', '').lstrip(':')
    if env_name and '/' in env_name:
        return env_name
    key = getattr(now.tzinfo, 'key', None)
    if key:
        return key
    try:
        value = Path('/etc/timezone').read_text(encoding='utf-8').strip()
        if value and '/' in value:
            return value
    except OSError:
        pass
    try:
        resolved = Path('/etc/localtime').resolve()
        marker = '/zoneinfo/'
        text = str(resolved)
        if marker in text:
            return text.split(marker, 1)[1]
    except OSError:
        pass
    return now.tzname() or str(now.utcoffset() or 'UTC')


def _datetime_builtin_values():
    """Take one consistent local date/time snapshot for a Sophon program."""
    now = datetime.now().astimezone()
    return {
        'date': now.date().isoformat(),
        'time': now.strftime('%H:%M:%S'),
        'date.day': now.day,
        'date.month': now.month,
        'date.year': now.year,
        'date.weekday': now.isoweekday(),
        'date.timezone': _local_timezone_name(now),
        'time.hour': now.hour,
        'time.minute': now.minute,
        'time.second': now.second,
    }


def _install_datetime_builtins(states, groups, path, line):
    """Expose datetime names as read-only built-in values after `use { datetime }`."""
    values = _datetime_builtin_values()
    reserved = {'date', 'time'}
    conflicts = reserved.intersection(set(states) | set(groups))
    if conflicts:
        name = sorted(conflicts)[0]
        raise SophonError('S245', f'"{name}" is reserved by the datetime module.', path.name, line, 1, None,
                          'Rename the state or multi-state id so the datetime built-in remains unambiguous.')
    states.update(values)


def _value_from_token(t, states, line, file, source, code='S103', in_list=False, groups=None):
    """Resolve one value token: a literal, a state reference, or a list.

    Inside a list a bare word is a literal string, so a list of words needs no quotes
    and a misspelled name can never be mistaken for a state.
    """
    t=t.strip()
    if t.startswith('[') and t.endswith(']'):
        return [_value_from_token(x,states,line,file,source,code,True,groups) for x in _list_tokens(t[1:-1],file,line,source,code) if x.strip()]
    if t=='null': return None
    if t=='true': return True
    if t=='false': return False
    if len(t)>=2 and t[0]=='"' and t[-1]=='"':
        try: return json.loads(t)
        except Exception: return t[1:-1]
    if re.fullmatch(r'-?\d+',t): return int(t)
    if re.fullmatch(r'-?(?:\d+\.\d*|\d*\.\d+)',t): return float(t)
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*',t):
        if in_list: return t
        if t in states: return states[t]
        if '.' in t and groups is not None: return _lookup_ref(t,states,groups,file)
        raise SophonError('S102',f'Unknown state "{t}"',file,line,1,source,
                          'Declare the state first, or quote it to use it as text: "'+t+'".')
    raise SophonError(code,f'Invalid value expression: {t}',file,line,1,source,'Use a string, integer, float, boolean, null, a list, or a state reference.')

def _eval_expression(expr, states, line, file, source, groups=None, functions=None, call_depth=0, modules=None):
    """Evaluate numeric arithmetic without exposing Python execution."""
    expr=expr.strip()
    # Interpolation is deliberately a string feature, not arithmetic concatenation.
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"',expr):
        value=_decode_string(expr)
        group_values=groups or {}
        def interpolate(match):
            ref=match.group(1)
            if ref in states: return str(states[ref])
            return str(_lookup_ref(ref,states,group_values,file))
        return re.sub(r'\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}',interpolate,value)
    if re.search(r'(?<![=!<>])\^',expr):
        expr=re.sub(r'(?<![=!<>])\^','**',expr)
    try:
        tree=ast.parse(expr,mode='eval')
        def calc(node):
            if isinstance(node,ast.Expression): return calc(node.body)
            if isinstance(node,ast.Constant) and type(node.value) in (int,float,str,bool,type(None)): return node.value
            if isinstance(node,ast.List): return [calc(item) for item in node.elts]
            if isinstance(node,ast.Name):
                if node.id in ('true','false','null'): return {'true':True,'false':False,'null':None}[node.id]
                if node.id not in states: raise KeyError(node.id)
                return states[node.id]
            if isinstance(node,ast.Attribute):
                parts=[]; current=node
                while isinstance(current,ast.Attribute):
                    parts.append(current.attr); current=current.value
                if not isinstance(current,ast.Name): raise ValueError('unsupported attribute')
                parts.append(current.id); dotted='.'.join(reversed(parts))
                return _lookup_ref(dotted,states,groups or {},file)
            if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                v=calc(node.operand); return v if isinstance(node.op,ast.UAdd) else -v
            if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
                a,b=calc(node.left),calc(node.right)
                if type(a) not in (int,float) or type(b) not in (int,float):
                    raise TypeError('arithmetic operators require numeric operands')
                if isinstance(node.op,ast.Add): return a+b
                if isinstance(node.op,ast.Sub): return a-b
                if isinstance(node.op,ast.Mult): return a*b
                if isinstance(node.op,ast.Div): return a/b
                return a**b
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='sqrt' and len(node.args)==1 and not node.keywords:
                return math.sqrt(calc(node.args[0]))
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='random':
                if 'random' not in (modules or ()):
                    raise SophonError('S114','Module \"random\" is not imported.',file,line,1,source,
                                      'Add random to use { random } before calling random functions.')
                if node.keywords:
                    raise SophonError('S291','Random functions accept positional arguments only.',file,line,1,source,
                                      'Pass the required values positionally, for example random.integer(1, 10).')
                args=[calc(arg) for arg in node.args]
                method=node.func.attr
                if method=='integer':
                    if len(args)!=2 or any(type(value) is not int for value in args):
                        raise SophonError('S292','random.integer requires two integer bounds.',file,line,1,source,
                                          'Use random.integer(minimum, maximum), with integer bounds.')
                    if args[0] > args[1]:
                        raise SophonError('S293','random.integer minimum exceeds maximum.',file,line,1,source,
                                          'The first bound must be less than or equal to the second bound.')
                    return _random.randint(args[0],args[1])
                if method=='float':
                    if args: raise SophonError('S294','random.float does not accept arguments.',file,line,1,source,
                                                'Use random.float() to generate a value in the range 0.0 to 1.0.')
                    return _random.random()
                if method=='boolean':
                    if args: raise SophonError('S294','random.boolean does not accept arguments.',file,line,1,source,
                                                'Use random.boolean() to generate true or false.')
                    return bool(_random.getrandbits(1))
                if method=='choice':
                    if len(args)!=1 or not isinstance(args[0],list):
                        raise SophonError('S295','random.choice requires one list.',file,line,1,source,
                                          'Use random.choice(["red", "green", "blue"]).')
                    if not args[0]:
                        raise SophonError('S296','random.choice cannot select from an empty list.',file,line,1,source,
                                          'Provide a list containing at least one item.')
                    return _random.choice(args[0])
                raise SophonError('S297',f'Unknown random function "{method}".',file,line,1,source,
                                  'Available functions: integer(min, max), float(), boolean(), choice(list).')
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                if functions is None or node.func.id not in functions:
                    raise SophonError('S275',f'Unknown function "{node.func.id}".',file,line,1,source,
                                      'Declare the function before calling it, or check its id.')
                positional=[calc(arg) for arg in node.args]
                keyword_names=[kw.arg for kw in node.keywords]
                if any(name is None for name in keyword_names): raise ValueError('expanded keyword arguments are not supported')
                if len(keyword_names)!=len(set(keyword_names)):
                    raise SophonError('S269','A named function argument was supplied more than once.',file,line,1,source,
                                      'Use each named argument once.')
                named={kw.arg:calc(kw.value) for kw in node.keywords}
                return _call_sophon_function(functions[node.func.id],positional,named,states,groups,file,line,functions,call_depth+1,modules=modules)
            raise ValueError('unsupported expression')
        result=calc(tree)
        if isinstance(result,complex) or (type(result) in (int,float) and not math.isfinite(float(result))):
            raise ValueError('non-finite result')
        return result
    except KeyError as e:
        raise SophonError('S102',f'Unknown state "{e.args[0]}"',file,line,1,source,'Declare the state first.')
    except ZeroDivisionError:
        raise SophonError('S243','Division by zero.',file,line,1,source,'Use a non-zero divisor.')
    except (SyntaxError,ValueError,TypeError,OverflowError) as e:
        raise SophonError('S244',f'Invalid arithmetic expression: {expr}',file,line,1,source,
                          'Use numbers, numeric states, +, -, *, /, ^, parentheses, or sqrt(expression).')

def _raise_unknown_state(name,file,line,source):
    raise SophonError('S102',f'Unknown state "{name}"',file,line,1,source,'Declare the state before using it in interpolation.')

def _value_type(value):
    if value is None: return 'null'
    if type(value) is bool: return 'boolean'
    if type(value) is int: return 'integer'
    if type(value) is float: return 'float'
    if type(value) is str: return 'string'
    if type(value) is list: return 'list'
    if type(value) is dict: return 'object'
    return 'unknown'

def parse_value(v, states, line, file, source, groups=None, functions=None, call_depth=0, modules=None):
    token=v.strip()
    if token.startswith('"') and token.endswith('"'):
        return _eval_expression(token,states,line,file,source,groups=groups,functions=functions,call_depth=call_depth,modules=modules)
    if token in ('true','false','null') or token.startswith('[') or re.fullmatch(r'-?\d+(?:\.\d+)?',token):
        return _value_from_token(token,states,line,file,source,groups=groups)
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*',token):
        return _value_from_token(token,states,line,file,source,groups=groups)
    if re.search(r'[+*/^()]|\s-\s|sqrt\s*\(',token):
        return _eval_expression(token,states,line,file,source,groups=groups,functions=functions,call_depth=call_depth,modules=modules)
    return _value_from_token(token,states,line,file,source,groups=groups)


def set_field(fields,name,value,pos=None,path=None,line=None,raw=None):
    """Set a multi-state field, optionally moving it to position `pos` (1-based)."""
    if pos is None or pos<1:
        if pos is not None:
            raise SophonError('S108',f'Multi-state position {pos} must be 1 or greater.',getattr(path,'name',path),line,1,raw,
                              'Positions are 1-based.')
        fields[name]=value; return
    items=[(k,v) for k,v in fields.items() if k!=name]
    items.insert(min(pos-1,len(items)),(name,value)); fields.clear(); fields.update(items)

def _parse_multi_fields(body, states, groups, path, header, group_name, functions=None, modules=None):
    is_initial = group_name not in groups
    fields = groups.setdefault(group_name, {})
    operations = []
    for rel_line, raw_line in enumerate(body, 1):
        clean = strip_comment(raw_line).strip()
        if not clean:
            continue
        if '=' in clean:
            entries = _pairs([clean])
            operations.extend((rel_line, entry['raw']) for entry in entries)
        else:
            operations.append((rel_line, clean))
    if not operations:
        raise SophonError('S105', 'A multi-state requires at least two fields.', path.name, header, 1,
                          _header_raw(_read_source(path), header), 'Declare at least two fields inside state { ... }.')

    parsed = []
    for rel_line, raw in operations:
        m = re.fullmatch(r'([A-Za-z_][\w]*)(?:\s*=\s*(.+?))?(?:\s+at\s+\[(\d+)\])?$', raw)
        if not m:
            raise SophonError('S106', 'Invalid multi-state field.', path.name, header+rel_line-1, 1, raw,
                              'Use: age = 18, age at [3], or age = 18 at [3].')
        key, val, pos = m.groups()
        parsed.append((rel_line, raw, key, val, int(pos) if pos is not None else None))

    # Resolve all assignments first, so a field can be reordered before its value
    # declaration in the same initial block without depending on source order.
    declared_here = {key for _, _, key, val, _ in parsed if val is not None}
    for rel_line, raw, key, val, _ in parsed:
        if key not in fields and not is_initial:
            raise SophonError('S107', f'Unknown multi-state field "{key}".', path.name, header+rel_line-1, 1, raw,
                              'Declare every field in the initial multi-state, then update or reorder existing fields.')
        if key not in fields and is_initial and key not in declared_here:
            raise SophonError('S107', f'Unknown multi-state field "{key}".', path.name, header+rel_line-1, 1, raw,
                              'Declare the field with name = value before reordering it.')
        if val is not None:
            fields[key] = parse_value(val, states, header+rel_line-1, path.name, raw, groups=groups, functions=functions, modules=modules)

    if len(fields) < 2:
        raise SophonError('S105', 'A multi-state requires at least two fields.', path.name, header, 1,
                          _header_raw(_read_source(path), header), 'Declare at least two fields.')

    for rel_line, raw, key, _, position in parsed:
        if position is None:
            continue
        if position < 1 or position > len(fields):
            raise SophonError('S108', f'Multi-state position {position} is outside the valid range 1..{len(fields)}.', path.name,
                              header+rel_line-1, 1, raw, 'Positions are 1-based and cannot exceed the number of fields.')
        set_field(fields, key, fields[key], position, path.name, header+rel_line-1, raw)
    return fields


def parse_multi(lines,i,name,states,groups,path,header,functions=None,modules=None):
    """Parse legacy named and current id/state multi-state declarations."""
    nxt, body = _block_body(lines, i, path, header, 'S105', 'multi-state block')
    if name:
        _parse_multi_fields(body, states, groups, path, header+1, name, functions=functions, modules=modules)
        return nxt
    group_id = None
    state_body = None
    for stmt in _statements(body, {'id','state'}):
        if not stmt['closed']:
            raise SophonError('S105', 'Unclosed multi-state declaration.', path.name, header+stmt['line']-1, 1, stmt['raw'], "Add the closing '}'.")
        if stmt['key'] == 'id':
            value = _required_pair_value(stmt,path,header+stmt['line']-1,'S106','Multi-state id','Use id = "user".')
            m = re.fullmatch(r'"([A-Za-z_][\w]*)"', value)
            if not m: raise SophonError('S106', 'Invalid multi-state id.', path.name, header+stmt['line']-1, 1, stmt['raw'], 'Use id = "user".')
            if group_id is not None: raise SophonError('S106', 'Duplicate multi-state id.', path.name, header+stmt['line']-1, 1, stmt['raw'])
            group_id = m.group(1)
        elif stmt['key'] == 'state' and stmt['kind'] == 'block':
            if state_body is not None: raise SophonError('S106', 'A multi-state accepts one state block.', path.name, header+stmt['line']-1, 1, stmt['raw'])
            state_body = stmt['body']
        else:
            raise SophonError('S106', 'A multi-state accepts only id and state { ... }.', path.name, header+stmt['line']-1, 1, stmt['raw'])
    if not group_id or state_body is None:
        raise SophonError('S106', 'Multi-state requires id and state block.', path.name, header, 1, _header_raw(lines,header), 'Use multi-state { id = "user" state { name = "Arda" age = 18 } }.')
    if group_id == 'random' and 'random' in (modules or ()):
        raise SophonError('S290','"random" is reserved by the random module.',path.name,header,1,_header_raw(lines,header),
                          'Choose another multi-state id; random is the module namespace.')
    if group_id in ('date', 'time') and any(k.startswith(('date.', 'time.')) for k in states):
        raise SophonError('S245', f'"{group_id}" is reserved by the datetime module.', path.name, header, 1, _header_raw(lines,header),
                          'Use another multi-state id; date and time are built-in namespaces.')
    _parse_multi_fields(state_body, states, groups, path, header+1, group_id, functions=functions, modules=modules)
    return nxt

DB_ACTIONS=('read','write','modify','remove')

def parse_database_block(lines,i,alias,states,path,header,groups=None,functions=None,modules=None):
    nxt,body=_block_body(lines,i,path,header,'S143','database block')
    connect=None; ops=[]
    for stmt in _statements(body,{'connect',*DB_ACTIONS}):
        if not stmt['closed']: raise SophonError('S143','Unclosed database block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        if stmt['key']=='connect':
            if connect is not None:
                raise SophonError('S148','A database block cannot declare connect more than once.',path.name,n,1,stmt['raw'],
                                  'Keep one connect = file.svt declaration.')
            val=_required_pair_value(stmt,path,n,'S140','Database connect','Use connect = users.svt.')
            m=re.fullmatch(r'(?:to\s+)?([A-Za-z0-9_./-]+\.svt)',val)
            if not m: raise SophonError('S140',f'Invalid database connect "{val}".',path.name,n,1,stmt['raw'],'Use connect = users.svt or connect to users.svt.')
            connect=m.group(1); continue
        action=stmt['key']; data={}; output_state=None
        if stmt['kind']!='block':
            raise SophonError('S148',f'Database {action} must use a block.',path.name,n,1,stmt['raw'],
                              f'Use {action} {{ id = 1 }}.')
        pair_items=_pairs(stmt['body']); pair_keys=[item['key'] for item in pair_items]
        duplicate_keys={key for key in pair_keys if pair_keys.count(key)>1}
        if duplicate_keys:
            raise SophonError('S148',f'Duplicate database {action} field "{sorted(duplicate_keys)[0]}".',path.name,n,1,stmt['raw'],
                              'Declare each query or record field once.')
        for m2 in pair_items:
            key=m2['key']
            if key=='state':
                if action!='read' or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',m2['value']):
                    raise SophonError('S148','Database state is only valid as a read output target.',path.name,n,1,m2['raw'],
                                      'Use read { id = 1 state = result } with an existing or new state name.')
                output_state=m2['value']; continue
            data[key]=parse_value(m2['value'],states,n+1,path.name,m2['raw'],groups=groups,functions=functions,modules=modules)
        ops.append((action,data,n,output_state))
    return nxt, {'alias':alias,'connect':connect,'ops':ops}

MODULE_NAME=r'[A-Za-z_][\w-]*'
_USE_ITEM_RE=re.compile(rf'^({MODULE_NAME})(?:\s+from\s+({MODULE_NAME}))?$')

def _parse_use_body(body,path,header):
    """Parse the inside of a use block into (plain modules, named imports).

    Accepts `mod`, `mod mod` and `name from mod`, inline or one per line.
    """
    uses=[]; imports=[]
    for raw in body:
        x=strip_comment(raw).strip().strip('{}').strip()
        if not x: continue
        toks=x.split(); k=0
        while k<len(toks):
            if toks[k+1:k+2]==['from']:
                if k+2>=len(toks):
                    raise SophonError('S111',f'Invalid module import "{toks[k]} from".',path.name,header+1,1,None,
                                      'Use: use { name from module }.')
                name,module=toks[k],toks[k+2]; k+=3
            else:
                if not re.fullmatch(MODULE_NAME,toks[k]):
                    raise SophonError('S111',f'Invalid module name "{toks[k]}".',path.name,header+1,1,None,
                                      'Use one module name, or name from module.')
                name,module=toks[k],None; k+=1
            if module is None:
                if name in PLANNED_MODULES:
                    raise SophonError('S250',f'Module "{name}" is designed but not implemented yet.',path.name,header+1,1,None,
                                      'This module is reserved for a future Sophon release; use only implemented modules: '+', '.join(MODULES)+'.')
                if name not in MODULES:
                    raise SophonError('S111',f'Unknown module "{name}".',path.name,header+1,1,None,
                                      'Available modules: '+', '.join(MODULES)+'.')
                if name in uses: raise SophonError('S112',f'Duplicate module import "{name}".',path.name,header+1,1,None,'Import each module only once.')
                uses.append(name); continue
            if module in PLANNED_MODULES:
                raise SophonError('S250',f'Module "{module}" is designed but not implemented yet.',path.name,header+1,1,None,
                                  'This module is reserved for a future Sophon release; use only implemented modules: '+', '.join(MODULES)+'.')
            if module not in MODULES:
                raise SophonError('S111',f'Unknown module "{module}".',path.name,header+1,1,None,
                                  'Available modules: '+', '.join(MODULES)+'.')
            if any(i['module']==module and i['name']==name for i in imports):
                raise SophonError('S112',f'Duplicate import "{name} from {module}".',path.name,header+1,1,None,'Import each name only once.')
            imports.append({'name':name,'module':module})
    if not uses and not imports:
        raise SophonError('S110','Use block cannot be empty.',path.name,header,1,None,'Import at least one module.')
    return uses,imports

def _module_available(uses,imports,module):
    """A module is available when imported whole, or when one of its names was imported."""
    return module in uses or any(i['module']==module for i in imports)

def _name_available(uses,imports,name,module):
    return module in uses or any(i['module']==module and i['name']==name for i in imports)

def _parse_use_block(lines,i,path,header):
    """Read a use block, inline or one item per line.

    Returns (next_index, plain modules, named imports).
    """
    nxt,body=_block_body(lines,i,path,header,'S113','use block')
    uses,imports=_parse_use_body(body,path,header)
    return nxt,uses,imports



def parse_agent_connect_block(lines,i,path,header):
    nxt,body=_block_body(lines,i,path,header,'A003','agent connect block')
    aid=None; seen_id=False
    for stmt in _statements(body,{'id'}):
        if not stmt['closed']: raise SophonError('A003','Unclosed agent connect block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        if stmt['key']!='id':
            raise SophonError('A002',f'Invalid agent connect statement "{stmt["raw"]}".',path.name,header+stmt['line']-1,1,stmt['raw'],'Use only id = 1001.')
        if seen_id:
            raise SophonError('A038','Agent connect cannot declare id more than once.',path.name,header+stmt['line']-1,1,stmt['raw'],'Keep one numeric id in each agent connect block.')
        seen_id=True
        value=_required_pair_value(stmt,path,header+stmt['line']-1,'A002','Agent connect id','Use id = 1001.')
        if re.fullmatch(r'\d+',value):
            aid=int(value)
        else:
            m=re.fullmatch(r'"([A-Za-z0-9_-]+)"',value)
            if not m: raise SophonError('A002',f'Invalid agent id "{value}".',path.name,header+stmt['line']-1,1,stmt['raw'],'Use a numeric id, for example id = 1001.')
            aid=m.group(1)  # Legacy XAF compatibility.
    if aid is None: raise SophonError('A001','Agent connect requires id.',path.name,header,1,_header_raw(lines,header),'Use id = 1001.')
    return nxt,aid

def parse_agent_message_block(lines,i,path,header,kind):
    """Parse agent run (message or task) and legacy agent task blocks."""
    nxt,body=_block_body(lines,i,path,header,'A009',f'agent {kind} block')
    aid=None; payload=None; attachments=[]; seen_input=False; output=None
    payload_kind=None; seen=set()
    allowed={'id','input','task'} if kind=='task' else {'id','input','message','task','output'}
    for stmt in _statements(body,allowed):
        if not stmt['closed']:
            raise SophonError('A009',f'Unclosed agent {kind} block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        key=stmt['key']; n=header+stmt['line']-1
        if key=='input':
            if stmt['kind']!='block':
                raise SophonError('A041','Agent input must be a block containing file assignments.',path.name,n,1,stmt['raw'],
                                  'Use input { file = "data.txt" }.')
            seen_input=True
            for item in _pairs(stmt['body']):
                if item['key']!='file': continue
                m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',item['value'])
                if not m: raise SophonError('A041',f'Invalid agent input "{item["value"]}".',path.name,n,1,item['raw'],'Use file = "path".')
                attachments.append(m.group(1))
            continue
        if key in seen:
            raise SophonError('A008',f'An agent {kind} block cannot declare {key} twice.',path.name,n,1,stmt['raw'],'Declare each setting once.')
        seen.add(key)
        if key=='id':
            value=_required_pair_value(stmt,path,n,'A008','Agent id','Use id = 1001.')
            if re.fullmatch(r'\d+',value): aid=int(value)
            else:
                m=re.fullmatch(r'"([A-Za-z0-9_-]+)"',value)
                if not m: raise SophonError('A008',f'Invalid agent id "{value}".',path.name,n,1,stmt['raw'],'Use a numeric Agent id, for example id = 1001.')
                aid=m.group(1)  # Legacy XAF compatibility.
            continue
        if key=='output':
            value=_required_pair_value(stmt,path,n,'A008','Agent output','Use output = response_state.')
            if kind!='run':
                raise SophonError('A008','output is supported only by agent run.',path.name,n,1,stmt['raw'],'Use output = response_state inside agent run.')
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value):
                raise SophonError('A008',f'Invalid agent output state "{value}".',path.name,n,1,stmt['raw'],'Use output = response_state.')
            output=value; continue
        if key in ('message','task'):
            if stmt['kind']!='block':
                raise SophonError('A008',f'Agent {key} content must use a block.',path.name,n,1,stmt['raw'],
                                  f'Use {key} {{ "..." }}.')
            if payload_kind is not None:
                raise SophonError('A032','agent run accepts exactly one of message or task.',path.name,n,1,stmt['raw'],
                                  'Choose message { ... } or task { ... }, not both.')
            payload_kind=key
            payload='\n'.join(sophon_line(x,path,n) for x in stmt['body'] if x.strip())
    if aid is None:
        raise SophonError('A004',f'agent {kind} requires id.',path.name,header,1,_header_raw(lines,header),'Use id = 1001.')
    if payload is None:
        required='task' if kind=='task' else 'message or task'
        raise SophonError('A005',f'agent {kind} requires {required} content.',path.name,header,1,_header_raw(lines,header),
                          'Add message { "..." } or task { "..." }.')
    if kind=='task' and payload_kind!='task':
        raise SophonError('A005','agent task requires task content.',path.name,header,1,_header_raw(lines,header),'Add task { "..." }.')
    if seen_input and not attachments:
        raise SophonError('A041','An agent input block requires a file.',path.name,header,1,_header_raw(lines,header),'Add file = "path".')
    call_kind='task' if payload_kind=='task' else 'run'
    return nxt,(call_kind,aid,payload,attachments,output)

def sophon_line(x,path,line):
    """One quoted content line of an agent message or task block."""
    v=x.strip()
    if len(v)>=2 and v[0]=='"' and v[-1]=='"': return _decode_string(v)
    raise SophonError('A006',f'Invalid agent content "{v}".',path.name,line,1,None,'Use a string inside the content block.')



def _decode_string(x):
    try: return json.loads(x)
    except Exception: return x[1:-1]

def _brace_delta(line):
    """Net brace depth of a line, ignoring braces inside comments and quoted strings."""
    depth=0; in_str=False; i=0
    while i<len(line):
        c=line[i]
        if c=='"' and (i==0 or line[i-1]!='\\'): in_str=not in_str
        elif not in_str and c=='/' and i+1<len(line) and line[i+1]=='/': break
        elif not in_str:
            if c=='{': depth+=1
            elif c=='}': depth-=1
        i+=1
    return depth

def _top_level_map(text):
    """Per character: True where it sits at nesting depth 0 and outside a string."""
    depth=0; in_str=False; out=[]; i=0; n=len(text)
    while i<n:
        c=text[i]
        if c=='"' and (i==0 or text[i-1]!='\\'):
            in_str=not in_str; out.append(depth==0 and not in_str)
        elif not in_str and c=='{':
            depth+=1; out.append(False)
        elif not in_str and c=='}':
            depth-=1; out.append(False)
        else: out.append(depth==0 and not in_str)
        i+=1
    return out

def _statements(body, keys, named=()):
    """Split a block body into ordered statements.

    A block may be written inline (`note { title = "t" text = "x" }`) or across lines
    and both forms must yield the same statements, so every block parser reads through
    here. `keys` is that parser's own set of statement keywords: a keyword followed by
    `{` opens a nested block, a keyword followed by `=` is a pair, and anything else is
    part of the value of the statement in progress. A keyword listed in `named` may
    carry an identifier before its block, as in `multi-state user { ... }`.
    """
    if not keys: return []
    text=''
    for r in body: text+=r+'\n'
    flat=_top_level_map(text)
    alt='|'.join(re.escape(k) for k in sorted(keys,key=len,reverse=True))
    pattern=rf'\b({alt})\b(\s*\{{\s*|\s*=\s*|(?=\s|$))'
    starts=[]
    for m in re.finditer(pattern,text):
        if not flat[m.start()]: continue
        if m.start() and not flat[m.start()-1]: continue
        starts.append([m.start(),m.end(),m.group(1),m.group(2),''])
    for st in starts:
        if st[2] not in named: continue
        ident,after=_next_named_id(text,flat,st[1])
        st[4]=ident
        if ident: st[1]=after
    out=[]
    for idx,(s,e,key,tail,name) in enumerate(starts):
        stop=starts[idx+1][0] if idx+1<len(starts) else len(text)
        raw=text[s:stop]
        line=text.count('\n',0,s)+1
        opens=bool(re.match(r'\s*\{',text[e:]))
        if tail.strip().startswith('{') or (name and opens):
            brace=text.find('{',s,stop+1)
            end=_closing_brace(text,brace)
            closed=end is not None
            if not closed: end=len(text)
            out.append({'kind':'block','key':key,'name':name or None,'body':text[e:end].splitlines(),
                        'raw':strip_comment(text[s:end+1]).strip() if closed else raw.strip(),
                        'line':line,'closed':closed})
        else:
            out.append({'kind':'pair','key':key,'name':name or None,
                        'value':strip_comment(text[e:stop]).strip(),
                        'raw':strip_comment(raw).strip(),'line':line,'closed':True})
    return out

def _required_pair_value(stmt, path, line, code, what, hint):
    """Return an assignment value or raise a located Sophon diagnostic."""
    if stmt.get('kind') != 'pair' or 'value' not in stmt:
        raise SophonError(code, f'{what} must be written as an assignment.', path.name, line, 1,
                          stmt.get('raw'), hint)
    return stmt['value']

def _pairs(body):
    """All `key = value` statements in a body, in order, with arbitrary keys.

    Used where a block holds data rather than a fixed vocabulary, such as a database
    operation or a vault record.
    """
    text=''
    for r in body: text+=r+'\n'
    flat=_top_level_map(text)
    starts=[(m.start(),m.end(),m.group(1)) for m in re.finditer(r'([A-Za-z_][\w-]*)\s*=\s*',text)
            if flat[m.start()] and (m.start()==0 or flat[m.start()-1])]
    out=[]
    for idx,(s,e,key) in enumerate(starts):
        stop=starts[idx+1][0] if idx+1<len(starts) else len(text)
        out.append({'kind':'pair','key':key,'value':strip_comment(text[e:stop]).strip(),
                    'raw':strip_comment(text[s:stop]).strip(),
                    'line':text.count('\n',0,s)+1,'closed':True})
    return out

def _closing_brace(text,brace):
    """Index of the brace closing the one at `brace`, or None when it is unclosed."""
    if brace<0: return None
    depth=0
    for i in range(brace,len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0: return i
    return None

def _next_named_id(text,flat,pos):
    """Read the identifier a named-block keyword carries, if one follows.

    Returns (identifier, index just past it).
    """
    m=re.match(r'\s*([A-Za-z_][\w.-]*)',text[pos:])
    if not m: return '',pos
    if not all(flat[i] for i in range(pos+m.start(),pos+m.end())): return '',pos
    return m.group(1),pos+m.end()


def _header_raw(lines,header):
    """The source line that opened a block, or None when the index is out of range."""
    return lines[header-1] if 0<header<=len(lines) else None

def _block_body(lines,i,path,header,code,what):
    """Return (index_after_block, body_lines) for the block opening at lines[i].

    The body may be written inline on the header line or span the following lines.
    """
    depth=0
    for j in range(i,len(lines)):
        depth += _brace_delta(lines[j])
        if depth==0:
            if j==i:
                head=lines[i].index('{')+1
                body=[lines[i][head:lines[i].rindex('}')]] if '}' in lines[i][head:] else []
            else:
                body=lines[i+1:j]
            return j+1, body
    raise SophonError(code,f'Unclosed {what}.',path.name,header,1,_header_raw(lines,header) if header-1<len(lines) else None,"Add the closing '}'.")

def _parse_list_operand(token, path, line, raw):
    """A list element: a bare word is literal text, matching state value lists."""
    kind,val=_parse_operand(token,path,line,raw)
    return ('lit',token.strip()) if kind=='ref' else (kind,val)

def _parse_operand(token, path, line, raw):
    """One operand of a surface item: a literal, a list, or a state reference.

    Literals and list elements are resolved when the file is read; a bare reference is
    resolved at run time so it can see state produced by an ask.
    """
    t=token.strip()
    if t.startswith('[') and t.endswith(']'):
        return ('list',[_parse_list_operand(x,path,line,raw) for x in _list_tokens(t[1:-1],path.name,line,raw,'S210') if x.strip()])
    if t=='null': return ('lit',None)
    if t=='true': return ('lit',True)
    if t=='false': return ('lit',False)
    if len(t)>=2 and t[0]=='"' and t[-1]=='"':
        try: return ('template',json.loads(t))
        except Exception: return ('template',t[1:-1])
    if re.fullmatch(r'-?\d+',t): return ('lit',int(t))
    if re.fullmatch(r'-?(?:\d+\.\d*|\d*\.\d+)',t): return ('lit',float(t))
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*',t): return ('ref',t)
    raise SophonError('S252',f'Invalid surface item "{t}".',path.name,line,1,raw,
                      'Use a string, number, boolean, null, or a state name.')

def _split_tokens(text, path, line, raw, code, what, joiner=None):
    """Split block text into whitespace-separated tokens, keeping quoted strings atomic."""
    toks=[]; buf=''; in_str=False; depth=0; i=0
    while i<len(text):
        c=text[i]
        if c=='"' and (i==0 or text[i-1]!='\\'): in_str=not in_str; buf+=c
        elif in_str: buf+=c
        elif c=='[':
            depth+=1; buf+=c
        elif c==']':
            depth-=1; buf+=c
        elif depth>0: buf+=c
        elif joiner and c==joiner:
            if buf: toks.append(buf); buf=''
            toks.append(joiner)
        elif c.isspace():
            if buf: toks.append(buf); buf=''
        else: buf+=c
        i+=1
    if in_str: raise SophonError(code,f'Unterminated string in {what}.',path.name,line,1,raw,'Close the quote before the closing brace.')
    if depth: raise SophonError(code,f'Unclosed "[" in {what}.',path.name,line,1,raw,'Close the bracket.')
    if buf: toks.append(buf)
    return toks

def _scan_operands(body, path, line, raw):
    """Split a surface/component body into whitespace-separated values.

    `+` is numeric-only in Sophon and is not a text-concatenation operator.
    Assign arithmetic to a state first; use `{state}` inside a string for
    interpolation. Reject the legacy surface concatenation form explicitly.
    """
    toks=_split_tokens(body,path,line,raw,'S253','surface block',joiner='+')
    if not toks:
        raise SophonError('S151','A surface block cannot be empty.',path.name,line,1,raw,
                          'List at least one state name or value.')
    if '+' in toks:
        raise SophonError('S251','The + operator cannot concatenate surface or component text.',path.name,line,1,raw,
                          'Use interpolation such as "Hello, {name}", or calculate a numeric state before surfacing it.')
    return [[_parse_operand(token,path,line,raw)] for token in toks]

def _format_value(v):
    if isinstance(v,list): return '['+', '.join(_format_value(x) for x in v)+']'
    if v is None: return 'null'
    if v is True: return 'true'
    if v is False: return 'false'
    return v if isinstance(v,str) else str(v)

def _format_source(v):
    """Render a value as Sophon source text, for writing a .svt back out."""
    if isinstance(v,list): return '['+' '.join(_format_source(x) for x in v)+']'
    if isinstance(v,str): return json.dumps(v,ensure_ascii=False)
    return _format_value(v)

def _lookup_ref(ref,states,groups,name):
    """Resolve a state, datetime built-in, or `group.field` multi-state reference."""
    if ref in states:
        return states[ref]
    if '.' in ref:
        root,*parts=ref.split('.')
        if root in states:
            value=states[root]
            for field in parts:
                if not isinstance(value,dict) or field not in value:
                    raise SophonError('S102',f'Unknown object field "{ref}"',name,1,1,None,
                                      'Check the object state and each nested field name.')
                value=value[field]
            return value
        if root in groups and len(parts)==1:
            field=parts[0]
            if field not in groups[root]:
                raise SophonError('S102',f'Unknown multi-state field "{ref}"',name,1,1,None,
                                  'Declare the field inside the multi-state block.')
            return groups[root][field]
        raise SophonError('S102',f'Unknown state or multi-state "{root}"',name,1,1,None,
                          'Declare the state or multi-state before referring to its fields.')
    if ref not in states:
        raise SophonError('S102',f'Unknown state "{ref}"',name,1,1,None,
                          'Declare the state, or ask for it, before surfacing it.')
    return states[ref]

def _eval_operand(operand,states,groups,secrets,name):
    kind,val=operand
    if kind=='list': return [_eval_operand(x,states,groups,secrets,name) for x in val]
    if kind=='ref':
        if val in secrets: return '*'
        return _lookup_ref(val,states,groups,name)
    if kind=='template':
        pattern=r'\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}'
        def replace(match):
            ref=match.group(1)
            if ref in secrets: return '*'
            return _format_value(_lookup_ref(ref,states,groups,name))
        return re.sub(pattern,replace,val)
    return val

def _eval_item(operands,states,groups,secrets,name):
    """Evaluate one surface item. Returns (text, is_single_state_ref)."""
    parts=[]; single=None
    for n,(kind,val) in enumerate(operands):
        if kind=='ref':
            if n==0 and len(operands)==1: single=val
            parts.append('*' if val in secrets else _format_value(_lookup_ref(val,states,groups,name)))
        else: parts.append(_format_value(_eval_operand((kind,val),states,groups,secrets,name)))
    return ''.join(parts), single

def parse_surface_block(lines,i,path,header):
    nxt,body=_block_body(lines,i,path,header,'S152','surface block')
    return nxt,_scan_operands('\n'.join(body),path,header,_header_raw(lines,header))

_SETTING_RE=re.compile(r'\b(prompt|suggestion|type|secret|requirement)\s*=\s*("(?:[^"\\]|\\.)*"|[A-Za-z]+)|'
                       r'\b(default|duration)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s]+)')
_SETTING_KEYS=('prompt','suggestion','type','default','secret','requirement','duration')

def _line_of(body,offset):
    return body.count('\n',0,offset)+1

def _parse_ask_settings(body, path, header):
    """Parse the settings of an ask or ask-field block.

    Settings are `key = value` pairs and may sit on their own lines or inline, so the
    body is scanned by position and anything that is not a setting is rejected.
    """
    out={'prompt':None,'suggestion':None,'type':None,'default':None,'secret':False,'requirement':False,'duration':None}
    default_seen=False; consumed=[]; pos=0
    for m in _SETTING_RE.finditer(body):
        gap=body[pos:m.start()]
        if gap.strip():
            line=header+_line_of(body,pos+len(gap)-len(gap.lstrip()))
            raise SophonError('S167',f'Invalid ask setting "{gap.strip().splitlines()[0]}".',path.name,line,1,None,
                              f'Use {", ".join(_SETTING_KEYS)} inside an ask block.')
        key=m.group(1) or m.group(3); val=m.group(2) or m.group(4)
        line=header+_line_of(body,m.start())
        if key in ('prompt','suggestion'):
            if out[key] is not None:
                raise SophonError('S164',f'Duplicate {key} in ask block.',path.name,line,1,None,f'Define {key} only once.')
            out[key]=json.loads(val) if val.startswith('"') else val
        elif key=='type':
            name=val[1:-1] if val.startswith('"') else val
            if name not in ASK_TYPES:
                raise SophonError('S165',f'Unknown ask type "{name}".',path.name,line,1,None,
                                  'Use type = '+' or '.join(f'"{t}"' for t in ASK_TYPES)+'.')
            out['type']=name
        elif key in ('secret','requirement'):
            if val not in ('true','false'):
                raise SophonError('S163',f'Invalid {key} value "{val}".',path.name,line,1,None,f'Use {key} = true or {key} = false.')
            out['secret' if key=='secret' else 'requirement']=val=='true'
        elif key=='duration':
            try: duration=float(val)
            except ValueError: duration=0
            if duration <= 0:
                raise SophonError('S175',f'Invalid ask duration "{val}".',path.name,line,1,None,'Use a positive duration in seconds, for example duration = 30.')
            out['duration']=duration
        else:
            if default_seen:
                raise SophonError('S164','Duplicate default in ask block.',path.name,line,1,None,'Define default only once.')
            default_seen=True
            kind,lit=_parse_operand(val,path,line,None)
            if kind=='ref':
                raise SophonError('S166','A default value must be a literal.',path.name,line,1,None,'Use a string, number, boolean, or null as the default.')
            out['default']=lit
        pos=m.end()
    if body[pos:].strip():
        raise SophonError('S167',f'Invalid ask setting "{body[pos:].strip().splitlines()[0]}".',path.name,header+_line_of(body,pos),1,None,
                          f'Use {", ".join(_SETTING_KEYS)} inside an ask block.')
    if out['requirement'] and out['duration'] is not None and (not default_seen or out['default'] is None):
        raise SophonError('S175','A required ask with duration needs a non-null default value.',path.name,header,1,None,
                          'Either remove duration, set requirement = false, or provide default = "...".')
    return out

def _ask_specs_from_multi_state(lines, path, header):
    """Read a multi-state { field { ... } ... } body into flat ask specs."""
    specs=[]; seen=set()
    for name,i,j,body in _named_blocks(lines,r'^\s*([A-Za-z_][\w]*)\s*\{'):
        if name in seen:
            raise SophonError('S168',f'Duplicate ask field "{name}".',path.name,header+i,1,None,'Use a unique field name.')
        seen.add(name)
        spec=_parse_ask_settings(body, path, header+i+1)
        if not spec['prompt']:
            raise SophonError('S162',f'Ask field "{name}" requires a prompt.',path.name,header+i,1,None,'Add prompt = "..." to the field.')
        spec['target']=name; specs.append(spec)
    if not specs:
        raise SophonError('S169','A multi-state ask requires at least one field.',path.name,header,1,None,'Add a field block, for example name { prompt = "..." }.')
    return specs

_ASK_ID_RE=re.compile(r'\bid\s*=\s*"([A-Za-z0-9_-]+)"')
_ASK_STATE_RE=re.compile(r'(?<![\w-])state\s*=\s*"?([A-Za-z_][A-Za-z0-9_]*)"?')
_MULTI_LINE_RE=re.compile(r'^\s*multi-state\s*\{\s*$')
_ID_LINE_RE=re.compile(r'id\s*=\s*"[A-Za-z0-9_-]+"')

def parse_ask_body(body,path,header,raw_header):
    """Read the body of an ask block. Returns a list of specs."""
    multi=None
    for k,raw in enumerate(body):
        if _MULTI_LINE_RE.match(raw):
            if multi is not None:
                raise SophonError('S163','An ask block cannot declare multi-state twice.',path.name,header+k+1,1,raw,'Keep a single multi-state block.')
            multi=k; break
    if multi is None:
        own=body; field_lines=None
    else:
        _,field_lines=_block_body(body,multi,path,header+multi,'S169','multi-state block')
        own=body[:multi]

    own_text='\n'.join(own)
    ask_id=None; target=None; resid=own_text
    m=_ASK_ID_RE.search(own_text)
    if m: ask_id=m.group(1); resid=resid[:m.start()]+resid[m.end():]
    m=_ASK_STATE_RE.search(resid)
    if m and field_lines is not None:
        raise SophonError('S163','An ask block cannot use both state and multi-state.',path.name,header+own_text[:m.start()].count('\n'),1,None,
                          'Keep the single state form or the multi-state form, not both.')
    if m: target=m.group(1); resid=resid[:m.start()]+resid[m.end():]
    if not ask_id:
        raise SophonError('S161','An ask block requires an id.',path.name,header,1,raw_header,'Add id = "label" so diagnostics can name the ask.')

    settings=_parse_ask_settings(resid, path, header)
    if field_lines is not None:
        specs=_ask_specs_from_multi_state(field_lines, path, header+multi+1)
    else:
        if not settings['prompt']:
            raise SophonError('S162','An ask block requires a prompt.',path.name,header,1,raw_header,'Add prompt = "..." to the ask block.')
        if target is None:
            raise SophonError('S199','An ask block requires a state target.',path.name,header,1,raw_header,
                              'Use confirmation for a yes/no question, or add state = <name>.')
        spec=dict(settings); spec['target']=target; specs=[spec]
    for s in specs: s['id']=ask_id; s.setdefault('kind','ask')
    return specs

def parse_ask_block(lines,i,path,header):
    """Read one ask block. Returns (next_index, [spec, ...])."""
    nxt,body=_block_body(lines,i,path,header,'S160','ask block')
    return nxt,parse_ask_body(body,path,header+1,_header_raw(lines,header))

def parse_multi_ask_block(lines,i,path,header):
    """Read sibling ask blocks inside a multi-ask group."""
    nxt,body=_block_body(lines,i,path,header,'S170','multi-ask block')
    gid=_require_block_id(body,path,header,'multi-ask','S174',('id','ask'))
    specs=[]
    for stmt in _statements(body,{'id','ask'}):
        if not stmt['closed']:
            raise SophonError('S170','Unclosed multi-ask block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        if stmt['key']=='id': continue
        if stmt['key']!='ask':
            raise SophonError('S173',f'A multi-ask block accepts only sibling ask blocks, found "{stmt["raw"]}".',
                              path.name,n,1,stmt['raw'],'Place each ask { ... } directly inside multi-ask.')
        one=parse_ask_body(stmt['body'],path,n,stmt['raw'])
        for spec in one:
            spec['group']=gid
            spec['line']=n
        specs.extend(one)
    if not specs:
        raise SophonError('S172','A multi-ask block requires at least one ask block.',path.name,header,1,_header_raw(lines,header),
                          'Add one or more ask { id = "..."; prompt = "..."; state = name } blocks.')
    return nxt,specs

_CHOICE_ASSIGN_RE=re.compile(r'([A-Za-z_][\w.-]*)\s*=\s*(.+)$')

def _parse_choice_block(body,path,header):
    """Read a choice block body. Returns [(label, value), ...]."""
    text='\n'.join(body)
    toks=_split_tokens(text,path,header,body[0] if body else None,'S182','choice block')
    raw_entries=[]; i=0
    while i<len(toks):
        t=toks[i]
        if len(t)>=2 and t[0]=='"' and t[-1]=='"': raw_entries.append((json.loads(t),None)); i+=1; continue
        if i+2<len(toks) and toks[i+1]=='=': raw_entries.append((t,toks[i+2])); i+=3; continue
        raise SophonError('S180',f'Invalid choice entry "{t}".',path.name,header+1,1,None,
                          'Use "text" or label = value inside choice { ... }.')
    if not raw_entries:
        raise SophonError('S182','A choice block requires at least one option.',path.name,header,1,body[0] if body else None,
                          'Add "evet" or evet = true inside choice { ... }.')
    choices=[]
    for label,rawval in raw_entries:
        if rawval is None: value=label
        else:
            kind,val=_parse_operand(rawval,path,header,None)
            if kind=='ref':
                raise SophonError('S181',f'Choice "{label}" must map to a literal value.',path.name,header,1,None,
                                  'Use a string, number, boolean, or null as the choice value.')
            value=val
        choices.append((label,value))
    labels=[c[0] for c in choices]
    if len(set(labels))!=len(labels):
        raise SophonError('S183','Choice labels must be unique.',path.name,header,1,body[0] if body else None,
                          'Use a distinct label for each option.')
    return choices

def parse_confirmation_body(body,path,header,raw_header):
    """Read the body of a confirmation block. Returns one spec."""
    conf_id=_require_block_id(body,path,header,'confirmation','S185',('id','prompt','suggestion','type','default','secret','state','multi-state','requirement','multiple-selection','min-selection','max-selection','choice'))
    prompt=None; requirement=False; target=None; multi=None; choices=None; default=None; default_declared=False
    multiple=False; min_sel=None; max_sel=None
    seen=set()
    for stmt in _statements(body,{'id','prompt','suggestion','type','default','secret','state',
                                 'multi-state','requirement','multiple-selection',
                                 'min-selection','max-selection','choice'}):
        if not stmt['closed']:
            raise SophonError('S184','Unclosed confirmation block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        key=stmt['key']; n=header+stmt['line']-1
        if key in ('prompt','suggestion','type','default','secret','state','requirement',
                   'multiple-selection','min-selection','max-selection','choice','multi-state'):
            if key in seen:
                raise SophonError('S186',f'A confirmation block cannot declare {key} twice.',path.name,n,1,stmt['raw'],
                                  'Keep a single declaration of each setting.')
            seen.add(key)
        if stmt['kind']=='block':
            if key=='choice': choices=_parse_choice_block(stmt['body'],path,n)
            else:
                multi=[strip_comment(r).strip() for r in stmt['body'] if strip_comment(r).strip()]
            continue
        val=stmt['value']
        if key=='state':
            m=re.fullmatch(r'"?([A-Za-z_][\w]*)"?',val)
            if not m: raise SophonError('S189',f'Invalid confirmation state "{val}".',path.name,n,1,stmt['raw'],'Use state = <name>.')
            target=m.group(1); continue
        if key in ('requirement','multiple-selection','secret'):
            if val not in ('true','false'):
                raise SophonError('S163',f'Invalid {key} value "{val}".',path.name,n,1,stmt['raw'],f'Use {key} = true or {key} = false.')
            if key=='requirement': requirement=val=='true'
            elif key=='multiple-selection': multiple=val=='true'
            continue
        if key in ('min-selection','max-selection'):
            if not val.isdigit():
                raise SophonError('S237',f'Invalid {key} value "{val}".',path.name,n,1,stmt['raw'],'Use a non-negative whole number.')
            if key=='min-selection': min_sel=int(val)
            else: max_sel=int(val)
            continue
        if key=='default':
            kind,value=_parse_operand(val,path,n,stmt['raw'])
            if kind=='ref':
                raise SophonError('S166','A confirmation default must be a literal.',path.name,n,1,stmt['raw'],
                                  'Use default = "option-label" or a literal choice value.')
            default=value; default_declared=True
            continue
        if key=='type':
            if val not in ASK_TYPES:
                raise SophonError('S165',f'Unknown ask type "{val}".',path.name,n,1,stmt['raw'],
                                  'Use type = '+' or '.join(f'"{t}"' for t in ASK_TYPES)+'.')
            continue
        if key in ('prompt','suggestion'):
            m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',val)
            if not m: raise SophonError('S189',f'Invalid confirmation {key} "{val}".',path.name,n,1,stmt['raw'],f'Use {key} = "..." .')
            if key=='prompt': prompt=m.group(1)
            continue
    if choices is None:
        raise SophonError('S190','A confirmation block requires a choice block.',path.name,header,1,raw_header,
                          'Add choice { "evet" hayir = false } inside the confirmation.')
    if not prompt:
        raise SophonError('S191','A confirmation block requires a prompt.',path.name,header,1,raw_header,
                          'Add prompt = "..." to the confirmation.')
    if target is None and multi is None:
        raise SophonError('S192','A confirmation block requires a state target.',path.name,header,1,raw_header,
                          'Add state = <name>, or multi-state { value text } to record the answer.')
    if multi is not None and len(multi)!=2:
        raise SophonError('S193','A confirmation multi-state must name exactly two fields.',path.name,header,1,raw_header,
                          'The first field receives the chosen value, the second the label the user typed.')
    for name in (multi or []):
        if not re.fullmatch(r'[A-Za-z_][\w]*',name):
            raise SophonError('S194',f'Invalid confirmation field "{name}".',path.name,header,1,raw_header,'Use a plain field name.')
    if default_declared:
        matched=[c for c in choices if c[0]==default or c[1]==default]
        if not matched:
            raise SophonError('S241',f'Confirmation default "{default}" does not match a choice.',path.name,header,1,raw_header,
                              'Set default to one of the choice labels or values.')
        if multiple:
            raise SophonError('S241','A multiple-selection confirmation cannot have one default choice.',path.name,header,1,raw_header,
                              'Remove default or use a single-selection confirmation.')
        default=matched[0]
    if multiple and not requirement:
        raise SophonError('S238','A multiple-selection confirmation requires requirement = true.',path.name,header,1,raw_header,
                          'The recorded list can only be well defined when every answer comes from the choice list.')
    if multiple and multi is not None:
        raise SophonError('S239','A multiple-selection confirmation writes to a single state, not multi-state.',path.name,header,1,raw_header,
                          'Use state = <name> so the selections are recorded as one list.')
    if min_sel is not None or max_sel is not None:
        lo=1 if min_sel is None else min_sel
        hi=len(choices) if max_sel is None else max_sel
        if lo>hi:
            raise SophonError('S237',f'min-selection {lo} is greater than max-selection {hi}.',path.name,header,1,raw_header,
                              'A confirmation must be able to satisfy the range.')
        if hi>len(choices):
            raise SophonError('S237',f'max-selection {hi} exceeds the {len(choices)} available choices.',path.name,header,1,raw_header,
                              f'Use a max-selection of at most {len(choices)}.')
    return {'kind':'confirmation','id':conf_id,'prompt':prompt,'choices':choices,
            'target':target,'multi':multi,'requirement':requirement,
            'multiple':multiple,'min':(1 if min_sel is None else min_sel),
            'max':(len(choices) if max_sel is None else max_sel),'secret':False,'default':default}

def parse_confirmation_block(lines,i,path,header):
    """Read one confirmation block. Returns (next_index, spec)."""
    nxt,body=_block_body(lines,i,path,header,'S184','confirmation block')
    return nxt,parse_confirmation_body(body,path,header+1,_header_raw(lines,header))

def parse_multi_confirmation_block(lines,i,path,header):
    """Read a multi-confirmation { id, confirmation { } } block."""
    nxt,body=_block_body(lines,i,path,header,'S195','multi-confirmation block')
    gid=_require_block_id(body,path,header,'multi-confirmation','S196',('id','confirmation'))
    specs=[]
    for stmt in _statements(body,{'id','confirmation'}):
        if not stmt['closed']: raise SophonError('S195','Unclosed multi-confirmation block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        if stmt['key']=='id': continue
        if stmt['key']!='confirmation':
            raise SophonError('S197',f'A multi-confirmation block accepts only confirmation blocks, found "{stmt["raw"]}".',path.name,n,1,stmt['raw'],
                              'Move non-confirmation statements out of the block.')
        spec=parse_confirmation_body(stmt['body'],path,n,stmt['raw'])
        spec['multi_group']=gid
        specs.append(spec)
    if not specs:
        raise SophonError('S198','A multi-confirmation block requires at least one confirmation block.',path.name,header,1,_header_raw(lines,header),
                          'Add a confirmation { id = "..." } block inside.')
    return nxt,specs

def _optional_block_id(body,keys=('id',)):
    return _own_block_id(body,keys)

def _require_module(uses,imports,name,path,line,raw):
    if not _module_available(uses,imports,name):
        raise SophonError('S114',f'Module "{name}" is not imported.',path.name,line,1,raw,
                          f'Add "{name}" to use {{ ... }}, or use {{ {name} from <module> }} if a named import covers it.')


def _parse_watch(body,path,header,selected,state_defs,multi_defs):
    """Parse watch entries as resource references; an empty watch is invalid."""
    for raw_line in body:
        for item in strip_comment(raw_line).strip().split():
            if not item: continue
            if item == 'self-observation':
                if selected:
                    raise SophonError('S121','self-observation must be the only watch entry.',path.name,header,1,raw_line,
                                      'self-observation already watches every resource in the selected source.')
                selected.append(('self-observation', '*'))
                continue
            if any(k=='self-observation' for k,_ in selected):
                raise SophonError('S121','No other watch entry may accompany self-observation.',path.name,header,1,raw_line,
                                  'self-observation already watches every resource in the selected source.')
            m = re.fullmatch(r'([A-Za-z_][\w]*)(?:\.([A-Za-z_][\w]*))?', item)
            if not m:
                raise SophonError('S121', f'Invalid observer watch component "{item}".', path.name, header, 1, raw_line,
                                  'Use a state, multi-state id, multi-state.field, or self-observation.')
            if m.group(2): selected.append(('multi-state', f'{m.group(1)}.{m.group(2)}'))
            else:
                # A bare name can resolve to a state or a whole multi-state at runtime.
                selected.append(('resource', m.group(1)))
    if not selected:
        raise SophonError('S121', 'Observer watch must contain at least one valid component.', path.name, header, 1,
                          None, 'Add at least one state, multi-state, multi-state.field, or self-observation.')


def parse_observer_body(body,path,header,raw_header):
    """Parse one unified observer declaration for self or external sources."""
    oid=None; desc=''; source=None; selected=[]; state_defs=[]; multi_defs=[]; seen=set()
    for stmt in _statements(body, {'id','description','source','watch'}):
        if not stmt['closed']:
            raise SophonError('S122', 'Unclosed observer block.', path.name, header+stmt['line']-1, 1, stmt['raw'], "Add the closing '}'.")
        key=stmt['key']; n=header+stmt['line']-1
        if key in seen:
            raise SophonError('S120', f'An observer block cannot declare {key} twice.', path.name, n, 1, stmt['raw'], 'Declare id, description, source, and watch once.')
        seen.add(key)
        if stmt['kind']=='block':
            if key!='watch':
                raise SophonError('S120',f'Observer {key} must be an assignment; watch is the only nested block.',path.name,n,1,stmt['raw'],
                                  'Use id = 1001, source = self, and watch { state_name }.')
            _parse_watch(stmt['body'],path,n+1,selected,state_defs,multi_defs)
            continue
        value=_required_pair_value(stmt,path,n,'S120',f'Observer {key}','Use an assignment such as id = 1001.')
        if key=='source' and value.strip()=='self':
            source='self'; continue
        if key=='id' and re.fullmatch(r'\d+',value):
            oid=int(value); continue
        m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',value)
        if not m:
            raise SophonError('S120', f'Invalid observer {key} "{value}".', path.name, n, 1, stmt['raw'],
                              'Use a numeric id, description = "...", or source = "file.sph" / self.')
        if key=='id': oid=m.group(1)
        elif key=='description': desc=m.group(1)
        elif key=='source': source=m.group(1)
    if oid is None:
        raise SophonError('S129', 'Observer id is required.', path.name, header, 1, raw_header, 'Use id = 1001.')
    if not source:
        raise SophonError('S120', 'Observer source is required.', path.name, header, 1, raw_header, 'Use source = "main.sph" or source = self.')
    if not selected:
        raise SophonError('S121', 'Observer watch must contain at least one valid component.', path.name, header, 1, raw_header,
                          'Add at least one component inside watch { ... }.')
    if source != 'self' and not source.endswith('.sph'):
        raise SophonError('S120', 'Observer source must be self or a .sph path.', path.name, header, 1, raw_header,
                          'Use source = "main.sph" or source = self.')
    return {'id':oid,'description':desc,'source':source,'selected':selected,'state_defs':state_defs,'multi_defs':multi_defs,
            'self_observation': any(k=='self-observation' for k,_ in selected)}


def parse_observer_block(lines,i,path,header):
    nxt,body=_block_body(lines,i,path,header,'S122','observer block')
    return nxt,parse_observer_body(body,path,header+1,_header_raw(lines,header))

def _own_block_id(body,keys=('id',)):
    """The id declared directly by a block, ignoring ids inside nested child blocks.

    `keys` is the full statement vocabulary of that block, so a value that merely
    contains the word id is never mistaken for the declaration.
    """
    for stmt in _statements(body,set(keys)):
        if stmt['kind']!='pair' or stmt['key']!='id': continue
        if re.fullmatch(r'\d+',stmt['value']): return int(stmt['value'])
        m=re.fullmatch(r'"([A-Za-z0-9_-]+)"',stmt['value'])
        if m: return m.group(1)  # Legacy identifier.
    return None


def _require_block_id(body,path,header,what,code,keys=('id',)):
    found=_own_block_id(body,keys)
    if found: return found
    raise SophonError(code,f'A {what} block requires an id.',path.name,header,1,body[0] if body else None,
                      'Add a numeric id, for example id = 1001.')

def parse_multi_observer_block(lines,i,path,header):
    """Read a multi-observer { id, observer { } } block."""
    nxt,body=_block_body(lines,i,path,header,'S131','multi-observer block')
    gid=_require_block_id(body,path,header,'multi-observer','S132',('id','description','observer'))
    group_description=''
    for meta in _statements(body, {'id','description','observer'}):
        if meta['key']=='description' and meta['kind']=='pair':
            dm=re.fullmatch(r'"((?:[^"\\]|\\.)*)"', meta['value'])
            if not dm: raise SophonError('S132','Invalid multi-observer description.',path.name,header+meta['line']-1,1,meta['raw'],'Use description = "...".')
            group_description=dm.group(1)
    obs=[]
    for stmt in _statements(body,{'id','description','observer'}):
        if not stmt['closed']: raise SophonError('S131','Unclosed multi-observer block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        if stmt['key'] in ('id','description'): continue
        if stmt['key']!='observer':
            raise SophonError('S133',f'A multi-observer block accepts only observer blocks, found "{stmt["raw"]}".',path.name,n,1,stmt['raw'],
                              'Move non-observer statements out of the multi-observer block.')
        obs.append(parse_observer_body(stmt['body'],path,n,stmt['raw']))
    if not obs:
        raise SophonError('S134','A multi-observer block requires at least one observer block.',path.name,header,1,_header_raw(lines,header),
                          'Add an observer { id = "..." source = self watch { state_name } } block inside.')
    return nxt,{'id':gid,'description':group_description,'observers':obs}

def _steps_from_prompts(specs):
    """Turn grouped prompt specs into form steps, inserting a section per group change."""
    steps=[]; last=None
    for s in specs:
        g=s.get('group')
        if g and g!=last: steps.append({'kind':'section','label':g}); last=g
        steps.append({'kind':'prompt','spec':s})
    return steps

BOX_KINDS=('form','note','list','table')

def _box_settings(body,path,header,what,content=()):
    """Read id/title/width from any box-shaped component body.

    `content` is the block's own content vocabulary, listed only so the scan stops at
    a content statement instead of swallowing it into the preceding value.
    """
    form={'id':None,'title':None,'width':60}
    for stmt in _statements(body,{'id','title','width',*content}):
        if not stmt['closed']: raise SophonError('S207',f'Unclosed {what} block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        if stmt['key'] in content: continue
        if stmt['kind']!='pair':
            raise SophonError('S254',f'{what} setting {stmt["key"]} must be an assignment.',path.name,header+stmt['line']-1,1,stmt['raw'],
                              f'Use {stmt["key"]} = "..." inside {what} {{ ... }}.')
        key,val=stmt['key'],stmt['value']
        if key=='width':
            if not val.isdigit() or int(val)<10:
                raise SophonError('S205',f'Invalid {what} width "{val}".',path.name,header+stmt['line']-1,1,stmt['raw'],'Use a width of at least 10.')
            form['width']=int(val); continue
        m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',val)
        if not m: raise SophonError('S207',f'Invalid {what} {key} "{val}".',path.name,header+stmt['line']-1,1,stmt['raw'],f'Use {key} = "..." inside {what} {{ ... }}.')
        form[key]=m.group(1)
    return form

def _parse_note(body,path,header):
    box=_box_settings(body,path,header,'note',('text',)); box['kind']='note'; box['lines']=[]
    for stmt in _statements(body,{'id','title','width','text'}):
        if not stmt['closed']: raise SophonError('S207','Unclosed note block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        if stmt['key']!='text': continue
        if stmt['kind']!='pair':
            raise SophonError('S254','Note text must be an assignment.',path.name,header+stmt['line']-1,1,stmt['raw'],
                              'Use text = "..." inside the note.')
        box['lines'].append(stmt['value'])
    if not box['lines']:
        raise SophonError('S208','A note requires at least one text line.',path.name,header,1,body[0] if body else None,'Add text = "..." inside the note.')
    return box

def _parse_list(body,path,header):
    box=_box_settings(body,path,header,'list',('item',)); box['kind']='list'; box['items']=[]
    for stmt in _statements(body,{'id','title','width','item'}):
        if not stmt['closed']: raise SophonError('S209','Unclosed list block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        if stmt['key']!='item': continue
        if stmt['kind']!='pair':
            raise SophonError('S254','List item must be an assignment.',path.name,header+stmt['line']-1,1,stmt['raw'],
                              'Use item = "..." inside the list.')
        box['items'].append(stmt['value'])
    if not box['items']:
        raise SophonError('S210','A list requires at least one item.',path.name,header,1,body[0] if body else None,'Add item = "..." inside the list.')
    return box

def _parse_table(body,path,header):
    box=_box_settings(body,path,header,'table',('row',)); box['kind']='table'
    box['rows']=[]
    for stmt in _statements(body,{'id','title','width','row'}):
        if stmt['key']!='row': continue
        if stmt['kind']!='pair':
            raise SophonError('S254','Table row must be an assignment.',path.name,header+stmt['line']-1,1,stmt['raw'],
                              'Use row "col1" "col2" inside the table.')
        box['rows'].append(_scan_operands(stmt['value'],path,header+stmt['line']-1,stmt['raw']))
    if not box['rows']:
        raise SophonError('S211','A table requires at least one row.',path.name,header,1,body[0] if body else None,'Add row "col1" "col2" inside the table.')
    return box

def _parse_group_block(body, child, path, header, raw_header):
    """Parse the interior of a multi-ask / multi-confirmation block handed over as a body.

    The real parsers take (lines, index); the block body is already an extracted list,
    so it is wrapped back into the one-line header form they expect.
    """
    lines=[child+' {']+list(body)+['}']
    parser = parse_multi_ask_block if child=='ask' else parse_multi_confirmation_block
    _,specs = parser(lines,0,path,header)
    return specs

def _parse_form(body,path,header):
    """Read a form body into a form dict with ordered steps."""
    form=_box_settings(body,path,header,'form',('surface','ask','confirmation','multi-ask','multi-confirmation'))
    form['kind']='form'; form['steps']=[]
    for stmt in _statements(body,{'id','title','width','surface','ask','confirmation','multi-ask','multi-confirmation'}):
        if not stmt['closed']:
            raise SophonError('S201','Unclosed form block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        key=stmt['key']
        if key in ('id','title','width'): continue
        if stmt['kind']!='block':
            raise SophonError('S254',f'Form step {key} must use a block.',path.name,n,1,stmt['raw'],
                              f'Use {key} {{ ... }} inside form.')
        if key=='surface':
            text='\n'.join(stmt['body']).strip()
            form['steps'].append({'kind':'surface','items':_scan_operands(text,path,n,stmt['raw'])}); continue
        if key=='ask':
            form['steps'].extend(_steps_from_prompts(parse_ask_body(stmt['body'],path,n,stmt['raw']))); continue
        if key=='confirmation':
            form['steps'].append({'kind':'prompt','spec':parse_confirmation_body(stmt['body'],path,n,stmt['raw'])}); continue
        specs=_parse_group_block(stmt['body'],'ask' if key=='multi-ask' else 'confirmation',path,n,stmt['raw'])
        form['steps'].extend(_steps_from_prompts(specs))
    if not form['steps']:
        raise SophonError('S206','A form requires at least one surface, ask, or confirmation.',path.name,header,1,body[0] if body else None,
                          'Add a surface { } or ask { } block inside the form.')
    return form





_BOX_PARSERS={'form':_parse_form,'note':_parse_note,'list':_parse_list,'table':_parse_table}

def parse_box_body(kind,body,path,header,uses,imports,raw_header):
    """Read the body of one component box of the given kind."""
    if not _name_available(uses,imports,kind,'component'):
        raise SophonError('S114',f'"{kind}" from "component" is not imported.',path.name,header,1,raw_header,
                          f'Add: use {{ {kind} from component }}')
    return _BOX_PARSERS[kind](body,path,header)

def _parse_box(kind,lines,i,path,header,uses,imports):
    """Read one component box, checking that its kind is imported."""
    code={'form':'S201','note':'S207','list':'S209','table':'S211'}[kind]
    nxt,body=_block_body(lines,i,path,header,code,f'{kind} block')
    return nxt,parse_box_body(kind,body,path,header+1,uses,imports,_header_raw(lines,header))

FILE_OPS=('create','write','append','read','list','delete','copy','move','mkdir','zip','unzip')
_FILE_SETTINGS=('path','from','to','state','data')


def parse_file_block(lines,i,path,header):
    """Read a file { <op> { ... } ... } block. Returns (next_index, [ops])."""
    nxt,body=_block_body(lines,i,path,header,'S220','file block')
    ops=[]; group=None
    for stmt in _statements(body,{'id',*FILE_OPS}):
        if not stmt['closed']:
            raise SophonError('S220','Unclosed file block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        if stmt['key']=='id':
            # File blocks may carry an optional label for readability; it is
            # metadata, not an operation. Preserve the documented legacy form.
            _required_pair_value(stmt,path,n,'S224','File block id','Use id = "files".')
            continue
        op=stmt['key']
        if stmt['kind']!='block':
            raise SophonError('S224',f'File operation {op} must use a block.',path.name,n,1,stmt['raw'],
                              f'Use {op} {{ path = "..." }}.')
        paths=[]; data=None; target=None; seen_settings=set()
        for f in _pairs(stmt['body']):
            key,val=f['key'],f['value']
            if key in seen_settings:
                raise SophonError('S248',f'Duplicate file {op} setting "{key}".',path.name,n,1,f['raw'],
                                  'Declare each operation setting once.')
            seen_settings.add(key)
            if key in ('path','from'):
                if not re.fullmatch(r'"(?:[^"\\]|\\.)*"',val):
                    raise SophonError('S225',f'File {op} path must be a quoted string.',path.name,n,1,f['raw'],'Use path = "folder/file".')
                paths.append(json.loads(val)); continue
            if key in ('to','state'):
                if target is not None:
                    raise SophonError('S223',f'File {op} accepts only one to/state target.',path.name,n,1,f['raw'],'Use to for a path, or state for a result.')
                if key=='to':
                    if not re.fullmatch(r'"(?:[^"\\]|\\.)*"',val):
                        raise SophonError('S223',f'File {op} target path must be a quoted string.',path.name,n,1,f['raw'],'Use to = "folder/file".')
                    target=(key,json.loads(val))
                else:
                    if not re.fullmatch(r'[A-Za-z_][\w]*',val):
                        raise SophonError('S223',f'Invalid state target "{val}".',path.name,n,1,f['raw'],'Use a plain state name.')
                    target=(key,val)
                continue
            if key=='data': data=val; continue
            raise SophonError('S224',f'Invalid file {op} setting "{key}".',path.name,n,1,f['raw'],
                              'Use path, from, to, state, or data.')
        if len(paths)>1:
            raise SophonError('S248',f'File {op} accepts one source path only.',path.name,n,1,stmt['raw'],
                              'Use one path = "..." or from = "..." value.')
        if not paths:
            raise SophonError('S225',f'File {op} requires a path.',path.name,n,1,stmt['raw'],'Add path = "..." inside the block.')
        if op in ('copy','move','zip','unzip') and (not paths or target is None or target[0]!='to'):
            raise SophonError('S225',f'File {op} requires a source path and a to = "..." target.',path.name,n,1,stmt['raw'],
                              'Add path = "source" to = "target" inside the block.')
        if op in ('read','list') and (target is None or target[0]!='state'):
            raise SophonError('S247',f'File {op} requires state = <name>.',path.name,n,1,stmt['raw'],
                              f'Use {op} {{ path = "..." state = result }}.')
        if op in ('write','append') and data is None:
            raise SophonError('S247',f'File {op} requires data.',path.name,n,1,stmt['raw'],
                              f'Use {op} {{ path = "..." data = value }}.')
        allowed_by_op={
            'create':{'path'},'mkdir':{'path'},'delete':{'path'},
            'read':{'path','state'},'list':{'path','state'},
            'write':{'path','data'},'append':{'path','data'},
            'copy':{'path','to'},'move':{'path','to'},
            'zip':{'path','to'},'unzip':{'path','to'},
        }
        if seen_settings-set(allowed_by_op.get(op,set())):
            unexpected=sorted(seen_settings-set(allowed_by_op.get(op,set())))[0]
            raise SophonError('S247',f'File {op} does not accept {unexpected}.',path.name,n,1,stmt['raw'],
                              'Check the operation-specific settings in the file reference.')
        ops.append({'op':op,'paths':paths,'target':target,'data':data,'line':n})
    if not ops:
        raise SophonError('S226','A file block requires at least one operation.',path.name,header,1,body[0] if body else None,
                          'Add a create { path = "..." } block inside.')
    return nxt,ops

SOPHON_COMMANDS={}
EXECUTE_DEPTH_MAX=4

def parse_execute_block(lines,i,path,header):
    """Read an execute { file = "..." command = "..." } block."""
    nxt,body=_block_body(lines,i,path,header,'S230','execute block')
    target=None; command=None; seen=set()
    for stmt in _statements(body,{'file','command'}):
        if not stmt['closed']: raise SophonError('S230','Unclosed execute block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        key=stmt['key']; n=header+stmt['line']-1
        if key in seen:
            raise SophonError('S233',f'An execute block cannot declare {key} twice.',path.name,n,1,stmt['raw'],'Keep one of file or command.')
        seen.add(key)
        value=_required_pair_value(stmt,path,n,'S231',f'Execute {key}','Use file = "program.sph" or command = "name".')
        m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',value)
        if not m: raise SophonError('S231',f'Invalid execute {key} "{value}".',path.name,n,1,stmt['raw'],'Use file = "program.sph" or command = "name".')
        if key=='file': target=m.group(1)
        else: command=m.group(1)
    if target is None and command is None:
        raise SophonError('S232','An execute block requires a file or a command.',path.name,header,1,body[0] if body else None,
                          'Add file = "program.sph" or command = "name".')
    if target and command:
        raise SophonError('S233','An execute block takes either a file or a command, not both.',path.name,header,1,body[0] if body else None,'Keep one of them.')
    return nxt,{'file':target,'command':command,'line':header}

def parse_component_block(lines,i,path,header,uses,imports):
    """Read component { id = "..."; form/note/list/table { ... } }."""
    nxt,body=_block_body(lines,i,path,header,'S200','component block')
    boxes=[]; seen=set(); component_id=None
    for stmt in _statements(body,{'id',*BOX_KINDS}):
        if not stmt['closed']:
            raise SophonError('S200','Unclosed component block.',path.name,header+stmt['line']-1,1,stmt['raw'],"Add the closing '}'.")
        n=header+stmt['line']-1
        if stmt['key']=='id':
            value=_required_pair_value(stmt,path,n,'S202','Component id','Use id = "component-id".')
            if component_id is not None:
                raise SophonError('S202','A component cannot declare id twice.',path.name,n,1,stmt['raw'],'Declare one component id.')
            m=re.fullmatch(r'"([A-Za-z0-9_-]+)"',value)
            if not m:
                raise SophonError('S202','Invalid component id.',path.name,n,1,stmt['raw'],'Use id = "component-id".')
            component_id=m.group(1)
            continue
        if stmt['key'] not in BOX_KINDS:
            raise SophonError('S202',f'A component block accepts only {", ".join(BOX_KINDS)} blocks, found "{stmt["raw"]}".',path.name,n,1,stmt['raw'],
                              'Move other statements out of the component block.')
        if stmt['kind']!='block':
            raise SophonError('S254',f'{stmt["key"]} in a component must be a block.',path.name,n,1,stmt['raw'],
                              f'Use {stmt["key"]} {{ ... }} inside component.')
        if stmt['key'] in seen:
            raise SophonError('S202',f'Duplicate {stmt["key"]} block in a component.',path.name,n,1,stmt['raw'],'Use one block of each kind, or split the component.')
        seen.add(stmt['key'])
        boxes.append(parse_box_body(stmt['key'],stmt['body'],path,n,uses,imports,stmt['raw']))
    if not boxes:
        raise SophonError('S203','A component block requires at least one component box.',path.name,header,1,_header_raw(lines,header),
                          'Add a form, note, list, or table block inside the component.')
    return nxt,component_id,boxes

def _read_source(path):
    """Read a Sophon source file, turning every filesystem failure into a SophonError.

    A missing file, a directory, or unreadable bytes are user-facing problems, not
    runtime faults, so they must not escape as raw Python exceptions.
    """
    p=Path(path); name=p.name
    if p.is_dir():
        raise SophonError('F018',f'"{name}" is a folder, not a Sophon source file.',name,1,1,None,
                          'Point the command at a .sph, .xaf or .svt file.')
    if not p.exists():
        raise SophonError('F019',f'"{name}" was not found.',name,1,1,None,'Check the path.')
    try:
        text=p.read_text(encoding='utf-8')
    except UnicodeDecodeError as e:
        raise SophonError('F020',f'"{name}" is not valid UTF-8 text ({e.reason}).',name,1,1,None,
                          'Sophon source files must be UTF-8 encoded.')
    except OSError as e:
        raise SophonError('F021',f'"{name}" could not be read ({e.strerror or e}).',name,1,1,None,
                          'Check the file permissions.')
    return _sanitize_source(text,name).splitlines()

_BOM='\ufeff'

def _sanitize_source(text,name):
    """Drop a leading byte order mark and make stray control characters visible.

    A BOM is an encoding artefact, not a statement, and a NUL or similar byte can only
    ever be a mistake; showing it escaped is the only way a diagnostic can point at it.
    """
    if text.startswith(_BOM):
        text=text[len(_BOM):]
    if any(ord(ch)<32 and ch not in '\t\n\r' for ch in text):
        out=[]
        for ch in text:
            out.append(ch if (ord(ch)>=32 or ch in '\t\n\r') else f'\\x{ord(ch):02x}')
        text=''.join(out)
    return text

FUNCTION_TYPES = {'string','integer','float','number','boolean','list','object','null'}
FUNCTION_DEPTH_MAX = 32


def _function_type_matches(value, expected):
    actual=_value_type(value)
    return actual==expected or (expected=='number' and actual in ('integer','float'))


def _split_function_statements(body):
    """Split local `state` and `set` statements, including inline execute blocks."""
    text=body if isinstance(body,str) else '\n'.join(body)
    flat=_top_level_map(text)
    starts=[]
    for match in re.finditer(r'\b(?:state|set)\s+[A-Za-z_][A-Za-z0-9_]*\b',text):
        if flat[match.start()] and (match.start()==0 or flat[match.start()-1]):
            starts.append(match.start())
    return [text[start:starts[index+1] if index+1<len(starts) else len(text)].strip()
            for index,start in enumerate(starts)]


def _parse_function_definition(lines,index,path,header):
    after,body=_block_body(lines,index,path,header,'S260','function')
    text='\n'.join(body)
    flat=_top_level_map(text)
    id_matches=[m for m in re.finditer(r'\bid\s*=\s*("[^"]+")',text) if flat[m.start()]]
    if len(id_matches)!=1:
        raise SophonError('S260','Function requires exactly one top-level id setting.',path.name,header,1,_header_raw(lines,header),
                          'Use function { id = "calculate" input { ... } execute { ... } output: integer = result }.')
    id_match=id_matches[0]
    raw_id=id_match.group(1)
    if not re.fullmatch(r'"[A-Za-z_][A-Za-z0-9_]*"',raw_id):
        raise SophonError('S260','Function id must be a quoted identifier.',path.name,header,1,_header_raw(lines,header),'Use id = "calculate".')
    fid=_decode_string(raw_id)
    children=[name for name,_ in _direct_children(text)]
    output_scalar_matches=[m for m in re.finditer(r'\boutput\s*:\s*(?:string|integer|float|number|boolean|list|object|null)\s*=\s*[A-Za-z_][A-Za-z0-9_]*',text) if flat[m.start()]]
    if len(output_scalar_matches)>1:
        raise SophonError('S261','Function may declare only one output.',path.name,header,1,_header_raw(lines,header),
                          'Choose one output: type = state declaration.')
    output_scalar=bool(output_scalar_matches)
    root_text=text
    for child_name in ('input','execute','output'):
        pattern=re.compile(rf'\b{child_name}\s*\{{')
        matches=[m for m in pattern.finditer(root_text) if _top_level_map(root_text)[m.start()]]
        for match in reversed(matches):
            brace=root_text.find('{',match.start(),match.end()); close=_closing_brace(root_text,brace)
            if close is not None: root_text=root_text[:match.start()]+root_text[close+1:]
    root_text=root_text[:id_match.start()]+root_text[id_match.end():]
    if output_scalar_matches:
        # Remove the scalar output declaration from the remaining root-level text.
        scalar=output_scalar_matches[0]
        root_text=root_text.replace(scalar.group(0),'',1)
    if root_text.strip():
        raise SophonError('S260',f'Unknown Function declaration content "{root_text.strip()}".',path.name,header,1,_header_raw(lines,header),
                          'Only id, input, execute, and output are valid at the Function root.')
    if set(children)-{'input','execute','output'} or children.count('input')!=1 or children.count('execute')!=1 or children.count('output')>1 or (children.count('output')==1 and output_scalar) or (children.count('output')==0 and not output_scalar):
        raise SophonError('S261','Function requires input, execute, and exactly one output declaration.',path.name,header,1,_header_raw(lines,header),
                          'Declare input { ... }, execute { ... }, and output: integer = result (or output { ... }).')
    input_body=_child_block(text,'input')
    execute_body=_child_block(text,'execute')
    output_body=_child_block(text,'output')
    params=[]; seen=set(); optional_seen=False
    input_text='\n'.join(strip_comment(raw) for raw in input_body.splitlines()).strip()
    param_pattern=re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(string|integer|float|number|boolean|list|object|null)(\?)?(?:\s*=\s*(.*?))?(?=(?:\s+[A-Za-z_][A-Za-z0-9_]*\s*:\s*(?:string|integer|float|number|boolean|list|object|null))|$)',re.S)
    matches=list(param_pattern.finditer(input_text))
    cursor=0
    for match in matches:
        if input_text[cursor:match.start()].strip(' ,\t\r\n'):
            bad=input_text[cursor:match.start()].strip()
            raise SophonError('S262',f'Invalid parameter declaration "{bad}".',path.name,header,1,_header_raw(lines,header),
                              'Use name: type, name: type?, or name: type = default.')
        name,typ,optional,default=match.groups(); default=default.strip() if default is not None else None
        if name in seen:
            raise SophonError('S263',f'Duplicate parameter "{name}".',path.name,header,1,_header_raw(lines,header),'Use a unique parameter name.')
        seen.add(name)
        if optional and default is not None:
            raise SophonError('S262',f'Parameter "{name}" cannot use both ? and a default value.',path.name,header,1,_header_raw(lines,header),
                              'Use either an optional parameter (name: type?) or a default (name: type = value).')
        if optional or default is not None: optional_seen=True
        elif optional_seen:
            raise SophonError('S262',f'Required parameter "{name}" follows an optional/default parameter.',path.name,header,1,_header_raw(lines,header),
                              'Place required parameters before optional or default-valued parameters.')
        params.append({'name':name,'type':typ,'optional':bool(optional),'default':default})
        cursor=match.end()
    if input_text[cursor:].strip(' ,\t\r\n'):
        bad=input_text[cursor:].strip()
        raise SophonError('S262',f'Invalid parameter declaration "{bad}".',path.name,header,1,_header_raw(lines,header),
                          'Use name: type, name: type?, or name: type = default.')
    statements=[]
    execute_text='\n'.join(strip_comment(raw) for raw in execute_body.splitlines())
    local_statements=_split_function_statements(execute_text)
    remainder=execute_text
    for statement_text in local_statements:
        remainder=remainder.replace(statement_text,'',1)
    if remainder.strip():
        raise SophonError('S264',f'Unsupported content in function execute: "{remainder.strip()}".',path.name,header,1,_header_raw(lines,header),
                          'Function execute currently supports local state declarations and set updates only.')
    mutable_names=set(seen)
    for offset,raw in enumerate(local_statements,1):
        line=strip_comment(raw).strip()
        if not line: continue
        declaration=re.fullmatch(r'state\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*(string|integer|float|number|boolean|list|object|null))?\s*=\s*(.+)',line,re.S)
        update=re.fullmatch(r'set\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)',line,re.S)
        if declaration:
            name,typ,expr=declaration.groups()
            if name in mutable_names:
                raise SophonError('S263',f'Local state "{name}" is already declared in this function.',path.name,header+offset,1,raw,
                                  'Use a unique local state name; parameters cannot be redeclared.')
            mutable_names.add(name)
            statements.append({'op':'state','name':name,'type':typ,'expression':expr.strip(),'line':header+offset})
        elif update:
            name,expr=update.groups()
            if name not in mutable_names:
                raise SophonError('S284',f'Function set cannot update unknown or external state "{name}".',path.name,header+offset,1,raw,
                                  'Use set only with a parameter or a local state declared earlier in execute.')
            statements.append({'op':'set','name':name,'type':None,'expression':expr.strip(),'line':header+offset})
        else:
            raise SophonError('S264',f'Unsupported statement in function execute: "{line}".',path.name,header+offset,1,raw,
                              'Use state name = value to declare a local state, or set name = value to update it.')
    # output may be a scalar declaration on the same line as its block opener, or a named result block.
    output_match_line=re.search(r'\boutput\s*:\s*(string|integer|float|number|boolean|list|object|null)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)',text)
    output_line=output_match_line.group(0) if output_match_line else None
    output_match=re.fullmatch(r'output\s*:\s*(string|integer|float|number|boolean|list|object|null)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)',output_line or '')
    if output_match:
        output={'kind':'single','type':output_match.group(1),'value':output_match.group(2)}
    else:
        names=[]
        for raw in output_body.splitlines():
            token=strip_comment(raw).strip()
            if not token: continue
            for name in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',token): names.append(name)
        if not names or len(names)!=len(set(names)):
            raise SophonError('S265','Function output block must contain unique local state names.',path.name,header,1,_header_raw(lines,header),
                              'Use output { sum difference } and declare both states inside execute.')
        output={'kind':'multi','names':names}
    return after,{'id':fid,'params':params,'execute':statements,'output':output,'line':header}


def _call_sophon_function(function,positional,named,outer_states,groups,file,line,functions,depth=0,modules=None):
    if depth>FUNCTION_DEPTH_MAX:
        raise SophonError('S266',f'Function call depth exceeds {FUNCTION_DEPTH_MAX}.',file,line,1,None,
                          'Check for recursive calls or reduce the recursion depth.')
    params=function['params']; names=[p['name'] for p in params]
    if len(positional)>len(params):
        raise SophonError('S267',f'Function "{function["id"]}" received too many positional arguments.',file,line,1,None,
                          f'Expected at most {len(params)} positional arguments.')
    local=dict(outer_states or {})
    for index,value in enumerate(positional): local[names[index]]=value
    for key,value in named.items():
        if key not in names:
            raise SophonError('S268',f'Unknown argument "{key}" for function "{function["id"]}".',file,line,1,None,
                              'Use only names declared in the function input block.')
        if key in local:
            raise SophonError('S269',f'Argument "{key}" was supplied more than once.',file,line,1,None,
                              'Use either a positional or named value for each parameter.')
        local[key]=value
    for param in params:
        name=param['name']
        if name not in local:
            if param['default'] is not None:
                local[name]=parse_value(param['default'],local,line,file,None,groups=groups,functions=functions,call_depth=depth,modules=modules or function.get('modules'))
            elif param['optional']:
                local[name]=None
            else:
                raise SophonError('S270',f'Missing required argument "{name}" for function "{function["id"]}".',file,line,1,None,
                                  'Supply the argument positionally or by name.')
        if not (param['optional'] and local[name] is None) and not _function_type_matches(local[name],param['type']):
            raise SophonError('S271',f'Argument "{name}" expects {param["type"]}, received {_value_type(local[name])}.',file,line,1,None,
                              f'Pass a value compatible with {param["type"]}.')
    mutable_types={p['name']:p['type'] for p in params}
    for statement in function['execute']:
        value=parse_value(statement['expression'],local,statement['line'],file,None,groups=groups,functions=functions,call_depth=depth,modules=modules or function.get('modules'))
        name=statement['name']
        if statement.get('op')=='set':
            expected=mutable_types.get(name)
            if expected and not _function_type_matches(value,expected):
                raise SophonError('S289',f'Function state "{name}" expects {expected}, received {_value_type(value)}.',file,statement['line'],1,None,
                                  'Assign a value compatible with the parameter or local state type.')
            if type(local[name]) is type(value) and local[name]==value:
                raise SophonError('S246',f'State "{name}" is assigned the same value again.',file,statement['line'],1,None,
                                  'Remove the redundant assignment or provide a different value.')
            local[name]=value
            continue
        expected=statement['type']
        if expected and not _function_type_matches(value,expected):
            raise SophonError('S272',f'Local state "{name}" expects {expected}, received {_value_type(value)}.',file,statement['line'],1,None,
                              'Change the expression or declare a compatible type.')
        local[name]=value
        mutable_types[name]=expected or _value_type(value)
    output=function['output']
    if output['kind']=='single':
        name=output['value']
        if name not in local:
            raise SophonError('S273',f'Function output state "{name}" was not declared.',file,function['line'],1,None,
                              'Declare the output state inside execute.')
        value=local[name]
        if not _function_type_matches(value,output['type']):
            raise SophonError('S274',f'Function output expects {output["type"]}, received {_value_type(value)}.',file,function['line'],1,None,
                              'Return a value compatible with the declared output type.')
        return value
    missing=[name for name in output['names'] if name not in local]
    if missing:
        raise SophonError('S273',f'Function output state "{missing[0]}" was not declared.',file,function['line'],1,None,
                          'Declare every output state inside execute.')
    return {name:local[name] for name in output['names']}


def parse_sph(path):
    lines=_read_source(path); path=Path(path);
    # Top-level XAF setup commands may be chained with '&'.
    expanded=[]
    for raw_line in lines:
        stripped=strip_comment(raw_line).strip()
        if '&' in stripped and not any(x in stripped for x in ('{','}')):
            parts=[x.strip() for x in stripped.split('&') if x.strip()]
            if parts and all(x in ('create','create xaf') or x.startswith('connect to ') for x in parts):
                target=next((x[11:].strip() for x in parts if x.startswith('connect to ')), path.with_suffix('.xaf').name)
                if any(x in ('create','create xaf') for x in parts):
                    expanded.append('connect to '+target)
                else: expanded.extend(parts)
                continue
        if stripped in ('create','create xaf'):
            expanded.append('connect to '+path.with_suffix('.xaf').name); continue
        expanded.append(raw_line)
    lines=expanded; states={}; groups={}; observers={}; observer_groups={}; databases=[]; agent_connects=[]; agent_calls=[]; asks=[]; renders=[]; files=[]; executes=[]
    connect=None; uses=[]; imports=[]; functions={}; decl_lines={}; state_types={}; i=0
    while i<len(lines):
        raw=lines[i]; line=strip_comment(raw).strip(); n=i+1
        if not line: i+=1; continue
        if re.match(r'use\s*\{',line):
            i,added,named=_parse_use_block(lines,i,path,n)
            for m in added:
                if m not in uses:
                    uses.append(m)
                    if m == 'datetime':
                        _install_datetime_builtins(states, groups, path, n)
                    elif m == 'random':
                        conflicts={'random'}.intersection(set(states) | set(groups))
                        if conflicts:
                            raise SophonError('S290','\"random\" is reserved by the random module.',path.name,n,1,raw,
                                              'Rename the state or multi-state id so random function calls remain unambiguous.')
            imports.extend(named)
            decl_lines['use:modules']=n
            for x in named: decl_lines[f'use:{x}']=n
            continue
        if line=='self-observer':
            raise SophonError('S100','The self-observer declaration has been replaced by features.self-observation and observer.watch.',path.name,n,1,raw,'Use features { self-observation = true } in XAF and watch { self-observation }.')
        if line.startswith('connect '):
            if connect: raise SophonError('X001','An SPH file can connect to only one XAF file.',path.name,n,1,raw,'Remove the second connection.')
            target=line[8:].strip()
            if not target.startswith('to '): raise SophonError('X002','Invalid SPH connect syntax.',path.name,n,1,raw,'Use: connect to sophon.xaf')
            target=target[3:].strip()
            if not re.fullmatch(r'[A-Za-z0-9_./-]+\.xaf',target): raise SophonError('X002','Invalid SPH connect syntax.',path.name,n,1,raw,'Use: connect to sophon.xaf')
            connect=target; decl_lines[f'connect:{target}']=n; i+=1; continue
        if re.match(r'function\s*\{',line):
            i,function=_parse_function_definition(lines,i,path,n)
            if function['id'] in functions:
                raise SophonError('S263',f'Duplicate function id "{function["id"]}".',path.name,n,1,raw,'Use a unique function id.')
            function['modules']=tuple(uses)
            functions[function['id']]=function; decl_lines[f'function:{function["id"]}']=n; continue
        if re.match(r'agent\s*\{',line):
            _require_module(uses,imports,'agent',path,n,raw); raise SophonError('A015','The standalone agent declaration is no longer supported.',path.name,n,1,raw,'Use: agent connect { id = \"agent-id\" }')
        if re.match(r'agent\s+connect\s*\{',line):
            _require_module(uses,imports,'agent',path,n,raw); i,aid=parse_agent_connect_block(lines,i,path,n)
            if aid in agent_connects:
                raise SophonError('A038',f'Agent {aid} is connected more than once.',path.name,n,1,raw,
                                  'Declare each Agent connection once.')
            agent_connects.append(aid); continue
        if re.match(r'multi-confirmation\s*\{',line):
            i,specs=parse_multi_confirmation_block(lines,i,path,n)
            for sp in specs: sp.setdefault('line',n)
            asks.extend(specs); continue
        if re.match(r'confirmation\s*\{',line):
            i,spec=parse_confirmation_block(lines,i,path,n); spec['line']=n; asks.append(spec); continue
        if re.match(r'multi-ask\s*\{',line):
            i,specs=parse_multi_ask_block(lines,i,path,n)
            for sp in specs: sp.setdefault('line',n)
            asks.extend(specs); continue
        if re.match(r'ask\s*\{',line):
            i,specs=parse_ask_block(lines,i,path,n)
            for sp in specs: sp.setdefault('line',n)
            asks.extend(specs); continue
        if re.match(r'file\s*\{',line):
            _require_module(uses,imports,'file',path,n,raw)
            i,ops=parse_file_block(lines,i,path,n)
            for op in ops: decl_lines[f"file:{op['op']}:{op['paths'][0] if op['paths'] else ''}"]=op['line']
            files.extend(ops); continue
        if re.match(r'execute\s*\{',line):
            _require_module(uses,imports,'execute',path,n,raw)
            i,item=parse_execute_block(lines,i,path,n); executes.append(item); decl_lines[f'execute:{item["file"] or item["command"]}']=n; continue
        if re.match(r'component\s*\{',line):
            _require_module(uses,imports,'component',path,n,raw)
            i,component_id,boxes=parse_component_block(lines,i,path,n,uses,imports); renders.append({'line':n,'kind':'component','id':component_id,'boxes':boxes}); continue
        m=re.match(r'([A-Za-z_][\w-]*)\s*\{',line)
        if m and m.group(1) in BOX_KINDS:
            i,box=_parse_box(m.group(1),lines,i,path,n,uses,imports)
            renders.append({'line':n,'kind':'component','boxes':[box]})
            decl_lines[f"{box['kind']}:{box.get('id') or box['kind']}"]=n
            continue
        if re.match(r'surface\s*\{',line):
            i,items=parse_surface_block(lines,i,path,n); renders.append({'line':n,'kind':'surface','items':items}); decl_lines['surface:surface']=n; continue
        if re.match(r'agent\s+run\s*\{',line):
            _require_module(uses,imports,'agent',path,n,raw); i,item=parse_agent_message_block(lines,i,path,n,'run'); agent_calls.append(item); continue
        if re.match(r'agent\s+task\s*\{',line):
            _require_module(uses,imports,'agent',path,n,raw); i,item=parse_agent_message_block(lines,i,path,n,'task'); agent_calls.append(item); continue
        m=re.match(r'database\s+([A-Za-z_][\w]*)\s*\{',line)
        if m:
            _require_module(uses,imports,'database',path,n,raw); i,db=parse_database_block(lines,i,m.group(1),states,path,n,groups=groups,functions=functions,modules=uses); db['line']=n; databases.append(db); continue
        if re.match(r'observer\s*\{',line):
            _require_module(uses,imports,'observer',path,n,raw)
            i,ob=parse_observer_block(lines,i,path,n)
            decl_lines[f'observer:{ob["id"]}']=n
            if ob['id'] in observers: raise SophonError('S130',f'Duplicate observer "{ob["id"]}".',path.name,n,1,raw,'Use a unique observer id.')
            observers[ob['id']]=ob; continue
        if re.match(r'multi-observer\s*\{',line):
            _require_module(uses,imports,'multi-observer',path,n,raw)
            i,group=parse_multi_observer_block(lines,i,path,n)
            decl_lines[f'multi-observer:{group["id"]}']=n
            if group['id'] in observer_groups: raise SophonError('S132',f'Duplicate multi-observer id "{group["id"]}".',path.name,n,1,raw,'Use a unique multi-observer id.')
            observer_groups[group['id']]=group
            for ob in group['observers']:
                if ob['id'] in observers: raise SophonError('S130',f'Duplicate observer "{ob["id"]}".',path.name,n,1,raw,'Use a unique observer id.')
                observers[ob['id']]=ob
            continue
        if re.match(r'observe\s*\{',line):
            raise SophonError('S100','The observe declaration has been removed; use observer { id source watch { ... } }.',path.name,n,1,raw,'Use the unified observer structure.')
        if re.match(r'^set(?:\s|$)',line):
            update=re.fullmatch(r'set\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$',line)
            if not update:
                raise SophonError('S284','Invalid set statement.',path.name,n,1,raw,
                                  'Use set existing_state = new_value.')
            state_name,expression=update.groups()
            if state_name not in states:
                raise SophonError('S284',f'Set cannot update unknown state "{state_name}".',path.name,n,1,raw,
                                  'Declare the state first with state name = value, then update it with set.')
            if state_name in ('date','time') and 'datetime' in uses:
                raise SophonError('S245',f'"{state_name}" is reserved by the datetime module.',path.name,n,1,raw,
                                  'Datetime built-ins are read-only; use another state name.')
            if state_name == 'random' and 'random' in uses:
                raise SophonError('S290','"random" is reserved by the random module.',path.name,n,1,raw,
                                  'Choose another state name; random is the module namespace.')
            value=parse_value(expression,states,n,path.name,raw,groups=groups,functions=functions,modules=uses)
            previous_type=state_types.get(state_name,_value_type(states[state_name]))
            expected={'number':('integer','float')}.get(previous_type,(previous_type,))
            actual_type=_value_type(value)
            if actual_type not in expected:
                raise SophonError('S289',f'State "{state_name}" expects {previous_type}, received {actual_type}.',path.name,n,1,raw,
                                  f'Assign a value compatible with {previous_type}.')
            if type(states[state_name]) is type(value) and states[state_name]==value:
                raise SophonError('S246',f'State "{state_name}" is assigned the same value again.',path.name,n,1,raw,
                                  'Remove the redundant assignment or provide a different value.')
            states[state_name]=value
            decl_lines[f'set:{state_name}']=n
            i+=1
            continue
        m=re.fullmatch(r'state\s+([A-Za-z_][\w]*)(?:\s*:\s*(string|integer|float|number|boolean|list|object|null))?\s*=\s*(.+)$',line)
        if m:
            state_name,declared_type,expression=m.groups()
            if state_name in ('date', 'time') and 'datetime' in uses:
                raise SophonError('S245',f'"{state_name}" is reserved by the datetime module.',path.name,n,1,raw,
                                  'Use another state name; date and time are built-in values.')
            if state_name == 'random' and 'random' in uses:
                raise SophonError('S290','"random" is reserved by the random module.',path.name,n,1,raw,
                                  'Choose another state name; random is the module namespace.')
            value=parse_value(expression,states,n,path.name,raw,groups=groups,functions=functions,modules=uses)
            actual_type=_value_type(value)
            declared_expected={'number':('integer','float')}.get(declared_type,(declared_type,)) if declared_type else None
            if declared_expected and actual_type not in declared_expected:
                raise SophonError('S242',f'State "{state_name}" expects {declared_type}, received {actual_type}.',path.name,n,1,raw,
                                  f'Provide a value compatible with {declared_type}.')
            if state_name in states:
                previous_type=state_types.get(state_name,_value_type(states[state_name]))
                expected={'number':('integer','float')}.get(previous_type,(previous_type,))
                if actual_type not in expected:
                    raise SophonError('S242',f'State "{state_name}" expects {previous_type}, received {actual_type}.',path.name,n,1,raw,
                                      f'Update the state with a value compatible with {previous_type}.')
                if states[state_name] == value and type(states[state_name]) is type(value):
                    raise SophonError('S246',f'State "{state_name}" is assigned the same value again.',path.name,n,1,raw,
                                      'Remove the redundant assignment or provide a different value.')
            else:
                state_types[state_name]=declared_type or actual_type
            states[state_name]=value; decl_lines[f'state:{state_name}']=n; i+=1; continue
        m=re.match(r'multi-state(?:\s+([A-Za-z_][\w]*))?\s*\{',line)
        if m: decl_lines[f'multi-state:{m.group(1) or n}']=n; i=parse_multi(lines,i,m.group(1),states,groups,path,n,functions=functions,modules=uses); continue
        if re.match(r'multi-state\s+[A-Za-z_][\w]*\.[A-Za-z_][\w]*\s*=',line): raise SophonError('S109','Direct multi-state field updates are not supported.',path.name,n,1,raw,'Use multi-state { id = "user" state { age = 18 at [3] } }.')
        if re.match(r'^multi-agent\s*\{',line):
            feature='Multi-Agent orchestration'
            raise SophonError('S250',f'{feature} syntax is designed but not implemented yet.',path.name,n,1,raw,
                              'This construct is documented as a future feature; use currently implemented Sophon statements.')
        raise SophonError('S100',f'Unknown statement: {line}',path.name,n,1,raw,'Check the Sophon syntax.')
    for call in agent_calls:
        if len(call)>4 and call[4] and call[4] not in states:
            raise SophonError('A033',f'Agent output state "{call[4]}" is not declared.',path.name,1,1,None,
                              'Declare state ' + call[4] + ' before or after the agent run block.')
    database_aliases=[db['alias'] for db in databases]
    if len(database_aliases)!=len(set(database_aliases)):
        duplicate=next(alias for alias in database_aliases if database_aliases.count(alias)>1)
        raise SophonError('S149',f'Duplicate database alias "{duplicate}".',path.name,1,1,None,
                          'Use one database block per alias, or combine its operations into the same block.')
    source_observers={}
    for observer_id, observer in observers.items():
        source_key=str(path.resolve()) if observer['source']=='self' else str((path.parent/observer['source']).resolve())
        existing=source_observers.setdefault(source_key,[])
        if observer['self_observation'] and existing:
            raise SophonError('S135',f'Source "{observer["source"]}" already has an observer; self-observation covers the whole source.',
                              path.name,1,1,None,'Use one observer with watch { self-observation } for this source.')
        if any(observers[x]['self_observation'] for x in existing):
            raise SophonError('S135',f'Source "{observer["source"]}" is already fully covered by self-observation.',
                              path.name,1,1,None,'Remove the additional observer for this source.')
        existing.append(observer_id)
        if observer['source'] != 'self':
            continue
        for kind, resource in observer['selected']:
            if kind == 'resource' and resource not in states and resource not in groups:
                raise SophonError('S121', f'Unknown watched resource "{resource}".', path.name, 1, 1, None,
                                  'Declare the state or multi-state before observing it.')
            if kind == 'multi-state':
                group, field = resource.split('.', 1)
                if group not in groups or field not in groups[group]:
                    raise SophonError('S121', f'Unknown watched multi-state component "{resource}".', path.name, 1, 1, None,
                                      'Use an existing multi-state id and field.')
    return SphProgram(states,groups,observers,observer_groups,connect,databases,agent_connects,uses,imports,agent_calls,asks,renders,files,executes,functions,decl_lines)

def _named_blocks(lines, pattern, key=1):
    """Return (name, header_index, end_index, body) for every block matching pattern.

    key is the capture group holding the block name, or None for un-named blocks.
    A block may span several lines or be written inline as `name { ... }` on one line.
    """
    blocks=[]
    for i,line in enumerate(lines):
        m=re.match(pattern,line)
        if not m: continue
        depth=0
        for j in range(i,len(lines)):
            depth += lines[j].count('{')-lines[j].count('}')
            if depth==0:
                body='\n'.join(lines[i+1:j])
                if j==i:
                    head=line.index('{')+1
                    body=line[head:line.rindex('}')] if '}' in line[head:] else line[head:]
                blocks.append((m.group(key) if key else None,i,j,body)); break
    return blocks

def _direct_children(body):
    """Return direct child blocks in both inline and multiline declarations."""
    text = body if isinstance(body, str) else '\n'.join(body)
    flat = _top_level_map(text)
    out = []
    pattern = re.compile(r'([A-Za-z_][\w-]*)\s*\{')
    for match in pattern.finditer(text):
        start = match.start(1)
        if start >= len(flat) or not flat[start] or (start and not flat[start-1]):
            continue
        brace = text.find('{', match.start(1), match.end())
        close = _closing_brace(text, brace)
        if close is None:
            continue
        out.append((match.group(1), text[brace+1:close]))
    return out

def _parse_bool(v): return True if v=='true' else False if v=='false' else None

def _parse_action_block(block,path,line):
    am=re.search(r'\baction\s*\{([^{}]*)\}',block,re.S)
    if not am: return {}
    vals={}
    for a,v in re.findall(rf'\b({"|".join(ACTIONS)})\s*=\s*(true|false|null)\b',am.group(1)):
        if a in vals: raise SophonError('X020',f'Duplicate action setting "{a}".',path.name,line,1,None,'Define each action only once.')
        vals[a]=_parse_bool(v)
    return vals


def _parse_v2_action_block(block,path,line):
    """Strict boolean action schema for XAF v2 policies."""
    body=_child_block(block,'action')
    if body is None: return {}
    if _direct_children(body):
        raise SophonError('X105','Policy action does not accept nested blocks.',path.name,line,1,None,
                          'Write only boolean action assignments inside action { ... }.')
    pairs=_pairs(body.splitlines())
    values={}
    for item in pairs:
        key,value=item['key'],item['value']
        if key not in ACTIONS:
            raise SophonError('X105',f'Unknown policy action "{key}".',path.name,line,1,None,
                              'Allowed actions: '+', '.join(ACTIONS)+'.')
        if value not in ('true','false'):
            raise SophonError('X105',f'Policy action {key} must be true or false.',path.name,line,1,None,
                              f'Use {key} = true or {key} = false.')
        if key in values:
            raise SophonError('X020',f'Duplicate action setting "{key}".',path.name,line,1,None,
                              'Define each action only once.')
        values[key]=(value=='true')
    return values

def _child_block(body, name):
    """Return a direct child block's contents in inline or multiline syntax."""
    text=body if isinstance(body,str) else '\n'.join(body)
    flat=_top_level_map(text)
    pattern=re.compile(rf'\b{re.escape(name)}\s*\{{')
    for match in pattern.finditer(text):
        if match.start()>=len(flat) or not flat[match.start()]:
            continue
        brace=text.find('{',match.start(),match.end())
        close=_closing_brace(text,brace)
        if close is not None:
            return text[brace+1:close]
    return None


def _strip_child_blocks(body,kinds):
    """Remove the named nested blocks from a body, so only bare words remain."""
    text=body
    for kind in kinds:
        pattern=re.compile(rf'\b{re.escape(kind)}\s*\{{')
        while True:
            m=pattern.search(text)
            if not m: break
            depth=0; end=None
            for i in range(m.end()-1,len(text)):
                if text[i]=='{': depth+=1
                elif text[i]=='}':
                    depth-=1
                    if depth==0: end=i+1; break
            if end is None: break
            text=text[:m.start()]+text[end:]
    return text

ACCESS_EMPTY={'state':False,'multi-state':False,'observer':set(),'database':set(),
              'surface':False,'ask':False,'input':False,'file-system':False,'execute':False}
FILE_ACTIONS=('create','read','modify','move','copy','delete')
FOLDER_ACTIONS=('create','read','modify','move','copy','delete','zip-unzip')

# XAF v2 separates capability grants (policy.access) from their configuration
# (config).  The older ACCESS_EMPTY layout remains available for reading legacy
# XAF files during the migration period.
XAF_ACCESS_KEYS=('multi','observer','database','file-system','execute','agent','component')
XAF_SOURCE_KEYS=('self','external')
MULTI_FEATURES=('multi-ask','multi-state','multi-confirmation','multi-observer')


def _root_blocks(lines, pattern, key=None):
    """Return only root-level blocks matching pattern.

    Unlike _named_blocks this deliberately ignores nested blocks with the same
    name, which matters for config.agent and config.observer.
    """
    out=[]; depth=0
    for i,line in enumerate(lines):
        if depth==0:
            m=re.match(pattern,line)
            if m:
                block_depth=0
                for j in range(i,len(lines)):
                    block_depth += _brace_delta(lines[j])
                    if block_depth==0:
                        if j==i:
                            head=line.find('{')+1
                            body=line[head:line.rindex('}')] if '}' in line[head:] else ''
                        else:
                            body='\n'.join(lines[i+1:j])
                        out.append((m.group(key) if key is not None else None,i,j,body))
                        break
        depth += _brace_delta(line)
    return out


def _direct_numeric_blocks(body):
    """Read direct child blocks whose names are positive integer identifiers."""
    text='\n'.join(body) if isinstance(body,(list,tuple)) else str(body)
    flat=_top_level_map(text); out=[]
    for m in re.finditer(r'(\d+)\s*\{',text):
        if not flat[m.start(1)] or (m.start(1) and not flat[m.start(1)-1]):
            continue
        brace=text.find('{',m.start(1),m.end())
        end=_closing_brace(text,brace)
        if end is None: continue
        out.append((int(m.group(1)),text[brace+1:end]))
    return out


def _xaf_integer(value, label, path, line=1, positive=True):
    if not re.fullmatch(r'\d+',str(value).strip()):
        raise SophonError('X070',f'{label} must be an integer.',path.name,line,1,None,
                          f'Use a numeric identifier, for example {label} = 1001.')
    number=int(value)
    if positive and number<1:
        raise SophonError('X070',f'{label} must be greater than zero.',path.name,line,1,None,
                          'Use a positive integer such as 1001.')
    return number


def _direct_pair_items(body):
    """Return ordered scalar assignments, excluding nested child blocks."""
    text='\n'.join(body) if isinstance(body,(list,tuple)) else str(body)
    flat=_top_level_map(text); spans=[]
    for match in re.finditer(r'([A-Za-z_][\w-]*)\s*\{',text):
        if not flat[match.start()] or (match.start() and not flat[match.start()-1]): continue
        brace=text.find('{',match.start(),match.end())
        end=_closing_brace(text,brace)
        if end is not None: spans.append((match.start(),end+1))
    for start,end in reversed(spans): text=text[:start]+text[end:]
    return _pairs(text.splitlines())


def _direct_pairs(body):
    """Return direct assignments from a block body as a dictionary."""
    return {item['key']:item['value'] for item in _direct_pair_items(body)}


def _parse_v2_policy_access(block,path,line):
    body=_child_block(block,'access')
    result={key:False for key in XAF_ACCESS_KEYS}
    result['source']={'self':False,'external':False}
    if body is None: return result
    source=_child_block(body,'source')
    access_children=[name for name,_ in _direct_children(body)]
    if any(name!='source' for name in access_children) or access_children.count('source')>1:
        raise SophonError('X073','Policy access accepts only one source block.',path.name,line,1,None,
                          'List capability names directly and declare source { self = ... external = ... } once.')
    bare=_strip_child_blocks(body,('source',))
    seen=set()
    for token in bare.split():
        if token not in XAF_ACCESS_KEYS:
            raise SophonError('X071',f'Unknown policy access capability "{token}".',path.name,line,1,None,
                              'Allowed access entries: '+', '.join(XAF_ACCESS_KEYS)+'.')
        if token in seen:
            raise SophonError('X072',f'Duplicate policy access capability "{token}".',path.name,line,1,None,
                              'Declare each access capability once.')
        seen.add(token); result[token]=True
    if source is not None:
        seen_source=set()
        for key,value in re.findall(r'\b(self|external)\s*=\s*(true|false)\b',source):
            if key in seen_source:
                raise SophonError('X073',f'Duplicate source permission "{key}".',path.name,line,1,None,
                                  'Declare self and external once each.')
            seen_source.add(key); result['source'][key]=(value=='true')
        stripped=re.sub(r'\b(self|external)\s*=\s*(true|false)\b','',source).strip()
        if stripped:
            raise SophonError('X073',f'Unknown source permission "{stripped}".',path.name,line,1,None,
                              'Use only self = true/false and external = true/false.')
    return result


def _merge_v2_access(parent,child):
    out={}
    for key in XAF_ACCESS_KEYS:
        out[key]=bool(parent.get(key,False) or child.get(key,False))
    out['source']={k:bool(parent.get('source',{}).get(k,False) or child.get('source',{}).get(k,False))
                   for k in XAF_SOURCE_KEYS}
    return out


def _parse_v2_denials(block,path,line):
    """Parse explicit deny-overrides for inherited access and action grants."""
    deny=_child_block(block,'deny')
    if deny is None:
        return {'access':{key:False for key in XAF_ACCESS_KEYS}|{'source':{'self':False,'external':False}},'action':{}}
    children=[name for name,_ in _direct_children(deny)]
    direct=_direct_pairs(deny)
    if direct or set(children)-{'access','action'} or len(children)!=len(set(children)):
        raise SophonError('X117','deny accepts access and action blocks only.',path.name,line,1,None,
                          'Use deny { access { multi } action { read = true } }.')
    access=_parse_v2_policy_access('access { '+(_child_block(deny,'access') or '')+' }',path,line)
    action={}
    action_body=_child_block(deny,'action')
    if action_body is not None:
        for item in _pairs(action_body.splitlines()):
            if item['key'] not in ACTIONS or item['value']!='true':
                raise SophonError('X117','Denied actions must be listed as action = true.',path.name,line,1,None,
                                  'Use deny { action { read = true modify = true } }.')
            if item['key'] in action:
                raise SophonError('X117',f'Duplicate denied action "{item["key"]}".',path.name,line,1,None,'Declare each denied action once.')
            action[item['key']]=True
    return {'access':access,'action':action}


def _apply_v2_denials(policy):
    denied=policy.get('deny',{})
    access=policy.setdefault('access',{})
    for key in XAF_ACCESS_KEYS:
        if denied.get('access',{}).get(key): access[key]=False
    for key in XAF_SOURCE_KEYS:
        if denied.get('access',{}).get('source',{}).get(key): access.setdefault('source',{})[key]=False
    for key,value in denied.get('action',{}).items():
        if value: policy.setdefault('action',{})[key]=False
    return policy


def _merge_v2_denials(parent,child):
    pa=parent.get('deny',{}).get('access',{}); ca=child.get('access',{})
    denied_access={key:bool(pa.get(key,False) or child.get('deny',{}).get('access',{}).get(key,False)) for key in XAF_ACCESS_KEYS}
    denied_access['source']={key:bool(pa.get('source',{}).get(key,False) or child.get('deny',{}).get('access',{}).get('source',{}).get(key,False)) for key in XAF_SOURCE_KEYS}
    denied_action=dict(parent.get('deny',{}).get('action',{})); denied_action.update(child.get('deny',{}).get('action',{}))
    return {'access':denied_access,'action':denied_action}


def _parse_agent_sections(block,path,line,allow_identity=False):
    """Parse shared Agent settings for either config.agent defaults or one Agent."""
    direct_items=_direct_pair_items(block)
    direct={item['key']:item['value'] for item in direct_items}
    direct_keys=[item['key'] for item in direct_items]
    duplicate_direct={key for key in direct_keys if direct_keys.count(key)>1}
    if duplicate_direct:
        raise SophonError('X074',f'Duplicate Agent setting "{sorted(duplicate_direct)[0]}".',path.name,line,1,None,
                          'Declare id, name, and policy at most once.')
    allowed_direct={'id','name','policy'} if allow_identity else set()
    unknown=set(direct)-allowed_direct
    if unknown:
        raise SophonError('X074',f'Unknown Agent setting "{sorted(unknown)[0]}".',path.name,line,1,None,
                          'Place Agent settings under permission, security, timing, input, output, or connection.')
    result={
        'permission':{'execute':False},
        'security':{'container':False},
        'timing':{'delay':60.0,'timeout':180.0,'retry':{'duration':1.0,'count':0}},
        'input':{'max-token':None,'max-bytes':5242880},
        'output':{'max-token':None},
        'connection':{'provider':'','model':'','key':'OPENROUTER_API_KEY'},
    }
    present={section:set() for section in ('permission','security','timing','input','output','connection')}
    allowed_children={'permission','security','timing','input','output','connection'}|({'policy'} if allow_identity else set())
    child_names=[name for name,_ in _direct_children(block)]
    unknown_children=set(child_names)-allowed_children
    if unknown_children:
        raise SophonError('X074',f'Unknown Agent section "{sorted(unknown_children)[0]}".',path.name,line,1,None,
                          'Allowed sections: '+', '.join(sorted(allowed_children))+'.')
    repeated={name for name in child_names if child_names.count(name)>1}
    if repeated:
        raise SophonError('X074',f'Duplicate Agent section "{sorted(repeated)[0]}".',path.name,line,1,None,
                          'Each Agent section may appear only once.')
    for section,valid in (
        ('permission',{'execute'}),('security',{'container'}),
        ('timing',{'delay','timeout'}),('input',{'max-token','max-bytes'}),
        ('output',{'max-token'}),('connection',{'provider','model','key'})):
        value=_child_block(block,section)
        if value is None: continue
        scalar_body=_strip_child_blocks(value,('retry',)) if section=='timing' else value
        pair_items=_direct_pair_items(scalar_body)
        pair_keys=[item['key'] for item in pair_items]
        duplicate_keys={key for key in pair_keys if pair_keys.count(key)>1}
        if duplicate_keys:
            raise SophonError('X075',f'Duplicate Agent {section} setting "{sorted(duplicate_keys)[0]}".',path.name,line,1,None,
                              'Declare each setting in a section only once.')
        pairs={item['key']:item['value'] for item in pair_items}
        unknown=set(pairs)-valid
        if unknown:
            raise SophonError('X075',f'Unknown Agent {section} setting "{sorted(unknown)[0]}".',path.name,line,1,None,
                              f'Allowed settings: '+', '.join(sorted(valid))+'.')
        for key,raw in pairs.items():
            present[section].add(key)
            if section in ('permission','security'):
                if raw not in ('true','false'):
                    raise SophonError('X076',f'Agent {section}.{key} must be true or false.',path.name,line,1,None,
                                      f'Use {key} = true or {key} = false.')
                result[section][key]=(raw=='true')
            elif section in ('input','output'):
                if not re.fullmatch(r'\d+',raw) or int(raw)<1:
                    raise SophonError('X077',f'Agent {section}.{key} must be a positive integer.',path.name,line,1,None,
                                      f'Use {key} = 4096.')
                result[section][key]=int(raw)
            elif section=='timing':
                try: number=float(raw)
                except ValueError: number=0
                if number<=0:
                    raise SophonError('X078',f'Agent timing.{key} must be a positive number of seconds.',path.name,line,1,None,
                                      f'Use {key} = 60.')
                result[section][key]=number
            else:
                m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',raw)
                if not m:
                    raise SophonError('X079',f'Agent connection.{key} must be a quoted string.',path.name,line,1,None,
                                      f'Use {key} = "value".')
                result[section][key]=_decode_string(raw)
    timing=_child_block(block,'timing')
    if timing is not None:
        timing_children=[name for name,_ in _direct_children(timing)]
        if set(timing_children)-{'retry'} or timing_children.count('retry')>1:
            raise SophonError('X080','timing accepts one retry block only.',path.name,line,1,None,
                              'Use timing { delay = 60 timeout = 180 retry { duration = 2 count = 3 } }.')
        retry=_child_block(timing,'retry')
        if retry is not None:
            retry_items=_direct_pair_items(retry)
            retry_keys=[item['key'] for item in retry_items]
            duplicate_retry={key for key in retry_keys if retry_keys.count(key)>1}
            if duplicate_retry:
                raise SophonError('X080',f'Duplicate retry setting "{sorted(duplicate_retry)[0]}".',path.name,line,1,None,
                                  'Declare duration and count at most once.')
            pairs={item['key']:item['value'] for item in retry_items}; unknown=set(pairs)-{'duration','count'}
            if unknown:
                raise SophonError('X080',f'Unknown retry setting "{sorted(unknown)[0]}".',path.name,line,1,None,
                                  'Use retry { duration = 2 count = 3 }.')
            if 'duration' in pairs:
                try: duration=float(pairs['duration'])
                except ValueError: duration=0
                if duration<0:
                    raise SophonError('X080','Retry duration cannot be negative.',path.name,line,1,None,
                                      'Use duration = 2 or duration = 0.')
                result['timing']['retry']['duration']=duration
                present['timing'].add('retry.duration')
            if 'count' in pairs:
                if not re.fullmatch(r'\d+',pairs['count']):
                    raise SophonError('X080','Retry count must be a non-negative integer.',path.name,line,1,None,
                                      'Use count = 2.')
                result['timing']['retry']['count']=int(pairs['count'])
                present['timing'].add('retry.count')
        # retry is a child of timing, not a timing scalar.
    if allow_identity:
        name=direct.get('name')
        if name is not None:
            m=re.fullmatch(r'"((?:[^"\\]|\\.)*)"',name)
            if not m: raise SophonError('X081','Agent name must be a quoted string.',path.name,line,1,None,'Use name = "Research Agent".')
            result['name']=_decode_string(name)
    result['_present']=present
    return result


def _parse_v2_agent(block,path,line,defaults=None):
    direct=_direct_pairs(block)
    if 'id' not in direct:
        raise SophonError('X082','Agent block requires id.',path.name,line,1,None,'Add id = 1001.')
    aid=_xaf_integer(direct['id'],'Agent id',path,line)
    parsed=_parse_agent_sections(block,path,line,allow_identity=True)
    if not parsed.get('name'):
        raise SophonError('X081','Agent name is required.',path.name,line,1,None,'Add name = "Research Agent".')
    policy_ref=None; inline_policy=None
    if 'policy' in direct:
        raw=direct['policy']
        if not re.fullmatch(r'\d+',raw):
            raise SophonError('X083','Agent policy reference must be an integer.',path.name,line,1,None,
                              'Use policy = 2001 or an inline policy { ... }.')
        policy_ref=int(raw)
    inline=_child_block(block,'policy')
    if inline is not None:
        if policy_ref is not None:
            raise SophonError('X084','Agent cannot declare both policy reference and inline policy.',path.name,line,1,None,
                              'Choose policy = 2001 or policy { access ... action ... }.')
        inline_children=[name for name,_ in _direct_children(inline)]
        inline_direct=_direct_pairs(inline)
        if inline_direct or set(inline_children)-{'access','action','deny'} or len(inline_children)!=len(set(inline_children)):
            raise SophonError('X084','Inline Agent policy accepts access, action, and deny blocks only.',path.name,line,1,None,
                              'Use policy { access { ... } action { ... } deny { ... } }.')
        inline_policy={'access':_parse_v2_policy_access(inline,path,line),
                      'action':_parse_v2_action_block(inline,path,line),
                      'deny':_parse_v2_denials(inline,path,line),
                      'schema_version':2}
        _apply_v2_denials(inline_policy)
    if policy_ref is None and inline_policy is None:
        raise SophonError('X085',f'Agent {aid} must reference a policy or declare an inline policy.',path.name,line,1,None,
                          'Use policy = 2001 or policy { access { ... } action { ... } }.')
    # config.agent supplies shared defaults; each concrete Agent overrides only
    # the settings it explicitly declares.
    defaults=defaults or _parse_agent_sections('',path,line,allow_identity=False)
    present=parsed.pop('_present')
    default_present=defaults.get('_present',{})
    for section in ('permission','security','timing','input','output','connection'):
        for key in parsed[section]:
            if key=='retry' and section=='timing':
                for retry_key in parsed['timing']['retry']:
                    if f'retry.{retry_key}' not in present['timing']:
                        if f'retry.{retry_key}' in default_present.get('timing',set()):
                            parsed['timing']['retry'][retry_key]=defaults['timing']['retry'][retry_key]
                continue
            if key not in present[section] and key in default_present.get(section,set()):
                parsed[section][key]=defaults[section][key]
    parsed.update({'id':aid,'policy':policy_ref,'inline_policy':inline_policy})
    parsed['execute']=parsed['permission']['execute']
    parsed['container']=parsed['security']['container']
    parsed['delay']=parsed['timing']['delay']
    parsed['api-key']={'provider':parsed['connection']['provider'],'model':parsed['connection']['model'],
                       'key':parsed['connection']['key']}
    return parsed


def _validate_observer_config(block,path,line):
    scalar_pairs=_pairs(block.splitlines())
    scalar_keys=[item['key'] for item in scalar_pairs]
    allowed_scalars={'watch','log','path','level'}
    unknown=set(scalar_keys)-allowed_scalars
    if unknown:
        raise SophonError('X086',f'Unknown Observer setting "{sorted(unknown)[0]}".',path.name,line,1,None,
                          'Allowed settings: watch, log, path, level, action.')
    repeated={key for key in scalar_keys if scalar_keys.count(key)>1}
    if repeated:
        raise SophonError('X086',f'Duplicate Observer setting "{sorted(repeated)[0]}".',path.name,line,1,None,
                          'Declare each Observer setting once.')
    def req(key):
        m=re.search(rf'\b{key}\s*=\s*(true|false)\b',block)
        if not m: raise SophonError('X086',f'Observer configuration requires {key}.',path.name,line,1,None,
                                    f'Use {key} = true or {key} = false.')
        return m.group(1)=='true'
    watch=req('watch'); log=req('log')
    pm=re.search(r'\bpath\s*=\s*(null|"(?:[^"\\]|\\.)*")',block)
    if not pm: raise SophonError('X087','Observer configuration requires path.',path.name,line,1,None,
                                  'Use path = "logs" or path = null.')
    raw_path=pm.group(1)
    if log and raw_path=='null': raise SophonError('X088','Observer path must be a string when log = true.',path.name,line,1,None,'Set path = "logs".')
    if not log and raw_path!='null': raise SophonError('X088','Observer path must be null when log = false.',path.name,line,1,None,'Set path = null.')
    level_match=re.search(rf'\blevel\s*=\s*({"|".join(LOG_LEVELS)})\b',block)
    if re.search(r'\blevel\s*=',block) and not level_match:
        raise SophonError('X089','Unknown Observer log level.',path.name,line,1,None,
                          'Use compact, normal, detailed, or debug.')
    if log and not level_match: raise SophonError('X089','Observer level is required when logging is enabled.',path.name,line,1,None,
                                                    'Use level = compact, normal, detailed, or debug.')
    action_block=_child_block(block,'action')
    if action_block is None: raise SophonError('X090','Observer configuration requires action.',path.name,line,1,None,
                                               'Add action { read = true ... }.')
    actions={}
    if _direct_children(action_block):
        raise SophonError('X091','Observer actions must be Boolean assignments, not nested blocks.',path.name,line,1,None,
                          'Write read = true, modify = true, and similar settings directly inside action.')
    action_pairs=_pairs(action_block.splitlines())
    for item in action_pairs:
        key,value=item['key'],item['value']
        if key not in OBSERVE_ACTIONS or value not in ('true','false'):
            raise SophonError('X091',f'Invalid observer action setting "{key} = {value}".',path.name,line,1,None,
                              'Use read, modify, create, remove, reorder = true/false.')
        if key in actions: raise SophonError('X091',f'Duplicate observer action "{key}".',path.name,line,1,None,'Declare each action once.')
        actions[key]=(value=='true')
    if not actions: raise SophonError('X090','Observer action cannot be empty.',path.name,line,1,None,'Enable at least one observation action.')
    log_path=None if raw_path=='null' else _decode_string(raw_path)
    if log and (not log_path or os.path.isabs(log_path) or '..' in Path(log_path).parts):
        raise SophonError('X116','Observer log path must be a non-empty project-relative path.',path.name,line,1,None,
                          'Use a relative folder such as "logs"; absolute paths and ".." are not allowed.')
    return {'watch':watch,'log':log,'path':log_path,
            'level':level_match.group(1) if level_match else 'compact','actions':actions}


def _parse_config(block,path,line):
    config={'multi':set(),'observer':{},'database':{'connection':{'provider':'local'},'max-records':None,'max-bytes':None},
            'file-system':None,'execute':{'files':[],'commands':[]},'agent':None}
    sections=[section for section,_ in _direct_children(block)]
    repeated={name for name in sections if sections.count(name)>1}
    if repeated:
        raise SophonError('X098',f'Duplicate config section "{sorted(repeated)[0]}".',path.name,line,1,None,
                          'Each config section may appear only once.')
    for section,body in _direct_children(block):
        if section=='multi':
            entries=body.split()
            unknown=set(entries)-set(MULTI_FEATURES)
            if unknown:
                raise SophonError('X092',f'Unknown multi configuration "{sorted(unknown)[0]}".',path.name,line,1,None,
                                  'Available multi components: '+', '.join(MULTI_FEATURES)+'.')
            if len(entries)!=len(set(entries)):
                raise SophonError('X093','Duplicate multi configuration entry.',path.name,line,1,None,'Declare each multi component once.')
            config['multi']=set(entries)
        elif section=='observer':
            if _direct_pairs(body):
                raise SophonError('X094','config.observer accepts only numeric observer-id blocks.',path.name,line,1,None,
                                  'Use config.observer { 1001 { ... } }.')
            numeric_blocks=_direct_numeric_blocks(body)
            observer_text=body if isinstance(body,str) else '\n'.join(body)
            residue=observer_text
            spans=[]
            flat=_top_level_map(observer_text)
            for match in re.finditer(r'(\d+)\s*\{',observer_text):
                if not flat[match.start(1)] or (match.start(1) and not flat[match.start(1)-1]):
                    continue
                close=_closing_brace(observer_text,observer_text.find('{',match.start(),match.end()))
                if close is None:
                    raise SophonError('X094','Observer profile block is not closed.',path.name,line,1,None,"Add the closing '}'.")
                spans.append((match.start(),close+1))
            for start,end in reversed(spans): residue=residue[:start]+(' '* (end-start))+residue[end:]
            if residue.replace(',',' ').strip():
                raise SophonError('X094','config.observer contains a non-numeric or malformed profile.',path.name,line,1,None,
                                  'Use numeric IDs such as 1001 { watch = true ... }.')
            for oid,oblock in numeric_blocks:
                _xaf_integer(str(oid),'Observer id',path,line)
                if oid in config['observer']:
                    raise SophonError('X094',f'Duplicate observer configuration id {oid}.',path.name,line,1,None,'Use a unique observer id.')
                config['observer'][oid]=_validate_observer_config(oblock,path,line)
        elif section=='database':
            db_items=_direct_pair_items(body)
            db_keys=[item['key'] for item in db_items]
            duplicate_db={key for key in db_keys if db_keys.count(key)>1}
            if duplicate_db:
                raise SophonError('X095',f'Duplicate database setting "{sorted(duplicate_db)[0]}".',path.name,line,1,None,
                                  'Declare each database setting once.')
            dbpairs={item['key']:item['value'] for item in db_items}
            if set(dbpairs)-{'max-records','max-bytes'}:
                raise SophonError('X095',f'Unknown database setting "{sorted(set(dbpairs)-{"max-records","max-bytes"})[0]}".',path.name,line,1,None,
                                  'Use max-records, max-bytes, or connection { provider = "local" }.')
            for key,raw in dbpairs.items():
                if not re.fullmatch(r'\d+',raw) or int(raw)<1:
                    raise SophonError('X095',f'Database {key} must be a positive integer.',path.name,line,1,None,f'Use {key} = 100000.')
                config['database'][key]=int(raw)
            conn=_child_block(body,'connection')
            if conn is not None:
                connection_items=_direct_pair_items(conn)
                connection_keys=[item['key'] for item in connection_items]
                if len(connection_keys)!=len(set(connection_keys)):
                    raise SophonError('X096','Database connection provider is declared more than once.',path.name,line,1,None,
                                      'Keep one provider = "local" setting.')
                cp={item['key']:item['value'] for item in connection_items}
                if set(cp)!={'provider'} or cp['provider']!='"local"':
                    raise SophonError('X096','Only the local .svt database provider is currently supported.',path.name,line,1,None,
                                      'Use connection { provider = "local" }. Each database path is connected in SPH with connect = "file.svt".')
            child_names=[name for name,_ in _direct_children(body)]
            if any(name!='connection' for name in child_names) or child_names.count('connection')>1:
                raise SophonError('X096','config.database accepts one connection block only.',path.name,line,1,None,
                                  'Use connection { provider = "local" } plus max-records/max-bytes.')
        elif section=='file-system':
            config['file-system']=_parse_file_system(body,path)
        elif section=='execute':
            child_names=[name for name,_ in _direct_children(body)]
            if set(child_names)-{'file','command'} or len(child_names)!=len(set(child_names)):
                raise SophonError('X097','config.execute accepts one file block and one command block.',path.name,line,1,None,
                                  'Use file { "worker.sph" } and command { } only.')
            file_block=_child_block(body,'file')
            command_block=_child_block(body,'command')
            if file_block is not None:
                matches=list(re.finditer(r'"((?:[^"\\]|\\.)*)"',file_block))
                residue=file_block
                for match in reversed(matches): residue=residue[:match.start()]+(' '*len(match.group(0)))+residue[match.end():]
                if residue.replace(',',' ').strip():
                    raise SophonError('X097','config.execute.file accepts quoted file paths only.',path.name,line,1,None,
                                      'Use file { "worker.sph" "processor.sph" }.')
                config['execute']['files']=[_decode_string(match.group(0)) for match in matches]
                if len(config['execute']['files'])!=len(set(config['execute']['files'])):
                    raise SophonError('X097','Duplicate executable file allowlist entry.',path.name,line,1,None,
                                      'List each .sph file only once.')
                for name in config['execute']['files']:
                    if not name.endswith('.sph') or os.path.isabs(name) or '..' in Path(name).parts:
                        raise SophonError('X097',f'Invalid executable file allowlist entry "{name}".',path.name,line,1,None,
                                          'List project-relative .sph files, for example "worker.sph".')
            if command_block is not None and command_block.strip():
                raise SophonError('X097','No Sophon commands are registered; config.execute.command must remain empty.',path.name,line,1,None,
                                  'Keep command { } empty until a Sophon command is registered.')
        elif section=='agent':
            config['agent']=_parse_agent_sections(body,path,line,allow_identity=False)
        else:
            raise SophonError('X098',f'Unknown config section "{section}".',path.name,line,1,None,
                              'Allowed config sections: multi, observer, database, file-system, execute, agent.')
    return config

def _parse_access_block(block,path=None):
    """Parse a policy access block.

    A bare line grants every resource of that kind. `observer` and `database` may also
    name specific resources; `surface`, `ask` and `input` are capability grants with no
    name list, so they are bare or absent.
    """
    body=_child_block(block,'access')
    if body is None: return {k:(v.copy() if isinstance(v,set) else v) for k,v in ACCESS_EMPTY.items()}
    out={k:(v.copy() if isinstance(v,set) else v) for k,v in ACCESS_EMPTY.items()}
    # Nested blocks are removed first so their contents can never be read as bare grants.
    bare=_strip_child_blocks(body,('observer','database','file-system','execute'))
    for token in bare.split():
        if token in out: out[token]=True
    if out.get('file-system') is True:
        raise SophonError('X056','file-system must use a scoped block with allowed_path.','',1,1,None,
                          'Use file-system { allowed_path { "data" } action { ... } }.')
    for k in ('file-system','execute'):
        if _child_block(body,k) is not None: out[k]=_parse_capability_block(k,body,path)
    for kind in ('observer','database'):
        if out[kind] is True: continue
        child=_child_block(body,kind)
        if child is not None: out[kind].update(re.findall(r'\b([A-Za-z_][\w.-]*)\b',child))
    for kind in GLOBAL_ACCESS:
        if _child_block(body,kind) is not None:
            raise SophonError('X031',f'access {{ {kind} }} does not take a name list.','',1,1,None,
                              f'Use a bare "{kind}" line, or omit it to deny the capability.')
    return out


def _parse_capability_block(kind,body,path):
    """Read a file-system or execute capability block out of a policy access block."""
    block=_child_block(body,kind)
    if kind=='file-system': return _parse_file_system(block,path)
    return _parse_execute(block,path)

def _parse_path_list(block,key):
    """Read one path setting, rejecting ignored text, duplicates, and malformed values."""
    text=block if isinstance(block,str) else '\n'.join(block)
    label=key.replace('_',r'(?:_|\s+)')
    scalar=re.search(rf'\b{label}\s*=\s*("(?:[^"\\]|\\.)*")',text)
    child=re.search(rf'\b{label}\s*\{{',text)
    if scalar and child:
        raise SophonError('X114',f'{key} cannot be declared both as an assignment and a block.','',1,1,None,
                          f'Choose {key} = "data" or {key} {{ "data" }}.')
    if scalar:
        value=json.loads(scalar.group(1))
        return [value]
    if child:
        brace=text.find('{',child.start(),child.end())
        close=_closing_brace(text,brace)
        if close is None:
            raise SophonError('X114',f'{key} block is not closed.','',1,1,None,"Add the closing '}'.")
        body=text[brace+1:close]
        values=[json.loads(m.group(0)) for m in re.finditer(r'"(?:[^"\\]|\\.)*"',body)]
        residue=re.sub(r'"(?:[^"\\]|\\.)*"','',body).replace(',',' ').strip()
        if residue:
            raise SophonError('X114',f'{key} contains an invalid path entry "{residue}".','',1,1,None,
                              'Use quoted project-relative paths only.')
        if len(values)!=len(set(values)):
            raise SophonError('X114',f'{key} contains duplicate paths.','',1,1,None,'List each path once.')
        return values
    if re.search(rf'\b{label}\s*(?:=|\{{)',text):
        raise SophonError('X114',f'{key} must contain quoted path strings.','',1,1,None,
                          f'Use {key} {{ "data" }}.')
    return None

def _validate_policy_paths(paths,key,path):
    if paths is None: return
    for item in paths:
        if not item or os.path.isabs(item) or '..' in Path(item).parts:
            raise SophonError('X055',f'Invalid {key} path "{item}".',path.name,1,1,None,
                              'Use a project-relative path without "..", for example "data".')


def _parse_file_system(block,path):
    """Parse strict, scoped file/folder access lists for XAF v2 and legacy policy."""
    text=block if isinstance(block,str) else '\n'.join(block)
    child_names=[name for name,_ in _direct_children(text)]
    pair_items=_direct_pair_items(text)
    pair_names=[item['key'] for item in pair_items]
    allowed={'allowed_path','forbidden_path','action'}
    if set(child_names)-allowed or set(pair_names)-{'allowed_path','forbidden_path'}:
        unknown=sorted((set(child_names)|set(pair_names))-allowed)[0]
        raise SophonError('X114',f'Unknown file-system setting "{unknown}".',path.name,1,1,None,
                          'Use only allowed_path, forbidden_path, and action.')
    declared=child_names+pair_names
    repeated={name for name in declared if declared.count(name)>1}
    if repeated:
        raise SophonError('X114',f'Duplicate file-system setting "{sorted(repeated)[0]}".',path.name,1,1,None,
                          'Declare each path list and action block once.')
    paths=_parse_path_list(text,'allowed_path')
    if paths is None:
        raise SophonError('X056','file-system requires allowed_path.',path.name,1,1,None,
                          'Add allowed_path { "data" } inside file-system.')
    if not paths:
        raise SophonError('X056','allowed_path cannot be empty.',path.name,1,1,None,'Add at least one allowed project path.')
    forbidden=_parse_path_list(text,'forbidden_path') or []
    _validate_policy_paths(paths,'allowed_path',path)
    _validate_policy_paths(forbidden,'forbidden_path',path)
    actions={'file':set(),'folder':set()}
    action_block=_child_block(text,'action')
    if action_block is not None:
        action_children=[name for name,_ in _direct_children(action_block)]
        action_pairs=_direct_pair_items(action_block)
        if set(action_children)-{'file','folder'} or action_pairs:
            raise SophonError('X114','file-system action accepts only file and folder action lists.',path.name,1,1,None,
                              'Use action { file { read write } folder { create delete } }.')
        repeated_children={name for name in action_children if action_children.count(name)>1}
        if repeated_children:
            raise SophonError('X114',f'Duplicate file-system action block "{sorted(repeated_children)[0]}".',path.name,1,1,None,
                              'Declare file and folder action blocks at most once.')
        for kind,valid in (('file',FILE_ACTIONS),('folder',FOLDER_ACTIONS)):
            kind_body=_child_block(action_block,kind)
            if kind_body is None: continue
            if _direct_children(kind_body) or _direct_pair_items(kind_body):
                raise SophonError('X114',f'{kind} actions must be listed as plain names.',path.name,1,1,None,
                                  f'Use {kind} {{ '+ ' '.join(valid) +' }.')
            tokens=[token.strip(',') for token in kind_body.split() if token.strip(',')]
            unknown=set(tokens)-set(valid)
            if unknown:
                raise SophonError('X051',f'Unknown {kind} action "{sorted(unknown)[0]}".',path.name,1,1,None,
                                  f'Valid {kind} actions: '+', '.join(valid)+'.')
            if len(tokens)!=len(set(tokens)):
                raise SophonError('X115',f'Duplicate {kind} file-system action.',path.name,1,1,None,
                                  'Declare each action once in its file or folder list.')
            actions[kind]=set(tokens)
    return {'paths':paths,'forbidden':forbidden,'actions':actions}

def _parse_execute(block,path):
    out={'file':False,'commands':[]}
    if re.search(r'^\s*file\s*$',block,re.M): out['file']=True
    cm=re.search(r'\bcommand\s*\{([^{}]*)\}',block,re.S)
    if cm:
        out['commands']=re.findall(r'"((?:[^"\\]|\\.)*)"',cm.group(1))
        bare=re.findall(r'^[A-Za-z][\w-]*$',cm.group(1),re.M)
        out['commands']+= [b for b in bare if b not in out['commands']]
    return out

def _validate_observe_policy(block,path,line):
    def req(key,code):
        m=re.search(rf'\b{key}\s*=\s*(true|false)\b',block)
        if not m: raise SophonError(code,f'Observe policy requires {key}.',path.name,line,1,None,f'Use {key} = true or {key} = false.')
        return m.group(1)=='true'
    watch=req('watch','X010'); log=req('log','X011')
    pm=re.search(r'\bpath\s*=\s*(null|"(?:[^"\\]|\\.)*")\s*',block)
    if not pm: raise SophonError('X012','Observe policy requires path.',path.name,line,1,None,'Use path = "logs" or path = null.')
    pv=pm.group(1)
    if log and pv=='null': raise SophonError('X013','path must be a string when log = true.',path.name,line,1,None,'Set a folder path, for example path = "logs".')
    if not log and pv!='null': raise SophonError('X014','path must be null when log = false.',path.name,line,1,None,'Use path = null when logging is disabled.')
    lm=re.search(rf'\blevel\s*=\s*({"|".join(LOG_LEVELS)})\b',block)
    if log and not lm: raise SophonError('X019','Observe policy requires a log level when logging is enabled.',path.name,line,1,None,'Use level = compact, normal, detailed, or debug.')
    level=lm.group(1) if lm else 'compact'
    am=re.search(r'\baction\s*\{([^{}]*)\}',block,re.S)
    if not am: raise SophonError('X015','Observe policy requires an action block.',path.name,line,1,None,'Add action { read = true ... }.')
    acts=re.findall(rf'\b({"|".join(OBSERVE_ACTIONS)})\s*=\s*(true|false)\b',am.group(1))
    if not acts: raise SophonError('X017','Action block cannot be empty.',path.name,line,1,None,'Add at least one action such as read = true.')
    if len(acts)!=len({a for a,_ in acts}): raise SophonError('X016','Duplicate action setting.',path.name,line,1,None,'Define each action only once.')
    sm=_child_block(block,'source')
    if sm is None:
        raise SophonError('X064','Observer policy requires a source permission block.',path.name,line,1,None,
                          'Add source { self = true external = true } and set each source permission explicitly.')
    source_permissions={'self':False,'external':False}; seen_sources=set()
    for key,value in re.findall(r'\b(self|external)\s*=\s*(true|false)\b',sm):
        if key in seen_sources:
            raise SophonError('X065',f'Duplicate observer source permission "{key}".',path.name,line,1,None,'Declare each source permission once.')
        seen_sources.add(key); source_permissions[key]=(value=='true')
    unknown=re.sub(r'\b(self|external)\s*=\s*(true|false)\b','',sm).strip()
    if unknown:
        raise SophonError('X065',f'Invalid observer source permission "{unknown}".',path.name,line,1,None,
                          'Use only self = true/false and external = true/false.')
    return {'watch':watch,'log':log,'path':None if pv=='null' else json.loads(pv),'level':level,
            'actions':{a:(v=='true') for a,v in acts},'sources':source_permissions}

def _find_named_blocks(lines, keyword):
    return _named_blocks(lines, rf'^{keyword}\s+"?([A-Za-z0-9_.-]+)"?\s*\{{')

def _extract_agent_policy(block):
    name=re.search(r'\bname\s*=\s*"((?:[^"\\]|\\.)*)"',block)
    policy=re.search(r'\bpolicy\s*=\s*"([A-Za-z0-9_.-]+)"',block)
    execute=re.search(r'\bexecute\s*=\s*(true|false)',block)
    container=re.search(r'\bcontainer\s*=\s*(true|false)',block)
    cm=re.search(r'\bconnect\s*\{([^{}]*)\}',block,re.S)
    connects=re.findall(r'\b([A-Za-z0-9_./-]+\.sph)\b',cm.group(1)) if cm else []
    km=re.search(r'\bapi-key\s*\{([^{}]*)\}',block,re.S)
    api={}
    if km:
        for k,v in re.findall(r'\b(provider|model|key)\s*=\s*"([^"]*)"',km.group(1)): api[k]=v
    im=re.search(r'\binput\s*\{([^{}]*)\}',block,re.S)
    limits={}
    if im:
        mm=re.search(r'\bmax-bytes\s*=\s*(\d+)',im.group(1))
        if mm: limits['max-bytes']=int(mm.group(1))
    dms=re.findall(r'\bdelay\s*=\s*([^\s}]+)',block)
    if len(dms)>1: raise SophonError('A031','Agent delay cannot be declared more than once.',path.name,1,1,None,'Keep one delay setting.')
    try: delay=float(dms[0]) if dms else 60.0
    except ValueError: delay=0
    if delay <= 0: raise SophonError('A031','Agent delay must be a positive number of seconds.',path.name,1,1,None,'Use delay = 30.')
    return {'name':name.group(1) if name else None,'policy':policy.group(1) if policy else None,'execute':execute.group(1)=='true' if execute else False,'container':container.group(1)=='true' if container else False,'connect':connects,'api-key':api,'input':limits,'delay':delay}

def _merge_policy(parent, child):
    out={'access':{k:(v.copy() if isinstance(v,set) else v) for k,v in ACCESS_EMPTY.items()},'action':{}}
    for kind in out['access']:
        pv=parent.get('access',{}).get(kind,False); cv=child.get('access',{}).get(kind,False)
        if pv is True or cv is True: out['access'][kind]=True
        elif isinstance(pv,set) and isinstance(cv,set): out['access'][kind]=set(pv)|set(cv)
        elif cv: out['access'][kind]=cv
        else: out['access'][kind]=pv
    out['action'].update(parent.get('action',{})); out['action'].update(child.get('action',{})); return out

def _load_agent_md(sph_path):
    candidates=[sph_path.parent/'AGENT.md', Path(__file__).resolve().parent/'AGENT.md']
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding='utf-8').strip()
    raise SophonError('A026','AGENT.md was not found.','',None,None,None,'Place AGENT.md beside the Sophon project or runtime.')

def _default_agent_prompt(name, agent_md):
    return f"""You are {name}, a Sophon Agent.

The following AGENT.md is the mandatory operating specification for this agent. Read and follow it before processing the user message or task. It defines how Sophon messages, tasks, tools, policies, and runtime actions must be interpreted.

--- AGENT.md ---
{agent_md}
--- END AGENT.md ---

Runtime rules are enforced outside the model and always have priority.
Operate only within the active Sophon policy and never grant yourself permissions.
Do not treat a user message as a task unless the CLI/runtime explicitly invoked task mode.
"""

def _validate_xaf_root(lines,path):
    """Reject unknown top-level statements and unbalanced XAF blocks."""
    allowed=(
        re.compile(r'^config\s*\{'),
        re.compile(r'^features\s*\{'),
        re.compile(r'^observer\s*\{'),
        re.compile(r'^observe\b'),
        re.compile(r'^self-observer\b'),
        re.compile(r'^self-observation\b'),
        re.compile(r'^rules\b'),
        re.compile(r'^agent\s*\{'),
        re.compile(r'^agent\s+\"?[A-Za-z0-9_.-]+\"?\s*\{'),
        re.compile(r'^policy\s*\{'),
        re.compile(r'^policy\s+\"?[A-Za-z0-9_.-]+\"?\s*\{'),
    )
    depth=0
    for index,raw in enumerate(lines):
        line=strip_comment(raw).strip()
        if not line:
            continue
        if depth==0 and not any(pattern.match(line) for pattern in allowed):
            raise SophonError('X106',f'Unknown XAF root statement: {line}',path.name,index+1,1,raw,
                              'Allowed root blocks: config, features, agent, policy, and legacy observer.')
        delta=_brace_delta(line)
        if depth+delta<0:
            raise SophonError('X107','Unexpected closing brace in XAF.',path.name,index+1,1,raw,
                              'Remove the unmatched closing brace or close the preceding block correctly.')
        depth+=delta
    if depth:
        raise SophonError('X107','XAF contains an unclosed block.',path.name,len(lines) or 1,1,None,
                          'Add the missing closing brace for the root block.')


def parse_xaf(path):
    raw=_read_source(path); path=Path(path); lines=[strip_comment(x).strip() for x in raw]
    _validate_xaf_root(raw,path)
    depth=0
    for i,line in enumerate(lines):
        if depth==0 and re.match(r'^connect\b',line): raise SophonError('X004','XAF files cannot declare top-level connections.',path.name,i+1,1,raw[i],'Declare the connection in the SPH file.')
        if depth==0 and re.match(r'^rules\b',line): raise SophonError('X005','The XAF policy keyword is "policy", not "rules".',path.name,i+1,1,raw[i],'Use: policy <name> { ... }')
        if depth==0 and re.match(r'^observe\b',line): raise SophonError('X062','The XAF observe block has been removed; use observer policies keyed by id.',path.name,i+1,1,raw[i],'Use observer { <id> { ... } }.')
        if depth==0 and re.match(r'^self-observer\b',line): raise SophonError('X063','The self-observer block has been replaced by features.self-observation.',path.name,i+1,1,raw[i],'Use features { self-observation = true } and observer policies keyed by id.')
        if depth==0 and re.match(r'^self-observation\b',line): raise SophonError('X007','self-observation must be declared inside features.',path.name,i+1,1,raw[i],'Use: features { self-observation = true }')
        depth += line.count('{')-line.count('}')
    config_blocks=_root_blocks(lines,r'^config\s*\{')
    new_agent_blocks=_root_blocks(lines,r'^agent\s*\{')
    new_policy_blocks=_root_blocks(lines,r'^policy\s*\{')
    is_v2=bool(config_blocks or new_agent_blocks or new_policy_blocks)
    if len(config_blocks)>1:
        raise SophonError('X099','XAF may contain only one config block.',path.name,1,1,None,
                          'Move all settings into the single root config { ... } block.')
    settings={'self':{},'agents':{},'policies':{},'features':{'self-observation':False},
              'config':{'multi':set(),'observer':{},'database':{'connection':{'provider':'local'},'max-records':None,'max-bytes':None},
                        'file-system':None,'execute':{'files':[],'commands':[]},'agent':None,'default-policy':None},
              'schema_version':2 if is_v2 else 1}
    if config_blocks:
        _,ci,_,config_body=config_blocks[0]
        config_items=_direct_pair_items(config_body)
        config_keys=[item['key'] for item in config_items]
        duplicate_config={key for key in config_keys if config_keys.count(key)>1}
        if duplicate_config:
            raise SophonError('X100',f'Duplicate root config setting "{sorted(duplicate_config)[0]}".',path.name,ci+1,1,None,
                              'Declare default-policy once; place other settings in their config sections.')
        direct={item['key']:item['value'] for item in config_items}
        if set(direct)-{'default-policy'}:
            raise SophonError('X100',f'Unknown root config setting "{sorted(set(direct)-{"default-policy"})[0]}".',path.name,ci+1,1,None,
                              'Use default-policy = 2001 or place settings under their named config sections.')
        if 'default-policy' in direct:
            settings['config']['default-policy']=_xaf_integer(direct['default-policy'],'default-policy',path,ci+1)
        parsed_config=_parse_config(config_body,path,ci+1)
        settings['config'].update(parsed_config)
    feature_seen = False
    feature_blocks=_root_blocks(lines,r'^features\s*\{',key=None)
    if len(feature_blocks)>1:
        raise SophonError('X060','XAF may contain only one features block.',path.name,feature_blocks[1][1]+1,1,None,
                          'Move every feature flag into one features { ... } block.')
    for _,fi,_,fbody in feature_blocks:
        feature_items=_direct_pair_items(fbody)
        feature_keys=[item['key'] for item in feature_items]
        if set(feature_keys)-{'self-observation'}:
            unknown=sorted(set(feature_keys)-{'self-observation'})[0]
            raise SophonError('X060',f'Unknown XAF feature "{unknown}".',path.name,fi+1,1,None,
                              'Currently supported feature: self-observation.')
        if len(feature_keys)!=len(set(feature_keys)):
            raise SophonError('X060','Duplicate features.self-observation setting.',path.name,fi+1,1,None,'Declare the feature once.')
        if feature_items:
            value=feature_items[0]['value']
            if value not in ('true','false'):
                raise SophonError('X060','Invalid features.self-observation value.',path.name,fi+1,1,None,'Use self-observation = true or false.')
            settings['features']['self-observation']=(value=='true'); feature_seen=True
    # New observer profiles are keyed by numeric IDs below config.observer.
    settings['self'].update(settings['config'].get('observer',{}))
    # Legacy observer profiles remain readable while projects migrate to config.observer.
    for _,i,_,body in _root_blocks(lines,r'^observer\s*\{',key=None):
        for child,b in _direct_children(body):
            settings['self'][child]=_validate_observe_policy(b,path,i+2)
    agent_defaults=settings['config'].get('agent') or _parse_agent_sections('',path,1,allow_identity=False)
    for _,i,_,body in new_agent_blocks:
        agent=_parse_v2_agent(body,path,i+1,agent_defaults)
        aid=agent['id']
        if aid in settings['agents']:
            raise SophonError('X101',f'Duplicate Agent id {aid}.',path.name,i+1,1,None,'Use a unique numeric Agent id.')
        settings['agents'][aid]=agent
    # Legacy named Agent blocks are still accepted but are not generated by the v2 schema.
    for aid,i,_,body in _find_named_blocks(lines,'agent'):
        if aid in settings['agents']:
            raise SophonError('X101',f'Duplicate Agent id "{aid}".',path.name,i+1,1,None,'Use a unique Agent id.')
        a=_extract_agent_policy(body); a['id']=aid; settings['agents'][aid]=a
    for _,i,_,body in new_policy_blocks:
        policy_items=_direct_pair_items(body)
        policy_keys=[item['key'] for item in policy_items]
        duplicate_policy={key for key in policy_keys if policy_keys.count(key)>1}
        if duplicate_policy:
            raise SophonError('X103',f'Duplicate Policy setting "{sorted(duplicate_policy)[0]}".',path.name,i+1,1,None,
                              'Declare id and inherits at most once.')
        direct={item['key']:item['value'] for item in policy_items}
        if 'id' not in direct:
            raise SophonError('X102','Policy block requires id.',path.name,i+1,1,None,'Add id = 2001.')
        pid=_xaf_integer(direct['id'],'Policy id',path,i+1)
        allowed={'id','inherits'}
        unknown=set(direct)-allowed
        if unknown:
            raise SophonError('X103',f'Unknown Policy setting "{sorted(unknown)[0]}".',path.name,i+1,1,None,
                              'Policy settings are id, inherits, access, and action.')
        children=[name for name,_ in _direct_children(body)]
        if set(children)-{'access','action','deny','inherits'} or len(children)!=len(set(children)):
            raise SophonError('X103','Policy accepts access, action, and one inherits block.',path.name,i+1,1,None,
                              'Use inherits { id = 2000 deny { ... } } when inherited permissions must be denied.')
        if pid in settings['policies']:
            raise SophonError('X104',f'Duplicate Policy id {pid}.',path.name,i+1,1,None,'Use a unique numeric Policy id.')
        inherits_body=_child_block(body,'inherits')
        if inherits_body is not None and 'inherits' in direct:
            raise SophonError('X103','Use either inherits = <id> or an inherits { ... } block, not both.',path.name,i+1,1,None,
                              'Use inherits = 2000 without denials, or inherits { id = 2000 deny { ... } }.')
        if inherits_body is not None:
            inh_items=_direct_pair_items(inherits_body)
            inh_keys=[item['key'] for item in inh_items]
            if inh_keys.count('id')!=1 or set(inh_keys)-{'id'}:
                raise SophonError('X103','inherits block requires exactly one id assignment.',path.name,i+1,1,None,
                                  'Use inherits { id = 2000 deny { access { multi } } }.')
            inh=_xaf_integer(next(item['value'] for item in inh_items if item['key']=='id'),'Policy inherits id',path,i+1)
            inh_children=[name for name,_ in _direct_children(inherits_body)]
            if set(inh_children)-{'deny'} or inh_children.count('deny')>1:
                raise SophonError('X103','inherits block accepts id and one deny block only.',path.name,i+1,1,None,
                                  'Place deny { access { ... } action { ... } } inside inherits.')
            nested_deny_body=_child_block(inherits_body,'deny')
            if nested_deny_body is None:
                raise SophonError('X103','inherits block is only used when a deny rule is present.',path.name,i+1,1,None,
                                  'Without deny, use inherits = 2000. With deny, use inherits { id = 2000 deny { ... } }.')
            if _child_block(body,'deny') is not None:
                raise SophonError('X103','deny must be nested inside inherits in the new policy schema.',path.name,i+1,1,None,
                                  'Move deny inside inherits { id = ... deny { ... } }.')
            denials=(_parse_v2_denials('deny { '+nested_deny_body+' }',path,i+1)
                     if nested_deny_body is not None else _parse_v2_denials('',path,i+1))
        else:
            inh=direct.get('inherits')
            if inh is not None:
                inh=_xaf_integer(inh,'Policy inherits',path,i+1)
            # Root-level deny remains readable for backward compatibility.
            denials=_parse_v2_denials(body,path,i+1)
        settings['policies'][pid]={'access':_parse_v2_policy_access(body,path,i+1),
                                   'action':_parse_v2_action_block(body,path,i+1),
                                   'deny':denials,'inherits':inh,'schema_version':2}
    for pname,i,_,body in _find_named_blocks(lines,'policy'):
        if pname in settings['policies']:
            raise SophonError('X104',f'Duplicate Policy id/name "{pname}".',path.name,i+1,1,None,'Use a unique Policy id/name.')
        access=_parse_access_block(body,path); action=_parse_action_block(body,path,i+1)
        inh=re.search(r'\binherits\s*=\s*"([A-Za-z0-9_.-]+)"',body)
        settings['policies'][pname]={'access':access,'action':action,'inherits':inh.group(1) if inh else None,'schema_version':1}
    for aid,a in settings['agents'].items():
        if a.get('inline_policy') is not None: continue
        if not a.get('policy'):
            raise SophonError('X021',f'Agent "{aid}" must define a policy.',path.name,1,1,None,'Add policy = 2001 or an inline policy block.')
        if a['policy'] not in settings['policies']:
            raise SophonError('X022',f'Policy "{a["policy"]}" for agent "{aid}" was not found.',path.name,1,1,None,'Define the Policy in the same XAF file.')
    resolved={}
    def resolve(name,stack=None):
        if name in resolved:return resolved[name]
        stack=stack or []
        if name in stack: raise SophonError('X023',f'Policy inheritance cycle involving "{name}".',path.name,1,1,None,'Policy inheritance must form an acyclic chain.')
        p=settings['policies'][name]
        if p.get('schema_version')==2:
            base={'access':{**{k:False for k in XAF_ACCESS_KEYS},'source':{'self':False,'external':False}},'action':{},
                  'deny':{'access':{**{k:False for k in XAF_ACCESS_KEYS},'source':{'self':False,'external':False}},'action':{}}}
        else:
            base={'access':{k:(v.copy() if isinstance(v,set) else v) for k,v in ACCESS_EMPTY.items()},'action':{}}
        if p['inherits']:
            if p['inherits'] not in settings['policies']: raise SophonError('X033',f'Parent policy "{p["inherits"]}" was not found.',path.name,1,1,None,'Define the inherited policy first.')
            base=resolve(p['inherits'],stack+[name])
        if p.get('schema_version')==2:
            merged={'access':_merge_v2_access(base['access'],p['access']),'action':dict(base.get('action',{})),
                    'deny':_merge_v2_denials(base,p)}
            merged['action'].update(p.get('action',{}))
            _apply_v2_denials(merged)
            merged['schema_version']=2
        else:
            merged=_merge_policy(base,p); merged['schema_version']=1
        resolved[name]=merged; return resolved[name]
    for p in settings['policies']: resolve(p)
    settings['resolved_policies']=resolved
    default_policy=settings['config'].get('default-policy')
    if default_policy is not None and default_policy not in resolved:
        raise SophonError('X105',f'default-policy {default_policy} was not found.',path.name,1,1,None,
                          'Define a policy { id = ... } with the same numeric id.')
    return settings

def _policy_for_agent(settings,aid):
    a=settings['agents'].get(aid)
    if not a: raise SophonError('A010',f'Agent "{aid}" was not found in the connected XAF.','')
    policy=a.get('inline_policy') or settings['resolved_policies'][a['policy']]
    return a,policy

def _append_once(text, marker, block):
    if marker in text: return text,False
    if not text.endswith('\n'): text+='\n'
    return text+'\n'+block.rstrip()+'\n',True

def _db_aliases(databases): return [d['alias'] for d in (databases or ())]

def _xaf_quote(value):
    """Return a Sophon quoted string suitable for generated XAF source."""
    return json.dumps(str(value), ensure_ascii=False)


def _policy_access_v2(program, uses=(), observers=None, agent_ids=(), sph_path=None):
    """Capabilities exercised by this program under the XAF v2 access model."""
    observers = observers or {}
    features = set()
    if program is not None:
        features = _program_multi_features(sph_path, program) if sph_path is not None else set()
        if program.groups: features.add('multi-state')
        if program.observer_groups: features.add('multi-observer')
    # When the source is not available to the render helper, imported multi
    # modules still provide a useful conservative hint.
    features.update(x for x in (uses or ()) if x in MULTI_FEATURES)
    capabilities=[]
    if features: capabilities.append('multi')
    if observers: capabilities.append('observer')
    if program is not None and program.databases: capabilities.append('database')
    if program is not None and (program.files or 'file' in (uses or ())): capabilities.append('file-system')
    if program is not None and program.executes: capabilities.append('execute')
    if agent_ids or (program is not None and program.agent_calls): capabilities.append('agent')
    if program is not None and any(item.get('kind')=='component' for item in program.renders): capabilities.append('component')
    source_self=any(item.get('source')=='self' for item in observers.values())
    source_external=any(item.get('source')!='self' for item in observers.values())
    return capabilities,features,source_self,source_external


def _config_xaf_lines(sph_path, program, agent_ids=(), uses=(), observers=None):
    """Build the XAF v2 config section from the actual program requirements."""
    observers=observers or {}
    caps,features,source_self,source_external=_policy_access_v2(program,uses,observers,agent_ids,sph_path)
    out=['config {','    default-policy = 2001']
    if features:
        out += ['', '    multi {']
        out += [f'        {name}' for name in sorted(features)]
        out += ['    }']
    if observers:
        out += ['', '    observer {']
        for oid in sorted(observers,key=lambda x: int(x) if str(x).isdigit() else str(x)):
            out += [f'        {oid} {{','            watch = true','            log = true',
                    '            path = "logs"','            level = normal',
                    '            action {','                read = true','                modify = true',
                    '                create = true','                remove = true','                reorder = true',
                    '            }','        }']
        out += ['    }']
    if program is not None and program.databases:
        out += ['', '    database {','        connection {','            provider = "local"','        }','    }']
    if program is not None and (program.files or 'file' in (uses or ())):
        out += ['', '    file-system {','        allowed_path { "." }','        forbidden_path { "secrets" }',
                '        action {','            file { create read modify move copy delete }',
                '            folder { create read modify move copy delete zip-unzip }','        }','    }']
    if program is not None and (program.executes or 'execute' in (uses or ())):
        file_names=[]
        if program is not None:
            file_names=sorted({item['file'] for item in program.executes if item.get('file')})
        out += ['', '    execute {','        file {']
        out += [f'            {_xaf_quote(name)}' for name in file_names]
        out += ['        }','        command {','            // No Sophon commands are registered yet.','        }','    }']
    if agent_ids:
        out += ['', '    agent {','        permission {','            execute = true','        }',
                '        security {','            container = false','        }',
                '        timing {','            delay = 60','            timeout = 180',
                '            retry {','                duration = 1','                count = 0','            }','        }',
                '        input {','            max-token = 12000','            max-bytes = 5242880','        }',
                '        output {','            max-token = 4096','        }',
                '        connection {','            provider = "openrouter"','            model = "provider/model-id"',
                '            key = "OPENROUTER_API_KEY"','        }','    }']
    out += ['}']
    return out, caps, source_self, source_external


def _policy_xaf_lines(program, sph_path, agent_ids=(), uses=(), observers=None):
    observers=observers or {}
    caps,features,source_self,source_external=_policy_access_v2(program,uses,observers,agent_ids,sph_path)
    out=['policy {','    id = 2001']
    out += ['    access {']
    out += [f'        {name}' for name in caps]
    if observers:
        out += ['        source {',f'            self = {str(source_self).lower()}',
                f'            external = {str(source_external).lower()}','        }']
    out += ['    }','    action {','        read = true','        write = true','        modify = true',
            '        remove = true','        create = true','        reorder = true','    }','}']
    return out


def _access_block_lines(observers, databases, capabilities=(), indent='    ', blocks=()):
    """Legacy generator retained for explicit migration scaffolds."""
    names=sorted(observers or ()); aliases=sorted(databases or ())
    out=[f'{indent}access {{',f'{indent}    state',f'{indent}    multi-state']
    out += [f'{indent}    {c}' for c in capabilities]
    if names:
        out += [f'{indent}    observer {{']+[f'{indent}        {n}' for n in names]+[f'{indent}    }}']
    if aliases:
        out += [f'{indent}    database {{']+[f'{indent}        {a}' for a in aliases]+[f'{indent}    }}']
    for block in blocks or ():
        out += [f'{indent}    {block}']
    out += [f'{indent}}}']
    return '\n'.join(out)


def _capability_lines(program):
    """Legacy scaffold helper. XAF v2 uses _policy_access_v2 instead."""
    needs=_program_needs(program)
    caps=[]
    if needs['surface']: caps.append('surface')
    if needs['ask']: caps.append('ask')
    if any(c[3] for c in program.agent_calls): caps.append('input')
    return caps


def _capability_blocks(program,uses=()):
    """Legacy scaffold helper retained for v1 XAF generation."""
    blocks=[]
    if program.files or 'file' in uses:
        blocks.append('file-system {\n        allowed_path { "." }\n        forbidden_path { "secrets" }\n        action {\n            file { create read modify }\n            folder { create read }\n        }\n    }')
    if program.executes: blocks.append('execute {\n        // no Sophon commands are registered\n    }')
    return blocks


def sync_xaf(sph_path, xaf_path, uses, agent_ids, observers, databases, capabilities=()):
    """Keep existing XAF files untouched; newly-created files use render_xaf v2."""
    return xaf_path, False

# ---------------------------------------------------------------- blok semasi
# Her blogun girdileri: (anahtar, bicim, zorunlu mu). IDE bu tabloyu okur,
# boylece oneri ile dogrulayici tek kaynaktan beslenir ve kopyalanmaz.
# Bicimler: kv `key = deger`, bare `key deger`, block `key { ... }`,
#           whole tam metin, target `state = <ad>`, choice ilk alternatif,
#           alias `<ad> {`, bare-statement tek satirlik deyim.
# `choice` turundeki bloklarin alternatif sirasi (yoksa bos).

# Blok girdileri: (anahtar, bicim, zorunlu mu).

# Dogrulayiciya acik ozet: zorunlu, opsiyonel, alternatifler.

# Ayar degerlerinin Sophon metni olarak ornekleri.

# Adi baslikta tasinan bildirimler.

# `key deger` bicimindeki cumleler.

# Ic ice bloklar: `key { ... }`.

# `choice` bicimi: blogun ilk alternatifi.

# Icerik parcasi: parantezleri ebeveyn blogu verir.

# Yalnizca baska bir blogun icinde gecerli olanlar.














def render_xaf(sph_path, program, agent_ids=(), uses=None, connect_target=None, observers=None, databases=None):
    """Return a complete XAF v2 scaffold. Existing XAF files are never overwritten."""
    uses=uses or []
    observers=observers or {}
    # A string Agent id is a legacy identifier. Keep the v1 scaffold for it so
    # older projects remain migratable; numeric ids always use the v2 schema.
    if any(not str(aid).isdigit() for aid in agent_ids) or any(not str(oid).isdigit() for oid in observers):
        n=chr(10)
        legacy=('// Legacy XAF scaffold; migrate Agent ids to integers for XAF v2.\n'
                'policy '+sph_path.name+' {\n'+_access_block_lines(observers,_db_aliases(databases),_capability_lines(program),
                    blocks=_capability_blocks(program,uses))+'\n    action { read = true write = true modify = true remove = true create = true reorder = true }\n}\n')
        blocks=[]
        for aid in agent_ids:
            blocks.append(f'agent {aid} {{\n    name = "{aid}"\n    policy = "{sph_path.name}"\n    execute = true\n    container = false\n    delay = 60\n    api-key {{ provider = "openrouter" model = "provider/model-id" key = "OPENROUTER_API_KEY" }}\n}}')
        return legacy,blocks
    config_lines,caps,source_self,source_external=_config_xaf_lines(sph_path,program,agent_ids,uses,observers)
    out=['// Automatically generated XAF v2 scaffold. Review and narrow permissions.']+config_lines+['']
    for aid in agent_ids:
        out += ['agent {',f'    id = {int(aid)}',f'    name = "Agent {int(aid)}"',
                '    policy = 2001','}']
        out += ['']
    out += _policy_xaf_lines(program,sph_path,agent_ids,uses,observers)
    return '\n'.join(out).rstrip()+'\n',[]


def _access_report(access):
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in access.items()}


def scaffold_report(sph_path, program, settings=None):
    """What the connected XAF should contain, and what the program still needs.

    Writes nothing. The editor renders this beside the program as it is typed, so a
    missing grant is visible before anything is run.
    """
    policy, blocks = render_xaf(sph_path, program, program.agent_connects, program.uses,
                               program.connect, program.observers, program.databases)
    surfaces = any(r['kind'] == 'surface' for r in program.renders)
    for r in program.renders:
        if r['kind'] == 'component':
            for box in r['boxes']:
                if any(s['kind'] == 'surface' for s in box.get('steps', [])):
                    surfaces = True
    needed = []
    if surfaces:
        needed.append({'capability': 'surface', 'code': 'X040', 'why': 'the program surfaces state'})
    if program.asks:
        needed.append({'capability': 'ask', 'code': 'X041', 'why': f'the program asks {len(program.asks)} question(s)'})
    if program.files:
        needed.append({'capability': 'file-system', 'code': 'X050', 'why': f'the program runs {len(program.files)} file operation(s)'})
    if program.executes:
        needed.append({'capability': 'execute', 'code': 'X053', 'why': f'the program executes {len(program.executes)} time(s)'})
    if any(c[3] for c in program.agent_calls):
        needed.append({'capability': 'input', 'code': 'X042', 'why': 'the program attaches input files'})
    # The governing policy is the agent's when one is connected, else the file's own name,
    # matching _program_policies.
    agents = (settings or {}).get('agents', {})
    names = [agents[a]['policy'] for a in program.agent_connects if a in agents]
    if not names:
        names = [sph_path.name]
    granted = []
    for name in names:
        pol = (settings or {}).get('resolved_policies', {}).get(name)
        if pol:
            granted.append({'policy': name, 'access': _access_report(pol['access']), 'action': pol['action']})
    missing = [n for n in needed
               if not any(g['access'].get(n['capability']) is True for g in granted)]
    return {'policy': policy, 'blocks': blocks, 'needed': needed, 'missing': missing, 'granted': granted}


def generate_xaf(sph_path, program, agent_ids=(), uses=None, connect_target=None, observers=None, databases=None):
    uses=uses or []
    observers=observers or {}
    databases=databases or []
    x=sph_path.with_suffix('.xaf') if not connect_target else (sph_path.parent/connect_target)
    if x.exists():
        return sync_xaf(sph_path,x,uses,agent_ids,observers,databases,_capability_lines(program))
    content,_blocks=render_xaf(sph_path,program,agent_ids,uses,connect_target,observers,databases)
    x.parent.mkdir(parents=True,exist_ok=True)
    x.write_text(content,encoding='utf-8')
    return x,True

# ---------------------------------------------------------------- blok semasi
# Her blogun girdileri: (anahtar, bicim, zorunlu mu). IDE bu tabloyu okur,
# boylece oneri ile dogrulayici tek kaynaktan beslenir ve kopyalanmaz.
# Bicimler: kv `key = deger`, bare `key deger`, block `key { ... }`,
#           whole tam metin, target `state = <ad>`, choice ilk alternatif,
#           alias `<ad> {`, bare-statement tek satirlik deyim.
# `choice` turundeki bloklarin alternatif sirasi (yoksa bos).
ALT_LISTS = {
    'use': ['module', 'name from module'],
    'form': ['surface', 'ask', 'multi-ask', 'confirmation', 'multi-confirmation'],
    'component': ['form', 'note', 'list', 'table'],
    'file': ['create', 'write', 'append', 'read', 'list', 'delete', 'copy', 'move', 'mkdir', 'zip', 'unzip'],
    'database': ['read', 'write', 'modify', 'remove'],
    'execute': ['file', 'command'],
}

# Blok girdileri: (anahtar, bicim, zorunlu mu).
SCHEMA = {
    'function': [('id', 'whole', 1)],
    'ask': [
        ('id', 'kv', 1),
        ('prompt', 'kv', 1),
        ('target', 'target', 1),
        ('suggestion', 'kv', 0),
        ('type', 'kv', 0),
        ('default', 'kv', 0),
        ('secret', 'kv', 0),
        ('requirement', 'kv', 0),
        ('duration', 'kv', 0),
    ],
    'multi-ask': [
        ('id', 'kv', 1),
        ('ask', 'block', 1),
    ],
    'confirmation': [
        ('id', 'kv', 1),
        ('prompt', 'kv', 1),
        ('choice', 'block', 1),
        ('target', 'target', 1),
        ('requirement', 'kv', 0),
        ('multiple-selection', 'kv', 0),
        ('min-selection', 'kv', 0),
        ('max-selection', 'kv', 0),
        ('default', 'kv', 0),
    ],
    'multi-confirmation': [
        ('id', 'kv', 1),
        ('confirmation', 'block', 1),
    ],
    'observer': [
        ('id', 'kv', 1),
        ('description', 'kv', 0),
        ('source', 'kv', 1),
        ('watch', 'block', 1),
    ],
    'multi-observer': [
        ('id', 'kv', 1),
        ('observer', 'block', 1),
    ],
    'database': [
        ('alias', 'alias', 1),
        ('connect', 'kv', 1),
        ('op', 'choice', 1),
    ],
    'file': [
        ('id', 'kv', 0),
        ('op', 'choice', 1),
    ],
    'execute': [
        ('one-of', 'choice', 1),
    ],
    'component': [
        ('id', 'kv', 0),
        ('one-of', 'choice', 1),
    ],
    'form': [
        ('id', 'kv', 0),
        ('title', 'kv', 0),
        ('width', 'kv', 0),
        ('one-of', 'choice', 1),
    ],
    'note': [
        ('text', 'kv', 1),
        ('id', 'kv', 0),
        ('title', 'kv', 0),
        ('width', 'kv', 0),
    ],
    'list': [
        ('item', 'kv', 1),
        ('id', 'kv', 0),
        ('title', 'kv', 0),
        ('width', 'kv', 0),
    ],
    'table': [
        ('row', 'bare', 1),
        ('id', 'kv', 0),
        ('title', 'kv', 0),
        ('width', 'kv', 0),
    ],
    'use': [
        ('one-of', 'choice', 1),
    ],
    'state': [
        ('whole', 'whole', 1),
    ],
    'multi-state': [
        ('whole', 'whole', 1),
    ],
    'surface': [
        ('item', 'bare', 1),
    ],
    'connect': [
        ('whole', 'whole', 1),
    ],
    'choice': [
        ('option', 'bare', 1),
    ],
    'input': [
        ('file', 'kv', 1),
    ],
}

# Dogrulayiciya acik ozet: zorunlu, opsiyonel, alternatifler.
BLOCK_SCHEMA = {
    'ask': {'required': ['id', 'prompt', 'target'], 'optional': ['suggestion', 'type', 'default', 'secret', 'requirement', 'duration']},
    'multi-ask': {'required': ['id', 'ask'], 'optional': []},
    'confirmation': {'required': ['id', 'prompt', 'choice', 'target'], 'optional': ['requirement', 'default', 'multiple-selection', 'min-selection', 'max-selection']},
    'multi-confirmation': {'required': ['id', 'confirmation'], 'optional': []},
    'observer': {'required': ['id', 'source', 'watch'], 'optional': ['description']},
    'multi-observer': {'required': ['id', 'observer'], 'optional': []},
    'database': {'required': ['alias', 'connect', 'op'], 'optional': [], 'alternatives': ['read', 'write', 'modify', 'remove']},
    'file': {'required': ['op'], 'optional': ['id'], 'alternatives': ['create', 'write', 'append', 'read', 'list', 'delete', 'copy', 'move', 'mkdir', 'zip', 'unzip']},
    'execute': {'required': ['one-of'], 'optional': [], 'alternatives': ['file', 'command']},
    'component': {'required': ['one-of'], 'optional': ['id'], 'alternatives': ['form', 'note', 'list', 'table']},
    'form': {'required': ['one-of'], 'optional': ['id', 'title', 'width'], 'alternatives': ['surface', 'ask', 'multi-ask', 'confirmation', 'multi-confirmation']},
    'note': {'required': ['text'], 'optional': ['id', 'title', 'width']},
    'list': {'required': ['item'], 'optional': ['id', 'title', 'width']},
    'table': {'required': ['row'], 'optional': ['id', 'title', 'width']},
    'use': {'required': ['one-of'], 'optional': [], 'alternatives': ['module', 'name from module']},
    'state': {'required': ['whole'], 'optional': []},
    'multi-state': {'required': ['whole'], 'optional': []},
    'surface': {'required': ['item'], 'optional': []},
    'connect': {'required': ['whole'], 'optional': []},
    'choice': {'required': ['option'], 'optional': []},
    'input': {'required': ['file'], 'optional': []},
}

# Ayar degerlerinin Sophon metni olarak ornekleri.
SETTINGS = {
    'id': '"etiket"',
    'prompt': '"Sorunuz?"',
    'suggestion': '"Ipucu"',
    'type': '"text"',
    'default': '"evet"',
    'secret': 'true',
    'state': 'hedef',
    'description': '"Aciklama"',
    'requirement': 'true',
    'duration': '30',
    'multiple-selection': 'false',
    'min-selection': '1',
    'max-selection': '1',
    'connect': 'vault.svt',
    'title': '"Baslik"',
    'width': '60',
    'text': '"metin"',
    'item': '"oge"',
    'file': '"program.sph"',
    'path': '"kaynak.xaf"',
    'source': '"kaynak.sph"',
    'value': '"deger"',
    'name': '"adim"',
    'alias': 'depo',
}

# Adi baslikta tasinan bildirimler.
WHOLE_STATEMENT = {
    'state': 'state adim = "deger"',
    'multi-state': 'multi-state {\n    id = "adim"\n    state {\n        alan = 1\n        diger = 2\n    }\n}',
    'connect': 'connect to kaynak.xaf',
    'function': 'function {\n    id = \"calculate\"\n    input { value: integer }\n    execute { state result = value }\n    output: integer = result\n}',
}

# `key deger` bicimindeki cumleler.
BARE_STATEMENT = {
    ('table', 'row'): 'row "a" "b"',
    ('surface', 'item'): 'ad',
    ('choice', 'option'): '"evet" "hayir"',
}

# Ic ice bloklar: `key { ... }`.
NESTED_BLOCK = {
    ('multi-ask', 'ask'): '{\n    id = "s1"\n    prompt = "?"\n    state = hedef\n}',
    ('confirmation', 'choice'): '{\n    evet = true\n    hayir = false\n}',
    ('multi-confirmation', 'confirmation'): '{\n    id = "c"\n    prompt = "?"\n    choice { evet = true hayir = false }\n    state sonuc\n    requirement = true\n}',
    ('multi-observer', 'observer'): '{\n    id = "gozlemci"\n    source = self\n    watch { hedef }\n}',
    ('observer', 'watch'): '{ hedef }',
}

# `choice` bicimi: blogun ilk alternatifi.
FIRST_ALTERNATIVE = {
    'database': ('read', 'read { id = 1 }'),
    'file': ('create', 'create { path = "yeni.txt" }'),
    'execute': ('file', 'file = "program.sph"'),
    'component': ('form', 'form { title = "Baslik" surface { metin } }'),
    'form': ('surface', 'surface { metin }'),
    'use': ('module', 'database'),
}

# Icerik parcasi: parantezleri ebeveyn blogu verir.
BLOCK_FRAGMENT = ('choice',)

# Yalnizca baska bir blogun icinde gecerli olanlar.
BLOCK_NESTED_ONLY = ('input',)


def render_block(keyword, schema=None):
    """One block filled with every setting it requires, as parseable Sophon source.

    The schema drives the shape, so a skeleton cannot drift from what the validator
    actually demands. The editor offers exactly this text.
    """
    entries = SCHEMA.get(keyword) if schema is None else schema
    if entries is None or keyword in BLOCK_FRAGMENT and keyword not in ('choice',):
        if entries is None:
            return None
    if keyword in BLOCK_NESTED_ONLY:
        return None
    out = []
    for key, style, _req in entries:
        if style == 'whole':
            return WHOLE_STATEMENT[keyword]
        if style == 'bare-statement':
            return BARE_STATEMENT[(keyword, key)]
        if style == 'alias':
            out.append(f'{keyword} {SETTINGS["alias"]} {{')
            continue
        if style == 'target':
            out.append(f'    state = {SETTINGS["state"]}')
        elif style == 'choice':
            out.append('    ' + FIRST_ALTERNATIVE[keyword][1])
        elif style == 'bare':
            out.append('    ' + BARE_STATEMENT[(keyword, key)])
        elif style == 'block':
            out.append(f'    {key} {NESTED_BLOCK[(keyword, key)]}')
        else:
            out.append(f'    {key} = {SETTINGS[key]}')
    body = chr(10).join(out)
    if keyword in BLOCK_FRAGMENT:
        return body
    if out and out[0].endswith('{'):
        return body + chr(10) + '}'
    return f'{keyword} {{' + chr(10) + body + chr(10) + '}'




def block_grammar():
    """Block schema plus a ready skeleton per block, for the editor's completion."""
    blocks = {}
    for kw, entries in SCHEMA.items():
        blocks[kw] = {
            'required': [k for k, _s, r in entries if r],
            'optional': [k for k, _s, r in entries if not r],
            'alternatives': ALT_LISTS.get(kw, []),
            'nestedOnly': kw in BLOCK_NESTED_ONLY,
            'skeleton': None if kw in BLOCK_NESTED_ONLY else render_block(kw),
        }
    return {'blocks': blocks, 'settings': dict(SETTINGS)}




BLOCK_PROGRAM = {
    'ask': 'state hedef = 1\n',
    'confirmation': 'state sonuc = 1\n',
    'multi-confirmation': 'state sonuc = 1\n',
    'multi-ask': 'state hedef = 1\n',
    'observer': 'use { observer }\nstate hedef = 1\nstate diger = 2\n',
    'multi-observer': 'use { multi-observer }\nstate hedef = 1\n',
    'note': 'use { note from component }\n',
    'list': 'use { list from component }\n',
    'table': 'use { table from component }\n',
    'database': 'use { database }\n',
    'file': 'use { file }\n',
    'execute': 'use { execute }\n',
    'component': 'use { component }\n',
    'form': 'use { component }\nstate metin = 1\n',
    'surface': '',
    'state': '',
    'multi-state': '',
    'use': '',
    'function': '',
}


def check_block_skeletons(tmpdir=None):
    """Parse a minimal program per block from the schema's own skeleton.

    Returns [(keyword, code, message), ...] for every skeleton that does not parse.
    This is the guard that keeps the completion table and the validator agreeing.
    """
    import tempfile as _tf
    from pathlib import Path as _P
    d = _P(tmpdir) if tmpdir else _P(_tf.mkdtemp())
    bad = []
    for keyword, prefix in BLOCK_PROGRAM.items():
        skel = render_block(keyword)
        if skel is None:
            continue
        f = d / f'{keyword}.sph'
        f.write_text(prefix + skel)
        try:
            parse_sph(f)
        except SophonError as e:
            bad.append((keyword, e.code, e.message))
    return bad


def _svt_parse_value(v,path=None,line=None,raw=None):
    v=v.strip()
    if v.startswith('[') and v.endswith(']'):
        return [_svt_parse_value(x,path,line,raw) for x in _list_tokens(v[1:-1],path,line,raw,'V011') if x.strip()]
    if v=='null': return None
    if v=='true': return True
    if v=='false': return False
    if len(v)>=2 and v[0]=='"' and v[-1]=='"': return json.loads(v)
    if re.fullmatch(r'-?\d+',v): return int(v)
    if re.fullmatch(r'-?(?:\d+\.\d*|\d*\.\d+)',v): return float(v)
    raise SophonError('V011',f'Invalid Sophon Vault value: {v}',getattr(path,'name',path),line,1,raw,
                      'Use null, true, false, a quoted string, a number, or a list.')

def parse_svt(path):
    """Parse one vault with strict nesting and primary-key validation."""
    lines=_read_source(path); path=Path(path)
    records=[]; saw_vault=False; inside_vault=False; current=None; record_line=1; ids=set()
    for i,raw in enumerate(lines):
        x=strip_comment(raw).strip(); n=i+1
        if not x: continue
        if re.fullmatch(r'vault(?:\s+"[^"]+")?\s*\{',x):
            if saw_vault or inside_vault or current is not None:
                raise SophonError('V003','A Sophon Vault may contain only one root vault block.',path.name,n,1,raw,
                                  'Keep one vault { ... } block at the top level.')
            saw_vault=True; inside_vault=True; continue
        if x=='record {':
            if not inside_vault or current is not None:
                raise SophonError('V003','record blocks must be direct children of vault.',path.name,n,1,raw,
                                  'Place record { ... } inside the open vault { ... } block.')
            current={}; record_line=n; continue
        if x=='}':
            if current is not None:
                if 'id' in current:
                    key=(type(current['id']).__name__,json.dumps(current['id'],sort_keys=True,ensure_ascii=False))
                    if key in ids:
                        raise SophonError('V014',f'Duplicate Vault record id {current["id"]}.',path.name,record_line,1,None,
                                          'Every record id must be unique; change or remove the duplicate record.')
                    ids.add(key)
                records.append(current); current=None; continue
            if inside_vault:
                inside_vault=False; continue
            raise SophonError('V003','Unexpected closing brace in Sophon Vault.',path.name,n,1,raw,
                              'Remove the unmatched closing brace.')
        if current is None:
            raise SophonError('V003','Vault fields and records must be inside vault { ... }.',path.name,n,1,raw,
                              'Use vault { record { field = value } }.')
        m=re.fullmatch(r'([A-Za-z_][\w]*)\s*=\s*(.+)$',x)
        if not m:
            raise SophonError('V001','Invalid SVT record field.',path.name,n,1,raw,'Use field = value.')
        key,value=m.groups()
        if key in current:
            raise SophonError('V013',f'Duplicate SVT record field "{key}".',path.name,n,1,raw,
                              'Declare each field once in a record.')
        current[key]=_svt_parse_value(value,path,n,raw)
    if current is not None:
        raise SophonError('V002','Unclosed SVT record.',path.name,record_line,1,None,"Add the closing '}'.")
    if inside_vault:
        raise SophonError('V002','Unclosed Sophon Vault block.',path.name,len(lines) or 1,1,None,"Add the closing '}'.")
    if not saw_vault:
        raise SophonError('V004','SVT file must contain a vault block.',path.name,1,1,None,'Start with: vault {')
    return records

def write_svt(path,records):
    """Persist a vault atomically so interruption cannot truncate the live file."""
    import tempfile, stat
    path=Path(path)
    out=['vault {']
    for rec in records:
        out.append('    record {')
        for k,v in rec.items():
            if isinstance(v,(str,list)): q=_format_source(v)
            elif v is None: q='null'
            elif v is True: q='true'
            elif v is False: q='false'
            else: q=str(v)
            out.append(f'        {k} = {q}')
        out.append('    }')
    out.append('}')
    payload='\n'.join(out)+'\n'
    temporary=None
    try:
        original_mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else None
        fd,temporary=tempfile.mkstemp(prefix=f'.{path.name}.',suffix='.tmp',dir=str(path.parent))
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if original_mode is not None:
            os.chmod(temporary,original_mode)
        os.replace(temporary,path)
        temporary=None
    except OSError as exc:
        detail=getattr(exc,'strerror',None) or str(exc)
        raise SophonError('V015',f'Could not save Sophon Vault "{path.name}": {detail}.',path.name,1,1,None,
                          'Check write permissions and available disk space; the previous vault file was left unchanged.')
    finally:
        if temporary:
            try: os.unlink(temporary)
            except OSError: pass

def _db_find(records,criteria):
    return [idx for idx,r in enumerate(records) if all(r.get(k)==v for k,v in criteria.items())]

def _grants(granted,name):
    """True when a policy access value covers a named resource.

    `True` is the bare-form grant for every resource of that kind; a set grants only
    the names it lists.
    """
    return granted is True or name in granted

def execute_databases(sph,databases,settings,agent_ids,program=None):
    for db in databases:
        if not db['connect']: raise SophonError('S147',f'Database "{db["alias"]}" has no connection.',sph.name,1,1,None,'Use connect = users.svt.')
        policies=_program_policies(sph,settings,agent_ids)
        # Database connections are project-scoped just like file and Agent inputs.
        path=_contained(sph.parent.resolve(),db['connect'])
        if not path.exists(): raise SophonError('V005',f'Sophon Vault "{db["connect"]}" was not found.',sph.name,1,1,None,'Create the .svt file or correct the connection.')
        db_config=settings.get('config',{}).get('database',{})
        byte_limit=db_config.get('max-bytes')
        if byte_limit is not None and path.stat().st_size>byte_limit:
            raise SophonError('V011',f'SVT file "{db["connect"]}" exceeds config.database.max-bytes.',sph.name,1,1,None,
                              'Increase max-bytes or reduce the vault file size.')
        records=parse_svt(path)
        for action,data,line,output_state in db['ops']:
            if not all(_grants(p['access'].get('database'),db['alias']) for p in policies):
                raise SophonError('X026',f'Database access denied for "{db["alias"]}".',sph.name,line,1,None,'Grant database access in the agent policy.')
            if not all(p['action'].get(action) is True for p in policies):
                raise SophonError('X027',f'Database action "{action}" denied for "{db["alias"]}".',sph.name,line,1,None,'Enable the action in the agent policy.')
            if action=='read':
                matches=_db_find(records,data)
                if output_state and program is not None:
                    program.states[output_state]=[dict(records[idx]) for idx in matches]
            elif action=='write':
                if 'id' not in data:
                    raise SophonError('V008','Database write requires an id.',sph.name,line,1,None,'Add id = <record id>. A record without an id can never be modified or removed.')
                if _db_find(records,{'id':data['id']}):
                    raise SophonError('V009',f'Database write duplicates existing id {data["id"]}.',sph.name,line,1,None,'Use modify to change an existing record, or write a different id.')
                records.append(dict(data))
            elif action=='modify':
                matches=_db_find(records,{k:v for k,v in data.items() if k=='id'}) if 'id' in data else []
                if not matches: raise SophonError('V006','Database modify requires a matching id record.',sph.name,line,1,None,'Provide id = <record id>.')
                if len(matches)>1: raise SophonError('V010',f'Database modify matched {len(matches)} records for id {data["id"]}.',sph.name,line,1,None,'Vault ids must be unique. Remove the duplicate records first.')
                for idx in matches: records[idx].update({k:v for k,v in data.items() if k!='id'})
            elif action=='remove':
                matches=_db_find(records,{k:v for k,v in data.items() if k=='id'}) if 'id' in data else []
                if not matches: raise SophonError('V007','Database remove requires a matching id record.',sph.name,line,1,None,'Provide id = <record id>.')
                records=[r for i,r in enumerate(records) if i not in matches]
        max_records=db_config.get('max-records')
        if max_records is not None and len(records)>max_records:
            raise SophonError('V012',f'Vault record count {len(records)} exceeds max-records = {max_records}.',sph.name,1,1,None,
                              'Increase config.database.max-records or remove records.')
        if db['ops'] and any(a in ('write','modify','remove') for a,_,_,_ in db['ops']):
            if byte_limit is not None:
                preview=['vault {']
                for rec in records:
                    preview.append('    record {')
                    for k,v in rec.items():
                        q=_format_source(v) if isinstance(v,(str,list)) else ('null' if v is None else 'true' if v is True else 'false' if v is False else str(v))
                        preview.append(f'        {k} = {q}')
                    preview.append('    }')
                preview.append('}')
                if len(('\n'.join(preview)+'\n').encode('utf-8'))>byte_limit:
                    raise SophonError('V011','Updated SVT data would exceed config.database.max-bytes.',sph.name,1,1,None,
                                      'Increase max-bytes or reduce the amount of stored data.')
            write_svt(path,records)

def snapshot_value(states,groups,selected):
    if any(k=='all' for k,_ in selected): return {'states':dict(states),'multi-state':{k:dict(v) for k,v in groups.items()}}
    out={'states':{},'multi-state':{}}
    for kind,res in selected:
        if kind=='state' and res in states: out['states'][res]=states[res]
        elif kind=='multi-state' and '.' in res:
            g,f=res.split('.',1)
            if g in groups and f in groups[g]: out['multi-state'].setdefault(g,{})[f]=groups[g][f]
        elif kind=='multi-state' and res in groups: out['multi-state'][res]=dict(groups[res])
        elif kind=='multi-state-view':
            # Merge, do not clobber: a full record and a view of the same group must
            # both survive into the snapshot.
            g,fs=res; out['multi-state'].setdefault(g,{}).update({f:parse_literal_for_log(v) for f,v,_ in fs})
        elif kind=='state-view': out['states'][res[0]]=parse_literal_for_log(res[1])
    return out

def parse_literal_for_log(v):
    v=v.strip()
    if v.startswith('[') and v.endswith(']'):
        return [_literal_log_value(x) for x in _list_tokens(v[1:-1],None,1,None,'S214') if x.strip()]
    return _literal_log_value(v)

def _literal_log_value(v):
    v=v.strip()
    if v=='null': return None
    if v=='true': return True
    if v=='false': return False
    if len(v)>=2 and v[0]=='"' and v[-1]=='"': return v[1:-1]
    try: return float(v) if '.' in v else int(v)
    except ValueError: return v

def diff_snapshot(old,new,prefix=''):
    changes=[]
    if isinstance(old,dict) and isinstance(new,dict):
        if set(old)==set(new) and list(old)!=list(new):
            changes.append({'path':prefix or '$','type':'reordered','old':list(old),'new':list(new)})
        for k in sorted(set(old)|set(new)):
            p=f'{prefix}.{k}' if prefix else k
            if k not in old: changes.append({'path':p,'type':'created','old':None,'new':new[k]})
            elif k not in new: changes.append({'path':p,'type':'removed','old':old[k],'new':None})
            else: changes.extend(diff_snapshot(old[k],new[k],p))
    elif old != new: changes.append({'path':prefix,'type':'modified','old':old,'new':new})
    return changes

def _snapshot_file(base,observer): return Path(base)/f'{re.sub(r"[^A-Za-z0-9_.-]","_",str(observer))}.json'
def _log_file(base): p=Path(base); p.mkdir(parents=True,exist_ok=True); return p/f'{date.today().isoformat()}.json'

_LOG_ROWS={}

def _load_log_rows(fp):
    key=str(fp)
    if key in _LOG_ROWS: return _LOG_ROWS[key]
    rows=[]
    if fp.exists():
        try:
            rows=json.loads(fp.read_text(encoding='utf-8'))
            if not isinstance(rows,list): raise ValueError('log root is not a list')
        except (ValueError,OSError) as e:
            _quarantine(fp,'W001',f'Observation log is unreadable ({e}); its history was not recorded this run.')
            rows=[]
    _LOG_ROWS[key]=rows; return rows

def write_json_log(base,observer,source,event,snapshot,old,changes,level,action='read'):
    entry={'timestamp':datetime.now().astimezone().isoformat(timespec='seconds'),'event':event,'action':action,'source':source.name,'observer':observer,'level':level}
    if LOG_LEVEL_RANK[level] >= LOG_LEVEL_RANK['normal']: entry['changes']=changes; entry['snapshot']=snapshot
    if LOG_LEVEL_RANK[level] >= LOG_LEVEL_RANK['detailed']: entry['previous_snapshot']=old
    if level=='debug': entry['runtime']={'python':sys.version.split()[0],'cwd':str(Path.cwd()),'log_format':'json','schema':'sophon-observation/v1'}
    fp=_log_file(Path(base)); rows=_load_log_rows(fp)
    rows.append(entry); fp.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8'); return fp

def _read_snapshot(sf):
    if not sf.exists(): return None
    try:
        data=json.loads(sf.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or 'states' not in data: raise ValueError('snapshot is not an observation')
        return data
    except (ValueError,OSError) as e:
        _quarantine(sf,'W002',f'Observation snapshot is unreadable ({e}); the next entry is recorded as initial, not as a diff.')
        return None

def record_snapshot(snapshot_dir,log_dir,observer,source,snapshot,cfg):
    """Persist one observation: snapshot file, then daily JSON log when the policy allows it."""
    sf=_snapshot_file(snapshot_dir,observer); old=_read_snapshot(sf)
    changes=diff_snapshot(old,snapshot) if old is not None else [{'path':'$','type':'initial','old':None,'new':snapshot}]
    sf.parent.mkdir(parents=True,exist_ok=True); sf.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    if cfg['watch'] and cfg['log'] and cfg['actions'].get('read') is True:
        action_for_type={'initial':'create','created':'create','removed':'remove','modified':'modify','reordered':'reorder'}
        filtered=[change for change in changes
                  if cfg['actions'].get(action_for_type.get(change.get('type'),'read')) is True]
        return write_json_log(log_dir,observer,source,'snapshot',snapshot,old,filtered,cfg['level'],'read')
    return None

def process_observation(source,program,observer,selected,cfg):
    snap=snapshot_value(program.states,program.groups,selected)
    root=source.parent.resolve()
    snapshot_dir=_contained(root,'.sophon/snapshots')
    log_dir=_contained(root,cfg['path']) if cfg.get('path') else root/'logs'
    return record_snapshot(snapshot_dir,log_dir,observer,source,snap,cfg)



DEFAULT_MAX_INPUT_BYTES = 5 * 1024 * 1024
_IMAGE_TYPES={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg',
              '.gif':'image/gif','.webp':'image/webp'}

def _load_attachments(agent,files,sph_path,policy,settings=None):
    """Resolve, validate and encode agent input files. Returns a content-parts list."""
    import base64
    limit=agent.get('input',{}).get('max-bytes',DEFAULT_MAX_INPUT_BYTES)
    root=sph_path.parent.resolve()
    parts=[]
    for name in files:
        path=(root/name)
        try: resolved=path.resolve()
        except OSError:
            raise SophonError('F001',f'Agent input path "{name}" could not be resolved.',sph_path.name,1,1,None,'Check the path.')
        if resolved!=root and root not in resolved.parents:
            raise SophonError('F002',f'Agent input "{name}" is outside the project directory.',sph_path.name,1,1,None,
                              'Agent input may only read files inside the project directory.')
        if not resolved.is_file():
            raise SophonError('F003',f'Agent input file "{name}" was not found.',sph_path.name,1,1,None,'Check the path.')
        size=resolved.stat().st_size
        if size>limit:
            raise SophonError('F004',f'Agent input "{name}" is {size} bytes, over the {limit} byte limit.',sph_path.name,1,1,None,
                              'Raise input { max-bytes = N } in XAF or attach a smaller file.')
        if policy.get('schema_version')!=2:
            if policy['access'].get('input') is not True:
                raise SophonError('A042',f'Agent input is denied by policy for "{name}".',sph_path.name,1,1,None,
                                  'Legacy policies require input in access; XAF v2 controls this through file-system access.')
        else:
            _fs_grant(policy['access'],'file','read',[resolved],root,1,
                      config_fs=(settings or {}).get('config',{}).get('file-system'),
                      policy_actions=policy.get('action',{}),v2=True,operation='read')
        raw=resolved.read_bytes()
        mime=_IMAGE_TYPES.get(resolved.suffix.lower())
        if mime:
            parts.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,{base64.b64encode(raw).decode()}'}})
        else:
            try: text=raw.decode('utf-8')
            except UnicodeDecodeError:
                raise SophonError('F005',f'Agent input "{name}" is neither a known image nor UTF-8 text.',sph_path.name,1,1,None,
                                  f'Attach a text file or one of: {", ".join(sorted(_IMAGE_TYPES))}.')
            parts.append({'type':'text','text':f'--- {name} ---\n{text}'})
    return parts

def _build_user_message(message,parts):
    if not parts: return message
    return [{'type':'text','text':message}]+parts


def _estimate_input_tokens(text):
    """Conservative, tokenizer-independent estimate for text-only input limits."""
    raw=str(text).encode('utf-8')
    return (len(raw)+2)//3

def _agent_api_call(agent, message, sph_path, policy=None, files=(), timeout=None, mode='run', settings=None):
    import urllib.request, urllib.error
    connection=agent.get('connection') or agent.get('api-key',{})
    provider=connection.get('provider','')
    model=connection.get('model','')
    env_name=connection.get('key','OPENROUTER_API_KEY')
    if provider!='openrouter': raise SophonError('A020',f'Unsupported agent provider "{provider}".','')
    if not model or model=='model-id': raise SophonError('A022','Agent model is not configured.','',None,None,None,'Set connection.model in XAF.')
    key=os.environ.get(env_name)
    if not key: raise SophonError('A021',f'Agent API environment variable "{env_name}" is not set.','',None,None,None,'Set the environment variable before running the agent.')
    if agent.get('security',{}).get('container',agent.get('container',False)):
        try:
            import sophon_sandbox
            return sophon_sandbox.run_agent(agent,message,sph_path,policy,files,timeout,mode,settings)
        except Exception as exc:
            if getattr(exc,'code',None):
                raise SophonError(exc.code,str(exc),getattr(exc,'file',None) or sph_path.name,
                                  getattr(exc,'line',None),1,None,getattr(exc,'hint',None)) from exc
            raise SophonError('A035',f'Agent container isolation could not be established: {exc}',sph_path.name,1,1,None,
                              'Use a Linux host with user/mount/PID/UTS/IPC/network namespaces enabled; container mode never falls back to unsandboxed execution.') from exc
    # Authorization and file safety are decided before any credential or network work.
    parts=_load_attachments(agent,files,sph_path,policy,settings) if files else []
    # AGENT.md is loaded before the user/task payload and becomes part of the immutable runtime system context.
    agent_md=_load_agent_md(sph_path)
    system=_default_agent_prompt(agent['name'],agent_md)
    if mode=='task':
        system += '\n\nInvocation mode: task. The payload is an explicit task from the Sophon program; execute it as a task within the active policy.'
    user_message=_build_user_message(message,parts)
    input_limit=agent.get('input',{}).get('max-token')
    if input_limit is not None:
        text_parts=[system]
        if isinstance(user_message,str): text_parts.append(user_message)
        elif isinstance(user_message,list):
            for part in user_message:
                if isinstance(part,dict) and part.get('type')=='text': text_parts.append(part.get('text',''))
        estimate=_estimate_input_tokens('\n'.join(text_parts))
        if estimate>input_limit:
            raise SophonError('A037',f'Agent text input is estimated at {estimate} tokens, over max-token = {input_limit}.',
                              sph_path.name,1,1,None,
                              'Shorten the prompt or increase input.max-token. Image token usage is model-dependent and is not included in this local estimate.')
    body={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user_message}]}
    max_output=agent.get('output',{}).get('max-token')
    if max_output is not None: body['max_tokens']=max_output
    req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','HTTP-Referer':'https://sophon.local','X-Title':'Sophon Agent'},method='POST')
    timing=agent.get('timing',{})
    per_attempt=float(timing.get('delay',agent.get('delay',60)))
    total_timeout=float(timeout or timing.get('timeout',per_attempt))
    retry=timing.get('retry',{})
    retry_count=int(retry.get('count',0)); retry_delay=float(retry.get('duration',0))
    deadline=time.monotonic()+total_timeout
    last_error=None
    for attempt in range(retry_count+1):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise SophonError('A024','Agent request exceeded its total timeout.','',None,None,None,
                              'Increase timing.timeout or reduce retry duration/count.')
        try:
            with urllib.request.urlopen(req,timeout=min(per_attempt,remaining)) as r:
                data=json.loads(r.read().decode())
            try: return data['choices'][0]['message']['content']
            except Exception: raise SophonError('A025','Agent provider returned no message content.','',None,None,None,'Check the model and provider response.')
        except urllib.error.HTTPError as e:
            detail=e.read().decode(errors='replace')
            last_error=SophonError('A023',f'Agent provider request failed: HTTP {e.code}.','',None,None,None,detail[:500])
            retryable=e.code in (408,409,425,429,500,502,503,504)
        except SophonError as e:
            if e.code=='A025': raise
            last_error=e; retryable=e.code=='A024'
        except Exception as e:
            last_error=SophonError('A024',f'Agent provider request failed: {e}','')
            retryable=True
        if not retryable or attempt>=retry_count: raise last_error
        remaining=deadline-time.monotonic()
        if remaining<=retry_delay:
            raise SophonError('A024','Agent request exceeded its total timeout while waiting to retry.','',None,None,None,
                              'Increase timing.timeout or reduce retry duration/count.')
        if retry_delay: time.sleep(retry_delay)
    raise last_error

def execute_agents(sph,settings,connects,calls,emit=True,program=None):
    for aid in connects:
        if aid not in settings['agents']:
            raise SophonError('A010',f'Agent "{aid}" was not found in the connected XAF.',sph.name,1,1,None,'Define the agent in XAF.')
        _policy_for_agent(settings,aid)
    connected=set(connects)
    responses=[]
    for kind,aid,payload,files,output_state in calls:
        if aid not in connected:
            raise SophonError('A011',f'Agent "{aid}" is not connected to this SPH.',sph.name,1,1,None,'Use agent connect { id = "..." } first.')
        a,policy=_policy_for_agent(settings,aid)
        if a.get('execute') is not True:
            raise SophonError('A012',f'Agent "{aid}" execution is denied by XAF.',sph.name,1,1,None,'Set execute = true for the agent.')
        if not policy['action'].get('read',False):
            code='A013' if kind=='run' else 'A030'
            raise SophonError(code,f'Agent "{aid}" cannot {kind} because its policy denies read.',sph.name,1,1,None,'Allow read in the agent policy.')
        if policy.get('schema_version')==2 and not policy['access'].get('agent'):
            raise SophonError('A036',f'Policy does not grant Agent access for "{aid}".',sph.name,1,1,None,
                              'Add agent to the policy access block.')
        response=_agent_api_call(a,payload,sph,policy,files,timeout=a.get('timing',{}).get('timeout',a.get('delay',60)),mode=kind,settings=settings)
        responses.append((kind,aid,response))
        if output_state and program is not None:
            program.states[output_state]=response
        if emit:
            print(response)
    return responses


def _observer_policy(settings, observer_id, source):
    cfg=settings['self'].get(observer_id)
    if cfg is None:
        raise SophonError('X028',f'Observer "{observer_id}" has no XAF observation configuration.',source.name,1,1,None,
                          'Add its numeric id below config.observer in XAF.')
    return cfg


def _validate_observers(sph, program, settings):
    """Validate source existence, source features, and XAF source-class grants."""
    current_feature=settings.get('features',{}).get('self-observation',False)
    for observer_id,observer in program.observers.items():
        if observer['source']=='self':
            if current_feature:
                raise SophonError('X061','Observer source = self is unavailable when features.self-observation = true.',
                                  sph.name,1,1,None,
                                  'Use an external source or remove source = self; self-observation already covers the current file.')
            source_path=sph
            source_program=program
            source_feature=current_feature
            source_kind='self'
        else:
            source_path=(sph.parent/observer['source']).resolve()
            if not source_path.exists():
                raise SophonError('O201',f'Observed source "{observer["source"]}" was not found.',sph.name,1,1,None,'Check the source path.')
            source_program=parse_sph(source_path)
            source_feature=False
            if source_program.connect:
                source_xaf=(source_path.parent/source_program.connect).resolve()
                if source_xaf.exists():
                    source_feature=parse_xaf(source_xaf).get('features',{}).get('self-observation',False)
            source_kind='external'
        if observer['self_observation'] and not source_feature:
            raise SophonError('O207','watch self-observation requires features.self-observation = true in the source file XAF.',
                              sph.name,1,1,None,
                              'Enable features { self-observation = true } in the XAF connected to the observer source.')
        cfg=_observer_policy(settings,observer_id,sph)
        policies=_program_policies(sph,settings,program.agent_connects)
        for policy in policies:
            if policy.get('schema_version')==2:
                if policy['access'].get('observer') is not True:
                    raise SophonError('X066',f'Observer access is denied for "{sph.name}".',sph.name,1,1,None,
                                      'Add observer to policy.access.')
                if policy['access'].get('source',{}).get(source_kind) is not True:
                    raise SophonError('X066',f'Observer "{observer_id}" is not permitted to observe {source_kind} sources.',
                                      sph.name,1,1,None,f'Enable access.source.{source_kind} in the governing policy.')
                if policy.get('action',{}).get('read') is not True:
                    raise SophonError('X066','Observer operation requires action.read = true in the governing policy.',
                                      sph.name,1,1,None,'Enable read in the policy action block to permit observation.')
            else:
                if not _grants(policy['access'].get('observer'),observer_id):
                    raise SophonError('X066',f'Observer access is denied for "{observer_id}".',sph.name,1,1,None,
                                      'Grant the Observer in the governing policy.')
                if not cfg.get('sources',{}).get(source_kind,False):
                    raise SophonError('X066',f'Observer "{observer_id}" is not permitted to observe {source_kind} sources.',
                                      sph.name,1,1,None,f'Enable source {{ {source_kind} = true }} in the legacy observer policy.')
        if observer['self_observation']:
            continue
        for kind,resource in observer['selected']:
            if kind=='resource':
                if resource not in source_program.states and resource not in source_program.groups:
                    raise SophonError('O208',f'Unknown watched resource "{resource}".',source_path.name,1,1,None,
                                      'Declare the state or multi-state in the source file.')
            elif kind=='multi-state':
                group,field=resource.split('.',1)
                if group not in source_program.groups or field not in source_program.groups[group]:
                    raise SophonError('O208',f'Unknown watched multi-state component "{resource}".',source_path.name,1,1,None,
                                      'Declare the multi-state and field in the source file.')

def _load_runtime(sph):
    parsed=parse_sph(sph)
    needs_xaf = bool(parsed.connect or parsed.agent_connects or parsed.databases or
                     any(module in XAF_MODULES for module in parsed.uses))
    if needs_xaf:
        generate_xaf(sph,parsed,parsed.agent_connects,parsed.uses,parsed.connect,parsed.observers,parsed.databases)
    settings={'self':{},'agents':{},'policies':{},'resolved_policies':{},'features':{'self-observation':False},
              'config':{'multi':set(),'observer':{},'database':{'connection':{'provider':'local'},'max-records':None,'max-bytes':None},
                        'file-system':None,'execute':{'files':[],'commands':[]},'agent':None,'default-policy':None},
              'schema_version':1}
    if parsed.connect:
        xp=(sph.parent/parsed.connect).resolve()
        if not xp.exists():
            raise SophonError('X006',f'Connected XAF "{parsed.connect}" was not found.',sph.name,1,1,None,'The runtime should create the connected XAF automatically; check the path and permissions.')
        settings=parse_xaf(xp)
        _validate_observers(sph, parsed, settings)
        if settings.get('schema_version')==2:
            _validate_v2_program_access(sph,parsed,settings)
        elif 'file' in parsed.uses:
            for governing in _program_policies(sph,settings,parsed.agent_connects):
                fs=governing['access'].get('file-system')
                if not isinstance(fs,dict) or not fs.get('paths'):
                    raise SophonError('X056','use { file } requires a file-system policy with allowed_path.',
                                      sph.name,1,1,None,'Add file-system { allowed_path { "data" } action { ... } } to the governing XAF policy.')
    elif any(module in XAF_MODULES for module in parsed.uses) or parsed.agent_connects or parsed.databases:
        raise SophonError('X008','This SPH uses XAF-backed features but has no XAF connection.',sph.name,1,1,None,'Add: connect to sophon.xaf')
    return parsed,settings


def _program_multi_features(sph,program):
    """Detect parsed multi constructs; string literals must never grant capabilities."""
    found=set()
    if program.groups:
        found.add('multi-state')
    if program.observer_groups:
        found.add('multi-observer')
    if any(spec.get('group') for spec in program.asks):
        found.add('multi-ask')
    if any(spec.get('multi_group') for spec in program.asks):
        found.add('multi-confirmation')
    return found


def _validate_v2_program_access(sph,program,settings):
    policies=_program_policies(sph,settings,program.agent_connects)
    def require(name,used):
        if not used: return
        if not all(policy.get('access',{}).get(name) is True for policy in policies):
            raise SophonError('X110',f'Policy access "{name}" is required by {sph.name}.',sph.name,1,1,None,
                              f'Add {name} to access {{ ... }} in every governing policy.')
    multis=_program_multi_features(sph,program)
    if multis:
        require('multi',True)
        configured=settings['config'].get('multi',set())
        missing=multis-configured
        if missing:
            raise SophonError('X111','Multi component(s) are not enabled in config: '+', '.join(sorted(missing))+'.',
                              sph.name,1,1,None,'List each used multi component inside config.multi { ... }.')
    require('observer',bool(program.observers))
    require('database',bool(program.databases))
    require('agent',bool(program.agent_connects or program.agent_calls))
    require('component',any(item.get('kind')=='component' for item in program.renders))
    require('file-system',bool(program.files or 'file' in program.uses))
    require('execute',bool(program.executes))
    if program.files or 'file' in program.uses:
        fs=settings['config'].get('file-system')
        if not isinstance(fs,dict) or not fs.get('paths'):
            raise SophonError('X112','config.file-system requires allowed_path.',sph.name,1,1,None,
                              'Add config.file-system { allowed_path { "data" } action { ... } }.')
    if program.executes:
        exe=settings['config'].get('execute',{})
        if not exe.get('files') and not exe.get('commands'):
            raise SophonError('X113','No executable files or commands are configured.',sph.name,1,1,None,
                              'Add allowed .sph files to config.execute.file { ... }. command may remain empty.')

def _program_policies(sph,settings,agent_ids):
    """Policies that govern a program: every connected agent's, else the file's own."""
    if agent_ids:
        # All declared agents must resolve; multiple declarations must not widen permissions.
        return [_policy_for_agent(settings,aid)[1] for aid in agent_ids]
    default_policy=settings.get('config',{}).get('default-policy')
    if default_policy is not None:
        return [settings['resolved_policies'][default_policy]]
    base_name=sph.name
    if base_name not in settings.get('resolved_policies',{}):
        raise SophonError('X025',f'No policy is available to authorize "{sph.name}".',sph.name,1,1,None,
                          'Define a policy for this SPH or attach an agent policy.')
    return [settings['resolved_policies'][base_name]]

def _require_capability(sph,settings,agent_ids,capability,used):
    if not used: return
    policies=_program_policies(sph,settings,agent_ids)
    # XAF v2 grants ordinary UI/input primitives by default. Only privileged
    # resource families are opt-in through the access block.
    if all(p.get('schema_version')==2 for p in policies) and capability in ('surface','ask','input'):
        return
    if not all(p['access'].get(capability) is True for p in policies):
        code='X040' if capability=='surface' else 'X041' if capability=='ask' else 'X042'
        raise SophonError(code,f'"{capability}" is denied by policy for "{sph.name}".',sph.name,1,1,None,
                          f'Add "{capability}" to the access block of the policy that governs this file.')

def execute_asks(sph,program,settings,agent_ids,stream,err):
    """Run every top-level prompt in source order. Returns the secret state names."""
    secrets=set()
    for spec in program.asks:
        if spec.get('kind')=='confirmation':
            _store_confirmation(spec,_read_confirmation(spec,stream,err),program); continue
        if spec['secret'] and spec['target']: secrets.add(spec['target'])
        value=_read_answer(spec,stream,err)
        if spec['target']: program.states[spec['target']]=value
    return secrets

def _store_confirmation(spec,answer,program):
    """Write the selected value; a skipped optional confirmation records null."""
    if spec.get('multiple'):
        program.states[spec['target']]=[spec['choices'][i][1] for i in answer]
        return
    if answer is None:
        if spec['target']: program.states[spec['target']]=None
        else:
            program.states[spec['multi'][0]]=None
            program.states[spec['multi'][1]]=None
        return
    label,value=answer
    if spec['target']: program.states[spec['target']]=value
    else:
        program.states[spec['multi'][0]]=value
        program.states[spec['multi'][1]]=label

def _choice_line(choices):
    return '  '+'  '.join(f'{n}) {lab}' for n,(lab,_) in enumerate(choices,1))

def _match_choice(choices,answer):
    if answer.isdigit():
        k=int(answer)
        if 1<=k<=len(choices): return choices[k-1]
        return None
    for entry in choices:
        if entry[0]==answer: return entry
    return None

def _confirmation_display(spec,answer):
    if answer is None: return '(skipped)'
    if spec.get('multiple'): return ' '.join(spec['choices'][i][0] for i in answer)
    return answer[0]

def _split_selection(answer):
    return [tok for tok in re.split(r'[\s,]+',answer.strip()) if tok]

def _read_multiple(spec,choices,answer,err):
    """Match a multi-token answer against the choice list. Returns picked indices or None."""
    picked=[]; bad=None
    for tok in _split_selection(answer):
        hit=_match_choice(choices,tok)
        if hit is None:
            bad=tok; break
        idx=choices.index(hit)
        if idx in picked: continue
        picked.append(idx)
    if bad is not None:
        print(f'  "{bad}" geçerli bir seçenek değil.',flush=True,file=err); return None
    lo,hi=spec['min'],spec['max']
    if not picked:
        print('  en az bir seçim yapmalısınız.',flush=True,file=err); return None
    if not lo<=len(picked)<=hi:
        print(f'  {len(picked)} seçim yapıldı, {lo}-{hi} arasında olmalı.',flush=True,file=err); return None
    return sorted(picked)

def _read_confirmation(spec,stream,err):
    label=spec['prompt']; choices=spec['choices']; attempts=0
    hint=f'  ({spec["min"]}-{spec["max"]} seçim)' if spec.get('multiple') else ''
    while True:
        print(f'{label} {_choice_line(choices)}{hint}',end='',flush=True,file=err)
        raw=stream.readline()
        if raw=='':
            if spec.get('default') is not None: return spec['default']
            if not spec['requirement']: return None
            raise SophonError('S164',f'confirmation "{spec["id"]}": input ended before an answer was given.','',None,None,None,
                              'Provide the answer on stdin.')
        answer=raw.strip()
        if not answer:
            if spec.get('default') is not None: return spec['default']
            if not spec['requirement']: return None
            print('  seçim zorunlu.',flush=True,file=err)
            attempts+=1
        elif spec.get('multiple'):
            picked=_read_multiple(spec,choices,answer,err)
            if picked is not None: return picked
            attempts+=1
        else:
            hit=_match_choice(choices,answer)
            if hit: return hit
            print(f'  "{answer}" geçerli bir seçenek değil.',flush=True,file=err)
            attempts+=1
        if attempts>ASK_RETRIES:
            raise SophonError('S165',f'confirmation "{spec["id"]}": no valid selection was given.','',None,None,None,
                              'Answer with one of the listed choices, or leave blank when requirement = false.')

def _readline_timeout(stream,duration):
    """Read one complete line before a deadline, including partially-written pipes."""
    if duration is None:
        return stream.readline()
    try:
        fd=stream.fileno()
    except (AttributeError,ValueError,OSError,TypeError):
        # In-memory streams used by tests and embedded runtimes are immediately readable.
        return stream.readline()
    deadline=time.monotonic()+duration
    chunks=bytearray()
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            return None
        try:
            ready,_,_=select.select([fd],[],[],remaining)
        except (OSError,ValueError,TypeError):
            return stream.readline()
        if not ready:
            return None
        chunk=os.read(fd,1)
        if chunk==b'':
            return chunks.decode('utf-8',errors='replace')+'\n' if chunks else ''
        if chunk in (b'\n',b'\r'):
            return chunks.decode('utf-8',errors='replace')+'\n'
        chunks.extend(chunk)


def _read_secret_timeout(stream,duration,label,err):
    """Read a hidden terminal answer with a timeout on POSIX terminals."""
    import termios, tty
    fd=stream.fileno()
    old=termios.tcgetattr(fd)
    print(label,end='',flush=True,file=err)
    chars=[]; deadline=time.monotonic()+duration
    try:
        tty.setraw(fd)
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0: return None
            ready,_,_=select.select([fd],[],[],remaining)
            if not ready: return None
            ch=os.read(fd,1)
            if ch in (b'\n',b'\r'): break
            if ch in (b'\x7f',b'\x08'):
                if chars: chars.pop()
            else: chars.append(ch)
        return b''.join(chars).decode('utf-8',errors='replace')+'\n'
    finally:
        termios.tcsetattr(fd,termios.TCSADRAIN,old)
        print('',flush=True,file=err)


def _read_answer(spec,stream,err):
    label=spec['prompt']
    if spec['suggestion']: label=f'{label} [öneri: {spec["suggestion"]}]'
    attempts=0
    while True:
        if spec['secret'] and stream is sys.stdin and sys.stdin.isatty():
            if spec.get('duration') is not None:
                line=_read_secret_timeout(stream,spec['duration'],label,err)
            else:
                import getpass
                line=getpass.getpass(f'{label} ')
        else:
            print(label,end='',flush=True,file=err)
            line=_readline_timeout(stream,spec.get('duration'))
        if line is None:
            if spec['default'] is not None: return spec['default']
            if not spec.get('requirement',False): return None
            raise SophonError('S176',f'ask "{spec["id"]}" timed out.','',None,None,None,
                              'Provide a default for a timed required ask.')
        if line=='':
            if spec['default'] is not None: return spec['default']
            if not spec.get('requirement',False): return None
            raise SophonError('S164',f'ask "{spec["id"]}": input ended before an answer was given.','',None,None,None,
                              'Provide the answer on stdin.')
        value=line.strip()
        if value=='':
            if spec['default'] is not None: return spec['default']
            if not spec.get('requirement',False): return None
            attempts+=1
        elif _answer_matches(spec['type'],value):
            return value
        else:
            attempts+=1
            print(f'  "{value}" geçerli değil, tekrar deneyin.',flush=True,file=err)
        if attempts>ASK_RETRIES:
            raise SophonError('S165',f'ask "{spec["id"]}": no valid answer was given.','',None,None,None,
                              'Use a valid value, set a default, or set requirement = false.')

def _answer_matches(kind,value):
    if kind in (None,'text'): return True
    if kind=='number':
        return bool(re.fullmatch(r'-?\d+(?:\.\d+)?',value))
    return True

FILE_OP_ACTION={'create':('file','create'),'write':('file','modify'),'append':('file','modify'),
                'read':('file','read'),'list':('folder','read'),'delete':('file','delete'),
                'copy':('file','copy'),'move':('file','move'),'mkdir':('folder','create'),
                'zip':('folder','zip-unzip'),'unzip':('folder','zip-unzip')}

def _contained(root,rel):
    """Resolve a project-relative path, refusing anything outside the project."""
    if os.path.isabs(rel):
        raise SophonError('F010',f'Path "{rel}" must be relative to the project.','',1,1,None,'Remove the leading "/".')
    try: resolved=(root/rel).resolve()
    except OSError:
        raise SophonError('F011',f'Path "{rel}" could not be resolved.','',1,1,None,'Check the path.')
    if resolved!=root and root not in resolved.parents:
        raise SophonError('F012',f'Path "{rel}" is outside the project directory.','',1,1,None,
                          'File operations may only reach inside the project directory.')
    return resolved

def _under(target,base):
    return target==base or base in target.parents

def _fs_grant(access,kind,action,resolved,root,line,config_fs=None,policy_actions=None,v2=False,operation=None):
    """Check already-resolved, already-contained paths against the policy file-system grant."""
    fs=access.get('file-system')
    if fs is None or fs is False:
        raise SophonError('X050',f'File operation "{action}" is not granted by policy.','',1,1,None,
                          'Add file-system to the access block of the governing policy.')
    if v2 or fs is True:
        fs=config_fs
        if not isinstance(fs,dict):
            raise SophonError('X056','config.file-system is not configured.','',1,1,None,
                              'Add allowed_path and action settings under config.file-system.')
    if not v2 and fs is True: return
    if action not in fs['actions'].get(kind,set()):
        raise SophonError('X051',f'File operation "{action}" is denied for {kind}.','',1,1,None,
                          f'Allow it under config.file-system action {kind} {{ ... }}.')
    if v2:
        policy_action=({'create':'create','write':'write','append':'write','read':'read','list':'read',
                        'delete':'remove','move':'modify','copy':'modify','mkdir':'create',
                        'zip':'modify','unzip':'modify'}.get(operation) if operation else
                       {'create':'create','read':'read','modify':'modify','delete':'remove',
                        'move':'modify','copy':'modify','zip-unzip':'modify'}.get(action,action))
        if (policy_actions or {}).get(policy_action) is not True:
            raise SophonError('X051',f'Policy action "{policy_action}" is denied for file operation "{action}".','',1,1,None,
                              f'Set {policy_action} = true in the governing policy action block.')
    allowed=fs['paths']
    bases=[(root/b).resolve() for b in allowed]
    forbidden=[(root/b).resolve() for b in fs.get('forbidden',[])]
    if any(_under(target,b) for target in resolved for b in forbidden):
        raise SophonError('X057','Path is inside a forbidden_path.','',1,1,None,
                          'Choose a path outside every forbidden_path entry.')
    if not all(any(_under(target,b) for b in bases) for target in resolved):
        raise SophonError('X052','Path is outside the allowed_path entries.','',1,1,None,
                          'Extend allowed_path in the file-system policy block.')

def _exec_grant(access,item,rel,root,line,config_execute=None):
    ex=access.get('execute')
    if ex is None or ex is False:
        raise SophonError('X053','Execution is not granted by policy.','',1,1,None,
                          'Add execute to the access block of the governing policy.')
    if ex is True:
        allowed=config_execute or {'files':[],'commands':[]}
        if item['file']:
            if item['file'] not in allowed.get('files',[]):
                raise SophonError('X053',f'File "{item["file"]}" is not on the execute allowlist.','',1,1,None,
                                  'Add its project-relative path to config.execute.file { ... }.')
        elif item['command'] not in allowed.get('commands',[]):
            raise SophonError('X054',f'Command "{item["command"]}" is not on the execute allowlist.','',1,1,None,
                              'Add a registered command to config.execute.command { ... }; no commands are currently registered.')
        return
    if not isinstance(ex,dict): return
    if item['file']:
        if not ex.get('file'):
            raise SophonError('X053','Executing a file is not granted by policy.','',1,1,None,'Add a bare "file" line to the execute block.')
    elif item['command'] not in ex.get('commands',[]):
        raise SophonError('X054',f'Command "{item["command"]}" is not granted by policy.','',1,1,None,
                          'List the command in the execute command block.')

def execute_runs(sph,settings,executes,depth=0):
    """Run execute blocks. A command is resolved from the Sophon command table, never a shell."""
    for item in executes:
        if depth>=EXECUTE_DEPTH_MAX:
            raise SophonError('S234',f'Execution depth limit of {EXECUTE_DEPTH_MAX} reached.',sph.name,item['line'],1,None,
                              'Remove the recursive execute chain.')
        if item['command']:
            if item['command'] not in SOPHON_COMMANDS:
                raise SophonError('S240',f'Unknown Sophon command "{item["command"]}".',sph.name,item['line'],1,None,
                                  'No Sophon commands are registered; commands are never passed to a shell.')
            SOPHON_COMMANDS[item['command']](sph)
            continue
        target=_contained(sph.parent.resolve(),item['file'])
        if not target.is_file():
            raise SophonError('S236',f'Execute file "{item["file"]}" was not found.',sph.name,item['line'],1,None,'Check the path.')
        if target.suffix!='.sph':
            raise SophonError('S236',f'Execute file "{item["file"]}" is not an SPH program.',sph.name,item['line'],1,None,'Execute runs .sph files.')
        sub_settings=parse_xaf(sph.parent/(item['file']).replace('.sph','.xaf')) if (sph.parent/(item['file']).replace('.sph','.xaf')).exists() else settings
        run(target,depth=depth+1)

def _eval_data(text,program):
    """Evaluate a file operation data expression against the current state."""
    items=_scan_operands(text,Path('file'),1,text)
    return ''.join(_eval_item(o,program.states,program.groups,set(),'file')[0] for o in items)

def _execute_files_impl(sph,program,files,settings,agent_ids):
    """Run file operations in source order under the governing policies."""
    if not files: return
    policies=_program_policies(sph,settings,agent_ids)
    root=sph.parent.resolve()
    for op in files:
        kind,action=FILE_OP_ACTION[op['op']]
        dest=None
        if op['target'] and op['target'][0]=='to': dest=_contained(root,op['target'][1])
        resolved=[_contained(root,rel) for rel in op['paths']]
        if op['op']=='delete' and resolved and resolved[0].is_dir():
            kind='folder'
        checked=resolved+([dest] if dest is not None else [])
        for pol in policies:
            _fs_grant(pol['access'],kind,action,checked,root,op['line'],
                      config_fs=settings.get('config',{}).get('file-system'),
                      policy_actions=pol.get('action',{}),v2=pol.get('schema_version')==2,operation=op['op'])
        p=op['paths'][0]
        target=resolved[0]
        if op['op']=='mkdir':
            target.mkdir(parents=True,exist_ok=True); continue
        if op['op']=='create':
            if not target.parent.is_dir():
                raise SophonError('F015',f'Parent folder for "{p}" does not exist.',sph.name,op['line'],1,None,
                                  'Create the parent folder first with mkdir.')
            if target.exists(): raise SophonError('F013',f'"{p}" already exists.',sph.name,op['line'],1,None,'Use write to replace it, or delete it first.')
            target.write_text('',encoding='utf-8'); continue
        if op['op'] in ('write','append'):
            if not target.parent.is_dir():
                raise SophonError('F015',f'Parent folder for "{p}" does not exist.',sph.name,op['line'],1,None,
                                  'Create the parent folder first with mkdir.')
            if not target.is_file():
                raise SophonError('F014',f'"{p}" does not exist as a file.',sph.name,op['line'],1,None,
                                  'Use create { path = "..." } before write or append.')
            text=_eval_data(op['data'],program)
            with target.open('a' if op['op']=='append' else 'w',encoding='utf-8') as fh: fh.write(text)
            continue
        if op['op']=='read':
            if not target.is_file(): raise SophonError('F014',f'"{p}" is not a file.',sph.name,op['line'],1,None,'Check the path.')
            program.states[op['target'][1]]=target.read_text(encoding='utf-8'); continue
        if op['op']=='list':
            if not target.is_dir(): raise SophonError('F015',f'"{p}" is not a folder.',sph.name,op['line'],1,None,'Check the path.')
            program.states[op['target'][1]]=sorted(x.name for x in target.iterdir()); continue
        if op['op']=='delete':
            if target.is_dir():
                import shutil
                shutil.rmtree(target)
            elif target.is_file(): target.unlink()
            else: raise SophonError('F014',f'"{p}" was not found.',sph.name,op['line'],1,None,'Check the path.')
            continue
        if op['op'] in ('copy','move'):
            source=resolved[0]
            if not source.is_file():
                raise SophonError('F014',f'"{op["paths"][0]}" is not a file.',sph.name,op['line'],1,None,'Check the source path.')
            if op['target'] and op['target'][0]=='state':
                raise SophonError('S223','File copy/move takes to = "path", not state.',sph.name,op['line'],1,None,'Use to for the destination path.')
            if not dest.parent.is_dir():
                raise SophonError('F015',f'Parent folder for "{dest.name}" does not exist.',sph.name,op['line'],1,None,
                                  'Create the parent folder first with mkdir.')
            if dest.exists():
                raise SophonError('F016',f'"{dest.name}" already exists.',sph.name,op['line'],1,None,
                                  'Delete the target first or choose another destination.')
            if op['op']=='copy': dest.write_bytes(source.read_bytes())
            else:
                if dest.exists():
                    raise SophonError('F016',f'"{dest.name}" already exists.',sph.name,op['line'],1,None,'Use copy, or delete the target first.')
                source.rename(dest)
            continue
        if op['op'] in ('zip','unzip'):
            import zipfile
            if op['op']=='zip':
                source=resolved[0]
                if not source.is_dir():
                    raise SophonError('F015',f'"{op["paths"][0]}" is not a folder.',sph.name,op['line'],1,None,'zip takes a folder.')
                if dest.exists():
                    raise SophonError('F016',f'"{dest.name}" already exists.',sph.name,op['line'],1,None,
                                      'Delete the archive first or choose another destination.')
                if not dest.parent.is_dir():
                    raise SophonError('F015',f'Parent folder for "{dest.name}" does not exist.',sph.name,op['line'],1,None,
                                      'Create the parent folder first with mkdir.')
                archive_items=sorted(source.rglob('*'))
                # Validate the complete tree before creating the archive so a
                # rejected symlink cannot leave a partial ZIP behind.
                for item in archive_items:
                    if item.is_symlink():
                        raise SophonError('F025',f'ZIP source contains symbolic link "{item.relative_to(root)}".',sph.name,op['line'],1,None,
                                          'Remove symbolic links from the source folder or copy approved contents into regular files before zipping.')
                with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as zf:
                    for item in archive_items:
                        if item.is_file(): zf.write(item,item.relative_to(source))
            else:
                source=resolved[0]
                if not source.is_file():
                    raise SophonError('F022',f'"{op["paths"][0]}" is not a zip file.',sph.name,op['line'],1,None,'unzip takes a .zip file.')
                if dest.exists():
                    raise SophonError('F016',f'Unzip target folder "{dest.name}" already exists.',sph.name,op['line'],1,None,
                                      'Choose a new target folder or delete the existing folder first.')
                if not dest.parent.is_dir():
                    raise SophonError('F015',f'Parent folder for "{dest.name}" does not exist.',sph.name,op['line'],1,None,
                                      'Create the parent folder first with mkdir.')
                for pol in policies:
                    _fs_grant(pol['access'],'folder','create',[dest],root,op['line'],
                              config_fs=settings.get('config',{}).get('file-system'),
                              policy_actions=pol.get('action',{}),v2=pol.get('schema_version')==2,operation='mkdir')
                with zipfile.ZipFile(source) as zf:
                    for name in zf.namelist():
                        out=dest/name
                        if out.resolve()!=dest and dest not in out.resolve().parents:
                            raise SophonError('F017',f'Archive entry "{name}" escapes the target folder.',sph.name,op['line'],1,None,'Refuse archives with absolute or traversing paths.')
                    dest.mkdir()
                    zf.extractall(dest)
            continue
        raise SophonError('S227',f'File operation "{op["op"]}" is not implemented yet.',sph.name,op['line'],1,None,
                          'Available: create, write, append, read, list, delete, mkdir, copy, move, zip, unzip.')

def execute_files(sph,program,files,settings,agent_ids):
    """Run file operations and turn operating-system failures into diagnostics."""
    import zipfile
    try:
        return _execute_files_impl(sph,program,files,settings,agent_ids)
    except SophonError:
        raise
    except zipfile.BadZipFile as exc:
        raise SophonError('F024',f'Invalid or corrupt ZIP archive: {exc}.',sph.name,1,1,None,
                          'Provide a valid ZIP file and retry the unzip operation.')
    except (OSError,UnicodeError) as exc:
        detail=getattr(exc,'strerror',None) or str(exc)
        raise SophonError('F023',f'File operation failed: {detail}.',sph.name,1,1,None,
                          'Check that the source and target are valid and that the project has the required filesystem permissions.')


def execute_surface_items(items,program,secrets,out,name):
    for operands in items:
        text,single=_eval_item(operands,program.states,program.groups,secrets,name)
        out.write(f'{single} = {text}\n' if single else f'{text}\n')

def _fit(text,width):
    return text if len(text)<=width else text[:max(0,width-1)]+'\u2026'

def _box_out(content,width):
    return '\u2502 '+_fit(content,width-4).ljust(width-4)+' \u2502\n'

def _box_prompt(prefix,answer,width):
    return '\u2502 '+_fit(prefix+answer,width-4).ljust(width-4)+' \u2502\n'

def _box_frame(box,out):
    width=box['width']; inner=width-4
    title=_fit(box.get('title') or box.get('id') or box['kind'],inner-1)
    out.write('\u250c\u2500 '+title+' '+'\u2500'*max(0,inner-1-len(title))+'\u2510\n')

def _box_close(width,out):
    out.write('\u2514'+'\u2500'*(width-2)+'\u2518\n')

def _eval_item_text(operands,program,secrets,name,label=True):
    text,single=_eval_item(operands,program.states,program.groups,secrets,name)
    return f'{single} = {text}' if (single and label) else text

def _render_note(box,program,secrets,out,name):
    _box_frame(box,out)
    for line in box['lines']:
        for operands in _scan_operands(line,Path(name),1,line):
            out.write(_box_out(_eval_item_text(operands,program,secrets,name),box['width']))
    _box_close(box['width'],out)

def _render_list(box,program,secrets,out,name):
    _box_frame(box,out)
    for idx,spec in enumerate(box['items'],1):
        for operands in _scan_operands(spec,Path(name),1,spec):
            out.write(_box_out(f'{idx}) '+_eval_item_text(operands,program,secrets,name,label=False),box['width']))
    _box_close(box['width'],out)

def _render_table(box,program,secrets,out,name):
    _box_frame(box,out)
    grid=[[_eval_item_text(o,program,secrets,name,label=False) for o in row] for row in box['rows']]
    width=max(len(r) for r in grid)
    grid=[r+['']*(width-len(r)) for r in grid]
    cols=[max(len(r[i]) for r in grid) for i in range(width)]
    for r in grid:
        out.write(_box_out('  '.join(cell.ljust(cols[i]) for i,cell in enumerate(r)).rstrip(),box['width']))
    _box_close(box['width'],out)

def execute_box(box,program,secrets,stream,err,name,out):
    """Render one component box. Only form is interactive; the rest are read-only."""
    if box['kind']=='note': return _render_note(box,program,secrets,out,name)
    if box['kind']=='list': return _render_list(box,program,secrets,out,name)
    if box['kind']=='table': return _render_table(box,program,secrets,out,name)
    return execute_form(box,program,secrets,stream,err,name,out)

def execute_form(form,program,secrets,stream,err,name,out):
    """Render one form as a terminal box, asking its prompts in source order."""
    width=form['width']; inner=width-4
    title=_fit(form.get('title') or form.get('id') or 'form',inner-1)
    out.write('\u250c\u2500 '+title+' '+'\u2500'*max(0,inner-1-len(title))+'\u2510\n')
    for step in form['steps']:
        if step['kind']=='section':
            lab=_fit(step['label'],inner-4)
            out.write(_box_out('\u2500\u2500 '+lab+' '+'\u2500'*max(0,inner-4-len(lab)),width)); continue
        if step['kind']=='surface':
            for operands in step['items']:
                text,single=_eval_item(operands,program.states,program.groups,secrets,name)
                out.write(_box_out(f'{single} = {text}' if single else text,width))
            continue
        spec=step['spec']
        if spec.get('kind')=='confirmation':
            answer=_read_confirmation(spec,stream,err)
            _store_confirmation(spec,answer,program)
            out.write(_box_prompt(spec['prompt']+' ',_confirmation_display(spec,answer),width))
            continue
        if spec['secret'] and spec['target']: secrets.add(spec['target'])
        value=_read_answer(spec,stream,err)
        if spec['target']: program.states[spec['target']]=value
        out.write(_box_prompt(spec['prompt']+' ','*' if spec['secret'] else value,width))
    out.write('\u2514'+'\u2500'*(width-2)+'\u2518\n')

def _program_needs(program):
    """Which capabilities the program actually exercises, including inside components."""
    needs={'ask':bool(program.asks),'surface':False}
    for entry in program.renders:
        if entry['kind']=='surface': needs['surface']=True; continue
        for box in entry['boxes']:
            if box['kind']!='form':
                needs['surface']=True; continue
            for step in box['steps']:
                if step['kind']=='surface': needs['surface']=True
                elif step['kind']=='prompt': needs['ask']=True
    return needs

def run(sph,depth=0):
    p,settings=_load_runtime(sph)
    execute_agents(sph,settings,p.agent_connects,p.agent_calls,emit=True,program=p)
    execute_databases(sph,p.databases,settings,p.agent_connects,p)
    execute_files(sph,p,p.files,settings,p.agent_connects)
    if p.executes:
        for item in p.executes:
            for pol in _program_policies(sph,settings,p.agent_connects):
                if item['file']: _exec_grant(pol['access'],item,item['file'],sph.parent.resolve(),item['line'],settings.get('config',{}).get('execute'))
                else: _exec_grant(pol['access'],item,item['command'],sph.parent.resolve(),item['line'],settings.get('config',{}).get('execute'))
        execute_runs(sph,settings,p.executes,depth)
    needs=_program_needs(p)
    _require_capability(sph,settings,p.agent_connects,'ask',needs['ask'])
    _require_capability(sph,settings,p.agent_connects,'surface',needs['surface'])
    secrets=execute_asks(sph,p,settings,p.agent_connects,sys.stdin,sys.stderr)
    for entry in sorted(p.renders,key=lambda e:e['line']):
        if entry['kind']=='surface':
            execute_surface_items(entry['items'],p,secrets,sys.stdout,sph.name)
        else:
            for box in entry['boxes']: execute_box(box,p,secrets,sys.stdin,sys.stderr,sph.name,sys.stdout)
    observed=p._replace(states={k:v for k,v in p.states.items() if k not in secrets})
    for observer_id, observer in p.observers.items():
        cfg=_observer_policy(settings,observer_id,sph)
        if observer['source']=='self':
            source_path=sph
            source_program=observed
        else:
            source_path=(sph.parent/observer['source']).resolve()
            source_program=parse_sph(source_path)
        if observer['self_observation']:
            selected=[('all','*')]
        else:
            selected=[]
            for kind,res in observer['selected']:
                if kind=='resource':
                    if res in source_program.states: selected.append(('state',res))
                    else: selected.append(('multi-state',res))
                else: selected.append((kind,res))
        if cfg['watch']:
            process_observation(source_path,source_program,observer_id,selected,cfg)
    return {'states':p.states,'multi-state':p.groups}

def _resolve_cli_agent(sph, mode):
    p,settings=_load_runtime(sph)
    if not p.agent_connects:
        raise SophonError('A014','No agent is configured for the CLI.',sph.name,1,1,None,'Declare agent connect { id = "..." } in the SPH file.')
    aid=p.agent_connects[0]
    if aid not in settings['agents']:
        raise SophonError('A010',f'Agent "{aid}" was not found in the connected XAF.',sph.name,1,1,None,'Define the agent in XAF.')
    agent,policy=_policy_for_agent(settings,aid)
    if agent.get('execute') is not True:
        raise SophonError('A012',f'Agent "{aid}" execution is denied by XAF.',sph.name,1,1,None,'Set execute = true for the agent.')
    if not policy['action'].get('read',False):
        raise SophonError('A013',f'Agent "{aid}" cannot {mode} because its policy denies read.',sph.name,1,1,None,'Allow read in the agent policy.')
    return sph,settings,aid,agent,policy

def cli_agent(sph,message=None,task=None):
    mode='run' if message is not None else 'task'
    sph,settings,aid,agent,policy=_resolve_cli_agent(sph,mode)
    payload=message if message is not None else task
    return _agent_api_call(agent,payload,sph,policy,timeout=agent.get('timing',{}).get('timeout',agent.get('delay',60)),mode=mode,settings=settings)

VERSION='Genesis 0.0.1'
USAGE='usage: sophon [--help] [--version] | sophon run <program.sph> | sophon agent -f <program.sph> -m "message" | sophon agent -f <program.sph> -t "task"'

def _cli_help():
    print(USAGE)
    print('\ncommands:')
    print('  run <program.sph>             Run a Sophon program')
    print('  agent -f <program.sph> -m ... Run the connected Agent with a message')
    print('  agent -f <program.sph> -t ... Run the connected Agent with a task')
    print('\noptions:')
    print('  -h, --help                    Show this help')
    print('  --version                     Show Sophon version')


def _cli_usage(problem=None):
    if problem: print(f'sophon: {problem}', file=sys.stderr)
    print(USAGE, file=sys.stderr)
    raise SystemExit(2)

def _cli_agent_command(rest):
    """sophon agent -f <program.sph> -m <message> | -t <task>"""
    target=None; mode=None; payload=None; k=0
    while k<len(rest):
        flag=rest[k]
        if flag in ('-f','-m','-t'):
            if k+1>=len(rest): _cli_usage(f'{flag} needs a value')
            if flag=='-f':
                if target is not None: _cli_usage('-f given twice')
                target=rest[k+1]
            else:
                if mode is not None: _cli_usage('-m and -t cannot be combined')
                mode='run' if flag=='-m' else 'task'
                payload=rest[k+1]
            k+=2; continue
        _cli_usage(f'unknown argument "{flag}"')
    if target is None: _cli_usage('-f is required: name the SPH program that owns the agent')
    if mode is None: _cli_usage('give either -m "message" or -t "task"')
    path=Path(target)
    if not path.is_file():
        raise SophonError('A027',f'Agent program "{target}" was not found.',target,1,1,None,
                          'Point -f at an existing .sph file.')
    return cli_agent(path.resolve(),**({'message':payload} if mode=='run' else {'task':payload}))

if __name__=='__main__':
    args=sys.argv[1:]
    try:
        if args and args[0] in ('-h','--help','help'):
            _cli_help(); raise SystemExit(0)
        if args and args[0]=='--version':
            print(VERSION); raise SystemExit(0)
        if args and args[0]=='run':
            if len(args)!=2: _cli_usage('run needs exactly one .sph file')
            run(Path(args[1]).resolve()); raise SystemExit(0)
        if args and args[0]=='agent':
            print(_cli_agent_command(args[1:])); raise SystemExit(0)
        if args: _cli_usage(f'unknown command "{args[0]}"')
        _cli_usage()
    except SophonError as e:
        print(e, file=sys.stderr); raise SystemExit(1)
