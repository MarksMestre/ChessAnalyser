"""Make a fresh clone deploy-ready.

Everything this project needs from the network is re-downloadable, which is why
``.gitignore`` throws all of it away: ~1 GB of engine binaries, a 153 MB neural
network, and a 600 KB opening book. What is tracked is the code, and this script is
what turns the code into a working install.

    python setup.py                # venv + deps + engines + net + book, then verify
    python setup.py --verify       # probe what is installed, download nothing
    python setup.py --skip-lc0     # Stockfish only (the analyser works without Lc0)
    python setup.py --force        # re-download even if already present

Design notes
------------
* **Versions are resolved, not hardcoded.** Stockfish and Lc0 publish tagged
  releases on GitHub; asking the API for the latest one means this script does not
  silently rot, and a new release is picked up without a code change. ``--pin``
  reinstalls the exact versions recorded in ``engines/INSTALL.json`` instead.
* **Checksums are verified.** GitHub's API returns a ``sha256`` digest per asset, so
  a truncated or tampered download fails here instead of at the first engine launch.
  Nets from lczero.org have no published digest, so only their size is checked.
* **Downloads are atomic.** Bytes go to a ``.part`` file and are renamed into place, so
  an interrupted run never leaves a half-written 582 MB archive that a later run would
  mistake for a complete one.
* **Idempotent.** Anything already present and complete is skipped, so re-running after
  a partial failure costs only what is still missing.
* **Offline-capable.** ``--verify`` and ``--only`` never touch the network beyond the
  release lookup, and ``--skip-book``/``--skip-net`` keep it to one file.

The default Lc0 build is chosen from what the machine actually has: the CUDA build on a
box with an NVIDIA GPU, the 25 MB DirectML build on any other DX12-capable Windows
machine, and the CPU build everywhere else. Lc0 is optional -- ``analyze.py --no-lc0``
runs on Stockfish alone -- so ``--skip-lc0`` is a fully supported install.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent
ENGINES = ROOT / "engines"
NETS = ROOT / "data" / "nets"
INSTALL_RECORD = ENGINES / "INSTALL.json"
REQUIREMENTS = ROOT / "requirements.txt"
VENV = ROOT / ".venv"

GITHUB_API = "https://api.github.com"
STOCKFISH_REPO = "official-stockfish/Stockfish"
LC0_REPO = "LeelaChessZero/lc0"
USER_AGENT = "chess-coach-setup/1.0"

# Lc0 network weights, with exact byte sizes read from the server. There is no
# published checksum for these, so size is the only integrity signal available. The
# filenames are the real upstream ones -- engines.find_net() matches them by prefix.
NET_SIZES = {
    "t3-512x15x16h-distill-swa-2767500.pb.gz": 153072487,
    "t1-512x15x8h-distilled-swa-3395000.pb.gz": 149758071,
    "t1-256x10-distilled-swa-2432500.pb.gz": 37118673,
}
NET_BASE = "https://storage.lczero.org/files/networks-contrib"
DEFAULT_NET = "t3-512x15x16h-distill-swa-2767500.pb.gz"

# Lc0 Windows builds, keyed by the short name used on the command line. "cuda12" is
# the one that bundles its CUDA DLLs (~582 MB, no separate CUDA install); the "-nodll"
# variants are small but assume the driver runtime is already on the machine.
LC0_BUILD_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "cuda12": {"must": ["windows-gpu-nvidia-cuda12.zip"], "forbid": ["nodll"]},
    "cuda12-nodll": {"must": ["windows-gpu-nvidia-cuda12-nodll.zip"], "forbid": []},
    "cuda11": {"must": ["windows-gpu-nvidia-cuda11.zip"], "forbid": ["nodll"]},
    "onnx-dml": {"must": ["windows-onnx-dml"], "forbid": []},
    "cpu-dnnl": {"must": ["windows-cpu-dnnl"], "forbid": []},
    "cpu-openblas": {"must": ["windows-cpu-openblas"], "forbid": []},
}

GPU_LC0_BUILDS = ("cuda12", "cuda12-nodll", "cuda11", "onnx-dml")
CPU_LC0_BUILDS = ("cpu-dnnl", "cpu-openblas")


# --------------------------------------------------------------------------
# small io helpers
# --------------------------------------------------------------------------

def _ssl_context() -> Optional[ssl.SSLContext]:
    """A verified TLS context.

    Windows Python ships no CA bundle, so this is not optional in practice. If
    certifi is missing we say so loudly rather than downgrading to an unverified
    connection.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


