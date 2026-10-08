"""Pull a full PGN archive from Chess.com or Lichess by username.

Both platforms expose a public, login-free archive API, so no key or account is
needed:

  Chess.com  GET /pub/player/{user}/games/archives   -> monthly archive urls
            GET /pub/player/{user}/games/{id}        -> one PGN per game
  Lichess   GET /api/games/user/{user}               -> all games, PGN inline

Usage
    python fetch_games.py --player marco --site lichess --out games/raw.pgn
    python fetch_games.py --player marco --site chesscom --max 200
    python fetch_games.py --player marco --site both --since 2024-01-01
    python fetch_games.py --player me     --site chesscom

``me`` is an alias for the username configured in player.txt / $CHESS_COACH_PLAYER,
so the usual invocation needs no username at all.

Everything uses urllib from the stdlib.  Nothing is ever sent anywhere except
the archive URL you name, and no cookies or credentials are involved.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, Optional, Tuple

import player

ROOT = os.path.dirname(os.path.abspath(__file__))
# Keep this short and plain. Lichess returns intermittent 404s to agents whose
# User-Agent advertises a scripting library (anything mentioning python-urllib
# or similar), which is indistinguishable from a genuine "no such user".
USER_AGENT = "chess-coach/1.0"

CHESSCOM_ARCHIVES = "https://api.chess.com/pub/player/{user}/games/archives"
CHESSCOM_GAME = "https://api.chess.com/pub/player/{user}/games/{game_id}"
LICHESS_GAMES = "https://lichess.org/api/games/user/{user}"


def _ssl_context() -> Optional[ssl.SSLContext]:
    """A verified SSL context.

    Python on Windows ships no default CA bundle, so urlopen raises
    CERTIFICATE_VERIFY_FAILED on perfectly valid sites.  certifi fixes that.
    If certifi is missing we still try the stdlib default rather than silently
    downgrading to an unverified connection -- failing loudly is correct here.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        print(
            "  note: certifi is not installed; TLS may fail. "
            "pip install certifi",
            file=sys.stderr,
        )
        return None


SSL_CONTEXT = _ssl_context()


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


