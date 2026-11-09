from pathlib import Path
import tempfile, json, subprocess, sys, os, shutil, atexit
sys.path.insert(0, str(Path(__file__).parent))
import sophon
ROOT=Path(__file__).parent
# Keep generated cases isolated in a fresh temporary directory.
TEST=Path(tempfile.mkdtemp(prefix='sophon-audit-'))
atexit.register(shutil.rmtree, TEST, ignore_errors=True)

def put(name, text):
    p=TEST/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8'); return p

base_xaf='''config {
    default-policy = 2001
    multi { multi-state multi-ask multi-confirmation multi-observer }
    observer {
        1001 {
            watch = true
            log = true
            path = "logs"
            level = detailed
            action { read = true modify = true create = true remove = true reorder = true }
        }
    }
    database {
        max-records = 10
        max-bytes = 100000
        connection { provider = "local" }
    }
    file-system {
        allowed_path { "data" "logs" "archives" }
        forbidden_path { "data/private" }
        action {
            file { create read modify move copy delete }
            folder { create read modify move copy delete zip-unzip }
        }
    }
    execute { file { "worker.sph" } command { } }
    agent { permission { execute = false } }
}
policy {
    id = 2001
    access { multi observer database file-system execute agent component source { self = true external = true } }
    action { read = true write = true modify = true remove = true create = true reorder = true }
}
'''
put('main.xaf',base_xaf)
put('data/users.svt','''vault {\n    record {\n        id = 1\n        name = "Ada"\n        age = 31\n        tags = ["math" "science"]\n    }\n}\n''')
put('worker.sph','''connect to worker.xaf\nstate result = "subprogram-ok"\nsurface { result }\n''')
put('worker.xaf','''policy worker.sph { access { surface } action { read = true } }\n''')

# Core values, expressions, multi-state, datetime and output.
put('core.sph','''connect to main.xaf
use { datetime }
state int_value: integer = 12
state float_value: float = 3.5
state numeric_value: number = int_value + float_value * 2
state power = 2 ^ 5
state root = sqrt(81)
state name = "Sophon"
state greeting = "Merhaba {name}"
state items = [alpha beta 4 true null]
multi-state { id = "person" state { name = "Ada" age = 31 } }
multi-state { id = "person" state { age = 32 } }
state today = date
state hour_now = time.hour
surface { numeric_value power root greeting items person.name person.age today date.weekday date.timezone hour_now }
''')

# Component types and form.
put('components.sph','''connect to main.xaf
use { component }
state product = "Sophon"
state count = 3
component {
    id = "dashboard"
    note { title = "Info" text = product text = "Status: ready" }
    list { title = "Features" item = "Agent-first" item = "Policy" item = product }
    table { title = "Metrics" row "name" "value" row "count" count }
}
''')
put('form.sph','''connect to main.xaf
use { component }
component {
    form {
        id = "signup"
        title = "Registration"
        ask { id = "username" prompt = "Name:" state = username }
        surface { username }
        confirmation {
            id = "consent"
            prompt = "Accept?"
            choice { yes = true no = false }
            state = accepted
        }
        surface { accepted }
    }
}
''')

# Ask and multi-ask/confirmation/multi-confirmation all top-level with stdin.
put('prompts.sph','''connect to main.xaf
multi-ask {
 id = "contact"
 ask { id = "city" prompt = "City:" state = city }
 ask { id = "country" prompt = "Country:" state = country }
}
confirmation {
 id = "color"
 prompt = "Color?"
 choice { red = "red" blue = "blue" }
 state = color
}
multi-confirmation {
 id = "features"
 confirmation {
  id = "notify"
  prompt = "Notify?"
  choice { yes = true no = false }
  state = notify
 }
}
surface { city country color notify }
''')

# Observer self and external source.
put('observed.sph','''connect to main.xaf
use { observer }
state value = 42
multi-state { id = "user" state { name = "Ada" age = 31 } }
observer { id = 1001 source = self watch { value user.age } }
surface { value }
''')
put('external.sph','''connect to external.xaf
state external_value = "external"
''')
put('external.xaf','''policy external.sph { access { surface } action { read = true } }\n''')

# Database read/write/modify/remove.
put('database.sph','''connect to main.xaf
use { database }
state selected = null
database users {
 connect = data/users.svt
 read { id = 1 state = selected }
 write { id = 2 name = "Grace" age = 29 }
 modify { id = 2 age = 30 }
}
surface { selected }
''')
put('database_remove.sph','''connect to main.xaf
use { database }
database users { connect = data/users.svt remove { id = 2 } }
''')

# File operation workflow.
put('files.sph','''connect to main.xaf
use { file }
state body = "alpha beta"
file {
 mkdir { path = "data/out" }\n mkdir { path = "archives" }
 create { path = "data/out/a.txt" }
 write { path = "data/out/a.txt" data = body }
 append { path = "data/out/a.txt" data = " gamma" }
 read { path = "data/out/a.txt" state = contents }
 list { path = "data/out" state = entries }
 copy { path = "data/out/a.txt" to = "data/out/b.txt" }
 move { path = "data/out/b.txt" to = "data/out/c.txt" }
 zip { path = "data/out" to = "archives/out.zip" }
 unzip { path = "archives/out.zip" to = "data/extracted" }
}
surface { contents entries }
''')

