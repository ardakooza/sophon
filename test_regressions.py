"""Focused regression tests for the unified observer and multi-state syntax."""
import json
import tempfile
import unittest
from pathlib import Path

import sophon


class SophonRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def test_multi_state_initial_update_and_reorder(self):
        path = self.write('multi.sph', '''multi-state {
    id = "user"
    state {
        name = "Arda"
        age = 17
        score = 9
    }
}
multi-state { id = "user" state { age = 18 } }
multi-state { id = "user" state { score at [1] } }
multi-state { id = "user" state { age = 19 at [2] } }
''')
        program = sophon.parse_sph(path)
        self.assertEqual(list(program.groups['user']), ['score', 'age', 'name'])
        self.assertEqual(program.groups['user']['age'], 19)

    def test_multi_state_initial_declaration_requires_two_fields(self):
        path = self.write('small.sph', '''multi-state {
    id = "user"
    state { age = 18 }
}
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S105')

    def test_multi_state_cannot_add_fields_during_update(self):
        path = self.write('unknown.sph', '''multi-state { id = "user" state { name = "Arda" age = 18 } }
multi-state { id = "user" state { height = 180 } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S107')

    def test_unified_multi_observer_uses_ids_and_sources(self):
        path = self.write('observers.sph', '''use { multi-observer }
state level = 12
multi-state { id = "user" state { name = "Arda" age = 18 } }
multi-observer {
    id = "group"
    description = "two observers"
    observer {
        id = "local"
        source = self
        watch { user user.age level }
    }
    observer {
        id = "external"
        source = "other.sph"
        watch { user.age }
    }
}
''')
        program = sophon.parse_sph(path)
        self.assertEqual(set(program.observers), {'local', 'external'})
        self.assertEqual(program.observers['local']['source'], 'self')
        self.assertEqual(program.observers['external']['source'], 'other.sph')
        self.assertEqual(program.observer_groups['group']['description'], 'two observers')

    def test_watch_must_not_be_empty(self):
        path = self.write('empty.sph', '''use { observer }
observer { id = "empty" source = self watch { } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S121')

    def test_xaf_v2_config_agent_defaults_and_numeric_policy(self):
        path = self.write('v2.xaf', '''config {
    agent {
        permission { execute = true }
        security { container = false }
        timing {
            delay = 45
            timeout = 120
            retry { duration = 2 count = 3 }
        }
        input { max-token = 12000 max-bytes = 2097152 }
        output { max-token = 4096 }
        connection { provider = "openrouter" model = "provider/model" key = "OPENROUTER_API_KEY" }
    }
}
agent {
    id = 1001
    name = "Research Agent"
    policy = 2001
}
policy {
    id = 2001
    access { agent }
    action { read = true }
}
''')
        settings = sophon.parse_xaf(path)
        agent = settings['agents'][1001]
        self.assertEqual(agent['policy'], 2001)
        self.assertTrue(agent['permission']['execute'])
        self.assertEqual(agent['timing']['retry'], {'duration': 2.0, 'count': 3})
        self.assertEqual(agent['input']['max-token'], 12000)
        self.assertEqual(agent['output']['max-token'], 4096)
        self.assertEqual(settings['resolved_policies'][2001]['access']['agent'], True)

    def test_xaf_v2_inline_agent_policy(self):
        path = self.write('inline.xaf', '''agent {
    id = 1002
    name = "Inline Agent"
    policy {
        access { agent }
        action { read = true }
    }
}
''')
        settings = sophon.parse_xaf(path)
        agent, policy = sophon._policy_for_agent(settings, 1002)
        self.assertEqual(agent['name'], 'Inline Agent')
        self.assertTrue(policy['access']['agent'])
        self.assertTrue(policy['action']['read'])

    def test_xaf_v2_observer_numeric_id_and_source_access(self):
        self.write('main.xaf', '''config {
    default-policy = 2001
    observer {
        1001 {
            watch = true
            log = true
            path = "logs"
            level = normal
            action { read = true modify = true create = true remove = false reorder = false }
        }
    }
}
policy {
    id = 2001
    access { observer source { self = true external = false } }
    action { read = true }
}
''')
        path = self.write('main.sph', '''connect to main.xaf
use { observer }
state status = "ready"
observer { id = 1001 source = self watch { status } }
''')
        program, settings = sophon._load_runtime(path)
        self.assertIn(1001, program.observers)
        self.assertEqual(settings['self'][1001]['path'], 'logs')

    def test_xaf_v2_execute_file_allowlist(self):
        path = self.write('execute.xaf', '''config {
    execute { file { "worker.sph" } command { } }
}
policy {
    id = 3001
    access { execute }
    action { read = true }
}
''')
        settings = sophon.parse_xaf(path)
        policy = settings['resolved_policies'][3001]
        allowed = {'file': 'worker.sph', 'command': None}
        denied = {'file': 'other.sph', 'command': None}
        sophon._exec_grant(policy['access'], allowed, 'worker.sph', self.root, 1, settings['config']['execute'])
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._exec_grant(policy['access'], denied, 'other.sph', self.root, 1, settings['config']['execute'])
        self.assertEqual(caught.exception.code, 'X053')

    def test_xaf_v2_access_rejects_input(self):
        path = self.write('input-access.xaf', '''policy {
    id = 4001
    access { input }
}
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_xaf(path)
        self.assertEqual(caught.exception.code, 'X071')

    def test_xaf_v2_policy_id_must_be_integer(self):
        path = self.write('string-id.xaf', '''policy {
    id = "policy-a"
    access { agent }
}
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_xaf(path)
        self.assertEqual(caught.exception.code, 'X070')

    def test_external_self_observation_requires_xaf_feature(self):
        self.write('source.sph', 'state a = 1\nstate b = 2\n')
        self.write('main.xaf', '''policy main.sph { access { state multi-state observer } action { read = true } }
observer {
    whole {
        watch = true
        log = true
        path = "logs"
        level = normal
        action { read = true }
        source { self = true external = true }
    }
}
''')
        path = self.write('main.sph', '''connect to main.xaf
use { observer }
observer { id = "whole" source = "source.sph" watch { self-observation } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._load_runtime(path)
        self.assertEqual(caught.exception.code, 'O207')

    def test_self_source_conflicts_with_enabled_feature(self):
        self.write('main.xaf', '''features { self-observation = true }
policy main.sph { access { state multi-state observer } action { read = true } }
observer {
    local {
        watch = true
        log = true
        path = "logs"
        level = normal
        action { read = true }
        source { self = true external = true }
    }
}
''')
        path = self.write('main.sph', '''connect to main.xaf
use { observer }
state level = 1
observer { id = "local" source = self watch { level } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._load_runtime(path)
        self.assertEqual(caught.exception.code, 'X061')

    def test_create_and_connect_command_chains(self):
        for index, command in enumerate((
            'create xaf & connect to main.xaf',
            'create & connect to main.xaf',
        )):
            path = self.write(f'chain{index}.sph', command + '\nstate value = 1\n')
            program = sophon.parse_sph(path)
            self.assertEqual(program.connect, 'main.xaf')

    def test_old_observe_declaration_is_rejected(self):
        path = self.write('old.sph', 'observe { source = "source.sph" name = "old" }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S100')

    def test_external_self_observation_records_whole_source(self):
        self.write('source.sph', 'connect to source.xaf\nstate a = 1\nstate b = 2\n')
        self.write('source.xaf', 'features { self-observation = true }\n')
        self.write('main.xaf', '''policy main.sph { access { state multi-state observer } action { read = true } }
observer {
    whole {
        watch = true
        log = true
        path = "logs"
        level = normal
        action { read = true }
        source { self = true external = true }
    }
}
''')
        path = self.write('main.sph', '''connect to main.xaf
use { observer }
observer { id = "whole" source = "source.sph" watch { self-observation } }
''')
        sophon.run(path)
        snapshot = next((self.root / '.sophon' / 'snapshots').glob('*.json'))
        self.assertEqual(json.loads(snapshot.read_text())['states'], {'a': 1, 'b': 2})

    def test_create_connect_generates_target_xaf(self):
        path = self.write('create.sph', 'create & connect to custom.xaf\nstate value = 1\n')
        sophon._load_runtime(path)
        self.assertTrue((self.root / 'custom.xaf').exists())

    def test_old_connect_form_is_rejected(self):
        path = self.write('old-connect.sph', 'connect main.xaf\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'X002')

    def test_old_xaf_observe_blocks_are_rejected(self):
        path = self.write('old-observe.xaf', 'observe source.sph { observer { } }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_xaf(path)
        self.assertEqual(caught.exception.code, 'X062')

    def test_old_xaf_self_observer_block_is_rejected(self):
        path = self.write('old-self.xaf', 'self-observer { watch = true }\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_xaf(path)
        self.assertEqual(caught.exception.code, 'X063')


    def test_multi_ask_uses_sibling_ask_blocks(self):
        path=self.write('multi-ask.sph', '''multi-ask {
    id = "group"
    ask { id = "first" prompt = "First:" state = first }
    ask { id = "second" prompt = "Second:" state = second }
}
''')
        program=sophon.parse_sph(path)
        self.assertEqual([x['target'] for x in program.asks],['first','second'])
        self.assertEqual([x['group'] for x in program.asks],['group','group'])

    def test_multi_ask_rejects_nested_ask_syntax(self):
        path=self.write('nested-ask.sph', '''multi-ask {
    id = "group"
    ask {
        id = "section"
        ask { id = "question" prompt = "?" state = answer }
    }
}
''')
        with self.assertRaises(sophon.SophonError):
            sophon.parse_sph(path)

    def test_ask_duration_requires_default_when_required(self):
        path=self.write('timed.sph', '''ask {
    id = "answer"
    prompt = "Answer:"
    state = answer
    requirement = true
    duration = 5
}
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S175')

    def test_ask_duration_and_default_are_parsed(self):
        path=self.write('timed.sph', '''ask {
    id = "answer"
    prompt = "Answer:"
    state = answer
    requirement = true
    default = "fallback"
    duration = 5
}
''')
        program=sophon.parse_sph(path)
        self.assertEqual(program.asks[0]['duration'],5.0)
        self.assertEqual(program.asks[0]['default'],'fallback')

    def test_optional_confirmation_skips_and_default_is_selected(self):
        source='''confirmation {
    id = "confirm"
    prompt = "Continue?"
    choice { yes = true no = false }
    state = result
    requirement = false
    default = "no"
}
'''
        path=self.write('confirm.sph',source)
        spec=sophon.parse_sph(path).asks[0]
        self.assertEqual(spec['default'],('no',False))
        answer=sophon._read_confirmation(spec,__import__('io').StringIO('\\n'),__import__('io').StringIO())
        self.assertEqual(answer,('no',False))
        spec['default']=None
        answer=sophon._read_confirmation(spec,__import__('io').StringIO('\\n'),__import__('io').StringIO())
        self.assertIsNone(answer)

    def test_component_accepts_component_id(self):
        path=self.write('component.sph','''use { component }
component {
    id = "dashboard"
    note { text = "Ready" }
}
''')
        program=sophon.parse_sph(path)
        self.assertEqual(program.renders[0]['id'],'dashboard')

    def test_agent_run_accepts_task_and_output_state(self):
        path=self.write('agent.sph','''use { agent }
agent connect { id = "assistant" }
agent run {
    id = "assistant"
    task { "Analyze source." }
    output = answer
}
state answer = ""
''')
        program=sophon.parse_sph(path)
        self.assertEqual(program.agent_calls[0][0],'task')
        self.assertEqual(program.agent_calls[0][4],'answer')

    def test_agent_run_rejects_message_and_task_together(self):
        path=self.write('agent.sph','''use { agent }
agent run {
    id = "assistant"
    message { "Hello" }
    task { "Analyze" }
}
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'A032')

    def test_file_system_requires_allowed_path_and_blocks_forbidden_path(self):
        xaf=self.write('paths.xaf','''policy app.sph {
    access {
        file-system {
            allowed_path { "data" }
            forbidden_path { "data/private" }
            action { file { create read modify } folder { create read } }
        }
    }
    action { read = true }
}
''')
        settings=sophon.parse_xaf(xaf)
        fs=settings['policies']['app.sph']['access']['file-system']
        self.assertEqual(fs['paths'],['data'])
        self.assertEqual(fs['forbidden'],['data/private'])
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._fs_grant({'file-system':fs},'file','read',
                             [self.root/'data'/'private'/'secret.txt'],self.root,1)
        self.assertEqual(caught.exception.code,'X057')

    def test_multi_observer_requires_its_own_module(self):
        path=self.write('multi-observer.sph','''use { observer }
multi-observer { id = "group" observer { id = "one" source = self watch { state } } }
state state = 1
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S114')


    def test_self_observation_must_be_the_only_watch_entry(self):
        path=self.write('watch.sph','''use { observer }
observer { id = "whole" source = self watch { self-observation level } }
state level = 1
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S121')

    def test_same_source_cannot_have_another_observer_after_self_observation(self):
        path=self.write('duplicate-source.sph','''use { observer }
observer { id = "whole" source = "source.sph" watch { self-observation } }
observer { id = "one-field" source = "source.sph" watch { level } }
state level = 1
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S135')

    def test_observer_source_class_is_controlled_by_xaf(self):
        self.write('main.xaf','''policy main.sph { access { state multi-state observer } action { read = true } }
observer {
    local {
        source { self = false external = true }
        watch = true
        log = false
        path = null
        action { read = true }
    }
}
''')
        path=self.write('main.sph','''connect to main.xaf
use { observer }
state level = 1
observer { id = "local" source = self watch { level } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._load_runtime(path)
        self.assertEqual(caught.exception.code,'X066')

    def test_file_module_requires_scoped_allowed_path(self):
        self.write('main.xaf','''policy main.sph { access { state multi-state } action { read = true } }
''')
        path=self.write('main.sph','''connect to main.xaf
use { file }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._load_runtime(path)
        self.assertEqual(caught.exception.code,'X056')

    def test_agent_delay_is_parsed_from_xaf(self):
        xaf=self.write('agents.xaf','''agent assistant {
    name = "assistant"
    policy = "agent-policy"
    execute = true
    delay = 12.5
    api-key { provider = "openrouter" model = "test-model" key = "TEST_KEY" }
}
policy agent-policy { access { state } action { read = true } }
''')
        settings=sophon.parse_xaf(xaf)
        self.assertEqual(settings['agents']['assistant']['delay'],12.5)


    def test_ask_duration_times_out_and_uses_default(self):
        import os
        import time
        read_fd,write_fd=os.pipe()
        stream=os.fdopen(read_fd,'r',encoding='utf-8')
        try:
            started=time.monotonic()
            result=sophon._readline_timeout(stream,0.05)
            self.assertIsNone(result)
            self.assertGreaterEqual(time.monotonic()-started,0.04)
        finally:
            stream.close()
            os.close(write_fd)

    def test_optional_ask_can_be_skipped(self):
        import io
        spec={'id':'optional','prompt':'Optional:','suggestion':None,'secret':False,
              'default':None,'requirement':False,'duration':None,'type':'text'}
        value=sophon._read_answer(spec,io.StringIO('\n'),io.StringIO())
        self.assertIsNone(value)


    def test_agent_response_is_written_to_output_state(self):
        from unittest.mock import patch
        path=self.write('agent-output.sph','''use { agent }
agent connect { id = "assistant" }
agent run {
    id = "assistant"
    message { "Say hello." }
    output = answer
}
state answer = ""
''')
        program=sophon.parse_sph(path)
        settings={'agents':{'assistant':{'execute':True,'delay':3,'name':'assistant'}},
                  'resolved_policies':{'agent-policy':{'action':{'read':True},'access':{}}},
                  'policies':{}}
        with patch.object(sophon,'_policy_for_agent',return_value=(settings['agents']['assistant'],
                    settings['resolved_policies']['agent-policy'])), \
             patch.object(sophon,'_agent_api_call',return_value='Hello') as call:
            sophon.execute_agents(path,settings,program.agent_connects,program.agent_calls,emit=False,program=program)
        self.assertEqual(program.states['answer'],'Hello')
        self.assertEqual(call.call_args.kwargs['timeout'],3)
        self.assertEqual(call.call_args.kwargs['mode'],'run')


    def test_typed_states_infer_types_and_evaluate_expressions(self):
        source = 'state base: integer = 4\nstate power = base ^ 2\nstate total: integer = power + 3 * 2\nstate root: float = sqrt(81)\nstate name = \"Arda\"\nstate message = \"Hello, {name}\"\n'
        path=self.write('expressions.sph',source)
        program=sophon.parse_sph(path)
        self.assertEqual(program.states, {'base':4,'power':16,'total':22,'root':9.0,
                                          'name':'Arda','message':'Hello, Arda'})

    def test_typed_state_rejects_incompatible_value(self):
        path=self.write('bad-type.sph','state count: integer = \"four\"\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S242')

    def test_expression_rejects_division_by_zero(self):
        path=self.write('zero.sph','state result = 8 / 0\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S243')


    def test_datetime_module_exposes_local_values_and_iso_weekday(self):
        path = self.write('datetime.sph', """use { datetime }
state today = date
state current_time = time
state day = date.day
state month = date.month
state year = date.year
state weekday = date.weekday
state timezone = date.timezone
state hour = time.hour
state minute = time.minute
state second = time.second
state next_year = date.year + 1
""")
        program = sophon.parse_sph(path)
        from datetime import datetime
        now = datetime.now().astimezone()
        self.assertEqual(program.states['date'], now.date().isoformat())
        self.assertEqual(program.states['time'], now.strftime('%H:%M:%S'))
        self.assertEqual(program.states['date.day'], now.day)
        self.assertEqual(program.states['date.month'], now.month)
        self.assertEqual(program.states['date.year'], now.year)
        self.assertEqual(program.states['date.weekday'], now.isoweekday())
        self.assertTrue(program.states['date.timezone'])
        self.assertEqual(program.states['time.hour'], now.hour)
        self.assertEqual(program.states['time.minute'], now.minute)
        self.assertEqual(program.states['time.second'], now.second)
        self.assertEqual(program.states['next_year'], now.year + 1)

    def test_datetime_is_local_module_and_does_not_require_xaf(self):
        path = self.write('datetime-local.sph', 'use { datetime }\nstate weekday = date.weekday\n')
        parsed, settings = sophon._load_runtime(path)
        self.assertIn('datetime', parsed.uses)
        self.assertEqual(settings['policies'], {})
        self.assertFalse(path.with_suffix('.xaf').exists())

    def test_datetime_builtins_are_available_to_surface(self):
        path = self.write('datetime-surface.sph', 'use { datetime }\nsurface { date date.day date.weekday date.timezone time time.hour }\n')
        program = sophon.parse_sph(path)
        self.assertEqual(program.renders[0]['kind'], 'surface')
        self.assertEqual([x[0][1] for x in program.renders[0]['items']],
                         ['date', 'date.day', 'date.weekday', 'date.timezone', 'time', 'time.hour'])

    def test_datetime_reserved_names_cannot_be_redeclared(self):
        path = self.write('datetime-reserved.sph', 'use { datetime }\nstate date = "custom"\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S245')

    def test_datetime_requires_import(self):
        path = self.write('datetime-no-import.sph', 'state today = date\n')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code, 'S102')

    def test_file_list_requires_a_path(self):
        path=self.write('list.sph','''use { file }
file { list { state entries } }
''')
        with self.assertRaises(sophon.SophonError) as caught:
            sophon.parse_sph(path)
        self.assertEqual(caught.exception.code,'S225')


    def test_xaf_v2_generated_scaffold_uses_numeric_ids_and_config(self):
        path = self.write('generated.sph', '''connect to generated.xaf
use { observer agent }
state status = "ready"
observer { id = 1001 source = self watch { status } }
agent connect { id = 7001 }
''')
        program = sophon.parse_sph(path)
        content, _ = sophon.render_xaf(path, program, program.agent_connects, program.uses,
                                       program.connect, program.observers, program.databases)
        target = self.write('generated-output.xaf', content)
        settings = sophon.parse_xaf(target)
        self.assertIn(7001, settings['agents'])
        self.assertIn(2001, settings['policies'])
        self.assertIn(1001, settings['config']['observer'])
        self.assertTrue(settings['resolved_policies'][2001]['access']['observer'])
        self.assertTrue(settings['resolved_policies'][2001]['access']['source']['self'])
        self.assertTrue(settings['resolved_policies'][2001]['access']['agent'])

    def test_observer_watch_without_log_keeps_internal_snapshot_only(self):
        source = self.write('observed.sph', 'state value = 1\n')
        snapshot_dir = self.root / '.sophon' / 'snapshots'
        log_dir = self.root / 'logs'
        cfg = {'watch': True, 'log': False, 'path': None, 'level': 'compact',
               'actions': {'read': True, 'create': True}}
        result = sophon.record_snapshot(snapshot_dir, log_dir, 1001, source,
                                        {'states': {'value': 1}, 'multi-state': {}}, cfg)
        self.assertIsNone(result)
        self.assertTrue((snapshot_dir / '1001.json').exists())
        self.assertFalse(log_dir.exists())

    def test_xaf_v2_file_write_uses_policy_write_action(self):
        fs = sophon._parse_file_system('''allowed_path { "." }
action { file { modify } folder { read } }''', self.root / 'policy.xaf')
        access = {'file-system': True}
        target = [self.root / 'data.txt']
        with self.assertRaises(sophon.SophonError) as caught:
            sophon._fs_grant(access, 'file', 'modify', target, self.root, 1,
                             config_fs=fs, policy_actions={'write': False, 'modify': True},
                             v2=True, operation='write')
        self.assertEqual(caught.exception.code, 'X051')
        sophon._fs_grant(access, 'file', 'modify', target, self.root, 1,
                         config_fs=fs, policy_actions={'write': True, 'modify': True},
                         v2=True, operation='write')

    def test_agent_connect_accepts_integer_id(self):
        path = self.write('agent-id.sph', '''use { agent }
agent connect { id = 1001 }
''')
        program = sophon.parse_sph(path)
        self.assertEqual(program.agent_connects, [1001])

if __name__ == '__main__':
    unittest.main()
