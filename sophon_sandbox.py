#!/usr/bin/env python3
"""Linux namespace/chroot sandbox used for isolated Sophon Agent provider calls.

The sandbox uses user, mount, PID, UTS, IPC and network namespaces; a chroot containing
only the Python runtime and CA/DNS files; a read-only project mount; and process
resource limits. Network is isolated; egress is proxied only to openrouter.ai:443.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import select
from pathlib import Path


class SandboxUnavailable(RuntimeError):
    pass


class SandboxWorkerError(RuntimeError):
    def __init__(self, code, message, file='', line=None, hint=None):
        super().__init__(message)
        self.code, self.file, self.line, self.hint = code, file, line, hint

class _OpenRouterConnectHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request=self.rfile.readline(8192).decode('ascii','replace').strip().split()
            while self.rfile.readline(8192) not in (b'\r\n',b'\n',b''):
                pass
            if len(request)<2 or request[0].upper()!='CONNECT' or request[1].lower()!='openrouter.ai:443':
                self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n')
                return
            remote=socket.create_connection(('openrouter.ai',443),timeout=15)
            self.wfile.write(b'HTTP/1.1 200 Connection Established\r\nProxy-Agent: Sophon-Sandbox\r\n\r\n')
            client=self.connection
            client.setblocking(False); remote.setblocking(False)
            peers=(client,remote)
            while True:
                readable,_,_=select.select(peers,[],[],90)
                if not readable: break
                for source in readable:
                    target=remote if source is client else client
                    try: data=source.recv(65536)
                    except OSError: data=b''
                    if not data: return
                    target.sendall(data)
        except (OSError,ValueError):
            return
        finally:
            try: remote.close()
            except Exception: pass


class _UnixProxyServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
    allow_reuse_address=True


def _start_openrouter_proxy(path):
    server=_UnixProxyServer(str(path),_OpenRouterConnectHandler)
    os.chmod(path,0o600)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    return server,thread


def _preexec_limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        if hasattr(resource, 'RLIMIT_NPROC'):
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except Exception:
        pass


def available():
    if sys.platform != 'linux':
        return False
    unshare = shutil.which('unshare')
    if not unshare:
        return False
    try:
        result = subprocess.run(
            [unshare, '--user', '--map-root-user', '--mount', '--pid', '--fork', '--uts', '--ipc', '--net', 'true'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _helper_source():
    return r'''import ctypes, json, os, sys
libc=ctypes.CDLL(None,use_errno=True)
MS_RDONLY=1; MS_BIND=4096; MS_REMOUNT=32; MS_REC=16384; MS_PRIVATE=1<<18
root=sys.argv[1]; mode=sys.argv[2]
def fail(label):
    err=ctypes.get_errno(); print(label+': '+os.strerror(err),file=sys.stderr); sys.exit(120)
if libc.mount(None,b'/',None,MS_REC|MS_PRIVATE,None)!=0: fail('make mounts private')
if libc.prctl(38,1,0,0,0)!=0: fail('set no_new_privs')
os.umask(0o077)
def bind(src,dst,readonly=True):
    if not os.path.exists(src): return
    if os.path.isdir(src): os.makedirs(dst,exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst),exist_ok=True)
        if not os.path.exists(dst): open(dst,'ab').close()
    if libc.mount(os.fsencode(src),os.fsencode(dst),None,MS_BIND|MS_REC,None)!=0: fail('bind '+src)
    if readonly and os.path.isdir(src):
        if libc.mount(None,os.fsencode(dst),None,MS_BIND|MS_REMOUNT|MS_RDONLY|MS_REC,None)!=0: fail('read-only '+src)
    elif readonly:
        if libc.mount(None,os.fsencode(dst),None,MS_BIND|MS_REMOUNT|MS_RDONLY,None)!=0: fail('read-only '+src)
for src,rel in [('/usr','usr'),('/lib','lib'),('/lib64','lib64'),('/etc/ssl','etc/ssl'),('/etc/resolv.conf','etc/resolv.conf'),('/etc/hosts','etc/hosts')]:
    bind(src,os.path.join(root,rel),True)
bind(sys.argv[3],os.path.join(root,'workspace'),True)
if len(sys.argv)>4 and sys.argv[4]: bind(sys.argv[4],os.path.join(root,'run/sophon-proxy.sock'),False)
os.chroot(root); os.chdir('/workspace')
os.environ.clear(); os.environ.update(json.loads(open('/tmp/sophon-env.json').read()))
if mode=='probe':
    visible=os.path.exists('/etc/passwd')
    write_blocked=False
    network_blocked=False
    try:
        import socket
        probe_sock=socket.create_connection(('1.1.1.1',53),timeout=0.4)
        probe_sock.close()
    except OSError:
        network_blocked=True
    try:
        open('/workspace/.sophon-sandbox-probe','w').write('not allowed')
    except OSError:
        write_blocked=True
    print(json.dumps({'pid':os.getpid(),'cwd':os.getcwd(),'root':os.path.realpath('/'),'host_etc_passwd_visible':visible,'workspace_read_only':write_blocked,'network_isolated':network_blocked}))
    sys.exit(0)
os.execv('/usr/bin/python3',['/usr/bin/python3','/opt/sophon/sandbox_worker.py','/tmp/payload.json'])
'''


def _run(project_dir: Path, runtime_dir: Path, payload: dict | None, env: dict,
         timeout: float, probe: bool = False, network_proxy: bool = False):
    project_dir = Path(project_dir).resolve()
    runtime_dir = Path(runtime_dir).resolve()
    if not project_dir.is_dir():
        raise SandboxUnavailable('Sandbox project directory does not exist.')
    unshare = shutil.which('unshare')
    if sys.platform != 'linux' or not unshare:
        raise SandboxUnavailable('Linux unshare is required for Sophon container isolation.')
    with tempfile.TemporaryDirectory(prefix='sophon-sandbox-') as tmp:
        root = Path(tmp) / 'root'
        for directory in ('usr','lib','lib64','etc/ssl','etc','workspace','opt/sophon','tmp'):
            (root / directory).mkdir(parents=True, exist_ok=True)
        # Runtime code is copied into the isolated root; the project itself is mounted read-only.
        shutil.copy2(runtime_dir / 'sophon.py', root / 'opt/sophon' / 'sophon.py')
        shutil.copy2(Path(__file__).with_name('sandbox_worker.py'), root / 'opt/sophon' / 'sandbox_worker.py')
        agent_md = runtime_dir / 'AGENT.md'
        if agent_md.is_file():
            shutil.copy2(agent_md, root / 'opt/sophon' / 'AGENT.md')
        (root / 'tmp' / 'sophon-env.json').write_text(json.dumps(env), encoding='utf-8')
        if payload is not None:
            (root / 'tmp' / 'payload.json').write_text(json.dumps(payload, default=lambda value: sorted(value) if isinstance(value, set) else str(value)), encoding='utf-8')
        helper = Path(tmp) / 'enter_sandbox.py'
        helper.write_text(_helper_source(), encoding='utf-8')
        proxy_server=None; proxy_thread=None; proxy_path=''
        if network_proxy:
            proxy_path=str(Path(tmp)/'openrouter-proxy.sock')
            proxy_server,proxy_thread=_start_openrouter_proxy(proxy_path)
        command = [unshare, '--user', '--map-root-user', '--mount', '--pid', '--fork', '--uts', '--ipc', '--net',
                   sys.executable, str(helper), str(root), 'probe' if probe else 'agent', str(project_dir), proxy_path]
        try:
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, timeout=max(5.0, timeout), check=False,
                                       env={'PATH': os.environ.get('PATH','/usr/bin:/bin')},
                                       preexec_fn=_preexec_limits if os.name == 'posix' else None)
        except subprocess.TimeoutExpired as exc:
            raise SandboxUnavailable('Sandbox process exceeded its wall-clock limit.') from exc
        finally:
            if proxy_server is not None:
                proxy_server.shutdown(); proxy_server.server_close()
                if proxy_thread is not None: proxy_thread.join(timeout=1)
        if completed.returncode != 0:
            detail=(completed.stderr or completed.stdout or 'unknown namespace/chroot error').strip()[-1200:]
            raise SandboxUnavailable('Could not establish Linux sandbox: '+detail)
        try:
            return json.loads(completed.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise SandboxUnavailable('Sandbox worker returned invalid output: '+completed.stdout[-500:]) from exc


def run_agent(agent, message, sph_path, policy, files, timeout, mode, settings):
    """Run the Agent's provider request in an isolated process and read-only project root."""
    agent = dict(agent)
    # This child is already inside the sandbox; avoid recursively creating another one.
    agent['security'] = dict(agent.get('security', {}), container=False)
    agent['container'] = False
    connection = agent.get('connection') or agent.get('api-key', {})
    env_name = connection.get('key') or 'OPENROUTER_API_KEY'
    secret = os.environ.get(env_name)
    if not secret:
        raise SandboxUnavailable(f'Agent API environment variable "{env_name}" is not set.')
    project = Path(sph_path).resolve().parent
    try:
        relative_sph = Path(sph_path).resolve().relative_to(project).as_posix()
    except ValueError as exc:
        raise SandboxUnavailable('Agent source file is outside its project root.') from exc
    payload = {
        'agent': agent, 'message': message, 'sph': '/workspace/' + relative_sph,
        'policy': policy, 'files': list(files or ()), 'timeout': timeout,
        'mode': mode, 'settings': {'config': {'file-system': (settings or {}).get('config',{}).get('file-system')}},
    }
    result = _run(project, Path(__file__).resolve().parent, payload,
                  {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','SOPHON_PROXY_SOCKET':'/run/sophon-proxy.sock',env_name:secret},
                  float(timeout or 180) + 15, network_proxy=True)
    if not result.get('ok'):
        error=result.get('error',{})
        if isinstance(error,dict):
            raise SandboxWorkerError(error.get('code','A035'),error.get('message','Sandbox Agent request failed.'),
                                     error.get('file',''),error.get('line'),error.get('hint'))
        raise SandboxUnavailable(str(error))
    return result.get('response','')


def probe(project_dir, runtime_dir=None):
    """Test the actual namespace/chroot backend without making a network request."""
    runtime_dir = Path(runtime_dir or __file__).resolve().parent
    return _run(Path(project_dir),runtime_dir,None,{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},10,probe=True)
