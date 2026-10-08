"""The orchestration: list the archives, decide which are stale, fetch, store.

The whole point of the run is that the second one is nearly free. A month already in
``metadata.json`` and outside the current calendar month is skipped without a single
request, so a no-op run costs exactly one GET (the archive list).

Deliberate choices inside :func:`run`:

* **Metadata is saved after every month, not once at the end.** A run interrupted at
  month 40 of 49 keeps the first 40; the alternative is redoing everything because
  something was killed at 95%.
* **Oldest month first.** Progress reads naturally, and a partial run lands on
  history rather than on the recent games you most want.
* **Closed months are not probed.** The metadata *is* the cache. HEADing every archive
  would cost one request per month and buy nothing.
* **A failed archive is never recorded.** Failures must stay retryable, so an entry is
  only written once the games are on disk. A partially written month is still recorded,
  because per-game dedup makes re-running that month cheap and correct.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, http_client
from .metadata import Metadata
from .pgn_store import PgnStore

Fetch = Callable[..., Optional[Any]]


class RunResult:
    """What one run did, for the CLI summary and for tests."""

    def __init__(self) -> None:
        self.planned: List[Tuple[str, Optional[str]]] = []   # (url, month)
        self.skipped: List[Tuple[str, Optional[str]]] = []
        self.fetched: List[Tuple[str, Optional[str]]] = []
        self.failed: List[Tuple[str, Optional[str]]] = []
        self.games_written = 0
        self.total_on_disk = 0
        self.listing_url: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self, total_on_disk: Optional[int] = None) -> str:
        text = (
            f"{len(self.skipped)} month(s) up to date, "
            f"{len(self.fetched)} fetched, {len(self.failed)} failed, "
            f"{self.games_written} new game(s) written"
        )
        if total_on_disk is not None:
            text += f", {total_on_disk} total on disk"
        return text


def plan_archives(
    md: Metadata,
    archives: List[str],
    current_month: str,
    *,
    force: bool = False,
    only_month: Optional[str] = None,
    limit: int = 0,
) -> List[Tuple[str, Optional[str]]]:
    """Decide what to download. Returns ``(url, month)`` oldest first.

    Split out from :func:`run` because the decision is the entire design and deserves to
    be testable without a socket.
    """
    chosen: List[Tuple[str, Optional[str]]] = []
    for url in archives:
        month = config.archive_month(url)
        if only_month is not None and month != only_month:
            continue
        if force or not md.is_up_to_date(url, current_month):
            chosen.append((url, month))
    chosen.reverse()                      # oldest first
    if limit and limit > 0:
        chosen = chosen[:limit]
    return chosen


def _missing_pgn_fallback(
    game: Dict[str, Any],
    player: Optional[str],
    fetch_text: Callable[..., Optional[str]],
    delay: float,
) -> Optional[str]:
    """The per-game endpoint, used only when a monthly archive omits the PGN.

    Rare, but it is the difference between a complete month and a silent hole.
    """
    game_id = game.get("uuid") or ""
    if not player or not game_id:
        return None
    url = config.CHESSCOM_GAME.format(player=player, game_id=game_id)
    body = fetch_text(url, delay=delay)
    if isinstance(body, dict):
        return body.get("pgn")
    return body


def run(
    player: Optional[str] = None,
    *,
    force: bool = False,
    only_month: Optional[str] = None,
    limit: int = 0,
    delay: float = config.DEFAULT_DELAY,
    dry_run: bool = False,
    today: Optional[date] = None,
    fetch: Optional[Fetch] = None,
    fetch_text: Optional[Callable[..., Optional[str]]] = None,
    store: Optional[PgnStore] = None,
    md: Optional[Metadata] = None,
    verbose: bool = True,
) -> RunResult:
    """Fetch every archive that is not provably up to date. Never raises for network
    problems; a failed archive is logged and skipped."""
    result = RunResult()
    store = store or PgnStore()
    md = md if md is not None else Metadata(player=player)
    fetch = fetch or http_client.get_json
    fetch_text = fetch_text or http_client.get

    url = config.archive_list_url(player)
    if not url:
        print(
            "error: no archive-list URL. Pass --player or add one to api.txt",
            file=sys.stderr,
        )
        return result
    result.listing_url = url

    listing = fetch(url, delay=delay)
    if listing is None:
        print(
            f"error: could not read the archive list from {url} "
            "(see the line above for the reason). "
            "Nothing was written; try again later.",
            file=sys.stderr,
        )
        return result
    if not isinstance(listing, dict) or not isinstance(listing.get("archives"), list):
        print(
            f"error: {url} returned {sorted(listing) if isinstance(listing, dict) else type(listing).__name__}, "
            "expected a JSON object with an 'archives' list. "
            "Nothing was written.",
            file=sys.stderr,
        )
        return result

    archives: List[str] = [a for a in listing["archives"] if isinstance(a, str)]
    current = config.current_month(today)
    if not md.player:
        md.player = config.player_from_url(url)

    if verbose:
        print(f"Archive list: {len(archives)} month(s) for {md.player or '?'}")

    result.planned = plan_archives(
        md, archives, current, force=force, only_month=only_month, limit=limit
    )
    planned_urls = {u for u, _ in result.planned}
    result.skipped = sorted(
        ((u, config.archive_month(u)) for u in archives if u not in planned_urls),
        key=lambda item: item[1] or "",
    )

    if dry_run:
        if verbose:
            for u, m in sorted(result.skipped, key=lambda x: x[1] or ""):
                print(f"  skip   {m or u}")
            for u, m in sorted(result.planned, key=lambda x: x[1] or ""):
                reason = "forced" if force else ("month" if only_month else "stale")
                print(f"  fetch  {m or u}  ({reason})")
            print(result.summary(store.total_games()))
        return result

    for archive_url, month in result.planned:
        # An unrecognised URL cannot be reasoned about, so it is stored under a
        # synthetic label that can never be mistaken for a calendar month. The digest
        # keeps two odd URLs from colliding in the same directory. `month` stays None,
        # so metadata records it as "" and the skip rule keeps re-planning it.
        label = month or (
            "unknown-" + hashlib.sha1(archive_url.encode("utf-8")).hexdigest()[:12]
        )

        body = fetch(archive_url, delay=delay)
        if body is None:
            # get_json already logged the cause: rate limit, HTTP status, network
            # error or a non-JSON body. Say only which month was lost.
            http_client.log(
                f"  skipping {label}: could not read the archive "
                "(see the line above for the reason)"
            )
            result.failed.append((archive_url, month))
            continue
        if not isinstance(body, dict) or not isinstance(body.get("games"), list):
            # The request succeeded but the payload is not what the API promises.
            http_client.log(
                f"  skipping {label}: archive returned {sorted(body) if isinstance(body, dict) else type(body).__name__}, "
                "expected a JSON object with a 'games' list"
            )
            result.failed.append((archive_url, month))
            continue

        games: List[Dict[str, Any]] = [g for g in body["games"] if isinstance(g, dict)]
        missing = [g for g in games if not (g.get("pgn") or "").strip()]
        for game in missing:
            pgn = _missing_pgn_fallback(game, md.player, fetch_text, delay)
            if pgn:
                game["pgn"] = pgn

        written = store.write_month(label, games, merge=True)
        result.games_written += written

        expected = len(games)
        on_disk = len(store.uuids_on_disk(label))
        if on_disk < expected:
            # Chess.com's monthly archives are documented as unpaginated, but we do not
            # bet the completeness claim on that: say so loudly instead.
            http_client.log(
                f"  warning: {label} has {on_disk} of {expected} game(s) on disk; "
                "re-run to retry the missing ones"
            )

        md.record(
            archive_url,
            month=month,
            label=label,
            current_month=current,
            store=store,
        )
        md.save()
        result.fetched.append((archive_url, month))

        if verbose:
            print(f"  {label}: {written} new of {expected} game(s)  [{on_disk} on disk]")

    result.total_on_disk = store.total_games()
    if verbose:
        print(result.summary(result.total_on_disk))
    return result


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

def self_test() -> int:
    """Check the skip predicate and the planning on top of it. No network, no clock.

    These two functions are the entire design: everything else in this module is
    I/O around the decision of what to download. Keeping the checks here means
    they sit next to the rules they describe rather than in a file that can drift
    away from them. ``python -m process_api.fetcher --self-test``.
    """
    checks = 0
    failures = []

    def check(label: str, got, want) -> None:
        nonlocal checks
        checks += 1
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    def url(month: str) -> str:
        """The per-month archive URL, e.g. .../games/2026/09.

        Not the *list* URL with the month appended: Chess.com returns
        .../games/archives once and .../games/<year>/<month> per archive, and
        archive_month only recognises the second shape.
        """
        year, mon = month.split("-")
        base = config.CHESSCOM_ARCHIVES.format(player="testuser")
        return base.rsplit("/", 1)[0] + f"/{year}/{mon}"

    this_month = "2026-10"

    # -- archive_month: the URL is the source of truth -------------------
    check("parses a month", config.archive_month(url("2026-09")), "2026-09")
    check("tolerates a trailing slash", config.archive_month(url("2026-09") + "/"), "2026-09")
    check("rejects a bad month number", config.archive_month(url("2026-13")), None)
    check("rejects a non-month path", config.archive_month("/pub/player/x/other"), None)
    check("pulls the player out of a url", config.player_from_url(url("2026-09")), "testuser")

    # -- the skip predicate ----------------------------------------------
    md = Metadata(player="testuser")
    closed, open_now = url("2026-09"), url("2026-10")

    check("unrecorded month is not up to date", md.is_up_to_date(closed, this_month), False)

    md.record(closed, current_month=this_month)
    check("closed month is up to date", md.is_up_to_date(closed, this_month), True)

    md.record(open_now, current_month=this_month)
    check("current month is never up to date", md.is_up_to_date(open_now, this_month), False)

    # The whole point: a month stays skipped as the calendar moves on, and
    # stops being skipped exactly when it becomes the open month.
    md.record(open_now, current_month="2026-09")
    check("month becomes stale once it is current", md.is_up_to_date(open_now, this_month), False)
    check("closed month still up to date next month", md.is_up_to_date(closed, "2026-11"), True)

    check("an unrecognised url makes no claim", md.is_up_to_date("/not/a/month", this_month), False)

    # -- planning --------------------------------------------------------
    # Chess.com returns the archive list newest month first, and plan_archives
    # reverses it, so the plan comes out oldest first: an interrupted run then
    # lands on history rather than on the games you most want.
    newest_first = [url(m) for m in ("2026-09", "2026-08", "2026-07", "2026-06")]

    plan = [m for _, m in plan_archives(md, newest_first, this_month)]
    check("everything unrecorded is planned", plan, ["2026-06", "2026-07", "2026-08"])
    check("planned oldest first", plan, sorted(plan))

    cached = Metadata(player="testuser")
    cached.record(closed, current_month=this_month)      # 2026-09
    plan = [m for _, m in plan_archives(cached, newest_first, this_month)]
    check("a recorded closed month is skipped", plan, ["2026-06", "2026-07", "2026-08"])

    plan = [m for _, m in plan_archives(cached, newest_first, this_month, force=True)]
    check("force ignores the cache", plan, ["2026-06", "2026-07", "2026-08", "2026-09"])

    plan = [m for _, m in plan_archives(cached, newest_first, this_month, only_month="2026-07")]
    check("only_month restricts to one", plan, ["2026-07"])

    plan = [m for _, m in plan_archives(cached, newest_first, this_month, limit=2)]
    check("limit keeps the oldest", plan, ["2026-06", "2026-07"])

    plan = [m for _, m in plan_archives(cached, newest_first, this_month, limit=99)]
    check("a limit above the count is harmless", len(plan), 3)

    plan = [m for _, m in plan_archives(cached, newest_first, this_month, only_month="2026-05")]
    check("only_month matching nothing plans nothing", plan, [])

    # -- reset -----------------------------------------------------------
    check("reset one month", md.reset("2026-09"), 1)
    check("that month is planned again",
          [m for _, m in plan_archives(md, newest_first, this_month)],
          ["2026-06", "2026-07", "2026-08", "2026-09"])
    check("reset everything", md.reset(), 1)
    check("nothing recorded now", len(md.archives), 0)

    print(f"fetcher: {checks - len(failures)}/{checks} checks passed")
    for problem in failures:
        print(f"  FAIL {problem}", file=sys.stderr)
    return 1 if failures else 0


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    print("usage: python -m process_api.fetcher --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())