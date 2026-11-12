"""HTTP client for an already running VirtualHome Unity simulator."""

import json
import math
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


class VirtualHomeError(RuntimeError):
    """The simulator rejected a command or could not acknowledge it."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_detail(body):
    text = body.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    return payload.get("message", text) if isinstance(payload, dict) else text


class UnityClient:
    def __init__(self, host="127.0.0.1", port=8080, timeout=30):
        if (not isinstance(host, str) or not host or not host.isprintable()
                or any(c.isspace() or c in "/?#@\\" for c in host)):
            raise ValueError("host must be a hostname or IP address.")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds.")
        if ":" in host:
            from ipaddress import IPv6Address
            # URLs require brackets around a literal IPv6 address.
            host = f"[{IPv6Address(host.removeprefix('[').removesuffix(']'))}]"
        self.endpoint = f"http://{host}:{port}/"
        self.timeout = timeout
        self.reset_protocol = None
        self._http = build_opener(ProxyHandler({}), _NoRedirect())

    def _post(self, action, **params):
        payload = {"id": uuid4().hex, "action": action, **params}
        request = Request(self.endpoint, data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._http.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    detail = _http_detail(response.read(4096))
                    raise VirtualHomeError(f"{action}: HTTP {response.status} {detail}")
                body = response.read()
        except HTTPError as exc:
            with exc:
                detail = _http_detail(exc.read(4096))
            raise VirtualHomeError(f"{action}: HTTP {exc.code} {detail}") from exc
        except (OSError, HTTPException) as exc:
            raise VirtualHomeError(f"{action}: no acknowledgement from {self.endpoint} ({exc})") from exc
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise VirtualHomeError(f"{action}: simulator returned invalid JSON.") from exc
        if not isinstance(result, dict) or type(result.get("success")) is not bool:
            raise VirtualHomeError(f"{action}: response must contain a boolean success field.")
        return result

    def _require_success(self, action, **params):
        result = self._post(action, **params)
        if not result["success"]:
            raise VirtualHomeError(f"{action} failed: {result.get('message', 'no message from Unity')}")
        return result

    def check_connection(self) -> bool:
        return self._post("idle")["success"]

    def reset(self, environment: int) -> None:
        if type(environment) is not int or environment < 0:
            raise ValueError("environment must be a nonnegative integer scene index.")
        self.reset_protocol = None
        clear = self._post("clear", intParams=[environment])
        if clear["success"]:
            self._require_success("environment", intParams=[environment])
            self.reset_protocol = "clear_environment"
            return
        message = clear.get("message", "no message from Unity")
        if not isinstance(message, str) or message.strip() != "Unknown action clear":
            raise VirtualHomeError(f"clear failed: {message}")
        # VirtualHome v2.0 reports an unknown command and uses one reset request.
        self._require_success("reset", intParams=[environment])
        self.reset_protocol = "reset"

    def add_character(self, resource="Chars/Male1", initial_room="") -> None:
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError("resource must be a nonempty character resource name.")
        if initial_room not in ("", "kitchen", "bedroom", "livingroom", "bathroom"):
            raise ValueError("initial_room must be empty, kitchen, bedroom, livingroom or bathroom.")
        character = {
            "character_resource": resource,
            "mode": "fix_room" if initial_room else "random",
            "character_position": {"x": 0, "y": 0, "z": 0},
            "initial_room": initial_room,
        }
        self._require_success("add_character", stringParams=[json.dumps(character)])

    def environment_graph(self) -> dict:
        response = self._require_success("environment_graph")
        try:
            graph = json.loads(response.get("message"))
        except (TypeError, ValueError) as exc:
            raise VirtualHomeError("environment_graph: message must contain a JSON scene graph.") from exc
        if not isinstance(graph, dict) or any(
            not isinstance(graph.get(key), list) or any(not isinstance(entry, dict) for entry in graph[key])
            for key in ("nodes", "edges")
        ):
            raise VirtualHomeError("environment_graph: expected nodes and edges arrays of objects.")
        return graph

    def render_script(self, script: list[str]) -> tuple[bool, object]:
        if not isinstance(script, list) or not script or any(
            not isinstance(line, str) or not line.strip() for line in script
        ):
            raise ValueError("script must be a nonempty list of script lines.")
        # Unity expects a serialized options object followed by individual lines.
        options = {
            "recording": False, "skip_animation": True, "find_solution": False,
            "skip_execution": False, "randomize_execution": False, "random_seed": -1,
            "processing_time_limit": 10, "time_scale": 1.0, "frame_rate": 5,
            "image_width": 640, "image_height": 480, "image_synthesis": ["normal"],
            "camera_mode": ["AUTO"], "save_scene_states": False, "save_pose_data": False,
            "output_folder": "Output/", "file_name_prefix": "script",
        }
        result = self._post("render_script", stringParams=[json.dumps(options), *script])
        if "message" not in result:
            raise VirtualHomeError("render_script: response is missing the Unity message.")
        message = result["message"]
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except ValueError:
                pass  # Unity may return a plain text execution message.
        return result["success"], message
