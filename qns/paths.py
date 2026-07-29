"""Where a session's generated files live.

Nonvolatile state is the emulator's own output, not part of the source
tree, so a bare filename should not land in whatever directory the
command happened to be run from - which is how a stray `flash.bin` ends
up sitting next to the code.  Bare names resolve into one gitignored
directory instead; anything written as a real path is left exactly where
it was asked for.
"""

from __future__ import annotations

import os
from pathlib import Path

# Checked against the text as written, because Path normalises "./x" to
# "x" - so asking Path how many parts it has would quietly redirect the
# very spelling meant to opt out.
_SEPARATORS = tuple(sep for sep in (os.sep, os.altsep) if sep)

SESSION_STATE_DIR = Path("session_state")


def resolve_state_path(value: str | Path) -> Path:
    """Resolve a state path, redirecting bare names into the session directory.

    A value with any directory component - `./flash.bin`, `runs/a.bin`,
    an absolute path - is returned untouched, so an explicit location is
    always honoured.  Only a bare name is relocated, and the caller
    prints the result, so the redirection is never silent.
    """
    path = Path(value)
    text = str(value)
    if path.is_absolute() or any(sep in text for sep in _SEPARATORS):
        return path
    SESSION_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STATE_DIR / path
