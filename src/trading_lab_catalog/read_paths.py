"""Read-only path anchoring. No creation, ACL changes, or SQLite initialization."""

import os
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .read_models import ReadFailure


@contextmanager
def pinned_catalogue(path: Path):
    """Keep Windows NTFS ancestors and the database open without delete sharing.

    Reuses the existing OS-only native primitive, not an execution coordinator.
    POSIX retains Store guards and rejects hardlink aliases; see documented limits.
    """
    with ExitStack() as stack:
        try:
            if os.name == "nt":
                from trading_lab_orchestration import study_storage_windows as native

                stack.enter_context(native.pinned_root(path.parent, existing=True))
                handle = native._open_no_reparse(
                    path, native.READ, native.SHARE_READ | native.SHARE_WRITE, 1
                )  # NT FILE_OPEN, never CREATE/OPEN_IF.
                stack.callback(native.close_handle, handle)
                info = native._info(handle)
                object_id = ("NTFS", info.volume, (info.index_high << 32) | info.index_low)
            else:
                info = path.stat(follow_symlinks=False)
                if path.is_symlink() or info.st_nlink != 1:
                    raise ValueError("Linked catalogue")
                object_id = ("POSIX", info.st_dev, info.st_ino)
        except (OSError, ValueError):
            raise ReadFailure("BLOCKED", "Catalogue path identity could not be anchored") from None
        yield object_id