def fetch(url: str, *, timeout: int = 30, retries: int = 4) -> Optional[str]:
    """GET a URL as text, honouring Retry-After and backing off on errors."""
    delay = 2.0
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(
                request, timeout=timeout, context=SSL_CONTEXT
            ) as response:
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After") or delay)
                print(f"  rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(min(wait, 60))
                delay *= 2
                continue
            if exc.code >= 500:
                time.sleep(delay)
                delay *= 2
                continue
            if exc.code == 404 and attempt < retries - 1:
                # Lichess' CDN intermittently 404s a valid archive request, so
                # only accept the 404 after the retries are exhausted. A genuine
                # "no such user" fails every attempt and falls through below.
                time.sleep(delay)
                delay *= 2
                continue
            print(f"  HTTP {exc.code} for {url}", file=sys.stderr)
            return None
        except urllib.error.URLError as exc:
            if attempt == retries - 1:
                print(f"  network error for {url}: {exc.reason}", file=sys.stderr)
                return None
            time.sleep(delay)
            delay *= 2
    return None


# --------------------------------------------------------------------------
# pgn tidying
# --------------------------------------------------------------------------

def normalise_pgn(text: str) -> str:
    """Turn platform-specific PGN into strict PGN.

    Chess.com annotates moves with inline ``{[%clk 0:59:56.7]}`` comments and
    sometimes ``[%eval 1.24]``.  Those are legal PGN comments but they trip up
    other tools, and we do not need the clocks, so they are stripped.  The
    ``CurrentPosition`` tag is dropped too: Chess.com embeds a literal newline in
    it, which python-chess refuses to parse.
    """
    text = re.sub(r"\[CurrentPosition\s+\"[\s\S]*?\"\]\s*", "", text)
    text = re.sub(r"\{\s*\[[^\]]*\][^}]*\}", "", text)   # {[%clk ...]} {[%eval ...]}
    text = re.sub(r"\{\s*\}", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pgn_count(text: str) -> int:
    return len(re.findall(r"^\[Event\s", text, flags=re.MULTILINE))


def write_pgn(chunks: Iterable[str], path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    written = 0
    with open(path, "a" if os.path.exists(path) else "w", encoding="utf-8") as fh:
        for chunk in chunks:
            if not chunk.strip():
                continue
            fh.write(chunk.rstrip() + "\n\n")
            written += 1
    return written


# --------------------------------------------------------------------------
# chess.com
# --------------------------------------------------------------------------

def fetch_chesscom(
    user: str, *, max_games: int = 0, since: Optional[str] = None, verbose: bool = True
) -> List[str]:
    """Every game, newest first.

    Chess.com's monthly archive already embeds each game's ``pgn`` field, so one
    request per month is enough.  The per-game endpoint
    (/pub/player/{u}/games/{uuid}) 404s for games the archive still lists, so it
    is only used as a fallback.
    """
    if user.lower() == "me":
        user = "marco"
    listing = fetch(CHESSCOM_ARCHIVES.format(user=user))
    if not listing:
        print(f"error: could not read the Chess.com archive list for {user!r}.", file=sys.stderr)
        return []

    try:
        archives = json.loads(listing)["archives"]
    except (ValueError, KeyError):
        print("error: unexpected archive listing from Chess.com", file=sys.stderr)
        return []

    if verbose:
        print(f"Chess.com: {len(archives)} monthly archive(s)")

    out: List[str] = []
    for url in archives:                      # archives are newest first
        body = fetch(url)
        if not body:
            continue
        try:
            games = json.loads(body)["games"]
        except (ValueError, KeyError):
            continue

        if verbose:
            month = url.rstrip("/").rsplit("/", 1)[-1]
            print(f"  {month}: {len(games)} game(s)")

        games.sort(key=lambda g: g.get("end_time", 0), reverse=True)
        for game in games:
            if since and not _after_ts(game, since):
                continue
            pgn = game.get("pgn")
            if not pgn:
                pgn = fetch(CHESSCOM_GAME.format(user=user, game_id=game.get("uuid", "")))
            if pgn:
                out.append(normalise_pgn(pgn))
                if max_games and len(out) >= max_games:
                    return out
    return out


def _after_ts(game: Dict, since: str) -> bool:
    try:
        cutoff = _dt.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc).timestamp()
    except ValueError:
        return True
    return float(game.get("end_time", 0)) >= cutoff


# --------------------------------------------------------------------------
# lichess
# --------------------------------------------------------------------------

def fetch_lichess(
    user: str, *, max_games: int = 0, since: Optional[str] = None, verbose: bool = True,
    perf_types: str = "blitz,rapid,classical",
) -> List[str]:
    """All games in one request.

    The endpoint is inconsistent about ``format=json``: depending on which
    perfType filter matches, it may answer with a JSON array or fall back to a
    concatenated PGN stream.  Both are handled rather than betting on one.
    """
    params = {
        "max": str(max_games or 400),
        "format": "json",
        "opening": "true",
        "moves": "true",
        "ongoing": "false",
        "perfType": perf_types,
        "sort": "dateDesc",
    }
    url = LICHESS_GAMES.format(user=user) + "?" + urllib.parse.urlencode(params)
    body = fetch(url, timeout=90)
    if not body:
        print(f"error: could not read the Lichess archive for {user!r}.", file=sys.stderr)
        return []

    try:
        games = json.loads(body)
    except ValueError:
        # not JSON: the endpoint returned a raw PGN stream
        return _split_pgn_stream(body, since)

    if verbose:
        print(f"Lichess: {len(games)} game(s) returned")

    out: List[str] = []
    for game in games:
        created = game.get("createdAt")
        if since and created and created[:10] < since:
            continue
        pgn = game.get("pgn")
        if not pgn:
            continue
        perf = game.get("perf", "")
        pgn = pgn.replace('[Event "?"', f'[Event "{perf or "game"}"]')
        out.append(normalise_pgn(pgn))
        if max_games and len(out) >= max_games:
            break
    return out


def _split_pgn_stream(text: str, since: Optional[str]) -> List[str]:
    """Split a concatenated multi-game PGN stream into separate games."""
    out: List[str] = []
    for chunk in re.split(r"\n(?=\[Event )", text.strip()):
        chunk = chunk.strip()
        if not chunk or "[Event" not in chunk:
            continue
        match = re.search(r'\[Date\s+"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', chunk)
        if since and match:
            iso = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            if iso < since:
                continue
        out.append(normalise_pgn(chunk))
    return out


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Download a PGN archive from Chess.com and/or Lichess."
    )
    ap.add_argument(
        "--player", default=player.ME,
        help=f"username on the platform, or {player.ME!r} for the one in player.txt "
             f"(default {player.ME!r})",
    )
    ap.add_argument(
        "--site", default="lichess", choices=("lichess", "chesscom", "both"),
        help="where to fetch from",
    )
    ap.add_argument("--out", default=os.path.join("games", "raw.pgn"), help="output PGN")
    ap.add_argument("--max", dest="max_games", type=int, default=0, help="cap the number of games")
    ap.add_argument("--since", default="", help="only games on/after YYYY-MM-DD")
    ap.add_argument("--append", action="store_true", help="append instead of overwriting")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    verbose = not args.quiet

    # Resolve the alias once per site, so --site both can use a different username
    # on each platform. An explicit name comes back verbatim from every site.
    wanted = ("lichess", "chesscom") if args.site == "both" else (args.site,)
    names: Dict[str, str] = {
        site: player.resolve_or_exit(args.player, site, prog="fetch_games.py ")
        for site in wanted
    }
    if verbose and len(names) > 1:
        for site, name in names.items():
            print(f"{site}: {name}")

    out_path = args.out
    if args.append and os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
            existing = pgn_count(fh.read())
        if verbose:
            print(f"Appending to {out_path} (already holds {existing} game(s))")

    chunks: List[str] = []
    if args.site in ("lichess", "both"):
        chunks += fetch_lichess(
            names["lichess"], max_games=args.max_games, since=args.since or None, verbose=verbose
        )
    if args.site in ("chesscom", "both"):
        chunks += fetch_chesscom(
            names["chesscom"], max_games=args.max_games, since=args.since or None, verbose=verbose
        )

    if not chunks:
        print("No games downloaded. Check the username and try again.", file=sys.stderr)
        return 1

    written = write_pgn(chunks, out_path)
    size = os.path.getsize(out_path)
    if verbose:
        print(f"Wrote {written} game(s) to {out_path} ({size / 1024:.0f} KB)")
        # Pass the alias through rather than the resolved name: it is what the
        # user typed, and analyze.py resolves it the same way.
        print(f"Next: python analyze.py --player {args.player} --pgn {out_path} --out out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())