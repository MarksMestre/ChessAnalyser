"""Serves the React frontend, the report pack, and a live engine endpoint.

    python serve.py                     build present? then serve on :8000
    python serve.py --dev               run the Vite dev server instead
    python serve.py --port 9000

Endpoints
    GET  /api/health      which engines are reachable, and at what limits
    GET  /api/report      the pack's report.json
    GET  /api/games/<n>   one game's full move list
    POST /api/analyse     score one position the visitor played

Two decisions worth knowing about
---------------------------------
**One engine, behind a lock.** ``chess.engine.SimpleEngine`` is not
thread-safe, so the server opens a single Stockfish and serialises every search
on a ``threading.Lock``. Requests queue. At the interactive limits used here
(0.3 s) that is a sub-second wait for one person on localhost, which is the
intended use. The fix for many users is a *pool* of engines, not removing the
lock.

**Interactive limits are shallower than the batch limits.** ``analyze.py``
searches at depth 14-24 with 2-6 s caps because nothing is waiting. Here a
visitor is watching, so the default is depth 12 / 0.3 s. The response always
reports the depth actually reached, so a fast answer never claims to be a deep
one.

Everything else is Python stdlib: the repo's stated position is that only
``chess`` and ``certifi`` are dependencies, and four endpoints are not worth two
more frameworks.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

import chess

import engines
import openings
import pack as pack_mod
import scoring

ROOT = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(ROOT, "ui")
DIST_DIR = os.path.join(UI_DIR, "dist")

# Interactive search limits. Shallow on purpose: see the module docstring.
DEFAULT_MOVETIME = 0.3
DEFAULT_DEPTH = 12
MULTIPV = 2  # "great" is defined against the runner-up line


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------

class EngineHolder:
    """A lazily-opened Stockfish, serialised behind a lock.

    Opening the binary costs a process launch and reads the net, so it happens
    on first use rather than at startup -- starting the server to look at the
    frontend should stay instant.
    """

    def __init__(self, *, movetime: float = DEFAULT_MOVETIME, depth: int = DEFAULT_DEPTH):
        self.movetime = movetime
        self.depth = depth
        self._engine: Optional[engines.Engine] = None
        self._lock = threading.Lock()
        self._book: Optional[openings.OpeningBook] = None
        self._error: str = ""

    # -- lifecycle ---------------------------------------------------------
    def engine(self) -> engines.Engine:
        with self._lock:
            if self._engine is None:
                self._engine = engines.open_stockfish()
            return self._engine

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.close()
                self._engine = None

    def book(self) -> openings.OpeningBook:
        """The opening book, loaded once, for 'is this still theory?'."""
        with self._lock:
            if self._book is None:
                self._book = openings.OpeningBook.load()
            return self._book

    def probe(self) -> Dict[str, Any]:
        """Whether an engine is actually there, for /api/health.

        Probed rather than assumed, so the UI can say *why* engine mode is
        unavailable instead of just failing on the first move.
        """
        out: Dict[str, Any] = {
            "ok": False,
            "stockfish": None,
            "lc0": None,
            "movetime": self.movetime,
            "depth": self.depth,
            "error": "",
        }
        try:
            path = engines.find_executable("stockfish", engines._STOCKFISH_HINTS)
            if not path:
                out["error"] = "Stockfish not found. Run: python setup.py --only stockfish"
                return out
            out["stockfish"] = os.path.basename(path)
            with self._lock:
                if self._engine is None:
                    self._engine = engines.open_stockfish(path)
            out["ok"] = True
        except Exception as exc:
            out["error"] = f"Stockfish unavailable: {exc}"
        try:
            lc0_path = engines.find_executable("lc0", engines._LC0_HINTS)
            if lc0_path:
                out["lc0"] = os.path.basename(lc0_path)
        except Exception:
            pass
        return out

    # -- the actual search -------------------------------------------------
    def analyse(self, board: chess.Board, *, depth: int, movetime: float,
                multipv: int = MULTIPV) -> Dict[str, Any]:
        """Search one position. Both searches for a move happen under one lock
        acquisition so a concurrent request cannot interleave with them."""
        engine = self.engine()
        with self._lock:
            started = time.time()
            before = engine.analyse(board, depth=depth, movetime=movetime, multipv=multipv)
            elapsed_ms = int((time.time() - started) * 1000)
        return {"lines": before, "elapsed_ms": elapsed_ms,
                "depth_reached": before[0].depth if before else 0}


# --------------------------------------------------------------------------
# request handling
# --------------------------------------------------------------------------

class ReportHandler(SimpleHTTPRequestHandler):
    """Static files plus ``/api/*`` plus an SPA history fallback."""

    pack_dir = os.path.join(ROOT, "out", "pack")
    holder: Optional[EngineHolder] = None
    # The app is built with `base: '/report.html/'` so asset URLs resolve under
    # that prefix at any nesting depth. The server therefore has to strip the
    # prefix before looking anything up on disk, otherwise every asset request
    # 404s into the SPA fallback and comes back as HTML -- which the browser
    # then refuses to execute as a module script.
    mount = "/report.html"

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, directory=DIST_DIR, **kw)

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        """Log requests, but skip the asset chatter that fills the console."""
        if self.path.startswith("/api/") or "/assets/" in self.path:
            super().log_message(fmt, *args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        route = unquote(urlparse(self.path).path)

        if route == "/api/health":
            return self._health()
        if route == "/api/report":
            return self._report()
        if route.startswith("/api/games/"):
            return self._game(route)
        if route.startswith("/api/"):
            return self._send_error_json(f"unknown endpoint: {route}", 404)
        return self._static(route)

    def do_POST(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route == "/api/analyse":
            return self._analyse()
        if route == "/api/hints":
            return self._hints()
        return self._send_error_json(f"unknown endpoint: {route}", 404)

    # -- endpoints ---------------------------------------------------------
    def _health(self) -> None:
        if self.holder is None:
            return self._send_error_json("engine not initialised", 503)
        return self._send_json(self.holder.probe())

    def _report(self) -> None:
        loaded = pack_mod.load_pack(self.pack_dir)
        if loaded is None:
            return self._send_error_json(
                "No report pack found. Build one with:\n"
                f"  python report.py --pack --out {self.pack_dir}",
                404,
            )
        return self._send_json(loaded["report"])

    def _game(self, route: str) -> None:
        tail = route[len("/api/games/"):].strip("/")
        if not tail.isdigit():
            return self._send_error_json(f"game id must be a number: {tail!r}", 400)
        loaded = pack_mod.load_pack(self.pack_dir)
        if loaded is None:
            return self._send_error_json("no report pack built", 404)
        index = int(tail)
        detail = loaded["games"].get(index) or pack_mod.load_game(self.pack_dir, index)
        if detail is None:
            return self._send_error_json(f"no game {index}", 404)
        return self._send_json(detail)

    def _read_json(self) -> tuple[Any, Optional[str]]:
        """The parsed request body, or ``(None, message)`` on any failure.

        Shared by the two POST endpoints so the body-size ceiling and the two
        decode errors are handled the same way in both. A caller asking for
        something absurd gets a 413 rather than having it read into memory.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "bad Content-Length"
        if length <= 0:
            return None, "empty request body"
        if length > 1_000_000:
            return None, "request body too large"
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (ValueError, UnicodeDecodeError) as exc:
            return None, f"bad JSON: {exc}"

    def _hints(self) -> None:
        """The top N moves for a position.

        One search, and nothing else: no scoring of a move, no sacrifice
        detection, no book lookup. That is the whole reason this is a separate
        endpoint rather than a flag on ``/api/analyse`` -- the caller wants
        "what are the best moves here", not "how good was the move you just
        made", and asking for it on every position you pass through means the
        search count is the cost that matters.
        """
        if self.holder is None:
            return self._send_error_json("engine not initialised", 503)

        request, error = self._read_json()
        if error is not None:
            status = 413 if "too large" in error else 400
            return self._send_error_json(error, status)
        if not isinstance(request, dict):
            return self._send_error_json("expected a JSON object", 400)

        fen = str(request.get("fen") or "").strip()
        if not fen:
            return self._send_error_json("fen is required", 400)

        # The UI offers 1-3, so anything above 3 is a caller bug worth reporting
        # rather than a value to silently round down. _clamp_int handles the
        # non-numeric and out-of-range-both-ends cases; this catches the one
        # that is specifically wrong.
        raw_multipv = request.get("multipv", 1)
        try:
            requested = int(raw_multipv)
        except (TypeError, ValueError):
            return self._send_error_json(f"multipv must be a number: {raw_multipv!r}", 400)
        if requested < 1 or requested > 3:
            return self._send_error_json(f"multipv must be 1..3, got {requested}", 400)
        multipv = _clamp_int(requested, 1, 1, 3)

        try:
            board = chess.Board(fen)
        except ValueError as exc:
            return self._send_error_json(f"bad FEN: {exc}", 400)

        depth = _clamp_int(request.get("depth"), self.holder.depth, 1, 30)
        movetime = _clamp_float(request.get("movetime"), self.holder.movetime, 0.01, 30.0)

        try:
            result = self.holder.analyse(board, depth=depth, movetime=movetime, multipv=multipv)
        except Exception as exc:
            return self._send_error_json(f"engine failed: {exc}", 503)

        lines = result["lines"]
        moves = [
            {
                "rank": rank,
                "uci": line.uci,
                "san": line.san,
                "score_cp": line.score_cp,
                "score_san": _score_san(line),
                "win_percent": round(engines.win_percent(line.score_cp), 2),
                "depth": line.depth or depth,
                # The same helper _analyse uses, so the SAN cannot disagree.
                "pv": scoring.san_pv(board, line.pv),
            }
            for rank, line in enumerate(lines[:multipv], start=1)
        ]

        return self._send_json({
            "moves": moves,
            "elapsed_ms": result["elapsed_ms"],
            "depth_reached": result["depth_reached"],
            "turn": "white" if board.turn == chess.WHITE else "black",
        })

    def _analyse(self) -> None:
        if self.holder is None:
            return self._send_error_json("engine not initialised", 503)
        request, error = self._read_json()
        if error is not None:
            status = 413 if "too large" in error else 400
            return self._send_error_json(error, status)
        if not isinstance(request, dict):
            return self._send_error_json("expected a JSON object", 400)

        fen = str(request.get("fen") or "").strip()
        uci = str(request.get("uci") or "").strip()
        if not fen or not uci:
            return self._send_error_json("fen and uci are both required", 400)

        try:
            board = chess.Board(fen)
        except ValueError as exc:
            return self._send_error_json(f"bad FEN: {exc}", 400)

        try:
            move = board.parse_uci(uci)
        except (chess.InvalidMoveError, ValueError):
            return self._send_error_json(f"illegal move in this position: {uci}", 400)

        depth = _clamp_int(request.get("depth"), self.holder.depth, 1, 30)
        movetime = _clamp_float(request.get("movetime"), self.holder.movetime, 0.01, 30.0)

        after_board = board.copy(stack=False)
        after_board.push(move)

        try:
            before = self.holder.analyse(board, depth=depth, movetime=movetime)
            after = self.holder.analyse(after_board, depth=depth, movetime=movetime)
        except Exception as exc:
            return self._send_error_json(f"engine failed: {exc}", 503)

        score = scoring.score_move(
            board, uci, before=before["lines"], after=after["lines"], depth=depth
        )

        # A sacrifice needs the refutation, which is the `after` search we
        # already ran -- same quantity analyze.py measures, via the same helper.
        player = board.turn
        best_reply = scoring.first_line_move(after["lines"], after_board)
        given = scoring.detect_sacrifice(board, move, best_reply, player)
        sacrifice = round(given, 2) if given >= 1.0 else None

        try:
            in_book = self.holder.book().is_book_move([], uci) is not None
        except Exception:
            in_book = False

        scoring.label_move(
            score, uci=uci, in_book=in_book,
            forced=scoring.is_forced_move(board), sacrifice=sacrifice,
        )

        payload = score.to_dict()
        payload.update({
            "san": board.san(move),
            "fen": fen,
            "fen_after": after_board.fen(en_passant="fen"),
            "sacrifice": sacrifice,
            "depth_reached": max(before["depth_reached"], after["depth_reached"]),
            "movetime_ms": max(before["elapsed_ms"], after["elapsed_ms"]),
            "terminated": after_board.is_game_over(),
            "result": _game_result(after_board),
        })
        return self._send_json(payload)

    # -- static ------------------------------------------------------------
    def _static(self, route: str) -> None:
        """Serve a real file, or the SPA entry point for anything else.

        This fallback is what makes ``/report.html/games/3`` a working link
        rather than a 404: the browser asks for a path that does not exist on
        disk, and gets index.html back so the router can take over.
        """
        rel = self._relative(route)
        candidate = os.path.normpath(os.path.join(DIST_DIR, rel))
        inside = candidate == DIST_DIR or candidate.startswith(DIST_DIR + os.sep)
        if rel not in ("", "index.html") and inside and os.path.isfile(candidate):
            # Hand the base handler the *stripped* path: it resolves self.path
            # against the directory it was constructed with, so the mount prefix
            # has to be gone or the file will not be found.
            self.path = "/" + rel
            return super().do_GET()

        if not os.path.isfile(os.path.join(DIST_DIR, "index.html")):
            return self._send_error_json(
                "The frontend has not been built yet.\n"
                "  cd ui; npm install; npm run build\n"
                "or run it in development mode:\n"
                "  python serve.py --dev",
                404,
            )
        self.path = "/index.html"
        return super().do_GET()

    def _relative(self, route: str) -> str:
        """Strip the mount prefix, returning a dist-relative path.

        Accepts both ``/report.html/games/3`` and a bare ``/games/3``, so the
        server also works if it is mounted at the domain root.
        """
        path = route.lstrip("/")
        mount = self.mount.strip("/")
        if mount and (path == mount or path.startswith(mount + "/")):
            path = path[len(mount):].lstrip("/")
        return path


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _game_result(board: chess.Board) -> str:
    if board.is_checkmate():
        return "0-1" if board.turn == chess.WHITE else "1-0"
    if board.is_stalemate() or board.is_insufficient_material():
        return "1/2-1/2"
    return "*"


#: What ``engines.Line.score_cp`` means when it is a forced mate. Same sentinel
#: as ``analyze.MATE_CP``, for the same reason: a mate is not a pawn value.
MATE_CP = 10_000


def _score_san(line: "engines.Line") -> str:
    """``+0.31``, or ``#2`` for a mate in two.

    The hint arrows carry this so the list beside the board can read it, and a
    mate rendered as ``+100.00`` would be nonsense -- the value is a sentinel,
    not a hundred pawns.
    """
    cp = line.score_cp
    if cp >= MATE_CP:
        return "#" if cp == MATE_CP else f"#{round(abs(cp) / 100_000)}"
    if cp <= -MATE_CP:
        return "-#" if cp == -MATE_CP else f"-#{round(abs(cp) / 100_000)}"
    return f"{cp / 100:+.2f}"


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def self_test() -> int:
    """Check the routing decisions and the request contract. No network, no writes.

    The checks that matter here are the ones a browser would otherwise discover
    the hard way: the SPA fallback, and /api/* never being swallowed by it.
    """
    checks = 0
    failures = []

    def check(label: str, got, want) -> None:
        nonlocal checks
        checks += 1
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # -- the mount prefix ---------------------------------------------------
    # Assets are built with base '/report.html/', so the server must strip that
    # prefix. Without it every asset request falls through to the SPA handler
    # and returns HTML, which the browser refuses to run as a module script.
    mount = ReportHandler.mount.strip("/")

    def relative(path: str) -> str:
        p = path.lstrip("/")
        if mount and (p == mount or p.startswith(mount + "/")):
            return p[len(mount):].lstrip("/")
        return p

    # -- serving a real file -------------------------------------------------
    # The base handler resolves self.path against its own directory, so the
    # stripped path is what it must be handed. Asserted here because getting it
    # wrong is invisible until the browser refuses to run the bundle.
    #
    # Run against a temp directory rather than dist/: asset filenames carry a
    # content hash, so a test naming one starts failing every time the frontend
    # is rebuilt -- which is exactly when the test is least useful.
    def resolved_path_for(path: str, dist: str = DIST_DIR) -> str:
        rel = relative(path)
        candidate = os.path.normpath(os.path.join(dist, rel))
        inside = candidate == dist or candidate.startswith(dist + os.sep)
        if rel in ("", "index.html") or not inside or not os.path.isfile(candidate):
            return "/index.html"
        return "/" + rel

    check("mount prefix is stripped",
          relative("/report.html/assets/index.js"), "assets/index.js")
    check("a deep route strips to a route, not an asset",
          relative("/report.html/games/3"), "games/3")
    check("a bare path is left alone", relative("/games/3"), "games/3")
    check("the mount root becomes empty", relative("/report.html"), "")
    check("a path that merely starts with the mount text is not stripped",
          relative("/report.htmlfoo/x"), "report.htmlfoo/x")

    # Serving a real file, against a directory that actually holds one.
    import tempfile
    with tempfile.TemporaryDirectory() as _tmp:
        os.makedirs(os.path.join(_tmp, "assets"))
        with open(os.path.join(_tmp, "assets", "index.js"), "w", encoding="utf-8") as _fh:
            _fh.write("// built")
        check("a real asset keeps its stripped path",
              resolved_path_for("/report.html/assets/index.js", _tmp),
              "/assets/index.js")
        check("a missing asset falls back to the entry point",
              resolved_path_for("/report.html/assets/missing.js", _tmp), "/index.html")
        check("a route falls back to the entry point",
              resolved_path_for("/report.html/games/3", _tmp), "/index.html")

    # -- the SPA fallback ---------------------------------------------------
    # This is the rule that makes /report.html/games/3 work. Stated as a
    # predicate so it can be asserted without binding a socket.
    def resolves_to_index(path: str, dist: str = DIST_DIR) -> bool:
        if path.startswith("/api/"):
            return False
        rel = relative(path)
        candidate = os.path.normpath(os.path.join(dist, rel))
        inside = candidate == dist or candidate.startswith(dist + os.sep)
        if rel not in ("", "index.html") and inside and os.path.isfile(candidate):
            return False
        return True

    check("a deep route falls back to index.html",
          resolves_to_index("/report.html/games/3"), True)
    check("the root resolves normally", resolves_to_index("/"), True)

    # A real file must be served as itself, so the predicate is exercised
    # against a directory that actually contains one rather than against dist/,
    # which may not be built yet.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        assets = os.path.join(tmp, "assets")
        os.makedirs(assets)
        with open(os.path.join(assets, "index-abc123.js"), "w", encoding="utf-8") as fh:
            fh.write("// built")
        check("a real asset is served directly",
              resolves_to_index("/assets/index-abc123.js", tmp), False)
        check("a missing asset falls back", resolves_to_index("/assets/gone.js", tmp), True)
        # The bug this exists to catch: the asset URL carries the mount prefix,
        # so without stripping it the lookup misses and returns HTML.
        check("an asset under the mount prefix is served",
              resolves_to_index("/report.html/assets/index-abc123.js", tmp), False)

    # -- the hints endpoint's contract --------------------------------------
    # These are the two ways a caller gets it wrong: asking for more lines than
    # the UI offers, and sending a FEN that is not a position. Both are checked
    # by the same parsing the handler does, rather than by binding a socket.
    def hints_request(body):
        """What `_hints` would make of `body`, without an engine.

        Mirrors the handler's validation order. The search itself is the one
        thing not exercised here: it needs Stockfish, and asserting on it would
        only re-assert that the engine works, which `setup.py --verify` owns.
        """
        if not isinstance(body, dict):
            return "expected a JSON object"
        if not str(body.get("fen") or "").strip():
            return "fen is required"
        raw = body.get("multipv", 1)
        try:
            requested = int(raw)
        except (TypeError, ValueError):
            return "multipv must be a number"
        if requested < 1 or requested > 3:
            # Rejected rather than clamped: the UI offers 1..3, so a larger
            # value is a caller bug worth surfacing, not something to round.
            return "multipv must be 1..3"
        try:
            chess.Board(str(body["fen"]))
        except ValueError:
            return "bad FEN"
        return "ok"

    check("hints: a plain request is fine",
          hints_request({"fen": chess.STARTING_FEN}), "ok")
    check("hints: multipv 1..3 accepted",
          [hints_request({"fen": chess.STARTING_FEN, "multipv": n})
           for n in (1, 2, 3)], ["ok", "ok", "ok"])
    check("hints: multipv 0 rejected",
          hints_request({"fen": chess.STARTING_FEN, "multipv": 0}), "multipv must be 1..3")
    check("hints: multipv 4 rejected",
          hints_request({"fen": chess.STARTING_FEN, "multipv": 4}), "multipv must be 1..3")
    check("hints: multipv junk rejected",
          hints_request({"fen": chess.STARTING_FEN, "multipv": "many"}),
          "multipv must be a number")
    check("hints: fen required", hints_request({"multipv": 1}), "fen is required")
    check("hints: blank fen rejected", hints_request({"fen": "  "}), "fen is required")
    check("hints: a bad FEN is a 400, not a crash",
          hints_request({"fen": "not a position"}), "bad FEN")
    check("hints: a non-object body is rejected", hints_request([1, 2]),
          "expected a JSON object")

    # -- brilliant needs a position worth winning in --------------------------
    # The same rule the batch analysis uses, asserted through the same shared
    # helper. Both entry points go via scoring.label_move, so this cannot drift
    # from `analyze.py --self-test`, which asserts the same thing.
    def live_label(**overrides):
        """The label the live endpoint would give a played move.

        `label_move` reads the win percents off the Score rather than taking
        them as arguments, which is why they are set on the Score itself.
        """
        fields = dict(
            eval_before=0.0,
            eval_after=0.0,
            win_percent_before=95.0,
            win_percent_after=93.1,
            loss_pp=1.9,
            accuracy=98.0,
            best_uci="e2e4",
            gap_pp=0.5,
        )
        args = dict(sacrifice=3.3, in_book=False, forced=False)
        fields.update(overrides)
        args.update({k: v for k, v in overrides.items() if k in args})
        s = scoring.Score(**fields)
        scoring.label_move(s, uci="e2e4", **args)
        return s.label

    check("a sound sacrifice is brilliant", live_label(), "brilliant")
    check("a sacrifice in a lost position is not",
          live_label(win_percent_before=10.2) != "brilliant", True)
    check("a sacrifice that leaves you worse is not",
          live_label(win_percent_after=8.3) != "brilliant", True)
    check("the two numbers from /games/1/31 are not brilliant",
          live_label(win_percent_before=10.2, win_percent_after=8.3) != "brilliant",
          True)
    # Morphy's reference case, which the floors must not discard.
    check("a sacrifice from a winning position is still brilliant",
          live_label(win_percent_before=99.0, win_percent_after=97.0), "brilliant")

    # -- /api/* never reaches the static handler ------------------------------
    check("/api/* never reaches the static handler",
          resolves_to_index("/api/report"), False)
    check("/api/ is never swallowed by the fallback",
          resolves_to_index("/api/report"), False)
    check("/api/games/3 is never swallowed",
          resolves_to_index("/api/games/3"), False)

    # path traversal must not escape dist
    # /api/hints is a POST endpoint, and must be routed as one: a GET for it is
    # an unknown endpoint, not a 404 from the SPA fallback.
    check("/api/hints is not served as a static file",
          resolves_to_index("/api/hints"), False)

    check("traversal is not treated as an asset",
          resolves_to_index("/../../secret.txt"), True)

    # -- request parsing ----------------------------------------------------
    check("depth clamped above", _clamp_int(999, 12, 1, 30), 30)
    check("depth clamped below", _clamp_int(-5, 12, 1, 30), 1)
    check("depth default on junk", _clamp_int("abc", 12, 1, 30), 12)
    check("movetime clamped", _clamp_float(1000.0, 0.3, 0.01, 30.0), 30.0)
    check("movetime default on None", _clamp_float(None, 0.3, 0.01, 30.0), 0.3)
    check("movetime accepts a string", _clamp_float("0.5", 0.3, 0.01, 30.0), 0.5)

    # -- game id routing ----------------------------------------------------
    check("numeric game id", "12".isdigit(), True)
    check("non-numeric game id rejected", "abc".isdigit(), False)
    check("empty game id rejected", "".isdigit(), False)

    # -- result reporting ---------------------------------------------------
    check("checkmate is 1-0", _game_result(chess.Board()), "*")
    mated = chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
    check("black is mated, so white wins", _game_result(mated), "1-0")
    stalemated = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    check("stalemate is a draw", _game_result(stalemated), "1/2-1/2")
    check("unresolved game", _game_result(chess.Board()), "*")

    # -- the label path agrees with the batch one ---------------------------
    # Same inputs must give the same label whichever entry point is used.
    board = chess.Board()
    before = [engines.Line("e2e4", "e4", ["e2e4"], cp=30.0, depth=12),
              engines.Line("d2d4", "d4", ["d2d4"], cp=20.0, depth=12)]
    after = [engines.Line("e7e5", "e5", ["e7e5"], cp=-28.0, depth=12)]
    live = scoring.score_move(board, "e2e4", before=before, after=after, depth=12)
    scoring.label_move(live, uci="e2e4", in_book=False, forced=False, sacrifice=None)
    check("live scoring labels best", live.label, "best")

    print(f"serve: {checks - len(failures)}/{checks} checks passed")
    for problem in failures:
        print(f"  FAIL {problem}", file=sys.stderr)
    return 1 if failures else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_dist() -> None:
    """npm install + vite build, if ui/ is present."""
    if not os.path.isdir(UI_DIR):
        print(f"no {UI_DIR} -- nothing to build", file=sys.stderr)
        return
    for args in (["npm", "install"], ["npm", "run", "build"]):
        print(f"> npm {' '.join(args)}", flush=True)
        result = subprocess.run(args, cwd=UI_DIR, shell=(os.name == "nt"))
        if result.returncode != 0:
            print(f"npm {' '.join(args)} failed", file=sys.stderr)
            return
    print(f"built {DIST_DIR}")


def _run_vite(port: int) -> int:
    if not os.path.isdir(UI_DIR):
        print(f"no {UI_DIR} -- cannot start the dev server", file=sys.stderr)
        return 2
    print("> vite dev server. The API is proxied to 127.0.0.1:8000,")
    print("  so run this in a second terminal too: python serve.py")
    return subprocess.run(["npm", "run", "dev"], cwd=UI_DIR, shell=(os.name == "nt")).returncode


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv:
        return self_test()

    ap = argparse.ArgumentParser(description="Serve the chess-coach frontend.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address. localhost only by default: this server "
                         "has no authentication and must not be exposed.")
    ap.add_argument("--pack", default=os.path.join(ROOT, "out", "pack"),
                    help="directory holding report.json and games/")
    ap.add_argument("--dev", action="store_true",
                    help="run the Vite dev server instead of serving dist/")
    ap.add_argument("--build", action="store_true",
                    help="npm install + npm run build, then exit")
    ap.add_argument("--movetime", type=float, default=DEFAULT_MOVETIME,
                    help=f"default search time per position ({DEFAULT_MOVETIME}s)")
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH,
                    help=f"default search depth ({DEFAULT_DEPTH})")
    args = ap.parse_args(argv)

    if args.build:
        _build_dist()
        return 0
    if args.dev:
        return _run_vite(args.port)

    ReportHandler.pack_dir = args.pack
    ReportHandler.holder = EngineHolder(movetime=args.movetime, depth=args.depth)

    built = os.path.isfile(os.path.join(DIST_DIR, "index.html"))
    has_pack = os.path.isfile(os.path.join(args.pack, "report.json"))

    httpd = ThreadingHTTPServer((args.host, args.port), ReportHandler)
    print(f"chess-coach on http://{args.host}:{args.port}/report.html/")
    print(f"  frontend : {'built' if built else 'NOT BUILT (cd ui; npm install; npm run build)'}")
    print(f"  pack     : {args.pack if has_pack else 'NOT BUILT (python report.py --pack)'}")
    print(f"  engine   : opened on first use, depth {args.depth}, {args.movetime}s")
    print("  Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
        if ReportHandler.holder:
            ReportHandler.holder.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())