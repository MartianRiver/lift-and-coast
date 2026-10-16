"""UDP listener + local dashboard + team radio.

    uv run python -m engineer.server [--no-record] [--radio-mode hold|toggle] [--no-radio]

Then open http://localhost:8077
"""
import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import diagnostics, driver, log, radiolog, usage, view
from .crew import assemble
from .pitwall import BUDGET, MODELS, notes
from .engineer import DEFAULT_MODEL
from .glance import glance
from .hub import Hub
from .lookups import BUTTONS
from .radio import QUICK, TRIGGER
from .recorder import SessionRecorder
from .state import RaceState
from .tts import DEFAULT_VOICE

_log = log.get("server")

WEB = Path(__file__).resolve().parent.parent / "web"
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".wav": "audio/wav"}
# changes every server start; open pages reload when they see a new one (stale JS bit us)
BUILD = str(time.time())


def lan_ip():
    # no packet is sent; this just asks the OS which interface routes outward
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def listen_udp(state, port, recorder):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(5)  # wake up to notice the game going quiet
    _log.info("udp listening", port=port)
    while True:
        try:
            buf, addr = sock.recvfrom(4096)
        except socket.timeout:
            if recorder:
                recorder.idle()
            continue
        if recorder:
            recorder.write(buf)
        state.ingest(buf, addr)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # browsers drop keep-alive sockets all the time; not worth a traceback
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return
        _log.error("http handler crashed", client=client_address[0])


