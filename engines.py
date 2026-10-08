"""Engine discovery and UCI helpers.

Wraps two engines behind a small, uniform surface:

  * Stockfish 19  -- the primary analyser.  Deep, fast, and the source of
                     truth for every label in the report.
  * Lc0 0.32.x    -- a neural engine used *only* as a second opinion on the
                     handful of moves where Stockfish disagrees with the
                     player.  Lc0 often prefers human creative moves that
                     Stockfish scores as slightly inferior, so "Lc0 agreed with
                     you, Stockfish didn't" is a genuinely good brilliant-move
                     signal that Stockfish alone cannot produce.

Only python-chess and the stdlib are used.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import chess
import chess.engine

ROOT = os.path.dirname(os.path.abspath(__file__))

# Lichess's win-probability model: win_prob = 1 / (1 + exp(-k * cp)).
LICHESS_WIN_PROB_K = 0.00368208


# --------------------------------------------------------------------------
# scoring helpers
# --------------------------------------------------------------------------

def win_prob(cp: float) -> float:
    """Lichess sigmoid win probability in [0, 1] for a centipawn score."""
    import math

    try:
        return 1.0 / (1.0 + math.exp(-LICHESS_WIN_PROB_K * cp))
    except OverflowError:  # pragma: no cover - only for absurd scores
        return 0.0 if cp < 0 else 1.0


def win_percent(cp: float) -> float:
    return win_prob(cp) * 100.0


def win_percent_to_cp(wp: float) -> float:
    """Inverse of :func:`win_percent`, used for WDL -> cp conversions."""
    import math

    wp = min(max(wp, 0.01), 99.99)
    return -math.log(wp / (100.0 - wp)) / LICHESS_WIN_PROB_K


def accuracy_from_loss(loss_pp: float) -> float:
    """Lichess's published per-move accuracy curve."""
    import math

    return 103.1668 * math.exp(-0.04354 * loss_pp) - 3.1669


# --------------------------------------------------------------------------
# engine discovery
# --------------------------------------------------------------------------

_STOCKFISH_HINTS = [
    "stockfish-windows-x86-64-universal.exe",
    "stockfish-windows-x86-64-avx2.exe",
    "stockfish-windows-x86-64.exe",
    "stockfish.exe",
    "stockfish",
]

_LC0_HINTS = ["lc0.exe", "lc0"]


