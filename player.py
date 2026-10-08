"""Who ``me`` stands for.

Every entry point wants ``--player``, and typing your own username into every
invocation is tedious and easy to mistype.  Pass ``--player me`` and this module
looks the real name up, in order:

  1. ``$CHESS_COACH_PLAYER``  -- one-off, touches no file
  2. ``player.txt`` in the project root, ``site=name`` lines or one bare ``name``

The alias is never a mode: an explicit ``--player someuser`` is passed straight
through, so ``me`` and a real name can be mixed freely in shell history, aliases
and scripts.  ``me`` matches case-insensitively and ignores surrounding space.

``player.txt`` is git-ignored, because a username is personal:

    # username(s) behind --player me
    chesscom=yourname
    lichess=yourname

A bare line sets the fallback for any site without its own entry::

    yourname

When no site is asked for (analyze.py matches a PGN, which is not a platform) a
per-site-only file still answers: the bare default first, then the first
configured site.  That keeps ``--player me`` working whichever shape you write.

This module deliberately knows nothing about ``process_api``: that sub-project is
git-ignored as a whole, so anything shipped here must not import from it.

The resolution rules are the fiddly part of every entry point, so they are
checked here rather than in a separate test file -- ``python player.py
--self-test`` runs them offline, and ``setup.py --verify`` calls it.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from typing import Dict, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
PLAYER_TXT = os.path.join(ROOT, "player.txt")
ENV_VAR = "CHESS_COACH_PLAYER"

#: The alias. Matched case-insensitively, so ``Me`` is the same thing.
ME = "me"

#: Sites ``player.txt`` may key a per-site name on.  ``chess.com``/``chess-com``
#: normalise onto ``chesscom`` because that is the spelling --site uses.
SITES = ("chesscom", "lichess")


def _normalise_site(site: str) -> str:
    return site.strip().lower().replace(".", "").replace("-", "").replace("_", "")


def is_me(value: Optional[str]) -> bool:
    """True for the alias, and for nothing at all -- both mean "look it up"."""
    name = (value or "").strip()
    return not name or name.lower() == ME


def _parse(text: str) -> Tuple[Optional[str], Dict[str, str]]:
    """Split config text into ``(default, {site: name})``.

    Unknown keys and blank names are ignored rather than rejected: a typo should
    not turn into a confusing "cannot resolve me" instead of falling through to
    the next source.  A name of ``me`` is dropped for the same reason -- it would
    only point back at itself.
    """
    default: Optional[str] = None
    sites: Dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        key, sep, value = line.partition("=")
        name = value.strip() if sep else line
        if not name or name.lower() == ME:
            continue
        if not sep:
            if default is None:
                default = name
            continue
        site = _normalise_site(key)
        if site in SITES and site not in sites:
            sites[site] = name
    return default, sites


def _read_file() -> Tuple[Optional[str], Dict[str, str]]:
    """``(default, {site: name})`` from ``player.txt``; both empty when unusable."""
    try:
        with open(PLAYER_TXT, "r", encoding="utf-8") as handle:
            return _parse(handle.read())
    except OSError:
        return None, {}


def _read_env() -> Tuple[Optional[str], Dict[str, str]]:
    return _parse(os.environ.get(ENV_VAR, ""))


def _lookup(default: Optional[str], sites: Dict[str, str], key: str) -> Optional[str]:
    """Pick one name out of one source's parsed config.

    With no site to go on (analyze.py matches a PGN, which is not a platform), a
    per-site-only file still has to answer: the bare default wins, otherwise the
    first configured site in SITES order.  Deterministic on purpose, because the
    result is compared against PGN headers and must not vary between runs.
    """
    if key and sites.get(key):
        return sites[key]
    if default:
        return default
    for site in SITES:
        if sites.get(site):
            return sites[site]
    return None


def resolve(value: Optional[str] = None, site: Optional[str] = None) -> Optional[str]:
    """The username ``value`` stands for, or ``None`` if the alias is unresolved.

    A real name is returned verbatim, whatever the site -- the site only chooses
    which ``site=name`` entry an alias picks up.
    """
    name = (value or "").strip()
    if name and name.lower() != ME:
        return name

    key = _normalise_site(site) if site else ""
    for default, sites in (_read_env(), _read_file()):
        found = _lookup(default, sites, key)
        if found:
            return found
    return None


def resolve_or_exit(value: Optional[str] = None, site: Optional[str] = None, prog: str = "") -> str:
    """``resolve()``, but an unresolved alias fails now with a way to fix it.

    Deferring this to the HTTP layer would surface as an indistinguishable 404.
    """
    name = resolve(value, site)
    if name:
        return name

    asked = (value or "").strip() or f"--player {ME}"
    print(f"error: {asked} has no username: neither ${ENV_VAR} nor {PLAYER_TXT} names one.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Set one of these:", file=sys.stderr)
    print(f"  ${ENV_VAR}=yourname", file=sys.stderr)
    print(f"  a line in {PLAYER_TXT}:  chesscom=yourname", file=sys.stderr)
    print("", file=sys.stderr)
    print("or skip the alias and name the player directly:", file=sys.stderr)
    print(f"  {prog}--player yourname", file=sys.stderr)
    raise SystemExit(2)


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def self_test() -> int:
    """Check the resolution rules against a temp player.txt. No network, no writes.

    Lives here rather than in a tests/ directory because the repo keeps no test
    files: these checks describe the contract of the module above them, so they
    cannot drift away from it the way a separate file can.
    """
    global PLAYER_TXT
    checks = 0
    failures = []

    def check(label: str, got, want) -> None:
        nonlocal checks
        checks += 1
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    original_txt = PLAYER_TXT
    original_env = os.environ.pop(ENV_VAR, None)

    class config:
        """resolve() against a throwaway player.txt, then put the real one back.

        ``text=None`` means no file at all, which is a case worth testing: an
        unconfigured machine must get None rather than a traceback.
        """

        def __init__(self, text, env=None):
            self.text = text
            self.env = env

        def __enter__(self):
            global PLAYER_TXT
            self._tmp = tempfile.TemporaryDirectory()
            PLAYER_TXT = os.path.join(self._tmp.name, "player.txt")
            if self.text is not None:
                with open(PLAYER_TXT, "w", encoding="utf-8") as fh:
                    fh.write(self.text)
            os.environ.pop(ENV_VAR, None)
            if self.env is not None:
                os.environ[ENV_VAR] = self.env
            return self

        def __exit__(self, *exc_info):
            global PLAYER_TXT
            PLAYER_TXT = original_txt
            os.environ.pop(ENV_VAR, None)
            if original_env is not None:
                os.environ[ENV_VAR] = original_env
            self._tmp.cleanup()
            return False

    # -- an explicit name is never looked up ------------------------------
    with config("chesscom=fromfile\n"):
        check("explicit name passes through", resolve("realname"), "realname")
        check("explicit name passes through for any site", resolve("realname", "lichess"), "realname")
        check("explicit name is stripped", resolve(" realname "), "realname")

    # -- the alias, with no usable config ---------------------------------
    with config(None):
        check("missing file is not an error", resolve(ME), None)
        check("empty argument looks up too", resolve(None), None)
        check("empty string looks up too", resolve(""), None)
    with config("# only a comment\n"):
        check("comment-only file is not an error", resolve(ME), None)

    # -- per-site vs bare line -------------------------------------------
    both = "chesscom=cc\nlichess=lc\n"
    with config(both):
        check("per-site chesscom", resolve(ME, "chesscom"), "cc")
        check("per-site lichess", resolve(ME, "lichess"), "lc")
        check("no site falls back to the first configured", resolve(ME), "cc")
    with config("lichess=lc\ncc2\n"):
        check("bare line wins when no site asked", resolve(ME), "cc2")
        check("bare line answers an unlisted site", resolve(ME, "chesscom"), "cc2")
        check("per-site entry still wins for its own site", resolve(ME, "lichess"), "lc")
    with config("chesscom=cc\nbogus=nope\n"):
        check("unknown site key is ignored, default used", resolve(ME, "lichess"), "cc")

    # -- site spelling is forgiving --------------------------------------
    for key in ("chesscom", "chess.com", "ChessCom", "chess-com", "chess_com"):
        with config(f"{key}=cc\n"):
            check(f"site key {key!r} normalises", resolve(ME, "chesscom"), "cc")

    # -- comments, blanks, and refusing to point at itself ----------------
    with config("\n# cc\n   \nchesscom=cc  # trailing\n"):
        check("comments and blanks are ignored", resolve(ME), "cc")
    with config("chesscom=me\n"):
        check("a name of me does not point at itself", resolve(ME), None)
        check("a name of ME does not point at itself", resolve("ME"), None)

    # -- precedence: env over file ---------------------------------------
    with config("chesscom=fromfile\n", env="fromenv"):
        check("env beats the file", resolve(ME), "fromenv")
    with config("chesscom=fromfile\n", env="chesscom=fromenv"):
        check("env accepts a site key", resolve(ME, "chesscom"), "fromenv")
        check("env site key beats the file's other site", resolve(ME, "lichess"), "fromenv")

    # -- the alias itself -------------------------------------------------
    for value in ("me", "ME", " Me ", "\tme\n", None, "", "   "):
        check(f"is_me({value!r})", is_me(value), True)
    for value in ("yourname", "memoir", "me_"):
        check(f"is_me({value!r})", is_me(value), False)

    # -- resolve_or_exit: the two outcomes --------------------------------
    with config("chesscom=cc\n"):
        check("resolve_or_exit returns a configured name", resolve_or_exit(ME, "chesscom"), "cc")
    with config("chesscom=cc\n"):
        check("resolve_or_exit passes an explicit name through", resolve_or_exit("realname"), "realname")
    with config(None):
        try:
            # The guidance goes to stderr and would otherwise be the only thing
            # printed by a passing run, so it is captured and checked instead.
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                resolve_or_exit(ME, "chesscom", prog="fetch_games.py ")
            check("resolve_or_exit exits when unresolved", "returned", "SystemExit")
        except SystemExit as exc:
            check("resolve_or_exit exits 2", exc.code, 2)
            note = err.getvalue()
            check("resolve_or_exit names the env var", ENV_VAR in note, True)
            check("resolve_or_exit names player.txt", "player.txt" in note, True)
            check("resolve_or_exit shows how to pass a name", "--player yourname" in note, True)

    # -- the template a fresh clone actually ships ------------------------
    # A placeholder must resolve to itself: if it ever resolved to nothing, the
    # first run of a fresh clone would fail with no obvious cause.
    template = os.path.join(ROOT, "player_example.txt")
    if os.path.isfile(template):
        with open(template, "r", encoding="utf-8") as fh:
            shipped = fh.read()
        with config(shipped):
            check("player_example.txt resolves", bool(resolve(ME, "chesscom")), True)
            check(
                "player_example.txt holds no real username",
                any(
                    part.lower() not in ("chesscom", "lichess")
                    for line in shipped.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                    for part in [line.split("=", 1)[-1].strip()]
                ),
                True,
            )

    print(f"player: {checks - len(failures)}/{checks} checks passed")
    for problem in failures:
        print(f"  FAIL {problem}", file=sys.stderr)
    return 1 if failures else 0


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    print("usage: python player.py --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())