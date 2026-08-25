#!/usr/bin/env python3
"""Normalize a Python sdist without carrying the build host's identity.

Setuptools preserves the local uid, gid, user and group in ``.tar.gz`` member
headers. Those fields are irrelevant to package installation and disclose the
machine that built a public release. This tool rewrites the reviewed sdist with
neutral ownership and a deterministic timestamp before checksumming it.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile


MAX_MEMBERS = 10_000
MAX_UNPACKED_BYTES = 100 * 1024 * 1024


def _epoch(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("epoch must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("epoch must be non-negative")
    return parsed


def _canonical_member_name(name: str) -> str:
    """Return a portable canonical POSIX archive path or fail closed."""
    if (
        not name
        or "\\" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValueError(f"non-portable sdist member path: {name!r}")
    if re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"drive-like sdist member path: {name!r}")
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"non-canonical sdist member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name:
        raise ValueError(f"unsafe sdist member path: {name!r}")
    return name


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    if not members:
        raise ValueError("sdist is empty")
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"sdist has too many members: {len(members)}")

    names: set[str] = set()
    roots: set[str] = set()
    unpacked = 0
    for member in members:
        canonical_name = _canonical_member_name(member.name)
        path = PurePosixPath(canonical_name)
        if canonical_name in names:
            raise ValueError(f"duplicate sdist member path: {canonical_name!r}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(
                f"unsupported sdist member type for {member.name!r}: {member.type!r}"
            )
        if member.size < 0 or (member.isdir() and member.size != 0):
            raise ValueError(f"invalid sdist member size for {member.name!r}")
        names.add(canonical_name)
        roots.add(path.parts[0])
        unpacked += member.size

    if len(roots) != 1:
        raise ValueError(
            f"sdist must have one top-level directory, found {sorted(roots)}"
        )
    if unpacked > MAX_UNPACKED_BYTES:
        raise ValueError(f"sdist expands beyond {MAX_UNPACKED_BYTES} bytes")


def _payloads_and_snapshot(
    archive: tarfile.TarFile,
    members: list[tarfile.TarInfo],
) -> tuple[dict[str, bytes], tuple[tuple[str, bytes, int, int, str], ...]]:
    payloads: dict[str, bytes] = {}
    snapshot: list[tuple[str, bytes, int, int, str]] = []
    for member in members:
        payload = b""
        if member.isfile():
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"could not read sdist member: {member.name!r}")
            payload = extracted.read()
            if len(payload) != member.size:
                raise ValueError(f"sdist member size mismatch: {member.name!r}")
            payloads[member.name] = payload
        snapshot.append(
            (
                member.name,
                member.type,
                member.mode & 0o777,
                member.size,
                hashlib.sha256(payload).hexdigest(),
            )
        )
    return payloads, tuple(snapshot)


def _normalized_tar_bytes(
    archive: Path, epoch: int
) -> tuple[bytes, tuple[tuple[str, bytes, int, int, str], ...]]:
    output = io.BytesIO()
    with tarfile.open(archive, mode="r:gz") as source:
        members = source.getmembers()
        _validate_members(members)
        payloads, snapshot = _payloads_and_snapshot(source, members)
        with tarfile.open(
            fileobj=output, mode="w", format=tarfile.PAX_FORMAT
        ) as target:
            for member in members:
                normalized = copy.copy(member)
                normalized.uid = 0
                normalized.gid = 0
                normalized.uname = ""
                normalized.gname = ""
                normalized.mtime = epoch
                normalized.pax_headers = {}
                normalized.mode &= 0o777
                payload = io.BytesIO(payloads[member.name]) if member.isfile() else None
                target.addfile(normalized, payload)
    return output.getvalue(), snapshot


def _verify_normalized_archive(
    archive: Path,
    epoch: int,
    expected_snapshot: tuple[tuple[str, bytes, int, int, str], ...],
) -> None:
    with tarfile.open(archive, mode="r:gz") as verified:
        members = verified.getmembers()
        _validate_members(members)
        _, actual_snapshot = _payloads_and_snapshot(verified, members)
        if actual_snapshot != expected_snapshot:
            raise RuntimeError(
                "sdist content, names, types, sizes, or modes changed during normalization"
            )
        if any(
            member.uid != 0
            or member.gid != 0
            or member.uname
            or member.gname
            or member.mtime != epoch
            or member.pax_headers
            for member in members
        ):
            raise RuntimeError("sdist metadata normalization did not verify")


def normalize_sdist(archive: Path, epoch: int) -> None:
    if (
        archive.is_symlink()
        or not archive.is_file()
        or not archive.name.endswith(".tar.gz")
    ):
        raise ValueError(f"expected an existing .tar.gz sdist: {archive}")

    tar_bytes, expected_snapshot = _normalized_tar_bytes(archive, epoch)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{archive.name}.", dir=archive.parent, delete=False
        ) as raw:
            temp_path = Path(raw.name)
            with gzip.GzipFile(
                filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=epoch
            ) as compressed:
                compressed.write(tar_bytes)
        _verify_normalized_archive(temp_path, epoch, expected_snapshot)
        temp_path.chmod(archive.stat().st_mode & 0o777)
        os.replace(temp_path, archive)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    _verify_normalized_archive(archive, epoch, expected_snapshot)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--epoch",
        type=_epoch,
        default=_epoch(os.environ.get("SOURCE_DATE_EPOCH", "0")),
        help="timestamp for all tar and gzip headers (default: SOURCE_DATE_EPOCH or 0)",
    )
    args = parser.parse_args()
    normalize_sdist(args.archive, args.epoch)
    print(f"normalized Python sdist metadata: {args.archive}")


if __name__ == "__main__":
    main()