SSL_CONTEXT = _ssl_context()


def say(message: str = "") -> None:
    print(message, flush=True)


def step(message: str) -> None:
    say(f"==> {message}")


def warn(message: str) -> None:
    print(f"  ! {message}", file=sys.stderr, flush=True)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def display(path: Path) -> str:
    """Path relative to the project root when it is inside it.

    Engines are also found on PATH and in the winget package directory, so the
    absolute form is the normal case here and must not raise.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def download(url: str, destination: Path, *, expect_size: int = 0) -> bool:
    """Stream ``url`` to ``destination``. Atomic: ``.part`` then rename.

    Returns True on success. A failure removes the partial file, so the next run
    starts clean rather than resuming onto bytes of unknown provenance.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = time.monotonic()
    written = 0
    declared = 0
    last_report = 0.0
    try:
        with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            total = declared or expect_size
            with open(partial, "wb") as fh:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    now = time.monotonic()
                    if now - last_report > 1.0:
                        pct = f" ({100 * written // total}%)" if total else ""
                        rate = written / max(now - started, 0.001)
                        say(f"    {human(written)}{pct} at {human(rate)}/s")
                        last_report = now
        # Two independent checks: what the server promised it would send, and what
        # this script expected to ask for. Either mismatch means a truncated file.
        if declared and written != declared:
            raise OSError(f"server declared {declared:,} bytes, received {written:,}")
        if expect_size and written != expect_size:
            raise OSError(f"expected {expect_size:,} bytes, got {written:,}")
        os.replace(partial, destination)
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        warn(f"download failed for {url}: {exc}")
        partial.unlink(missing_ok=True)
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def get_json(url: str) -> Optional[dict]:
    """GET JSON, or None. A failure here is never fatal -- it falls back to pins."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60, context=SSL_CONTEXT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        warn(f"could not read {url}: {exc}")
        return None


def extract(archive: Path, destination: Path) -> bool:
    """Unpack a zip or tarball, flattening the single top-level folder if there is one.

    Both projects ship flat archives, but a future release adding a wrapper directory
    would otherwise nest the binary where ``engines.find_executable`` cannot see it.
    """
    destination.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(destination.name + "-unpack")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)
        else:
            with tarfile.open(archive, "r:*") as tf:
                if hasattr(tarfile, "data_filter"):
                    tf.extractall(staging, filter="data")   # noqa: S202 - trusted upstream
                else:
                    tf.extractall(staging)                  # noqa: S202
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        warn(f"could not unpack {archive.name}: {exc}")
        shutil.rmtree(staging, ignore_errors=True)
        return False

    entries = list(staging.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        source = entries[0]
    else:
        source = staging
    for item in source.iterdir():
        shutil.move(str(item), str(destination / item.name))
    shutil.rmtree(staging, ignore_errors=True)
    return True


# Directories that ship inside the upstream archives and are of no use to an installed
# binary: the Stockfish zip in particular carries its entire C++ source tree and wiki.
# Only well-known names are removed, and never a directory holding the binary, so a
# release that nests its DLLs beside the executable keeps working.
SOURCE_DIRS = ("src", "source", "tests", "test", "wiki", "doc", "docs", "po", ".github")


def prune_sources(directory: Path, binary: Path) -> int:
    """Drop source/doc directories that came in with the archive.

    Skips any candidate that contains the binary, so a release nesting its DLLs in a
    subdirectory keeps everything it needs.
    """
    keep_root = binary.parent.resolve()
    removed = 0
    for name in SOURCE_DIRS:
        # Materialise before deleting: rglob walks the tree lazily and would otherwise
        # trip over directories that have just been removed underneath it.
        for candidate in list(directory.rglob(name)):
            if not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            if resolved == keep_root or resolved in keep_root.parents:
                continue
            count = sum(1 for p in candidate.rglob("*") if p.is_file())
            shutil.rmtree(candidate, ignore_errors=True)
            removed += count
    return removed


def make_executable(directory: Path, names: Iterable[str]) -> None:
    """Restore the exec bit. The tar filter and some zips drop it."""
    if os.name == "nt":
        return
    for item in directory.rglob("*"):
        if item.is_file() and any(n in item.name for n in names):
            item.chmod(item.stat().st_mode | 0o755)


# --------------------------------------------------------------------------
# release resolution
# --------------------------------------------------------------------------

@dataclass
class Asset:
    name: str
    url: str
    size: int
    digest: str = ""

    @property
    def expected_sha256(self) -> str:
        # The API reports "sha256:<hex>"; older assets report null.
        return self.digest.split(":", 1)[1] if ":" in self.digest else ""


@dataclass
class Release:
    repo: str
    tag: str
    name: str
    assets: List[Asset] = field(default_factory=list)

    def pick(
        self, must: Sequence[str] = (), forbid: Sequence[str] = ()
    ) -> Optional[Asset]:
        """Best asset containing every ``must`` substring and no ``forbid`` one.

        Ties go to the largest file, which is the right default: among near-identical
        archives the bigger one is the less-trimmed build.
        """
        candidates = [
            a
            for a in self.assets
            if all(m in a.name for m in must) and not any(f in a.name for f in forbid)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda a: a.size)


def latest_release(repo: str) -> Optional[Release]:
    data = get_json(f"{GITHUB_API}/repos/{repo}/releases/latest")
    return _to_release(repo, data) if data else None


def tagged_release(repo: str, tag: str) -> Optional[Release]:
    data = get_json(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}")
    return _to_release(repo, data) if data else None


def _to_release(repo: str, data: dict) -> Optional[Release]:
    if not isinstance(data, dict) or "assets" not in data:
        return None
    return Release(
        repo=repo,
        tag=str(data.get("tag_name", "")),
        name=str(data.get("name") or data.get("tag_name", "")),
        assets=[
            Asset(
                name=str(a.get("name", "")),
                url=str(a.get("browser_download_url", "")),
                size=int(a.get("size") or 0),
                digest=str(a.get("digest") or ""),
            )
            for a in data["assets"]
            if a.get("browser_download_url")
        ],
    )


def load_record() -> dict:
    try:
        return json.loads(INSTALL_RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_record(record: dict) -> None:
    ENGINES.mkdir(parents=True, exist_ok=True)
    record["installed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["python"] = platform.python_version()
    record["platform"] = f"{platform.system()} {platform.machine()}"
    tmp = INSTALL_RECORD.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, INSTALL_RECORD)


# --------------------------------------------------------------------------
# platform detection
# --------------------------------------------------------------------------

def stockfish_asset_patterns() -> List[str]:
    """Candidate Stockfish asset names for this machine, best first."""
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        if machine in ("arm64", "aarch64"):
            return ["stockfish-windows-arm64-universal.zip"]
        return [
            "stockfish-windows-x86-64-universal.zip",
            "stockfish-windows-x86-64.zip",
        ]
    if system == "Darwin":
        return ["stockfish-macos-universal.tar.gz"]
    if machine in ("arm64", "aarch64"):
        return ["stockfish-linux-arm64-universal.tar.gz"]
    return [
        "stockfish-linux-x86-64-avx2.tar.gz",
        "stockfish-linux-x86-64-universal.tar.gz",
    ]


def has_nvidia_gpu() -> bool:
    """True if this looks like a box with an NVIDIA card and its driver installed."""
    if shutil.which("nvidia-smi"):
        return True
    if platform.system() != "Windows":
        return Path("/dev/nvidiactl").exists()
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return (system32 / "nvidiaapi.dll").is_file() or (system32 / "nvapi64.dll").is_file()


def auto_lc0_build() -> str:
    """Pick an Lc0 build from the hardware, so the default download is not 582 MB."""
    if platform.system() != "Windows":
        return "cpu-dnnl" if platform.system() != "Darwin" else "cpu-openblas"
    if has_nvidia_gpu():
        return "cuda12"
    warn("no NVIDIA GPU detected; using the 25 MB DirectML build (works on any DX12 GPU)")
    return "onnx-dml"


# --------------------------------------------------------------------------
# install steps
# --------------------------------------------------------------------------

def step_venv(force: bool, interpreter: str = "") -> bool:
    """Create ``.venv`` if needed and install requirements into it."""
    if not REQUIREMENTS.is_file():
        warn(f"{REQUIREMENTS.name} not found; skipping the dependency step")
        return False

    interpreter = interpreter or sys.executable
    python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    created = False
    if not python.is_file():
        step(f"creating {VENV.name} with {interpreter}")
        result = subprocess.run([interpreter, "-m", "venv", str(VENV)])
        if result.returncode != 0 or not python.is_file():
            warn("venv creation failed; install requirements manually")
            return False
        created = True
    elif force:
        say(f"    {VENV.name} already exists")

    if created or force:
        step(f"installing {REQUIREMENTS.name} into {VENV.name}")
        result = subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            warn("pip install failed; the rest of setup will still run")
            return False
    else:
        say(f"    {VENV.name} already has its dependencies (use --force to reinstall)")
    say(f"    run things with: {python}")
    return True


def install_stockfish(record: dict, *, force: bool, pin: str) -> bool:
    target = ENGINES / "stockfish"
    entry = record.get("stockfish")
    if not isinstance(entry, dict):
        entry = {"tag": entry} if isinstance(entry, str) and entry else {}
        record["stockfish"] = entry

    found = _engine_binary(target, ("stockfish",))
    if found and not force:
        say(f"    Stockfish already present: {display(found)}")
        entry.setdefault("binary", display(found))
        return True

    step("Stockfish")
    release = tagged_release(STOCKFISH_REPO, pin) if pin else latest_release(STOCKFISH_REPO)
    if release is None:
        warn("could not resolve a Stockfish release; install it with "
             "'winget install --id=Stockfish.Stockfish -e' or set STOCKFISH_PATH")
        return False

    asset = None
    for name in stockfish_asset_patterns():
        asset = release.pick(must=[name])
        if asset:
            break
    if asset is None:
        warn(f"release {release.tag} has no asset for this platform "
             f"(saw: {', '.join(a.name for a in release.assets[:6])}...)")
        return False

    say(f"    {release.name} -> {asset.name} ({human(asset.size)})")
    archive = target / asset.name
    if not archive.is_file() or force:
        if not download(asset.url, archive, expect_size=asset.size):
            return False
    if not _verify_digest(archive, asset):
        archive.unlink(missing_ok=True)
        return False
    if not extract(archive, target):
        return False
    archive.unlink(missing_ok=True)          # keep the repo small; it is re-downloadable
    make_executable(target, ("stockfish",))

    binary = _engine_binary(target, ("stockfish",))
    if binary is None:
        warn("unpacked, but no Stockfish binary found in the archive")
        return False
    dropped = prune_sources(target, binary)
    if dropped:
        say(f"    removed {dropped} unused source file(s) from the archive")
    entry.update(
        {"tag": release.tag, "asset": asset.name, "binary": display(binary)}
    )
    say(f"    installed {display(binary)}")
    return True


def install_lc0(record: dict, *, build: str, force: bool, pin: str) -> bool:
    if platform.system() != "Windows":
        warn("Lc0 Windows builds are the supported configuration here; skipping Lc0")
        return False

    target = ENGINES / ("lc0-gpu" if build in GPU_LC0_BUILDS else "lc0-cpu")
    found = _engine_binary(target, ("lc0.exe", "lc0"))
    entry = record.get("lc0")
    if not isinstance(entry, dict):
        entry = {"tag": entry} if isinstance(entry, str) and entry else {}
        record["lc0"] = entry
    recorded_build = str(entry.get("build") or "")
    if found and not force:
        if recorded_build not in ("", "unknown") and recorded_build != build:
            # A known, different build was explicitly requested. Say what is being
            # replaced: the builds are not interchangeable, and both ship an
            # identically named lc0.exe.
            warn(f"{display(found)} is the {recorded_build} build; installing {build} instead")
        else:
            say(f"    Lc0 already present: {display(found)}")
            entry["binary"] = display(found)
            if recorded_build:
                entry["build"] = recorded_build
            else:
                # Not installed by setup.py, so the build genuinely is unknown. Saying
                # so beats recording the requested build and quietly being wrong.
                entry["build"] = "unknown"
                say("      build not recorded; pass --force to install a different one")
            return True

    step(f"Lc0 ({build})")
    release = tagged_release(LC0_REPO, pin) if pin else latest_release(LC0_REPO)
    if release is None:
        warn("could not resolve an Lc0 release; download it from "
             "https://lczero.org/play/download/ or skip with --skip-lc0")
        return False

    patterns = LC0_BUILD_PATTERNS.get(build)
    if patterns is None:
        warn(f"unknown Lc0 build {build!r}; choose from {', '.join(LC0_BUILD_PATTERNS)}")
        return False
    asset = release.pick(must=patterns["must"], forbid=patterns["forbid"])
    if asset is None:
        warn(f"release {release.tag} has no {build} asset for Windows")
        return False

    if found:
        # A build swap leaves the old files behind, and both builds ship an
        # identically named lc0.exe. Clear the directory first so the extractor
        # cannot leave a stale DLL next to the new binary.
        say(f"    replacing the existing build in {display(target)}")
        shutil.rmtree(target, ignore_errors=True)

    say(f"    {release.name} -> {asset.name} ({human(asset.size)})")
    archive = target / asset.name
    if archive.is_file() and force:
        archive.unlink()
    if not archive.is_file():
        if not download(asset.url, archive, expect_size=asset.size):
            return False
    if not _verify_digest(archive, asset):
        archive.unlink(missing_ok=True)
        return False
    if not extract(archive, target):
        return False
    archive.unlink(missing_ok=True)
    make_executable(target, ("lc0",))

    binary = _engine_binary(target, ("lc0.exe", "lc0"))
    if binary is None:
        warn("unpacked, but no lc0 binary found in the archive")
        return False
    entry.update(
        {
            "tag": release.tag,
            "asset": asset.name,
            "build": build,
            "binary": display(binary),
        }
    )
    say(f"    installed {display(binary)}")
    return True


def install_net(record: dict, *, name: str, force: bool) -> bool:
    NETS.mkdir(parents=True, exist_ok=True)
    target = NETS / name
    expected = NET_SIZES.get(name, 0)
    if not expected:
        warn(f"{name} is not a known network; size cannot be verified")

    # Look for the network under any name. The project matches nets by prefix
    # (engines.find_net), and a hand-renamed copy is still the right net, so
    # downloading a second 153 MB copy of what is already on disk would be silly.
    prefix = name.split("-distil")[0]
    for candidate in sorted(NETS.glob("*.pb.gz")):
        if force or not candidate.stem.startswith(prefix):
            continue
        actual = candidate.stat().st_size
        if not expected or abs(actual - expected) <= expected * 0.05:
            if candidate != target:
                say(f"    {display(candidate)} is already this network "
                    f"({human(actual)}); not downloading it again")
            else:
                say(f"    net already present: {display(candidate)} ({human(actual)})")
            record["net"] = candidate.name
            return True
        warn(f"{candidate.name} is {human(actual)}, expected about {human(expected)}")

    step(f"Lc0 network: {name}")
    if not download(f"{NET_BASE}/{name}", target, expect_size=expected):
        return False
    record["net"] = name
    say(f"    installed {display(target)} ({human(target.stat().st_size)})")
    return True


def install_book(record: dict, *, force: bool) -> bool:
    step("opening book (lichess-org/chess-openings, CC0)")
    try:
        import openings
    except ImportError as exc:
        warn(f"cannot import openings ({exc}); run this from the project root")
        return False
    if force:
        for name in openings.FILES:
            (Path(openings.BOOK_DIR) / name).unlink(missing_ok=True)
    count, notes = openings.ensure_book()
    for note in notes:
        say(f"    {note}")
    if count == 0:
        warn("opening book is empty; openings will fall back to a move-15 heuristic")
        return False
    record["book_entries"] = count
    say(f"    {count:,} openings available")
    return True


def _engine_binary(directory: Path, names: Sequence[str]) -> Optional[Path]:
    """The engine executable in ``directory``, preferring an exact name match.

    Mirrors ``engines.find_executable``'s hint order so that what setup installs is
    what the analyser finds.
    """
    if not directory.is_dir():
        return None
    files = [p for p in directory.rglob("*") if p.is_file()]
    for hint in names:
        for path in files:
            if path.name.lower() == hint:
                return path
    for hint in names:
        for path in files:
            if hint in path.name.lower():
                return path
    return None


def _verify_digest(path: Path, asset: Asset) -> bool:
    """Check the downloaded archive against the API's sha256, when it has one."""
    expected = asset.expected_sha256
    if not expected:
        warn(f"{asset.name} has no published digest; size was checked only")
        return True
    say(f"    verifying sha256 ({human(path.stat().st_size)})")
    actual = sha256_file(path)
    if actual != expected:
        warn(f"checksum mismatch for {asset.name}")
        warn(f"  expected {expected}")
        warn(f"  got      {actual}")
        return False
    return True


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def probe(name: str, path: Path, *, timeout: int = 60) -> Optional[str]:
    """Run a UCI handshake and return the engine's self-reported name."""
    say(f"    {name}: {display(path)}")
    try:
        proc = subprocess.run(
            [str(path)],
            input=b"uci\nisready\nquit\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn(f"{name} did not respond: {exc}")
        return None
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.lower().startswith("id name"):
            return line.split(None, 2)[2] if len(line.split(None, 2)) > 2 else name
    warn(f"{name} produced no 'id name' line")
    return None


def verify(record: dict) -> bool:
    """Report what is installed and whether the analyser can actually use it."""
    step("verification")
    ok = True

    sys.path.insert(0, str(ROOT))
    import engines as engine_discovery

    stockfish = engine_discovery.find_executable("stockfish", engine_discovery._STOCKFISH_HINTS)
    if stockfish and probe("Stockfish", Path(stockfish)):
        say(f"      {human(_bench_hint(Path(stockfish)))} binary, ready for analyze.py")
    else:
        ok = False
        warn("Stockfish is not usable; the analyser cannot run without it")

    lc0 = engine_discovery.find_executable("lc0", engine_discovery._LC0_HINTS)
    if lc0:
        name = probe("Lc0", Path(lc0))
        if name:
            net = engine_discovery.find_net()
            if net:
                say(f"      net {Path(net).name} ({human(Path(net).stat().st_size)})")
            else:
                ok = False
                warn("Lc0 is installed but no .pb.gz network is present in data/nets/")
            backends = engine_discovery.lc0_backends(str(lc0))
            say(f"      backends {', '.join(backends[:5]) if backends else '(could not be read)'}")
            if "onnx-dml" in backends and not list(
                Path(lc0).parent.glob("DirectML.dll")
            ):
                warn(
                    "DirectML.dll is missing; run install.cmd next to lc0.exe "
                    "or the onnx-dml backend will fall back to the CPU"
                )
        else:
            ok = False
    else:
        say("    Lc0: not installed -- fine, analyze.py --no-lc0 still works")

    try:
        import openings

        count, _ = openings.ensure_book(allow_download=False)
        if count:
            say(f"    opening book: {count:,} entries")
        else:
            warn("opening book is empty or missing")
            ok = False
    except ImportError:
        warn("cannot import openings; run setup.py from the project root")

    for key in ("stockfish", "lc0", "net"):
        if record.get(key):
            say(f"    {key}: {record[key]}")
    return ok


def _bench_hint(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python setup.py",
        description="Install everything this project downloads: venv, dependencies, "
                    "Stockfish, Lc0, a neural network and the opening book.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python setup.py                    everything, then verify\n"
            "  python setup.py --verify           probe what is installed, download nothing\n"
            "  python setup.py --skip-lc0         Stockfish only (Lc0 is optional)\n"
            "  python setup.py --only book        just the opening book\n"
            "  python setup.py --lc0-build onnx-dml   25 MB DirectML build, no CUDA needed\n"
            "  python setup.py --force            re-download even if present\n"
        ),
    )
    ap.add_argument("--only", nargs="+", metavar="STEP",
                    choices=["venv", "stockfish", "lc0", "net", "book"],
                    help="run only these steps")
    ap.add_argument("--skip", nargs="+", metavar="STEP", default=[],
                    choices=["venv", "stockfish", "lc0", "net", "book"],
                    help="skip these steps")
    ap.add_argument("--verify", action="store_true",
                    help="probe what is installed and download nothing")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the verification pass at the end")
    ap.add_argument("--force", action="store_true",
                    help="re-download and reinstall even if present")
    ap.add_argument("--pin", action="store_true",
                    help="reinstall the versions recorded in engines/INSTALL.json")
    ap.add_argument("--lc0-build", default="auto",
                    help=f"Lc0 build to install: auto, {', '.join(LC0_BUILD_PATTERNS)}")
    ap.add_argument("--net", default=DEFAULT_NET, metavar="FILE",
                    help=f"Lc0 network filename (default {DEFAULT_NET})")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter used to create the virtualenv")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    record = load_record()

    if args.verify:
        return 0 if verify(record) else 1

    wanted = set(args.only) if args.only else {"venv", "stockfish", "lc0", "net", "book"}
    wanted -= set(args.skip)

    say(f"chess-coach setup on {platform.system()} {platform.machine()}, "
        f"Python {platform.python_version()}")
    say()

    pins = {
        "stockfish": str(record.get("stockfish") or ""),
        "lc0": str(record.get("lc0") or ""),
    }
    if not args.pin:
        pins = {"stockfish": "", "lc0": ""}
    if args.pin:
        for key in ("stockfish", "lc0"):
            value = pins[key]
            pins[key] = value if isinstance(value, str) else ""
            if not pins[key]:
                warn(f"--pin requested but no recorded {key} version; using the latest")

    results: Dict[str, bool] = {}
    if "venv" in wanted:
        results["venv"] = step_venv(args.force, args.python)
    if "stockfish" in wanted:
        results["stockfish"] = install_stockfish(
            record, force=args.force, pin=pins["stockfish"]
        )
    if "lc0" in wanted:
        build = auto_lc0_build() if args.lc0_build == "auto" else args.lc0_build
        results["lc0"] = install_lc0(
            record, force=args.force, pin=pins["lc0"], build=build
        )
    if "net" in wanted:
        results["net"] = install_net(record, name=args.net, force=args.force)
    if "book" in wanted:
        results["book"] = install_book(record, force=args.force)

    save_record(record)

    say()
    step("summary")
    for name, good in results.items():
        say(f"    {'ok  ' if good else 'FAIL'} {name}")
    required = {"stockfish"} & wanted
    missing = [name for name in required if not results.get(name)]

    if not args.no_verify:
        say()
        verify(record)

    if missing:
        say()
        warn(f"required step(s) failed: {', '.join(missing)}")
        return 1
    say()
    say("Next:  python -m process_api.cli --player YOURNAME --dry-run")
    say("       python analyze.py --player YOURNAME --out out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())