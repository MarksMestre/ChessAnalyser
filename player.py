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
"""

from __future__ import annotations

import os
import sys
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