def _winget_package_dir() -> List[str]:
    """Return winget package install roots that may contain the engines."""
    roots: List[str] = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.append(os.path.join(local, "Microsoft", "WinGet", "Packages"))
    home = os.path.expanduser("~")
    roots.append(os.path.join(home, ".cache", "winget", "packages"))
    roots.append(os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages"))
    return [r for r in roots if os.path.isdir(r)]


def _scan_dirs(dirnames: Sequence[str]) -> List[str]:
    found: List[str] = []
    for d in dirnames:
        if not d or not os.path.isdir(d):
            continue
        try:
            for entry in sorted(os.listdir(d)):
                full = os.path.join(d, entry)
                if os.path.isfile(full):
                    found.append(full)
                elif os.path.isdir(full):
                    for sub in sorted(os.listdir(full)):
                        subfull = os.path.join(full, sub)
                        if os.path.isfile(subfull):
                            found.append(subfull)
        except OSError:
            continue
    return found


def find_executable(name: str, hints: Sequence[str]) -> Optional[str]:
    """Locate an engine binary: explicit override, then PATH, then known dirs."""
    override = os.environ.get(name.upper() + "_PATH")
    if override and os.path.isfile(override):
        return override

    for hint in hints:
        which = shutil.which(hint)
        if which:
            return which

    candidates = [
        os.path.join(ROOT, "engines", name),
        # prefer the GPU build: the CPU fallback runs ~50x slower
        os.path.join(ROOT, "engines", name + "-gpu"),
        os.path.join(ROOT, "engines", name + "-cpu"),
    ]
    # engines/ is ours, so walk it fully: the binaries live in subfolders like
    # engines/lc0-gpu/ that the flat candidate list above never sees
    gpu_first = sorted(
        _scan_dirs([os.path.join(ROOT, "engines")]),
        key=lambda p: ("gpu" not in p.lower(), p),
    )
    candidates += gpu_first
    candidates += _scan_dirs(_winget_package_dir())
    for d in _winget_package_dir():
        candidates.append(d)

    for hint in hints:
        for cand in candidates:
            base = os.path.basename(cand).lower()
            if hint.lower() in base and os.path.isfile(cand):
                return cand
    for cand in candidates:
        for hint in hints:
            if os.path.isfile(cand) and hint.lower() == os.path.basename(cand).lower():
                return cand
    return None


def find_net(explicit: Optional[str] = None) -> Optional[str]:
    """Locate an Lc0 weights file."""
    if explicit and os.path.isfile(explicit):
        return explicit
    override = os.environ.get("LC0_NET")
    if override and os.path.isfile(override):
        return override
    nets_dir = os.path.join(ROOT, "data", "nets")
    if not os.path.isdir(nets_dir):
        return None
    available = [
        os.path.join(nets_dir, e)
        for e in sorted(os.listdir(nets_dir))
        if e.endswith(".pb.gz")
    ]
    if not available:
        return None

    # Prefer the strongest net that this machine can actually feed.  A 768-wide
    # network needs ~2.6 GB of VRAM and will thrash (or fail) on a 4 GB card,
    # so rank by a preference list and fall back to whatever is present.
    #
    # Matched by prefix, not exact name: the upstream files are named after the
    # training run ("t3-512x15x16h-distill-swa-2767500.pb.gz"), so an exact match
    # against "t3-512x15x16h.pb.gz" would never hit and the ranking would silently
    # degrade to "largest file on disk".
    by_name = sorted(available, key=lambda p: os.path.basename(p))
    for preferred in (
        "t3-512x15x16h",
        "t1-512x15x8h",
        "t1-256x10",
    ):
        for path in by_name:
            if os.path.basename(path).startswith(preferred):
                return path
    # otherwise take the largest on disk
    return max(available, key=os.path.getsize)


# --------------------------------------------------------------------------
# engine wrapper
# --------------------------------------------------------------------------

@dataclass
class Line:
    """One principal variation, scored from the side-to-move's point of view."""

    uci: Optional[str]
    san: Optional[str]
    pv: List[str] = field(default_factory=list)
    cp: Optional[float] = None       # None when it is a forced mate
    mate: Optional[int] = None       # moves to mate, +ve = side to move mates
    depth: int = 0
    seldepth: int = 0
    nodes: int = 0

    @property
    def is_mate(self) -> bool:
        return self.mate is not None

    @property
    def score_cp(self) -> float:
        """Mate scores collapse to a large centipawn value for arithmetic."""
        if self.mate is not None:
            return 100000.0 if self.mate > 0 else -100000.0
        return float(self.cp or 0.0)

    def to_dict(self) -> Dict:
        return {
            "uci": self.uci,
            "san": self.san,
            "pv": self.pv,
            "cp": self.cp,
            "mate": self.mate,
            "depth": self.depth,
            "seldepth": self.seldepth,
        }


def _to_line(info: Dict, board: chess.Board, ply: int) -> Line:
    pv = info.get("pv") or []
    score = info.get("score")
    cp = mate = None
    if score is not None:
        pov = score.pov(board.turn)
        if pov.is_mate():
            mate = pov.mate()
        else:
            cp = float(pov.score(mate_score=100000))
    return Line(
        uci=pv[0].uci() if pv else None,
        san=_safe_san(board, pv[0]) if pv else None,
        pv=[m.uci() for m in pv[:10]],
        cp=cp,
        mate=mate,
        depth=int(info.get("depth") or 0),
        seldepth=int(info.get("seldepth") or 0),
        nodes=int(info.get("nodes") or 0),
    )


def _safe_san(board: chess.Board, move: chess.Move) -> Optional[str]:
    """SAN for a move, or None if it cannot be rendered on this board."""
    try:
        return board.san(move)
    except (chess.AmbiguousMoveError, chess.InvalidMoveError,
            chess.IllegalMoveError, ValueError):
        return move.uci()


class Engine:
    """Thin, uniform wrapper over Stockfish or Lc0.

    Results are memoised per (fen, depth, nodes, movetime, multipv) so that the
    position *after* a move is never searched twice: the same FEN is reused as
    the "before" position of the next ply.  With a 2x saving on engine calls this
    is the difference between a one-minute and a two-minute report.

    ``max_movetime`` is a hard per-position wall-clock cap handed to the engine.
    Depth alone does not bound cost: one hard position at depth 22 can take
    minutes, so a game with a handful of awkward positions would otherwise blow
    past any sensible runtime.  The engine stops early and reports whatever depth
    it reached, which is still plenty for a second opinion.
    """

    def __init__(
        self,
        name: str,
        path: str,
        *,
        extra_args: Optional[Sequence[str]] = None,
        options: Optional[Dict[str, object]] = None,
        max_movetime: Optional[float] = None,
        verbose: bool = False,
    ) -> None:
        self.name = name
        self.path = path
        self.verbose = verbose
        self.max_movetime = max_movetime
        command = [path] + list(extra_args or [])
        self._engine = chess.engine.SimpleEngine.popen_uci(
            command, timeout=600.0, debug=False
        )
        self.id = self._engine.id
        for key, value in (options or {}).items():
            try:
                self._engine.configure({key: value})
            except Exception as exc:  # engine may not know the option
                if verbose:
                    print(f"  ! {name}: option {key} rejected ({exc})", file=sys.stderr)
        self._cache: Dict[tuple, List[Line]] = {}
        self.positions_searched = 0
        self.cache_hits = 0

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        try:
            self._engine.quit()
        except Exception:
            pass

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- analysis ----------------------------------------------------------
    def analyse(
        self,
        board: chess.Board,
        *,
        depth: Optional[int] = None,
        nodes: Optional[int] = None,
        movetime: Optional[float] = None,
        multipv: int = 2,
        use_cache: bool = True,
    ) -> List[Line]:
        key = (board.fen(en_passant="fen"), depth, nodes, movetime, multipv)
        if use_cache and key in self._cache:
            self.cache_hits += 1
            return self._cache[key]

        # bound the search: whichever of the two limits is set, the engine
        # stops at the first one reached
        if self.max_movetime and movetime is None:
            movetime = self.max_movetime
        limit = chess.engine.Limit(depth=depth, nodes=nodes, time=movetime)
        infos = self._engine.analyse(board, limit, multipv=multipv)
        lines = [_to_line(i, board, 0) for i in infos]
        lines.sort(key=lambda ln: ln.score_cp, reverse=True)
        if use_cache:
            self._cache[key] = lines
        self.positions_searched += 1
        return lines

    def pv_line(self, board: chess.Board, **kw) -> Line:
        lines = self.analyse(board, multipv=1, **kw)
        return lines[0] if lines else Line(None, None)


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------

def open_stockfish(
    path: Optional[str] = None, *, threads: Optional[int] = None, hash_mb: int = 512,
    max_movetime: Optional[float] = None, verbose: bool = False,
) -> Engine:
    path = path or find_executable("stockfish", _STOCKFISH_HINTS)
    if not path:
        raise FileNotFoundError(
            "Stockfish not found. Install it with:\n"
            "  winget install --id=Stockfish.Stockfish -e\n"
            "or set the STOCKFISH_PATH environment variable."
        )
    if threads is None:
        # One thread is fastest here. This tool searches one position at a time,
        # so Stockfish's multi-threaded search mostly pays helper-thread overhead
        # and contention: on a 12-thread machine a single position is searched
        # ~100x faster on 1 thread than on 12. Raise --threads for big batches
        # where per-node cost matters more than per-position latency.
        threads = 1
    # Stockfish 19 rejects --threads/--hash on the command line, so both go
    # through UCI setoption instead.
    return Engine(
        "Stockfish",
        path,
        options={"Threads": threads, "Hash": hash_mb},
        max_movetime=max_movetime,
        verbose=verbose,
    )


def lc0_backends(path: str) -> List[str]:
    """The neural backends this lc0 build actually accepts.

    The valid set differs per build and is not something we can guess: the CUDA
    build accepts cuda-auto/cuda/cuda-fp16, the DirectML build accepts
    onnx-dml/onnx-cpu/onnx-cuda/onnx-trt, and the CPU build accepts blas/eigen.
    Asking the binary keeps us off the hardcoded-list treadmill that silently
    failed on any non-CUDA install.

    Parsed from ``--help``, where the entry reads::

        -b, --backend=CHOICE
                       Neural network computational backend to use.
                       [UCI: Backend  DEFAULT: cuda-auto  VALUES: cuda-auto,cuda,...]

    Scoped to that one option on purpose: --help lists a VALUES: line for every
    enumerated flag (FpuStrategy has one too), so a plain search for the first
    VALUES: picks up the wrong set.  Returns [] if the text cannot be read, and
    the caller then falls back to the known names.
    """
    try:
        proc = subprocess.run(
            [path, "--help"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    out = (proc.stdout or "") + (proc.stderr or "")
    flag = out.find("--backend")
    if flag < 0:
        return []
    # The VALUES: list belongs to this option, but stop before the next flag so a
    # neighbouring option cannot contribute.
    nxt = out.find("\n  -", flag)
    section = out[flag : nxt if nxt > flag else len(out)]
    match = re.search(r"VALUES:\s*([A-Za-z0-9_,\-]+)", section)
    if not match:
        return []
    names = [n.strip() for n in match.group(1).split(",") if n.strip()]
    # The diagnostic backends below are never what we want to search with.
    return [n for n in names if n not in _LC0_JUNK_BACKENDS]


# Never searched with on purpose: harnesses and network-eval stubs that accept
# the flag but do not play chess.
_LC0_JUNK_BACKENDS = {
    "trivial",
    "random",
    "check",
    "roundrobin",
    "recordreplay",
    "multiplexing",
    "demux",
}

# Preference order for the ONNX-era builds, fastest first.  Only consulted when
# the binary will not tell us what it supports.
_LC0_BACKEND_PREFERENCE = (
    "onnx-dml",
    "onnx-cuda",
    "onnx-trt",
    "cuda-fp16",
    "cuda",
    "cuda-auto",
    "openvino",
    "blas",
    "eigen",
    "onednn",
)

# Cached per path so a long analysis run does not re-launch --help per game.
_lc0_backend_cache: Dict[str, List[str]] = {}


def open_lc0(
    path: Optional[str] = None,
    *,
    net: Optional[str] = None,
    backend: str = "",
    threads: int = 4,
    verbose: bool = False,
) -> Engine:
    path = path or find_executable("lc0", _LC0_HINTS)
    if not path:
        raise FileNotFoundError(
            "Lc0 not found. Download it from https://lczero.org/play/download/ "
            "and place lc0.exe in the engines/ directory."
        )
    net = net or find_net()
    if not net:
        raise FileNotFoundError(
            "No Lc0 network (.pb.gz) found in data/nets/. Download one from "
            "https://lczero.org/play/networks/bestnets/"
        )

    # An explicit backend wins outright; otherwise ask the build what it takes.
    if backend:
        backends = [backend]
    else:
        supported = _lc0_backend_cache.get(path)
        if supported is None:
            supported = lc0_backends(path)
            _lc0_backend_cache[path] = supported
        if supported:
            backends = sorted(
                supported,
                key=lambda b: (
                    _LC0_BACKEND_PREFERENCE.index(b)
                    if b in _LC0_BACKEND_PREFERENCE
                    else len(_LC0_BACKEND_PREFERENCE),
                    b,
                ),
            )
        else:
            # Could not ask; try the names we know, best first.
            backends = list(_LC0_BACKEND_PREFERENCE)
        if verbose:
            print(f"  Lc0 backends: {', '.join(backends[:4])}", file=sys.stderr)

    tried: List[str] = []
    last_exc: Optional[Exception] = None
    for be in backends:
        try:
            eng = Engine(
                "Lc0",
                path,
                extra_args=[
                    f"--weights={net}",
                    f"--backend={be}",
                    f"--threads={threads}",
                ],
                options={"Threads": threads},
                verbose=verbose,
            )
            eng.net = net  # type: ignore[attr-defined]
            eng.backend = be  # type: ignore[attr-defined]
            if verbose and tried:
                print(f"  Lc0 backend: fell back to {be}", file=sys.stderr)
            return eng
        except Exception as exc:  # pragma: no cover - depends on local drivers
            last_exc = exc
            tried.append(be)
    hint = ""
    if any(b.startswith("onnx-dml") for b in tried):
        # The DirectML build ships without DirectML.dll on purpose; its README
        # tells you to fetch it with the bundled install.cmd.
        hint = (
            " DirectML builds need DirectML.dll beside lc0.exe"
            " (run install.cmd in that folder)."
        )
    raise RuntimeError(f"Lc0 failed to start with backends {tried}: {last_exc}.{hint}")


def probe(name: str, path: str) -> str:
    """Run a tiny UCI handshake and return the engine's name."""
    proc = subprocess.run(
        [path],
        input=b"uci\nisready\nquit\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    text = proc.stdout.decode("utf-8", "replace")
    for line in text.splitlines():
        if line.lower().startswith("id name"):
            return line.split(None, 2)[2] if len(line.split(None, 2)) > 2 else name
    return name