def make_handler(state, listen, hub, crew, recorder=None):
    radio, engineer, caller, speaker, wall = crew.radio, crew.engineer, crew.caller, crew.speaker, crew.wall

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            _log.trace("http", line=format % args)

        def _json(self, obj, status=200):
            body = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, name, root=WEB):
            path = (root / name).resolve()
            if path.parent != root.resolve() or not path.is_file():
                return self._json({"error": "not found"}, 404)
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(path.suffix, "application/octet-stream"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _sse(self, kind, data):
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data, allow_nan=False)}\n\n".encode())

        def _stream(self):
            # SSE for anything latency-sensitive (buttons, radio); polling would add up to 250ms
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seq = hub.seq
            self._sse("hello", {
                "build": BUILD,
                "buttonNames": BUTTONS,
                "buttons": state.buttons,
                "radio": radio.snapshot(),
                "messages": list(radio.messages),
                "fixes": radio.lexicon.fixes,
                "replies": list(engineer.replies) if engineer else [],
                "calls": list(caller.sent) if caller else [],
                "engineer": {"model": engineer.model, "error": engineer.error} if engineer else {"error": "off"},
                "speech": speaker.state if speaker else "off",
            })
            self.wfile.flush()
            _log.debug("stream opened", client=self.client_address[0])
            try:
                while True:
                    items, seq = hub.wait(seq, timeout=15)
                    for _, kind, data in items:
                        self._sse(kind, data)
                    if not items:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                _log.debug("stream closed", client=self.client_address[0])

        def _local(self):
            # only pages served from here: a JSON content type makes the browser preflight a cross-site
            # POST (which we never answer), and the Host check stops DNS rebinding
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("localhost", "127.0.0.1", "::1"):
                self._json({"error": "forbidden"}, 403)
                return False
            return True

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._local():
                return
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json({"error": "send application/json"}, 415)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if path == "/api/radio":
                    radio.edge(bool(body["pressed"]), "keyboard")
                    return self._json(radio.snapshot())
                if path == "/api/ask":
                    if not str(body["text"]).strip():
                        raise ValueError("empty question")
                    radio.typed(str(body["text"]))
                    return self._json({"ok": True})
                if path == "/api/pitwall/prep" and wall:
                    wall.prepare()
                    return self._json(wall.snapshot())
                if path == "/api/pitwall/brief" and wall:
                    if str(body["text"]).strip():
                        wall.tell(str(body["text"]))
                    else:
                        notes.write_brief("")
                    return self._json(wall.snapshot())
                if path == "/api/driver":
                    return self._json(driver.save(body["name"], body["pronouns"]))
                if path == "/api/fixes":
                    radio.lexicon.teach(body["heard"], body["meant"])
                    return self._json(radio.lexicon.fixes)
                if path == "/api/fixes/forget":
                    radio.lexicon.forget(body["heard"])
                    return self._json(radio.lexicon.fixes)
                return self._json({"error": "not found"}, 404)
            except (KeyError, ValueError) as e:
                return self._json({"error": f"bad request: {e}"}, 400)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if not self._local():
                return
            try:
                if url.path == "/":
                    return self._file("index.html")
                if url.path == "/api/state":
                    listen["ip"] = lan_ip()  # DHCP / private Wi-Fi address can move it mid-session
                    listen["recording"] = str(recorder.path) if recorder and recorder.path else None
                    snap = view.snapshot(state, listen)
                    snap["meta"]["sessionCost"] = usage.session_cost(snap["meta"]["sessionUID"])
                    return self._json(snap)
                if url.path == "/api/driver":
                    return self._json({**driver.get(), "choices": driver.PRONOUNS,
                                       "fromGame": driver.from_game(view.player_identity(state))})
                if url.path == "/api/diagnostics":
                    return self._json(view.clean(diagnostics.report(state, wall)))
                if url.path == "/api/race":
                    g = glance(state) or {"waiting": True}
                    if wall and not g.get("waiting"):
                        g["team"] = wall.glance()
                    return self._json(g)
                if url.path == "/api/pitwall":
                    return self._json(view.clean(wall.snapshot()) if wall else {"off": True})
                if url.path == "/api/car":
                    return self._json(view.car_detail(state, int(q["idx"][0])))
                if url.path == "/api/raw":
                    return self._json(view.raw(state, int(q["id"][0])))
                if url.path == "/api/stream":
                    return self._stream()
                if url.path == "/api/clip":  # a radio message's audio, by the clip name on the message
                    return self._file(q["name"][0], radiolog.CLIPS)
                if url.path == "/api/logs":
                    since = float(q.get("since", ["0"])[0])
                    return self._json([r for r in list(log.ring) if r["t"] > since])
                return self._file(url.path.lstrip("/"))
            except (KeyError, ValueError) as e:
                return self._json({"error": f"bad request: {e}"}, 400)
            except BrokenPipeError:
                pass
            except Exception as e:
                _log.error("request failed", path=self.path, error=str(e))
                return self._json({"error": str(e)}, 500)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--udp-port", type=int, default=20777)
    ap.add_argument("--http-port", type=int, default=8077)
    ap.add_argument("--no-record", action="store_true", help="don't save sessions to captures/sessions/")
    ap.add_argument("--radio-mode", choices=["hold", "toggle"], default="hold")
    ap.add_argument("--no-radio", action="store_true", help="skip mic + speech model (typed questions still work)")
    ap.add_argument("--radio-button", default=os.environ.get("RE_RADIO_BUTTON", TRIGGER),
                    help='button that keys the radio: a UDP action number or a name ("Left Stick Click")')
    ap.add_argument("--quick-button", default=os.environ.get("RE_QUICK_BUTTON", QUICK), help="button for the quick brief")
    ap.add_argument("--engineer-model", default=os.environ.get("RE_ENGINEER_MODEL", DEFAULT_MODEL),
                    help="OpenRouter model id for the engineer")
    ap.add_argument("--no-engineer", action="store_true", help="transcribe only, no LLM replies")
    ap.add_argument("--no-voice", action="store_true", help="text only, the engineer doesn't speak aloud")
    ap.add_argument("--voice", default=os.environ.get("RE_VOICE", DEFAULT_VOICE),
                    help="engine[:voice] (kokoro:bm_george, kokoro:bm_daniel, soprano, kitten, qwen3:ryan)")
    ap.add_argument("--radio-fx", action="store_true", help="band-limit the voice so it sounds like a radio")
    ap.add_argument("--audio-out", help="output device name (default: system output)")
    ap.add_argument("--no-calls", action="store_true", help="don't speak up unprompted (gaps, warnings, safety car...)")
    ap.add_argument("--pitwall-models", default=os.environ.get("RE_PITWALL_MODELS", ",".join(MODELS)),
                    help="the strategy team: lead[,second opinion] OpenRouter ids")
    ap.add_argument("--pitwall-budget", type=float, help=f"$ a session for the team (default {BUDGET})")
    ap.add_argument("--no-pitwall", action="store_true", help="no strategy team: the engineer and the code make the calls")
    args = ap.parse_args()

    hub = Hub()
    state = RaceState(hub)
    crew = assemble(hub, state, args.engineer_model, engineer=not args.no_engineer, mic=not args.no_radio,
                    radio_mode=args.radio_mode, voice=None if args.no_voice else args.voice, fx=args.radio_fx,
                    device=args.audio_out, calls=not args.no_calls,
                    team=None if args.no_pitwall else args.pitwall_models.split(","), budget=args.pitwall_budget,
                    buttons={"trigger": args.radio_button, "quick": args.quick_button})
    recorder = None if args.no_record else SessionRecorder()
    listen = {"ip": lan_ip(), "udpPort": args.udp_port, "recording": None,
              "dev": os.environ.get("RE_ENV") != "prod"}

    threading.Thread(target=listen_udp, args=(state, args.udp_port, recorder), daemon=True).start()
    # SIGTERM (pkill, closing the terminal) should still flush the capture
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    httpd = Server(("127.0.0.1", args.http_port), make_handler(state, listen, hub, crew, recorder))
    _log.info("dashboard up", url=f"http://localhost:{args.http_port}", ip=listen["ip"])
    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        usage.flush()
        if recorder:
            recorder.close(wait=True)


if __name__ == "__main__":
    main()
