# Sophon integration audit fixtures

These are executable Sophon source fixtures (`.sph`), control-plane policies (`.xaf`), and a Vault database (`.svt`). They are exercised by `test_language_integration.py` against the actual Sophon runtime. The Agent provider is mocked; the suite makes no external network request and requires no real API key.

Run from the project directory:

```bash
python3 -m unittest test_language_integration.py
```

For the parser/documentation gates, also run:

```bash
python3 test_regressions.py
python3 check_docs.py
```
