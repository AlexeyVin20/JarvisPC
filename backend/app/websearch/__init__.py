"""Vendored web-search pipeline (4get metasearch -> MinHash/MMR -> DOM->Markdown
-> heuristic scoring -> window stitching) plus an async voice-facing wrapper.

Code is copied as-is from the article project; only the import wiring and the
config loader were adapted. Neural decision models are intentionally excluded —
the heuristic ("v4") decision layer is used instead.
"""

from .search import web_search

__all__ = ["web_search"]
