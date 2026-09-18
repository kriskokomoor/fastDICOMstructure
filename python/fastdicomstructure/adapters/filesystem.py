"""The one concrete adapter pair S1.5 proves: a single named file as
source, a single named file as destination. I/O only -- see the package
docstring for the ownership boundary this preserves. No directory
enumeration, no globbing, no recursion, no watching, no queue semantics --
each adapter names exactly one configured file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .. import execution as _execution
from . import AdapterResolutionError

__all__ = ["FilesystemSource", "FilesystemDestination"]

_SOURCE_OPTION_FIELDS = {"path"}
_DESTINATION_OPTION_FIELDS = {"path", "overwrite"}


class FilesystemSource:
    """Reads exactly the file named by `options["path"]` and returns its
    bytes. A missing or unreadable file is reported as
    `execution.SourceAcquisitionError` (never raised directly to the
    caller of `execution.run()`, which catches exactly that type). Never
    calls an attrs primitive of any kind -- parsing is entirely
    `execution.py`'s responsibility."""

    def __init__(self, options: Mapping[str, Any]):
        unknown = set(options.keys()) - _SOURCE_OPTION_FIELDS
        if unknown:
            raise AdapterResolutionError("ADAPTER_OPTIONS_INVALID")
        path = options.get("path")
        if not isinstance(path, str) or not path:
            raise AdapterResolutionError("ADAPTER_OPTIONS_INVALID")
        self._path = Path(path)

    @property
    def _resolved_path(self) -> Path:
        """Package-internal only -- used solely by
        `adapters.check_source_destination_collision`. Never exposed as
        part of `execution.ExecutionResult` or any diagnostic surface
        (accepted design checkpoint Correction 2)."""
        return self._path.resolve()

    def acquire(self) -> bytes:
        try:
            return self._path.read_bytes()
        except OSError as exc:
            raise _execution.SourceAcquisitionError(exc) from exc


def _best_effort_unlink(path: Path) -> None:
    """Removes a temporary file without ever masking a real failure/success
    that already occurred -- this function's own outcome is deliberately
    never surfaced (design checkpoint section 15, "never mask the original
    write/commit failure with cleanup failure")."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


class FilesystemDestination:
    """Durably publishes bytes to exactly the file named by
    `options["path"]`, honoring `options["overwrite"]` (default `False`).

    Safety, precisely:

    1. Bytes are first written to a temporary file created in the *same
       directory* as the final target (`tempfile.mkstemp(dir=...)`) --
       guaranteeing the later publish step is a same-filesystem operation.
    2. The temporary file is flushed and `fsync`'d before any publish step
       is attempted, so a crash between write and publish cannot leave a
       truncated file visible at the final path (nothing is visible at the
       final path yet at all).
    3. Publish, `overwrite=True`: `os.replace(temp, target)` -- POSIX
       `rename(2)`, atomic, unconditionally replaces an existing target.
    4. Publish, `overwrite=False` (default): **not** a check-then-rename
       sequence (which would race against a concurrent creator of
       `target` between the check and the rename). Instead,
       `os.link(temp, target)` -- POSIX `link(2)` creates the new
       directory entry `target` atomically and fails with
       `FileExistsError` if `target` already exists, without ever
       touching or truncating it -- this is the standard atomic
       "publish-if-absent" technique (the same one Maildir delivery and
       content-addressed object stores rely on), and is what makes the
       no-overwrite path race-free. The temporary name is then removed
       (`target` now has its own independent directory entry to the same
       inode; only one name should remain).
    5. Any failure at the write step is reported as
       `execution.DestinationWriteError(category="DESTINATION_WRITE_FAILED")`;
       a `target`-already-exists failure at the publish step is reported
       as `category="DESTINATION_ALREADY_EXISTS"`; any other publish-step
       failure (permission, cross-device, disk full on the directory
       entry) is `category="DESTINATION_COMMIT_FAILED"`. In every failure
       case the temporary file is removed on a best-effort basis
       (`_best_effort_unlink`) -- its own outcome is never allowed to mask
       the real failure being reported.

    Never calls an attrs primitive -- serialization is entirely
    `execution.py`'s responsibility; this class only ever receives
    already-serialized bytes.
    """

    def __init__(self, options: Mapping[str, Any]):
        unknown = set(options.keys()) - _DESTINATION_OPTION_FIELDS
        if unknown:
            raise AdapterResolutionError("ADAPTER_OPTIONS_INVALID")
        path = options.get("path")
        if not isinstance(path, str) or not path:
            raise AdapterResolutionError("ADAPTER_OPTIONS_INVALID")
        overwrite = options.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise AdapterResolutionError("ADAPTER_OPTIONS_INVALID")
        self._path = Path(path)
        self._overwrite = overwrite

    @property
    def _resolved_path(self) -> Path:
        """Package-internal only -- see `FilesystemSource._resolved_path`."""
        return self._path.resolve()

    def write(self, data: bytes) -> None:
        target = self._path
        directory = target.parent

        try:
            fd, temp_name = tempfile.mkstemp(prefix=".fds-tmp-", dir=str(directory))
        except OSError as exc:
            raise _execution.DestinationWriteError(exc, category="DESTINATION_WRITE_FAILED") from exc
        temp_path = Path(temp_name)

        wrote_successfully = False
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            wrote_successfully = True
        except OSError as exc:
            raise _execution.DestinationWriteError(exc, category="DESTINATION_WRITE_FAILED") from exc
        finally:
            if not wrote_successfully:
                _best_effort_unlink(temp_path)

        try:
            if self._overwrite:
                os.replace(str(temp_path), str(target))
            else:
                os.link(str(temp_path), str(target))
        except FileExistsError as exc:
            _best_effort_unlink(temp_path)
            raise _execution.DestinationWriteError(exc, category="DESTINATION_ALREADY_EXISTS") from exc
        except OSError as exc:
            _best_effort_unlink(temp_path)
            raise _execution.DestinationWriteError(exc, category="DESTINATION_COMMIT_FAILED") from exc
        else:
            if not self._overwrite:
                # os.link left two directory entries (temp_path, target)
                # pointing at the same inode -- only the final target name
                # should remain.
                _best_effort_unlink(temp_path)
