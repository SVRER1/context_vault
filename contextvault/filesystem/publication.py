"""Filesystem helpers for publishing verified files without replacing a target."""

from __future__ import annotations

import os
from pathlib import Path


def publish_no_replace(source: Path, destination: Path) -> None:
    """Move a staged file into place, failing if another file owns the target.

    Windows ``os.rename`` refuses an existing destination and is atomic for
    same-volume paths. Other platforms use hard-link creation, whose target
    creation also fails if the destination already exists.
    """
    if os.name == "nt":
        os.rename(source, destination)
        return

    os.link(source, destination)
    source.unlink()
