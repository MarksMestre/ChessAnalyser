"""Incremental Chess.com archive fetcher.

Downloads every game from the player's monthly Chess.com archives, and uses
``data/metadata.json`` so that a run which has nothing new to do costs exactly one
request.

    python -m process_api.cli --player me --dry-run
"""

__all__ = ["config", "fetcher", "http_client", "metadata", "pgn_store", "cli"]