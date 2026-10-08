"""Command line entry point.

    python -m process_api.cli --player me --dry-run
    python -m process_api.cli --player me
    python -m process_api.cli --verify

``--dry-run`` first: it answers "what would this run download?" in one cheap request,
which is the question the metadata design exists to make cheap.

``me`` is an alias for the username configured in the root ``player.txt`` (see
player.py), so no username needs typing here at all.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

import player

from . import config, fetcher, http_client, metadata as md_mod
from .pgn_store import PgnStore


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m process_api.cli",
        description=(
            "Download every game from a Chess.com monthly archive, skipping "
            "months that are already recorded as complete."
        ),
    )
    ap.add_argument(
        "--player",
        default=player.ME,
        help=f"username, or {player.ME!r} for the one in player.txt "
             "(default %(default)r); empty falls back to the URL in api.txt",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the skip/fetch decision for every archive and exit",
    )
    ap.add_argument(
        "--force", action="store_true", help="ignore the skip predicate, re-fetch all"
    )
    ap.add_argument("--month", help="restrict to one archive, YYYY-MM")
    ap.add_argument(
        "--delay",
        type=float,
        default=config.DEFAULT_DELAY,
        help=f"seconds between requests (default {config.DEFAULT_DELAY})",
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="stop after this many archives"
    )
    ap.add_argument(
        "--verify",
        action="store_true",
        help="check recorded metadata against the PGN on disk",
    )
    ap.add_argument(
        "--reset", action="store_true", help="drop metadata so the next run re-fetches"
    )
    ap.add_argument(
        "--delete-pgn",
        action="store_true",
        help="with --reset, also delete the stored PGN for the affected month(s)",
    )
    ap.add_argument("--quiet", action="store_true", help="only report problems")
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet
    store = PgnStore()
    md = md_mod.load()

    if args.reset:
        month = args.month
        dropped = md.reset(month)
        md.save()
        removed = store.remove_month(month) if (args.delete_pgn and month) else 0
        target = month or "every month"
        print(f"Reset metadata for {target}: {dropped} entr{'y' if dropped == 1 else 'ies'} dropped")
        if removed:
            print(f"Deleted {removed} stored game file(s) for {month}")
        if not args.month and not args.delete_pgn:
            print("Stored PGN left in place; --delete-pgn would remove it.")
        return 0

    if args.verify:
        problems = md_mod.verify(md, config.current_month(), store)
        if not problems:
            print(
                f"OK: {len(md.archives)} archive(s) recorded, "
                f"{store.total_games()} game(s) on disk"
            )
            return 0
        print(f"{len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    if args.month and config.archive_month(f"/games/{args.month}") is None:
        print(f"error: --month must look like YYYY-MM, got {args.month!r}", file=sys.stderr)
        return 2

    # `me` resolves through player.txt / $CHESS_COACH_PLAYER; an unresolved alias
    # becomes None so api.txt still gets its say rather than failing outright.
    name = player.resolve(args.player, "chesscom")
    if name and player.is_me(args.player):
        if verbose:
            print(f"player: {name}")

    result = fetcher.run(
        name,
        force=args.force,
        only_month=args.month,
        limit=args.limit,
        delay=args.delay,
        dry_run=args.dry_run,
        store=store,
        md=md,
        verbose=verbose,
    )

    if not result.listing_url:
        return 2
    if not result.ok and not result.fetched and not result.skipped:
        return 1
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())