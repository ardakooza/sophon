"""Executable end-to-end audit of real Sophon .sph/.xaf/.svt fixtures.

The provider API is mocked: the suite exercises request construction and retry
behavior without network access or real credentials.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import sophon

FIXTURES = Path(__file__).parent / 'audit_suite'


class _MockResponse:
    def __init__(self, content='audit-agent-ok'):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps({'choices': [{'message': {'content': self.content}}]}).encode()


class SophonLanguageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(FIXTURES, self.root, dirs_exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def run_source(self, name, stdin=''):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                result = sophon.run(self.root / name)
        finally:
            sys.stdin = old_stdin
        return result, out.getvalue(), err.getvalue()

    def expect_error(self, path, code):
        with self.assertRaises(sophon.SophonError) as caught:
            if path.suffix == '.xaf':
                sophon.parse_xaf(path)
            elif path.suffix == '.svt':
                sophon.parse_svt(path)
            else:
                sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertTrue(caught.exception.message)
        self.assertTrue(caught.exception.hint)

    def test_cli_help_and_version_are_successful(self):
        import subprocess
        script = Path(sophon.__file__).with_name('sophon.py')
        help_run = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertIn('commands:', help_run.stdout)
        self.assertIn('agent -f', help_run.stdout)
        version_run = subprocess.run([sys.executable, str(script), '--version'], capture_output=True, text=True)
        self.assertEqual(version_run.returncode, 0, version_run.stderr)
        self.assertIn('Genesis 0.0.1', version_run.stdout)

    def test_reserved_future_features_have_explicit_diagnostics(self):
        for name in ('math', 'system', 'sys', 'multi-agent'):
            with self.subTest(module=name):
                self.expect_error(self.write('future_module.sph', f'use {{ {name} }}\n'), 'S250')
        self.expect_error(self.write('malformed_function.sph', 'function { id = \"work\" }\n'), 'S261')
        self.expect_error(self.write('future_multi_agent.sph', 'multi-agent { id = \"team\" }\n'), 'S250')

    def test_functions_run_as_real_sophon_program(self):
        result, _output, _ = self.run_source('functions.sph')
        self.assertEqual(result['states']['total'], 30)
        self.assertEqual(result['states']['stats'], {'sum': 13, 'difference': 5})
        self.assertEqual(result['states']['greeting_text'], 'Hello, Sophon')

    def test_functions_execute_with_typed_default_optional_named_and_multi_outputs(self):
        source = self.write('functions.sph', '''state global_factor = 3
function {
    id = "calculate"
    input {
        a: integer
        b: integer = 10
        c: integer?
    }
    execute {
        state temporary = a * b
        state result = temporary + 10
    }
    output: integer = result
}
function {
    id = "stats"
    input { a: integer b: integer }
    execute { state sum = a + b state difference = a - b }
    output { sum difference }
}
function {
    id = "greet"
    input { name: string }
    execute { state result = "Hello, {name}" }
    output: string = result
}
function { id = "global_read" input { value: integer } execute { state result = value * global_factor } output: integer = result }
function { id = "nested" input { value: integer } execute { state result = calculate(a = value) } output: integer = result }
state nested_total = nested(4)
state total = calculate(2)
state global_total = global_read(4)
state named = calculate(a = 3, b = 4)
state results = stats(9, 4)
state sum = results.sum
state difference = results.difference
state greeting = greet("Arda")
''')
        parsed = sophon.parse_sph(source)
        self.assertEqual(parsed.states['total'], 30)
        self.assertEqual(parsed.states['global_total'], 12)
        self.assertEqual(parsed.states['nested_total'], 50)
        self.assertEqual(parsed.states['named'], 22)
        self.assertEqual(parsed.states['results'], {'sum': 13, 'difference': 5})
        self.assertEqual(parsed.states['sum'], 13)
        self.assertEqual(parsed.states['difference'], 5)
        self.assertEqual(parsed.states['greeting'], 'Hello, Arda')
        self.assertNotIn('temporary', parsed.states)
        self.assertEqual(set(parsed.functions), {'calculate','stats','greet','global_read','nested'})

    def test_set_updates_existing_top_level_state_and_preserves_type(self):
        source = self.write('set_update.sph', '''state name = "arda"
set name = "elif"
state age: integer = 18
set age = 19
state score: number = 10
set score = 10.5
''')
        parsed = sophon.parse_sph(source)
        self.assertEqual(parsed.states['name'], 'elif')
        self.assertEqual(parsed.states['age'], 19)
        self.assertEqual(parsed.states['score'], 10.5)

    def test_set_rejects_unknown_same_value_and_wrong_type(self):
        cases = [
            ('unknown_set.sph', 'set missing = 1\n', 'S284'),
            ('malformed_set.sph', 'set missing\n', 'S284'),
            ('same_set.sph', 'state value = 1\nset value = 1\n', 'S246'),
            ('wrong_type_set.sph', 'state value: integer = 1\nset value = "text"\n', 'S289'),
            ('date_set.sph', 'use { datetime }\nset date = "tomorrow"\n', 'S245'),
        ]
        for filename, text, code in cases:
            with self.subTest(filename=filename):
                self.expect_error(self.write(filename, text), code)

    def test_set_updates_function_parameters_and_prior_local_states_only(self):
        source = self.write('function_set.sph', '''state global_value = 4
function {
    id = "update"
    input { value: integer }
    execute {
        set value = value + 1
        state result = value
        set result = result * 2
    }
    output: integer = result
}
state answer = update(5)
''')
        parsed = sophon.parse_sph(source)
        self.assertEqual(parsed.states['answer'], 12)
        forbidden = self.write('function_set_global.sph', '''state global_value = 4
function {
    id = "bad"
    input {}
    execute { set global_value = 5 state result = 1 }
    output: integer = result
}
state answer = bad()
''')
        self.expect_error(forbidden, 'S284')
        wrong_type = self.write('function_set_type.sph', '''function {
    id = "bad_type"
    input { value: integer }
    execute { set value = "text" state result = 1 }
    output: integer = result
}
state answer = bad_type(5)
''')
        self.expect_error(wrong_type, 'S289')

    def test_function_signature_output_and_body_validation(self):
        definitions = [
            ('too_many.sph', 'function { id = "f" input { a: integer } execute { state r = a } output: integer = r }\nstate x = f(1, 2)\n', 'S267'),
            ('unknown_arg.sph', 'function { id = "f" input { a: integer } execute { state r = a } output: integer = r }\nstate x = f(b = 1)\n', 'S268'),
            ('duplicate_arg.sph', 'function { id = "f" input { a: integer } execute { state r = a } output: integer = r }\nstate x = f(a = 1, a = 2)\n', 'S269'),
            ('mixed_arg.sph', 'function { id = "f" input { a: integer b: integer } execute { state r = a + b } output: integer = r }\nstate x = f(1, a = 2)\n', 'S269'),
            ('missing_output.sph', 'function { id = "f" input {} execute { state r = 1 } output: integer = absent }\nstate x = f()\n', 'S273'),
            ('wrong_output.sph', 'function { id = "f" input {} execute { state r = "text" } output: integer = r }\nstate x = f()\n', 'S274'),
            ('bad_order.sph', 'function { id = "f" input { a: integer? b: integer } execute { state r = 1 } output: integer = r }\n', 'S262'),
            ('bad_body.sph', 'function { id = "f" input {} execute { surface { "no" } } output: integer = absent }\n', 'S264'),
        ]
        for filename, text, code in definitions:
            with self.subTest(filename=filename):
                self.expect_error(self.write(filename, text), code)

    def test_function_is_in_editor_block_grammar_and_skeletons(self):
        grammar = sophon.block_grammar()
        self.assertIn('function', grammar['blocks'])
        self.assertIsNotNone(grammar['blocks']['function']['skeleton'])
        self.assertEqual(sophon.check_block_skeletons(), [])

    def test_function_call_errors_are_sophon_diagnostics(self):
        definition = '''function { id = "calculate" input { a: integer } execute { state result = a + 1 } output: integer = result }\n'''
        cases = [
            ('missing.sph', definition + 'state value = calculate()\n', 'S270'),
            ('wrong_type.sph', definition + 'state value = calculate("wrong")\n', 'S271'),
            ('unknown.sph', 'state value = missing(1)\n', 'S275'),
            ('recursive.sph', 'function { id = "loop" input { value: integer } execute { state next = loop(value) } output: integer = next }\nstate value = loop(1)\n', 'S266'),
        ]
        for filename, text, code in cases:
            with self.subTest(filename=filename):
                self.expect_error(self.write(filename, text), code)

    def test_policy_child_denials_override_parent_and_cannot_be_regranted(self):
        xaf = self.write('deny.xaf', '''config { default-policy = 3 multi { multi-state } }
policy {
    id = 1
    access { multi agent source { self = true external = true } }
    action { read = true write = true }
}
policy {
    id = 2
    inherits = 1
    access { multi }
    action { read = true }
    deny { access { multi source { external = true } } action { read = true } }
}
policy {
    id = 3
    inherits = 2
    access { multi source { external = true } }
    action { read = true }
}
''')
        settings = sophon.parse_xaf(xaf)
        effective = settings['resolved_policies'][3]
        self.assertFalse(effective['access']['multi'])
        self.assertTrue(effective['access']['agent'])
        self.assertTrue(effective['access']['source']['self'])
        self.assertFalse(effective['access']['source']['external'])
        self.assertFalse(effective['action']['read'])
        self.assertTrue(effective['action']['write'])
        inline = self.write('inline_deny.xaf', '''agent {
    id = 91
    name = "Inline"
    policy {
        access { agent }
        action { read = true }
        deny { access { agent } action { read = true } }
    }
}
''')
        inline_settings = sophon.parse_xaf(inline)
        inline_policy = inline_settings['agents'][91]['inline_policy']
        self.assertFalse(inline_policy['access']['agent'])
        self.assertFalse(inline_policy['action']['read'])
        protected = self.write('protected.sph', '''connect to deny.xaf
multi-state { id = "person" state { name = "Ada" age = 31 } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.run(protected)
        self.assertEqual(caught.exception.code, 'X110')

    def test_policy_denials_are_nested_inside_inherits_block(self):
        xaf = self.write('nested_inherits.xaf', '''config { default-policy = 3 }
policy {
    id = 1
    access { multi agent source { self = true external = true } }
    action { read = true write = true }
}
policy {
    id = 2
    inherits {
        id = 1
        deny {
            access { multi source { external = true } }
            action { read = true }
        }
    }
    access { multi }
    action { read = true }
}
policy {
    id = 3
    inherits = 2
    access { multi source { external = true } }
    action { read = true }
}
''')
        settings = sophon.parse_xaf(xaf)
        effective = settings['resolved_policies'][3]
        self.assertFalse(effective['access']['multi'])
        self.assertTrue(effective['access']['agent'])
        self.assertTrue(effective['access']['source']['self'])
        self.assertFalse(effective['access']['source']['external'])
        self.assertFalse(effective['action']['read'])
        self.assertTrue(effective['action']['write'])
        missing_deny = self.write('inherits_without_deny.xaf', 'policy { id = 1 }\npolicy { id = 2 inherits { id = 1 } }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_xaf(missing_deny)
        self.assertEqual(caught.exception.code, 'X103')

    def test_linux_container_backend_creates_real_namespace_and_chroot(self):
        import sophon_sandbox
        if not sophon_sandbox.available():
            self.skipTest('Linux user/mount/PID namespaces are unavailable on this host.')
        result = sophon_sandbox.probe(self.root)
        self.assertEqual(result['cwd'], '/workspace')
        self.assertEqual(result['root'], '/')
        self.assertEqual(result['pid'], 1)
        self.assertFalse(result['host_etc_passwd_visible'])
        self.assertTrue(result['workspace_read_only'])
        self.assertTrue(result['network_isolated'])

    def test_explicit_state_types_are_enforced(self):
        typed = 'state age: integer = 18\nstate ratio: number = 1.5\nstate ready: boolean = true\n'
        parsed = sophon.parse_sph(self.write('typed.sph', typed))
        self.assertEqual(parsed.states, {'age': 18, 'ratio': 1.5, 'ready': True})
        self.expect_error(self.write('bad_type.sph', 'state age: integer = \"eighteen\"\n'), 'S242')

    def test_core_types_arithmetic_interpolation_and_datetime(self):
        result, output, _ = self.run_source('core.sph')
        self.assertEqual(result['states']['computed'], 19.0)
        self.assertEqual(result['states']['power'], 32)
        self.assertEqual(result['states']['root'], 9.0)
        self.assertEqual(result['multi-state']['person']['age'], 32)
        self.assertEqual(result['states']['full_name'], 'Person Ada, age 32')
        self.assertEqual(result['states']['next_age'], 33)
        self.assertIn('Hello Sophon', output)
        self.assertIn('person.name = Ada', output)

    def test_surface_syntax_errors_have_distinct_codes_from_multi_ask(self):
        bad_item = self.write('bad_surface_item.sph', 'surface { @invalid }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(bad_item)
        self.assertEqual(caught.exception.code, 'S252')

        unclosed = self.write('bad_surface_list.sph', 'surface { [1 2 }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(unclosed)
        self.assertEqual(caught.exception.code, 'S253')

        empty_group = self.write('empty_multi_ask.sph', 'multi-ask { id = "group" }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(empty_group)
        self.assertEqual(caught.exception.code, 'S172')

    def test_malformed_nested_blocks_return_sophon_diagnostics_not_python_errors(self):
        cases = [
            ('bad_multi_id.sph', 'multi-state { id { value } state { a = 1 b = 2 } }\n', 'S106'),
            ('bad_agent_connect.sph', 'use { agent }\nagent connect { id { 1001 } }\n', 'A002'),
            ('bad_agent_run.sph', 'use { agent }\nagent connect { id = 1001 }\nagent run { id { 1001 } message { hi } }\n', 'A008'),
            ('bad_execute.sph', 'use { execute }\nexecute { file { "worker.sph" } }\n', 'S231'),
            ('bad_component_id.sph', 'use { component }\ncomponent { id { "x" } note { text = "hello" } }\n', 'S202'),
            ('bad_note_text.sph', 'use { component }\ncomponent { note { text { nested } } }\n', 'S254'),
            ('bad_list_item.sph', 'use { component }\ncomponent { list { item { nested } } }\n', 'S254'),
            ('bad_table_row.sph', 'use { component }\ncomponent { table { row { nested } } }\n', 'S254'),
            ('bad_form_step.sph', 'use { component }\ncomponent { form { surface = "x" } }\n', 'S254'),
            ('bad_database_connect.sph', 'use { database }\ndatabase users { connect { users.svt } }\n', 'S140'),
            ('bad_file_operation.sph', 'use { file }\nfile { read = "data/a.txt" }\n', 'S224'),
        ]
        for name, source, code in cases:
            with self.subTest(name=name):
                self.expect_error(self.write(name, source), code)

    def test_string_concatenation_in_state_expression_is_rejected(self):
        for expression in ('"left" + "right"', '"left" + name'):
            with self.subTest(expression=expression):
                path = self.write('string_concat.sph', f'state name = "x"\nstate result = {expression}\n')
                with self.assertRaises(sophon.SophonError) as caught:
                    sophon.parse_sph(path)
                self.assertEqual(caught.exception.code, 'S244')
                self.assertTrue(caught.exception.hint)

    def test_plus_is_numeric_only_and_text_uses_interpolation(self):
        path = self.write('legacy_concat.sph', '''state name = "Sophon"
surface { "Hello, " + name }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S251')
        self.assertTrue(caught.exception.hint)

        result, output, _ = self.run_source('core.sph')
        self.assertEqual(result['states']['computed'], 19.0)
        self.assertIn('Person Ada, age 32', result['states']['full_name'])
        self.assertIn('Hello Sophon', output)

    def test_note_list_table_and_component_container(self):
        _, output, _ = self.run_source('components.sph')
        self.assertIn('Info', output)
        self.assertIn('Agent-first', output)
        self.assertIn('count  3', output)

    def test_multi_ask_confirmation_and_multi_confirmation(self):
        result, output, _ = self.run_source('prompts.sph', 'Izmir\nTurkey\nblue\nyes\nno\n')
        self.assertEqual(result['states']['city'], 'Izmir')
        self.assertEqual(result['states']['country'], 'Turkey')
        self.assertEqual(result['states']['notify'], True)
        self.assertEqual(result['states']['backup'], False)
        self.assertIn('Izmir', output)

    def test_observer_creates_snapshot_and_log(self):
        self.run_source('observer.sph')
        snapshot = self.root / '.sophon' / 'snapshots' / '1001.json'
        self.assertTrue(snapshot.is_file())
        data = json.loads(snapshot.read_text(encoding='utf-8'))
        self.assertEqual(data['states']['status'], 'ready')
        logs = list((self.root / 'logs').glob('*.json'))
        self.assertTrue(logs)

    def test_observer_external_source_permissions_and_snapshot(self):
        self.write('external_source.sph', 'state status = "external-ready"\n')
        self.write('external_observer.xaf', '''config {
    default-policy = 2002
    observer {
        2001 {
            watch = true
            log = true
            path = "logs"
            level = normal
            action { read = true modify = false create = false remove = false reorder = false }
        }
    }
}
policy {
    id = 2002
    access { observer source { self = false external = true } }
    action { read = true }
}
''')
        self.write('external_observer.sph', '''connect to external_observer.xaf
use { observer }
observer { id = 2001 source = "external_source.sph" watch { status } }
''')
        self.run_source('external_observer.sph')
        snapshot = self.root / '.sophon' / 'snapshots' / '2001.json'
        self.assertTrue(snapshot.is_file())
        self.assertIn('external-ready', snapshot.read_text(encoding='utf-8'))

    def test_self_observation_requires_feature_and_captures_all_states(self):
        self.write('tracked.xaf', 'features { self-observation = true }\n')
        self.write('tracked.sph', '''connect to tracked.xaf\nstate secret = \"visible-to-observer\"\n''')
        self.write('self_observer.xaf', '''config {\n    default-policy = 3002\n    observer {\n        3001 {\n            watch = true\n            log = true\n            path = \"logs\"\n            level = debug\n            action { read = true modify = true create = true remove = true reorder = true }\n        }\n    }\n}\npolicy { id = 3002 access { observer source { self = false external = true } } action { read = true } }\n''')
        self.write('self_observer.sph', '''connect to self_observer.xaf\nuse { observer }\nobserver { id = 3001 source = \"tracked.sph\" watch { self-observation } }\n''')
        self.run_source('self_observer.sph')
        snapshot = json.loads((self.root / '.sophon' / 'snapshots' / '3001.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['states']['secret'], 'visible-to-observer')

    def test_agent_inline_policy_parses_without_reference(self):
        path = self.write('inline_policy.xaf', '''config {
    agent { permission { execute = true } }
}
agent {
    id = 8101
    name = "Inline Policy Agent"
    policy {
        access { agent }
        action { read = true }
    }
    connection { provider = "openrouter" model = "mock/model" key = "UNUSED_TEST_KEY" }
}
''')
        settings = sophon.parse_xaf(path)
        self.assertIn(8101, settings['agents'])
        self.assertTrue(settings['agents'][8101]['inline_policy']['action']['read'])

    def test_database_read_write_modify_and_remove(self):
        result, output, _ = self.run_source('database.sph')
        self.assertEqual(result['states']['selected'][0]['name'], 'Ada')
        self.assertIn("'name': 'Ada'", output)
        records = sophon.parse_svt(self.root / 'data' / 'users.svt')
        grace = next(item for item in records if item['id'] == 2)
        self.assertEqual(grace['age'], 30)
        self.run_source('database_remove.sph')
        records = sophon.parse_svt(self.root / 'data' / 'users.svt')
        self.assertFalse(any(item['id'] == 2 for item in records))

    def test_file_crud_copy_move_zip_unzip_and_readback(self):
        result, output, _ = self.run_source('files.sph')
        self.assertEqual(result['states']['contents'], 'alpha beta gamma')
        self.assertEqual(result['states']['entries'], ['a.txt'])
        self.assertIn('alpha beta gamma', output)
        self.assertEqual((self.root / 'data' / 'extracted' / 'a.txt').read_text(), 'alpha beta gamma')

    def test_folder_delete_uses_folder_permission_and_is_recursive(self):
        self.run_source('file_delete.sph')
        self.assertFalse((self.root / 'data' / 'remove-me').exists())

    def test_execute_allowlisted_sph_with_its_own_xaf(self):
        _, output, _ = self.run_source('execute_main.sph')
        self.assertIn('subprogram-ok', output)

    def test_legacy_named_policy_remains_compatible(self):
        _, output, _ = self.run_source('legacy.sph')
        self.assertIn('legacy-compatible', output)

    def test_agent_api_mock_output_limit_and_state_result(self):
        old_value = os.environ.get('SOPHON_AUDIT_API_KEY')
        os.environ['SOPHON_AUDIT_API_KEY'] = 'mock-secret'
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['body'] = json.loads(request.data.decode())
            captured['timeout'] = timeout
            return _MockResponse()

        try:
            with patch('urllib.request.urlopen', side_effect=fake_urlopen) as mocked:
                result, output, _ = self.run_source('agent.sph')
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(captured['body']['max_tokens'], 123)
            self.assertEqual(result['states']['answer'], 'audit-agent-ok')
            self.assertIn('audit-agent-ok', output)
        finally:
            if old_value is None:
                os.environ.pop('SOPHON_AUDIT_API_KEY', None)
            else:
                os.environ['SOPHON_AUDIT_API_KEY'] = old_value

    def test_agent_retries_transient_transport_error(self):
        old_value = os.environ.get('SOPHON_AUDIT_API_KEY')
        os.environ['SOPHON_AUDIT_API_KEY'] = 'mock-secret'
        calls = {'n': 0}

        def fake_urlopen(_request, timeout=None):
            calls['n'] += 1
            if calls['n'] == 1:
                raise urllib.error.URLError('temporary network failure')
            return _MockResponse('retry-ok')

        try:
            with patch('urllib.request.urlopen', side_effect=fake_urlopen):
                result, _, _ = self.run_source('agent.sph')
            self.assertEqual(calls['n'], 2)
            self.assertEqual(result['states']['answer'], 'retry-ok')
        finally:
            if old_value is None:
                os.environ.pop('SOPHON_AUDIT_API_KEY', None)
            else:
                os.environ['SOPHON_AUDIT_API_KEY'] = old_value

    def test_string_literal_containing_multi_word_does_not_request_multi_access(self):
        self.write('plain.xaf', '''config { default-policy = 1 }
policy { id = 1 action { read = true } }
''')
        source = self.write('plain.sph', '''connect to plain.xaf
state message = "This sentence mentions multi-state as text."
surface { message }
''')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = sophon.run(source)
        self.assertIn('multi-state as text', out.getvalue())
        self.assertEqual(result['states']['message'], 'This sentence mentions multi-state as text.')

    def test_duplicate_state_has_actionable_diagnostic(self):
        self.expect_error(self.write('duplicate.sph', 'state item = 1\nstate item = 1\n'), 'S246')

    def test_state_reassignment_updates_only_when_value_changes(self):
        program = sophon.parse_sph(self.write('state_update.sph', '''state name = \"arda\"\nstate name = \"elif\"\nstate count: integer = 1\nstate count = 2\n'''))
        self.assertEqual(program.states['name'], 'elif')
        self.assertEqual(program.states['count'], 2)
        self.expect_error(self.write('state_type_change.sph', 'state count: integer = 1\nstate count = "two"\n'), 'S242')

    def test_duplicate_agent_connection_has_actionable_diagnostic(self):
        self.expect_error(self.write('agent_duplicate.sph', '''use { agent }
agent connect { id = 7001 }
agent connect { id = 7001 }
'''), 'A038')

    def test_file_read_requires_state_and_write_requires_data(self):
        self.expect_error(self.write('missing_state.sph', '''use { file }
file { read { path = "data/a.txt" } }
'''), 'S247')
        self.expect_error(self.write('missing_data.sph', '''use { file }
file { write { path = "data/a.txt" } }
'''), 'S247')

    def test_write_does_not_create_file_without_explicit_create(self):
        self.expect_runtime_error('write_missing.sph', '''connect to common.xaf
use { file }
file { write { path = "data/not-created.txt" data = "x" } }
''', 'F014')
        self.assertFalse((self.root / 'data' / 'not-created.txt').exists())

    def test_forbidden_file_path_is_rejected(self):
        self.expect_runtime_error('forbidden.sph', '''connect to common.xaf
use { file }
file { mkdir { path = "data/private" } }
''', 'X057')

    def test_corrupt_zip_returns_sophon_error_not_python_traceback(self):
        (self.root / 'archives').mkdir(exist_ok=True)
        (self.root / 'archives' / 'broken.zip').write_text('not a zip', encoding='utf-8')
        self.expect_runtime_error('bad_zip.sph', '''connect to common.xaf
use { file }
file { unzip { path = "archives/broken.zip" to = "data/broken" } }
''', 'F024')

    def test_existing_unzip_target_is_not_overwritten(self):
        (self.root / 'archives').mkdir(exist_ok=True)
        import zipfile
        with zipfile.ZipFile(self.root / 'archives' / 'one.zip', 'w') as archive:
            archive.writestr('one.txt', 'one')
        (self.root / 'data' / 'existing').mkdir(exist_ok=True)
        self.expect_runtime_error('existing_target.sph', '''connect to common.xaf
use { file }
file { unzip { path = "archives/one.zip" to = "data/existing" } }
''', 'F016')
        self.assertFalse((self.root / 'data' / 'existing' / 'one.txt').exists())

    def test_agent_input_attachment_is_checked_and_sent_to_provider(self):
        (self.root / 'data' / 'brief.txt').write_text('evidence text', encoding='utf-8')
        xaf = (self.root / 'agent.xaf').read_text(encoding='utf-8')
        xaf = xaf.replace('access { agent }', 'access { agent file-system }')
        xaf = xaf.replace('    agent {', '''    file-system {
        allowed_path { "data" }
        action { file { read } folder { } }
    }
    agent {''')
        (self.root / 'agent.xaf').write_text(xaf, encoding='utf-8')
        self.write('agent_file.sph', '''connect to agent.xaf
use { agent }
state answer = ""
agent connect { id = 7001 }
agent run {
    id = 7001
    input { file = "data/brief.txt" }
    message { "Summarize the attachment." }
    output = answer
}
''')
        old_value = os.environ.get('SOPHON_AUDIT_API_KEY')
        os.environ['SOPHON_AUDIT_API_KEY'] = 'mock-secret'
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured['body'] = json.loads(request.data.decode())
            return _MockResponse('attachment-ok')

        try:
            with patch('urllib.request.urlopen', side_effect=fake_urlopen):
                result, _, _ = self.run_source('agent_file.sph')
            self.assertEqual(result['states']['answer'], 'attachment-ok')
            content = captured['body']['messages'][1]['content']
            self.assertTrue(any(part.get('type') == 'text' and 'evidence text' in part.get('text', '') for part in content))
        finally:
            if old_value is None:
                os.environ.pop('SOPHON_AUDIT_API_KEY', None)
            else:
                os.environ['SOPHON_AUDIT_API_KEY'] = old_value

    def test_agent_input_token_limit_and_container_guard(self):
        old_value = os.environ.get('SOPHON_AUDIT_API_KEY')
        os.environ['SOPHON_AUDIT_API_KEY'] = 'mock-secret'
        try:
            xaf = (self.root / 'agent.xaf').read_text(encoding='utf-8')
            self.write('agent_limit.xaf', xaf.replace('max-token = 10000', 'max-token = 1'))
            source = self.write('agent_limit.sph', (self.root / 'agent.sph').read_text().replace('agent.xaf', 'agent_limit.xaf'))
            with patch('urllib.request.urlopen') as mocked:
                with self.assertRaises(sophon.SophonError) as caught:
                    sophon.run(source)
                mocked.assert_not_called()
            self.assertEqual(caught.exception.code, 'A037')

            self.write('agent_container.xaf', xaf.replace('container = false', 'container = true').replace('max-token = 10000', 'max-token = 1'))
            container_source = self.write('agent_container.sph', (self.root / 'agent.sph').read_text().replace('agent.xaf', 'agent_container.xaf'))
            with patch('urllib.request.urlopen') as mocked:
                with self.assertRaises(sophon.SophonError) as caught:
                    sophon.run(container_source)
                mocked.assert_not_called()
            self.assertEqual(caught.exception.code, 'A037')
        finally:
            if old_value is None:
                os.environ.pop('SOPHON_AUDIT_API_KEY', None)
            else:
                os.environ['SOPHON_AUDIT_API_KEY'] = old_value

    def test_database_connection_cannot_escape_project_root(self):
        project = self.root / 'subproject'
        project.mkdir()
        (project / 'common.xaf').write_text((self.root / 'common.xaf').read_text(encoding='utf-8'), encoding='utf-8')
        (self.root / 'outside.svt').write_text('vault { record { id = 1 name = "outside" } }', encoding='utf-8')
        self.write('subproject/db_escape.sph', '''connect to common.xaf
use { database }
state selected = null
database users { connect = ../outside.svt read { id = 1 state = selected } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.run(project / 'db_escape.sph')
        self.assertEqual(caught.exception.code, 'F012')
        self.assertIn('outside the project', caught.exception.message)

    def test_observer_paths_cannot_write_outside_project(self):
        common = (self.root / 'common.xaf').read_text(encoding='utf-8')
        self.write('bad_observer_path.xaf', common.replace('path = "logs"', 'path = "../outside-logs"'))
        bad_source = self.write('bad_observer_path.sph', (self.root / 'observer.sph').read_text(encoding='utf-8').replace('common.xaf', 'bad_observer_path.xaf'))
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.run(bad_source)
        self.assertEqual(caught.exception.code, 'X116')

        outside = self.root.parent / (self.root.name + '-outside-logs')
        outside.mkdir(exist_ok=True)
        link = self.root / 'escape-logs'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.rmtree(outside, ignore_errors=True)
            self.skipTest('Directory symlink creation is not supported in this environment.')
        self.write('symlink_observer.xaf', common.replace('path = "logs"', 'path = "escape-logs"'))
        source = self.write('symlink_observer.sph', (self.root / 'observer.sph').read_text(encoding='utf-8').replace('common.xaf', 'symlink_observer.xaf'))
        try:
            with self.assertRaises(sophon.SophonError) as caught:
                sophon.run(source)
            self.assertEqual(caught.exception.code, 'F012')
            self.assertFalse(list(outside.glob('*.json')))
        finally:
            link.unlink(missing_ok=True)
            shutil.rmtree(outside, ignore_errors=True)

        snapshot_outside = self.root.parent / (self.root.name + '-outside-snapshots')
        snapshot_outside.mkdir(exist_ok=True)
        internal_meta = self.root / '.sophon'
        if internal_meta.exists() and not internal_meta.is_symlink():
            shutil.rmtree(internal_meta)
        try:
            internal_meta.symlink_to(snapshot_outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.rmtree(snapshot_outside, ignore_errors=True)
            self.skipTest('Directory symlink creation is not supported in this environment.')
        try:
            clean_source = self.write('snapshot_symlink.sph', (self.root / 'observer.sph').read_text(encoding='utf-8'))
            with self.assertRaises(sophon.SophonError) as caught:
                sophon.run(clean_source)
            self.assertEqual(caught.exception.code, 'F012')
            self.assertFalse(list(snapshot_outside.glob('**/*.json')))
        finally:
            internal_meta.unlink(missing_ok=True)
            shutil.rmtree(snapshot_outside, ignore_errors=True)

    def test_multi_observer_runs_multiple_profiles(self):
        self.write('multi_observer.xaf', '''config {
    default-policy = 1
    multi { multi-observer }
    observer {
        1001 { watch = true log = true path = "logs" level = normal action { read = true modify = true create = true remove = true reorder = true } }
        1002 { watch = true log = true path = "logs" level = normal action { read = true modify = true create = true remove = true reorder = true } }
    }
}
policy {
    id = 1
    access { multi observer source { self = true } }
    action { read = true }
}
''')
        self.write('multi_observer.sph', '''connect to multi_observer.xaf
use { multi-observer }
state count = 2
multi-observer {
    id = "audit"
    observer { id = 1001 source = self watch { count } }
    observer { id = 1002 source = self watch { count } }
}
surface { count }
''')
        self.run_source('multi_observer.sph')
        self.assertTrue((self.root / '.sophon' / 'snapshots' / '1001.json').is_file())
        self.assertTrue((self.root / '.sophon' / 'snapshots' / '1002.json').is_file())

    def test_zip_slip_archive_is_rejected_before_extraction(self):
        import zipfile
        (self.root / 'archives').mkdir(exist_ok=True)
        with zipfile.ZipFile(self.root / 'archives' / 'escape.zip', 'w') as archive:
            archive.writestr('../../escaped.txt', 'not allowed')
        self.expect_runtime_error('zip_slip.sph', '''connect to common.xaf
use { file }
file { unzip { path = "archives/escape.zip" to = "data/escape" } }
''', 'F017')
        self.assertFalse((self.root / 'escaped.txt').exists())
        self.assertFalse((self.root / 'data' / 'escape').exists())

    def test_zip_rejects_symlinks_inside_source_folder(self):
        outside = self.root.parent / (self.root.name + '-zip-secret.txt')
        outside.write_text('private payload', encoding='utf-8')
        link = self.root / 'data' / 'zip-leak.txt'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            outside.unlink(missing_ok=True)
            self.skipTest('Symlink creation is not supported in this environment.')
        (self.root / 'archives').mkdir(exist_ok=True)
        try:
            self.expect_runtime_error('zip_symlink.sph', '''connect to common.xaf
use { file }
file { zip { path = "data" to = "archives/leak.zip" } }
''', 'F025')
            self.assertFalse((self.root / 'archives' / 'leak.zip').exists())
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

    def test_symlink_cannot_escape_project_root(self):
        outside = self.root.parent / (self.root.name + '-outside.txt')
        outside.write_text('secret', encoding='utf-8')
        link = self.root / 'data' / 'external-link.txt'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is not supported in this environment.')
        try:
            self.expect_runtime_error('symlink.sph', '''connect to common.xaf
use { file }
state value = ""
file { read { path = "data/external-link.txt" state = value } }
''', 'F012')
        finally:
            outside.unlink(missing_ok=True)

    def test_xaf_unknown_root_and_duplicate_config_settings_are_rejected(self):
        self.expect_error(self.write('unknown_root.xaf', 'mystery { value = true }\n'), 'X106')
        self.expect_error(self.write('duplicate_config.xaf', '''config {
 default-policy = 1
 default-policy = 2
}
policy { id = 1 }
'''), 'X100')

    def test_xaf_nested_schema_rejects_malformed_and_duplicate_settings(self):
        self.expect_error(self.write('bad_observer.xaf', '''config {
    observer { observer-name { watch = true } }
}
'''), 'X094')
        self.expect_error(self.write('duplicate_db_provider.xaf', '''config {
    database { connection { provider = "local" provider = "local" } }
}
'''), 'X096')
        self.expect_error(self.write('bad_fs_path.xaf', '''config { file-system { allowed_path { "data" "data" } } }
policy { id = 1 access { file-system } }
'''), 'X114')
        self.expect_error(self.write('duplicate_fs_action.xaf', '''config { file-system { allowed_path { "data" } action { file { read read } } } }
policy { id = 1 access { file-system } }
'''), 'X115')

    def test_svt_write_is_atomic_when_replace_fails(self):
        path = self.root / 'data' / 'users.svt'
        original = path.read_text(encoding='utf-8')
        with patch('sophon.os.replace', side_effect=OSError('simulated replace failure')):
            with self.assertRaises(sophon.SophonError) as caught:
                sophon.write_svt(path, [{'id': 9, 'name': 'New'}])
        self.assertEqual(caught.exception.code, 'V015')
        self.assertEqual(path.read_text(encoding='utf-8'), original)
        self.assertFalse(list(path.parent.glob('.users.svt.*.tmp')))

    def test_svt_duplicate_fields_and_duplicate_ids_are_rejected(self):
        self.expect_error(self.write('duplicate_field.svt', '''vault {
 record {
  id = 1
  name = "A"
  name = "B"
 }
}
'''), 'V013')
        self.expect_error(self.write('duplicate_id.svt', '''vault {
 record {
  id = 1
  name = "A"
 }
 record {
  id = 1
  name = "B"
 }
}
'''), 'V014')

    def test_random_module_executes_all_basic_generators(self):
        path = self.write('random.sph', '''use { random }
state dice = random.integer(1, 6)
state ratio = random.float()
state enabled = random.boolean()
state color = random.choice(["red", "green", "blue"])
''')
        result = sophon.run(path)
        states = result['states']
        self.assertGreaterEqual(states['dice'], 1)
        self.assertLessEqual(states['dice'], 6)
        self.assertGreaterEqual(states['ratio'], 0.0)
        self.assertLess(states['ratio'], 1.0)
        self.assertIs(type(states['enabled']), bool)
        self.assertIn(states['color'], ('red', 'green', 'blue'))

    def test_random_choice_accepts_a_list_state(self):
        path = self.write('random_list_state.sph', '''use { random }
state colors = ["red", "green", "blue"]
state selected = random.choice(colors)
''')
        selected = sophon.run(path)['states']['selected']
        self.assertIn(selected, ('red', 'green', 'blue'))

    def test_random_unknown_function_has_specific_error(self):
        self.expect_runtime_error('random_unknown.sph', 'use { random }\nstate value = random.shuffle()\n', 'S297')

    def test_random_integer_requires_integer_arguments(self):
        self.expect_runtime_error('random_type.sph', 'use { random }\nstate value = random.integer(1, 2.5)\n', 'S292')

    def test_random_module_import_after_function_definition_is_available(self):
        path = self.write('random_late_import.sph', '''function {
 id = "roll"
 input { minimum: integer maximum: integer }
 execute { state result = random.integer(minimum, maximum) }
 output: integer = result
}
use { random }
state rolled = roll(2, 8)
''')
        value = sophon.run(path)['states']['rolled']
        self.assertGreaterEqual(value, 2)
        self.assertLessEqual(value, 8)

    def test_random_module_is_available_inside_functions(self):
        path = self.write('random_function.sph', '''use { random }
function {
 id = "roll"
 input { minimum: integer maximum: integer }
 execute { state result = random.integer(minimum, maximum) }
 output: integer = result
}
state rolled = roll(10, 20)
''')
        states = sophon.run(path)['states']
        self.assertGreaterEqual(states['rolled'], 10)
        self.assertLessEqual(states['rolled'], 20)

    def test_random_requires_explicit_import(self):
        self.expect_runtime_error('random_no_import.sph', 'state value = random.integer(1, 2)\n', 'S114')

    def test_random_invalid_bounds_and_empty_choice_have_specific_errors(self):
        self.expect_runtime_error('random_bounds.sph', 'use { random }\nstate value = random.integer(5, 2)\n', 'S293')
        self.expect_runtime_error('random_empty.sph', 'use { random }\nstate value = random.choice([])\n', 'S296')

    def test_random_module_is_available_in_multi_state_values(self):
        path = self.write('random_multi.sph', '''use { random }
multi-state { id = "roll" state { die = random.integer(1, 6) color = random.choice(["red", "blue"]) } }
''')
        group = sophon.run(path)['multi-state']['roll']
        self.assertGreaterEqual(group['die'], 1)
        self.assertLessEqual(group['die'], 6)
        self.assertIn(group['color'], ('red', 'blue'))

    def test_random_functions_validate_call_shapes(self):
        self.expect_runtime_error('random_keyword.sph', 'use { random }\nstate value = random.integer(minimum=1, maximum=4)\n', 'S291')
        self.expect_runtime_error('random_float_args.sph', 'use { random }\nstate value = random.float(1)\n', 'S294')
        self.expect_runtime_error('random_choice_type.sph', 'use { random }\nstate value = random.choice("not-a-list")\n', 'S295')

    def test_random_namespace_is_reserved(self):
        self.expect_runtime_error('random_reserved.sph', 'use { random }\nstate random = 4\n', 'S290')

    def expect_runtime_error(self, name, source, code):
        path = self.write(name, source)
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.run(path)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertTrue(caught.exception.message)
        self.assertTrue(caught.exception.hint)


if __name__ == '__main__':
    unittest.main()
