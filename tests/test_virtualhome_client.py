import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue

from simulators.virtualhome_client import UnityClient, VirtualHomeError


class UnityTestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.received.append((self.path, self.headers["Content-Type"], payload))
        status, body, delay = self.server.responses.get_nowait()
        if delay:
            time.sleep(delay)
        body = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # The timeout test closes the socket before this reply.

    def log_message(self, *args):
        pass


class UnityClientTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), UnityTestHandler)
        self.server.received = []
        self.server.responses = Queue()
        self.worker = threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True)
        self.worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.worker.join, 2)
        self.addCleanup(self.server.shutdown)
        self.client = UnityClient(port=self.server.server_port, timeout=2)

    def reply(self, body, status=200, delay=0):
        self.server.responses.put((status, body, delay))

    def test_unity_wire_protocol_and_distinct_request_ids(self):
        graph = {"nodes": [{"id": 12, "class_name": "book"}], "edges": []}
        for _ in range(5):
            self.reply({"success": True})
        self.reply({"success": True, "message": json.dumps(graph)})
        self.reply({"success": True, "message": '{"executed": 2}'})

        self.assertTrue(self.client.check_connection())
        self.client.reset(2)
        self.assertEqual(self.client.reset_protocol, "clear_environment")
        self.client.add_character()
        self.client.add_character("Chars/Female1", "bedroom")
        self.assertEqual(self.client.environment_graph(), graph)
        lines = ["<char0> [Walk] <book> (12)", "<char0> [Grab] <book> (12)"]
        self.assertEqual(self.client.render_script(lines), (True, {"executed": 2}))

        requests = []
        ids = []
        for path, content_type, payload in self.server.received:
            self.assertEqual((path, content_type), ("/", "application/json"))
            ids.append(payload.pop("id"))
            requests.append(payload)
        self.assertTrue(all(isinstance(i, str) and i for i in ids))
        self.assertEqual(len(set(ids)), 7)
        self.assertEqual(requests[:3], [
            {"action": "idle"}, {"action": "clear", "intParams": [2]},
            {"action": "environment", "intParams": [2]},
        ])
        for request, resource, room, mode in [
            (requests[3], "Chars/Male1", "", "random"),
            (requests[4], "Chars/Female1", "bedroom", "fix_room"),
        ]:
            self.assertEqual(request["action"], "add_character")
            self.assertEqual(len(request["stringParams"]), 1)
            self.assertEqual(json.loads(request["stringParams"][0]), {
                "character_resource": resource, "initial_room": room, "mode": mode,
                "character_position": {"x": 0, "y": 0, "z": 0},
            })
        self.assertEqual(requests[5], {"action": "environment_graph"})
        self.assertEqual(requests[6]["action"], "render_script")
        params = requests[6]["stringParams"]
        self.assertEqual(params[1:], lines)
        options = json.loads(params[0])
        self.assertIs(options["recording"], False)
        self.assertIs(options["skip_animation"], True)
        self.assertIs(options["find_solution"], False)
        self.assertIs(options["skip_execution"], False)

    def test_clear_and_environment_must_both_acknowledge_reset(self):
        self.reply({"success": False, "message": "clear refused"})
        with self.assertRaisesRegex(VirtualHomeError, "clear refused"):
            self.client.reset(1)
        self.assertEqual(len(self.server.received), 1)
        self.reply({"success": True})
        self.reply({"success": False, "message": "unknown apartment"})
        with self.assertRaisesRegex(VirtualHomeError, "unknown apartment"):
            self.client.reset(1)
        self.assertEqual(len(self.server.received), 3)
        self.assertIsNone(self.client.reset_protocol)

    def test_v2_reset_after_an_explicit_unknown_clear(self):
        self.reply({"success": False, "message": " Unknown action clear "})
        self.reply({"success": True})
        self.client.reset(3)
        requests = [(r["action"], r["intParams"]) for _, _, r in self.server.received]
        self.assertEqual(requests, [("clear", [3]), ("reset", [3])])
        self.assertEqual(self.client.reset_protocol, "reset")

    def test_reset_does_not_fall_back_on_http_error_or_similar_message(self):
        self.reply({"success": False, "message": "Unknown action clear"}, status=503)
        with self.assertRaisesRegex(VirtualHomeError, "503"):
            self.client.reset(0)
        self.reply({"success": False, "message": "Unknown action clear after partial reset"})
        with self.assertRaisesRegex(VirtualHomeError, "partial reset"):
            self.client.reset(0)
        self.assertEqual([r["action"] for _, _, r in self.server.received], ["clear", "clear"])
        self.assertIsNone(self.client.reset_protocol)

    def test_render_failure_keeps_engine_message_and_http_status(self):
        lines = ["<char0> [Walk] <book> (12)"]
        self.reply({"success": False, "message": "book is unreachable"})
        self.assertEqual(self.client.render_script(lines), (False, "book is unreachable"))
        self.reply({"message": "scene is busy"}, status=503)
        with self.assertRaisesRegex(VirtualHomeError, "503.*scene is busy"):
            self.client.render_script(lines)
        self.assertEqual(len(self.server.received), 2)

    def test_malformed_responses(self):
        for body in [b"not JSON", [], {"message": "OK"}, {"success": 1}]:
            with self.subTest(body=body):
                self.reply(body)
                with self.assertRaises(VirtualHomeError):
                    self.client.check_connection()
        for message in ["bad", "{}", '{"nodes": [], "edges": [2]}']:
            with self.subTest(message=message):
                self.reply({"success": True, "message": message})
                with self.assertRaisesRegex(VirtualHomeError, "environment_graph"):
                    self.client.environment_graph()

    def test_timeout_does_not_resend_a_command(self):
        self.reply({"success": True}, delay=0.35)
        client = UnityClient(port=self.server.server_port, timeout=0.1)
        with self.assertRaisesRegex(VirtualHomeError, "clear.*timed out"):
            client.reset(1)
        self.assertEqual([r["action"] for _, _, r in self.server.received], ["clear"])

    def test_connection_refused_names_endpoint(self):
        # An exclusively bound but non-listening socket reserves an unused port.
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            client = UnityClient(port=reserved.getsockname()[1], timeout=1)
            with self.assertRaisesRegex(VirtualHomeError, "idle.*127.0.0.1"):
                client.check_connection()
