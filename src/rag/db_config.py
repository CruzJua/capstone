"""Database-name resolution for development, training and evaluation code.

MONGODB_DB_NAME is the production database. Everything used for training, synthetic data and
evaluation must read MONGODB_TRAINING_DB_NAME instead, and must never fall back to production.
"""

import os
from typing import Mapping, Optional


def resolve_training_db_name(env: Optional[Mapping[str, str]] = None) -> str:
    """Return MONGODB_TRAINING_DB_NAME, or raise if it is unset or empty."""
    source = os.environ if env is None else env
    name = (source.get("MONGODB_TRAINING_DB_NAME") or "").strip()
    if not name:
        raise ValueError(
            "MONGODB_TRAINING_DB_NAME is not set. Dev, training and evaluation code must use it "
            "and never fall back to the production MONGODB_DB_NAME."
        )
    return name
