"""Docs gate: parse every code block in SYNTAX.md with the real parser.

Fragment blocks (blocks that show a nested construct on its own) are checked for
parse *shape* by wrapping them in a host block, so a broken fragment is still
caught. Everything else must parse exactly as written.

    python3 check_docs.py
"""

import importlib
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sophon  # noqa: E402

importlib.reload(sophon)

DOCS = [pathlib.Path(__file__).parent / name for name in ('SYNTAX.md', 'XAF_V2_SCHEMA.md')]

# A block that is a nested construct rather than a whole program, and the host
# block that gives it a legal context. Verified by the same parser.
HOSTS = {
    'choice {': 'confirmation {\n    id = "c"\n    prompt = "p"\n    state = s\n%s\n}',
    'input {': 'agent run {\n    id = "a"\n    message { "m" }\n%s\n}',
}

MODULES = 'use { database observer multi-observer agent component file execute datetime random }\n'


def code(text):
    m = re.search(r'\[(\w+)\]', str(text))
    return m.group(1) if m else '?'


def check_block(lang, body, tmp, index):
    d = tmp / f'b{index}'
    d.mkdir(exist_ok=True)

    if lang == 'sph':
        stripped = body.lstrip()
        if stripped.startswith(('choice {', 'input {')):
            key = next(k for k in HOSTS if stripped.startswith(k))
            body = HOSTS[key] % body.rstrip()
            stripped = body.lstrip()
        src = stripped if stripped.startswith('connect ') else 'connect to p.xaf\n' + MODULES + body
        f = d / 'p.sph'
        f.write_text(src)
        try:
            sophon.parse_sph(f)
        except sophon.SophonError as e:
            return code(e), str(e).splitlines()[0]
        return None

    parser = sophon.parse_xaf if lang == 'xaf' else sophon.parse_svt
    f = d / f'p.{lang}'
    f.write_text(body)
    try:
        parser(f)
    except sophon.SophonError as e:
        return code(e), str(e).splitlines()[0]
    return None


def main():
    missing=[doc for doc in DOCS if not doc.exists()]
    if missing:
        for doc in missing: print(f'kayit yok: {doc}')
        return 1
    blocks=[]
    for doc in DOCS:
        blocks.extend((doc.name,lang,body) for lang,body in
                      re.findall(r'```(sph|xaf|svt)\n(.*?)```',doc.read_text(),re.S))
    tmp = pathlib.Path(tempfile.mkdtemp())
    failures = []
    for i, (doc_name,lang, body) in enumerate(blocks, 1):
        result = check_block(lang, body, tmp, i)
        if result:
            failures.append((i, doc_name, lang, result[0], result[1]))

    print(f'{len(blocks)} kod blogu denetlendi ({", ".join(doc.name for doc in DOCS)}).')
    if failures:
        print(f'{len(failures)} blogu ayristirilamadi:')
        for i, doc_name, lang, c, msg in failures:
            print(f'  {doc_name} #{i} [{lang}] {c}: {msg}')

    source = pathlib.Path(__file__).parent / 'sophon.py'
    catalog = pathlib.Path(__file__).parent / 'SYNTAX.md'
    source_codes = set(re.findall(r"SophonError\(\s*['\"]([A-Z]\d{3})['\"]", source.read_text(encoding='utf-8')))
    catalog_text = catalog.read_text(encoding='utf-8')
    section = catalog_text.split('## Hata ve uyarı kataloğu', 1)[-1]
    section = section.split('\n## ', 1)[0]
    catalog_codes = set(re.findall(r'`([A-Z]\d{3})`', section))
    undocumented = sorted(source_codes - catalog_codes)
    if undocumented:
        print(f'{len(undocumented)} hata kodu katalogda eksik: {", ".join(undocumented)}')

    if failures or undocumented:
        return 1
    print(f'hepsi ayristirildi; {len(source_codes)} hata kodunun tamami katalogda.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
