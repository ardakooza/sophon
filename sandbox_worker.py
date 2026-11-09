#!/usr/bin/env python3
"""Internal worker executed only after entering the Sophon Linux sandbox."""
import json
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, '/opt/sophon')
import sophon

# Network namespace has no external interface. The only egress is a host-side
# Unix-socket CONNECT proxy which accepts openrouter.ai:443 and nothing else.
proxy_path=os.environ.get('SOPHON_PROXY_SOCKET','/run/sophon-proxy.sock')
def _proxy_connection(address, timeout=None, source_address=None, *, all_errors=False):
    host,port=address
    if str(host).lower()!='openrouter.ai' or int(port)!=443:
        raise OSError('Sophon sandbox network policy permits only openrouter.ai:443')
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    if timeout is not None: sock.settimeout(timeout)
    sock.connect(proxy_path)
    sock.sendall(b'CONNECT openrouter.ai:443 HTTP/1.1\r\nHost: openrouter.ai:443\r\n\r\n')
    response=bytearray()
    while b'\r\n\r\n' not in response:
        chunk=sock.recv(1024)
        if not chunk: raise OSError('Sophon sandbox proxy closed the connection')
        response.extend(chunk)
        if len(response)>8192: raise OSError('Invalid Sophon sandbox proxy response')
    if not response.startswith(b'HTTP/1.1 200 '):
        raise OSError('Sophon sandbox proxy denied the network request')
    return sock
socket.create_connection=_proxy_connection

payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
try:
    response=sophon._agent_api_call(
        payload['agent'],payload['message'],Path(payload['sph']),payload.get('policy'),
        payload.get('files',()),payload.get('timeout'),payload.get('mode','run'),payload.get('settings'),
    )
    print(json.dumps({'ok':True,'response':response},ensure_ascii=False))
except sophon.SophonError as exc:
    print(json.dumps({'ok':False,'error':{'code':exc.code,'message':exc.message,'file':exc.file,'line':exc.line,'hint':exc.hint}},ensure_ascii=False))
except Exception as exc:
    print(json.dumps({'ok':False,'error':f'Agent sandbox worker failed: {type(exc).__name__}: {exc}'},ensure_ascii=False))
