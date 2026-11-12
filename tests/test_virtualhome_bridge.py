"""Integration checks for the fixed tabletop bridge; HTTP fixtures emulate the wire protocol."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain, repeat
from pathlib import Path
from unittest.mock import Mock

from simulators.virtualhome import bind_scene, compile_script, execute_transfer, observe_goal
from simulators.virtualhome_client import UnityClient, VirtualHomeError


ROOT = Path(__file__).resolve().parents[1]
ITEM, DEST, TABLE, CHAR, OTHER = 81, 206, 49, 17, 371
APPLE = json.loads((ROOT / 'tasks/apple_to_counter.json').read_text(encoding='utf-8'))
CUP = json.loads((ROOT / 'tasks/cup_to_tray.json').read_text(encoding='utf-8'))


def edge(source, relation, target):
    return {'from_id': source, 'to_id': target, 'relation_type': relation}


def scene(item='apple', destination='kitchencounter'):
    nodes = [(ITEM, item), (DEST, destination), (TABLE, 'kitchentable'),
             (CHAR, 'character'), (OTHER, 'coffeetable')]
    edges = [edge(ITEM, 'ON', TABLE)]
    if destination == 'tray':
        edges.append(edge(DEST, 'ON', TABLE))
    return {'nodes': [{'id': i, 'class_name': name} for i, name in nodes], 'edges': edges}


def recorded(bundle):
    return {'status': 'passed', 'actions': deepcopy(bundle['actions']), 'source': 'recorded_reference'}


def client_with_graphs(before, after):
    client = Mock(spec=UnityClient)
    client.check_connection.return_value = True
    client.environment_graph.side_effect = chain([deepcopy(before)], repeat(deepcopy(after)))
    client.render_script.return_value = (True, 'acknowledged')
    return client


class VirtualHomeBridgeTests(unittest.TestCase):
    def test_unique_bindings_and_script_use_the_graph_instance_ids_and_spelling(self):
        for task, item, dest, item_symbol, dest_symbol in (
            (APPLE, 'apple', 'kitchencounter', 'apple_1', 'counter_1'),
            (CUP, 'Mug', 'tray', 'cup_1', 'tray_1'),
        ):
            with self.subTest(item=item):
                graph = scene(item, dest)
                bindings = bind_scene(task, graph)
                self.assertEqual(bindings, {item_symbol: ITEM, dest_symbol: DEST, 'table_1': TABLE})
                script = compile_script(task['actions'], graph, bindings)
                self.assertEqual(script[-1], {
                    'action_index': len(task['actions']) - 1,
                    'line': f'<char0> [putback] <{item}> ({ITEM}) <{dest}> ({DEST})',
                })
                self.assertIn(f'<char0> [grab] <{item}> ({ITEM})', [s['line'] for s in script])

    def test_ambiguous_item_requires_an_existing_class_correct_explicit_binding(self):
        graph = scene('Mug', 'tray')
        graph['nodes'].extend([{'id': 5, 'class_name': 'cup'}, {'id': 7, 'class_name': 'kitchencounter'}])
        with self.assertRaises(ValueError):
            bind_scene(CUP, graph)
        self.assertEqual(bind_scene(CUP, graph, {'cup_1': ITEM})['cup_1'], ITEM)
        for wrong in ({'cup_1': 9999}, {'cup_1': ITEM, 'tray_1': 7}):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                bind_scene(CUP, graph, wrong)

    def test_source_support_must_match_the_initial_scene(self):
        for label, relations, supplied in (
            ('explicit wrong table', [edge(ITEM, 'ON', TABLE)], {'table_1': OTHER}),
            ('already at destination', [edge(ITEM, 'ON', DEST)], None),
            ('contradictory supports', [edge(ITEM, 'ON', TABLE), edge(ITEM, 'ON', OTHER)], {'table_1': TABLE}),
            ('held item', [edge(ITEM, 'ON', TABLE), edge(CHAR, 'HOLDS_RH', ITEM)], None),
        ):
            with self.subTest(label=label), self.assertRaises(ValueError):
                bind_scene(APPLE, {**scene(), 'edges': relations}, supplied)
        graph = scene('Mug', 'tray')
        graph['edges'] = [edge(ITEM, 'ON', TABLE), edge(DEST, 'ON', OTHER)]
        with self.assertRaises(ValueError):
            bind_scene(CUP, graph)

    def test_rejected_or_falsely_passed_plan_never_contacts_client(self):
        for status in ('failed', 'passed'):
            with self.subTest(status=status):
                client = Mock(spec=UnityClient)
                # Omitting the transfer cannot meet the symbolic goal even with a passed label.
                result = execute_transfer(APPLE, {'status': status, 'actions': []}, client)
                self.assertEqual(result['status'], 'invalid_plan')
                self.assertEqual(client.mock_calls, [])

    def test_rejection_stops_execution_even_if_final_observation_fails(self):
        for after in (scene(), VirtualHomeError('graph unavailable')):
            with self.subTest(observation_available=isinstance(after, dict)):
                client = client_with_graphs(scene(), after)
                client.render_script.side_effect = [(True, 'walk'), (False, 'cannot grab')]
                report = execute_transfer(APPLE, recorded(APPLE), client)
                self.assertEqual(report['status'], 'execution_failed')
                self.assertEqual(client.render_script.call_count, 2)
                self.assertEqual(report['execution'][-1]['message'], 'cannot grab')

    def test_timeout_with_uncertain_side_effect_is_unknown_and_never_retried(self):
        final = scene()
        final['edges'] = [edge(ITEM, 'ON', DEST)]
        client = client_with_graphs(scene(), final)
        client.render_script.side_effect = [(True, 'walk'), (True, 'grab'), (True, 'walk'),
                                            VirtualHomeError('no acknowledgement: timed out')]
        report = execute_transfer(APPLE, recorded(APPLE), client)
        self.assertEqual(report['status'], 'unknown')
        self.assertIsNone(report['goal_met'])
        self.assertEqual(client.render_script.call_count, 4)
        self.assertIsNone(report['execution'][-1]['success'])
        self.assertIn('[putback]', report['execution'][-1]['line'])
        self.assertEqual(client.environment_graph.call_count, 2)

    def test_all_render_acknowledgements_still_require_independent_goal_evidence(self):
        for relations, on, empty in (
            ([edge(ITEM, 'ON', TABLE)], False, True),
            ([edge(ITEM, 'ON', DEST), edge(CHAR, 'HOLDS_LH', OTHER)], True, False),
        ):
            with self.subTest(relations=relations):
                final = {**scene(), 'edges': relations}
                report = execute_transfer(APPLE, recorded(APPLE), client_with_graphs(scene(), final))
                self.assertTrue(all(step['success'] for step in report['execution']))
                self.assertEqual(report['status'], 'failed')
                self.assertIs(report['goal_met'], False)
                checks = {c['rule']: c['value'] for c in report['observed_goal']['checks']}
                self.assertEqual(checks, {'item_on_destination': on, 'character_hands_empty': empty})

    def test_missing_final_nodes_leave_goal_unknown(self):
        before = scene()
        bindings = bind_scene(APPLE, before)
        after = {'nodes': [n for n in before['nodes'] if n['id'] != ITEM], 'edges': []}
        self.assertEqual(observe_goal(APPLE, after, bindings, CHAR)['status'], 'unknown')

    def test_cli_recorded_transfer_against_loopback_protocol_fixture(self):
        # A local HTTP peer advances one fixture graph on grab/putback. No Unity engine is involved.
        graph = scene()
        received = []
        rendered = []
        expected = [f'<char0> [walk] <apple> ({ITEM})', f'<char0> [grab] <apple> ({ITEM})',
                    f'<char0> [walk] <kitchencounter> ({DEST})',
                    f'<char0> [putback] <apple> ({ITEM}) <kitchencounter> ({DEST})']

        class ProtocolFixture(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                action = request['action']
                received.append(action)
                reply = {'success': True, 'message': 'ok'}
                if action == 'environment_graph':
                    reply['message'] = json.dumps(graph)
                elif action == 'render_script':
                    lines = request['stringParams'][1:]
                    index = len(rendered)
                    rendered.extend(lines)
                    if index >= len(expected) or lines != [expected[index]]:
                        reply = {'success': False, 'message': 'unexpected command'}
                    elif index == 1:
                        graph['edges'] = [edge(CHAR, 'HOLDS_RH', ITEM)]
                    elif index == 3:
                        graph['edges'] = [edge(ITEM, 'ON', DEST)]
                elif action not in ('idle', 'clear', 'environment', 'add_character'):
                    reply = {'success': False, 'message': 'unknown operation'}
                body = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(('127.0.0.1', 0), ProtocolFixture) as server, tempfile.TemporaryDirectory() as directory:
            worker = threading.Thread(target=server.serve_forever, args=(0.02,), daemon=True)
            worker.start()
            try:
                run = subprocess.run([sys.executable, '-B', '-S', 'main.py', 'virtualhome', 'run',
                                      '--recorded', '--task', 'apple_to_counter', '--port', str(server.server_port),
                                      '--output-dir', directory], cwd=ROOT, capture_output=True, text=True, timeout=20)
            finally:
                server.shutdown()
                worker.join(2)
            self.assertEqual(run.returncode, 0, (run.stdout, run.stderr))
            output = Path(directory)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(json.loads(run.stdout), report)
            self.assertEqual((report['status'], report['goal_met']), ('passed', True))
            self.assertEqual(received, ['idle', 'clear', 'environment', 'add_character', 'environment_graph',
                                        *(['render_script'] * 4), 'environment_graph'])
            self.assertEqual(rendered, expected)
            self.assertEqual((output / 'script.txt').read_text(encoding='utf-8').splitlines(), expected)
            for name in ('after_graph', 'before_graph', 'bindings'):
                self.assertEqual(json.loads((output / (name + '.json')).read_text(encoding='utf-8')), report[name])
            self.assertEqual(report['before_graph']['edges'], [edge(ITEM, 'ON', TABLE)])
            self.assertEqual(report['after_graph']['edges'], [edge(ITEM, 'ON', DEST)])


if __name__ == '__main__':
    unittest.main()