# Execute allowlisted file.
put('execute_main.sph','''connect to main.xaf
use { execute }
execute { file = "worker.sph" }
''')

# Legacy XAF compatibility.
put('legacy.xaf','''policy legacy.sph { access { surface } action { read = true } }\n''')
put('legacy.sph','''connect to legacy.xaf
state x = "legacy"
surface { x }
''')

# Parse-only Agent (prevent network call using missing API key after all validations).
put('agent_parse.sph','''connect to agent.xaf
use { agent }
agent connect { id = 7001 }
state response = ""
agent run { id = 7001 message { "test" } output = response }
surface { response }
''')
put('agent.xaf','''config {
 agent {
  connection {
   provider = "openrouter"
   model = "provider/model"
   key = "SOPHON_TEST_MISSING_KEY"
  }
  permission {
   execute = true
  }
 }
}
agent {
 id = 7001
 name = "Test Agent"
 policy = 7002
}
policy {
 id = 7002
 access { agent }
 action { read = true }
}
''')


cases=[]
for name in ['core.sph','components.sph','form.sph','prompts.sph','observed.sph','database.sph','database_remove.sph','files.sph','execute_main.sph','legacy.sph']:
    p=TEST/name
    try:
        if name=='prompts.sph':
            # use StringIO directly to exercise interactive input deterministically
            import io, contextlib
            oldin,oldout,olderr=sys.stdin,sys.stdout,sys.stderr
            sys.stdin=io.StringIO('Izmir\nTurkey\nblue\nyes\n'); out=io.StringIO(); err=io.StringIO(); sys.stdout=out; sys.stderr=err
            try: result=sophon.run(p)
            finally: sys.stdin,sys.stdout,sys.stderr=oldin,oldout,olderr
            cases.append((name,'PASS',out.getvalue().strip().replace('\n',' | ')))
        elif name=='form.sph':
            import io
            oldin,oldout,olderr=sys.stdin,sys.stdout,sys.stderr
            sys.stdin=io.StringIO('Arda\nyes\n'); out=io.StringIO(); err=io.StringIO(); sys.stdout=out; sys.stderr=err
            try: result=sophon.run(p)
            finally: sys.stdin,sys.stdout,sys.stderr=oldin,oldout,olderr
            cases.append((name,'PASS',out.getvalue().strip().replace('\n',' | ')))
        else:
            import io, contextlib
            out=io.StringIO()
            with contextlib.redirect_stdout(out): result=sophon.run(p)
            cases.append((name,'PASS',out.getvalue().strip().replace('\n',' | ') or f'states={len(result["states"])}'))
    except Exception as e:
        code=getattr(e,'code',type(e).__name__)
        cases.append((name,'FAIL',f'{code}: {e}'))

# XAF parse + Agent validation stage should fail before networking due to missing key.
try:
    sophon.run(TEST/'agent_parse.sph')
    cases.append(('agent_parse.sph','UNEXPECTED','call succeeded without key'))
except sophon.SophonError as e:
    cases.append(('agent_parse.sph',f'EXPECTED-{e.code}',e.message))

# Edge / malformed cases: report current behavior.
edge={
 'unknown_root_xaf':'mystery { value = true }\npolicy {\n id = 9001\n access { agent }\n}\n',
 'duplicate_default':'config {\n default-policy = 1\n default-policy = 2\n}\npolicy {\n id = 1\n}\npolicy {\n id = 2\n}\n',
 'duplicate_agent_field':'agent {\n id = 1\n name = "A"\n policy = 2\n permission {\n  execute = true\n  execute = false\n }\n}\npolicy {\n id = 2\n access { agent }\n}\n',
 'duplicate_retry':'agent {\n id = 1\n name = "A"\n policy = 2\n timing {\n  retry {\n   count = 1\n   count = 2\n  }\n }\n}\npolicy {\n id = 2\n access { agent }\n}\n',
}
for key,src in edge.items():
    p=put('edge_'+key+'.xaf',src)
    try:
        settings=sophon.parse_xaf(p)
        cases.append((key,'ACCEPTED',str({k:v for k,v in settings.items() if k in ('agents','config','policies')})))
    except sophon.SophonError as e:
        cases.append((key,f'REJECTED-{e.code}',e.message))

print('CASE RESULTS')
for x in cases: print('|'.join(map(str,x)))
print('--- generated outputs ---')
for fp in sorted(TEST.rglob('*')):
    if fp.is_file() and (fp.suffix in ('.txt','.svt','.json') or fp.name.endswith('.json')):
        print(fp.relative_to(TEST), 'bytes=',fp.stat().st_size)
