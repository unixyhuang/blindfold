"""Ask local Ollama a single descriptive question using its /api/chat endpoint.

Run with `python ollama_client.py` or `python main.py ollama`.
API reference: https://docs.ollama.com/api/chat
"""

from http.client import HTTPConnection, HTTPException
import json
import sys


def main(model: str = "llama3.1") -> int:
    if not isinstance(model, str) or not model.strip():
        print("An Ollama model tag is required.", file=sys.stderr)
        return 1
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": "The empty cup is on the tray. Where is the cup? Reply in English.",
        }],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 32},
    }
    connection = HTTPConnection("127.0.0.1", 11434, timeout=90)
    try:
        connection.request("POST", "/api/chat", body=json.dumps(payload).encode("utf-8"),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            detail = body.decode("utf-8", errors="replace").strip()[:300]
            print(f"Ollama returned HTTP {response.status}: {detail}", file=sys.stderr)
            if response.status == 404:
                print(f"Check that {model} is available on this server with ollama list.", file=sys.stderr)
            return 1
        reply = json.loads(body)
        message = reply.get("message") if isinstance(reply, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            print("Ollama returned an empty or invalid chat response.", file=sys.stderr)
            return 1
        print(content.strip())
        return 0
    except (OSError, HTTPException) as error:
        print(f"Could not complete the request to Ollama at 127.0.0.1:11434: {error}",
              file=sys.stderr)
        return 1
    except (ValueError, UnicodeError):
        print("Ollama returned invalid JSON.", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
