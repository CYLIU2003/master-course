"""Bounded Windows sharing-lock retry for already serialized state writers."""
from pathlib import Path
import time
from uuid import uuid4


def replace_bytes(path: Path, data: bytes) -> None:
    """Keep the last good file and failed temporary evidence on persistent error.

    This is not a transaction/CAS primitive. The caller must own its existing
    campaign/batch lock. In particular, never delete the destination to retry.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_bytes(data)
    for attempt in range(7):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 6:
                raise
            time.sleep(min(.05 * 2 ** attempt, .4))
