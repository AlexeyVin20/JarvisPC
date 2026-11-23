"""Minimal runtime configuration for the vendored web-search pipeline.

Replaces the article's ``config.py``/``config.json`` loader. Only the keys
actually read by ``pipeline.py`` are provided; everything is overridable via
``WEBSEARCH_*`` environment variables.
"""

import os
from typing import Any

CONFIG: dict[str, Any] = {
    "search": {
        # 4get metasearch endpoint (local Docker container, port 80).
        "endpoint": os.getenv("WEBSEARCH_ENDPOINT", "http://localhost/web"),
    },
    "pipeline": {
        # Keys read by pipeline.score_sentences().
        "min_query_terms": int(os.getenv("WEBSEARCH_MIN_QUERY_TERMS", "2")),
        "min_overlap": float(os.getenv("WEBSEARCH_MIN_OVERLAP", "0.15")),
        "max_candidates": int(os.getenv("WEBSEARCH_MAX_CANDIDATES", "0")) or None,
    },
}
