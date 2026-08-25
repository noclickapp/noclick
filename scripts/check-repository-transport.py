#!/usr/bin/env python3
"""Reject repository transports that can smuggle hidden content.

The default mode audits the current index.  ``--history REV`` independently
walks every commit snapshot and unique tree/blob reachable from ``REV``.  A
nested pack, bundle, archive, LFS pointer, submodule, unsafe symlink, appended
image payload, or repository-shaping indirection must never become an
unreviewed second content channel beside ordinary tracked files.
"""

from __future__ import annotations

import argparse
import bz2
import io
import lzma
import os
import posixpath
import re
import struct
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


ALLOWED_MODES = {"100644", "100755", "120000"}
ARCHIVE_SUFFIXES = (
    ".7z",
    ".a",
    ".apk",
    ".bundle",
    ".bz2",
    ".cab",
    ".cpio",
    ".crate",
    ".deb",
    ".dmg",
    ".gem",
    ".gz",
    ".img",
    ".idx",
    ".ipa",
    ".iso",
    ".jar",
    ".lz4",
    ".nupkg",
    ".pack",
    ".rar",
    ".rev",
    ".rpm",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tbz",
    ".tbz2",
    ".tgz",
    ".tlz",
    ".txz",
    ".war",
    ".whl",
    ".xz",
    ".zst",
    ".zip",
)
MAGIC_PREFIXES = (
    (b"# v2 git bundle\n", "Git bundle"),
    (b"# v3 git bundle\n", "Git bundle"),
    (b"PACK", "Git pack"),
    (b"\xfftOc", "Git pack index"),
    (b"PK\x03\x04", "ZIP archive"),
    (b"PK\x05\x06", "empty ZIP archive"),
    (b"PK\x07\x08", "spanned ZIP archive"),
    (b"\x1f\x8b", "gzip archive"),
    (b"BZh", "bzip2 archive"),
    (b"\xfd7zXZ\x00", "xz archive"),
    (b"\x28\xb5\x2f\xfd", "zstd archive"),
    (b"\x04\x22\x4d\x18", "LZ4 archive"),
    (b"7z\xbc\xaf'\x1c", "7z archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"!<arch>\n", "ar archive"),
    (b"070701", "cpio archive"),
    (b"070702", "cpio archive"),
    (b"070707", "cpio archive"),
)
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
MAX_SYMLINK_BYTES = 4096
MAX_BLOB_BYTES = 128 * 1024 * 1024
MAX_COMMIT_BYTES = 8 * 1024 * 1024
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_CURRENT_TOTAL_BLOB_BYTES = 4 * 1024 * 1024 * 1024
MAX_HISTORY_TOTAL_BLOB_BYTES = 16 * 1024 * 1024 * 1024
MAX_HISTORY_COMMITS = 100_000
MAX_HISTORY_TREES = 250_000
MAX_HISTORY_BLOBS = 250_000
MAX_HISTORY_TREE_ENTRIES = 1_000_000
MAX_TREE_ENTRIES_PER_OBJECT = 100_000
MAX_HISTORY_PATHS_PER_SNAPSHOT = 250_000
MAX_HISTORY_SNAPSHOT_PATHS = 50_000_000
MAX_HISTORY_TREE_DEPTH = 256
MAX_PORTABLE_PATH_BYTES = 4096
MAX_PORTABLE_COMPONENT_BYTES = 255
MAX_DECOMPRESSED_PROBE_BYTES = 16 * 1024 * 1024
MAX_EMBEDDED_COMPRESSION_CANDIDATES = 128
MAX_CONTAINER_CANDIDATES = 4096
MAX_CONTAINER_BLOCKS = 4096
MAX_TOTAL_SYMLINK_BYTES = 64 * 1024 * 1024
TAR_CHECKSUM_ANCHOR_PATTERN = re.compile(rb"(?:[ \x00][0-7]|[0-7][ \x00]|[0-7]{8})")
FORBIDDEN_CURRENT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
)
FORBIDDEN_HISTORY_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)
WINDOWS_DEVICE_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class TransportGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexEntry:
    mode: str
    oid: str
    path: str


@dataclass(frozen=True)
class BlobSample:
    prefix: bytes
    size: int


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    oid: str
    name: str


@dataclass(frozen=True)
class HistoryStats:
    commits: int
    root_trees: int
    trees: int
    blobs: int
    snapshot_paths: int
    symlink_snapshots: int


class _CatFileBatch:
    """Read one bounded object at a time without buffering the whole history."""

    def __init__(self, root: Path, *, history: bool) -> None:
        command = ["git", "--no-replace-objects"]
        if history:
            command.extend(["-c", "core.commitGraph=false"])
        command.extend(["-C", os.fspath(root), "cat-file", "--batch"])
        env = os.environ.copy()
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
        if history:
            env["GIT_NO_LAZY_FETCH"] = "1"
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def __enter__(self) -> _CatFileBatch:
        return self

    def __exit__(self, exc_type: object, _exc: object, _tb: object) -> None:
        process = self.process
        if exc_type is not None:
            process.kill()
            process.wait()
            return
        assert process.stdin is not None
        process.stdin.close()
        stderr = process.stderr.read() if process.stderr is not None else b""
        returncode = process.wait()
        if returncode:
            raise TransportGateError(
                "git cat-file failed: " f"{stderr.decode('utf-8', 'replace').strip()}"
            )

    def read(self, oid: str, *, expected: str, maximum: int) -> bytes:
        process = self.process
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(oid.encode("ascii") + b"\n")
        process.stdin.flush()
        header = process.stdout.readline()
        fields = header.rstrip(b"\n").split()
        if len(fields) != 3 or fields[0] != oid.encode("ascii"):
            raise TransportGateError(f"cannot read Git object {oid}")
        actual = fields[1].decode("ascii", "replace")
        if actual != expected:
            raise TransportGateError(
                f"Git object {oid} is {actual}, expected {expected}"
            )
        try:
            size = int(fields[2])
        except ValueError as exc:
            raise TransportGateError(f"invalid size for Git object {oid}") from exc
        if size < 0 or size > maximum:
            raise TransportGateError(
                f"Git {expected} object {oid} is too large: {size} bytes"
            )
        data = process.stdout.read(size)
        if len(data) != size:
            raise TransportGateError(f"truncated Git object {oid}")
        if process.stdout.read(1) != b"\n":
            raise TransportGateError(f"malformed cat-file response for {oid}")
        return data


def _validate_portable_components(path: str, *, label: str) -> PurePosixPath:
    pure = PurePosixPath(path)
    if (
        "\\" in path
        or len(path.encode("utf-8")) > MAX_PORTABLE_PATH_BYTES
        or unicodedata.normalize("NFC", path) != path
        or any(unicodedata.category(character).startswith("C") for character in path)
    ):
        raise TransportGateError(f"non-portable {label}: {path!r}")
    for part in pure.parts:
        if part in {".", ".."}:
            continue
        trimmed = part.rstrip(" .")
        stem = trimmed.split(".", 1)[0].casefold()
        if (
            not trimmed
            or trimmed != part
            or len(part.encode("utf-8")) > MAX_PORTABLE_COMPONENT_BYTES
            or ":" in part
            or stem in WINDOWS_DEVICE_NAMES
        ):
            raise TransportGateError(f"non-portable {label}: {path!r}")
    return pure


def _run_git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    history: bool = False,
    allowed_returncodes: frozenset[int] = frozenset({0}),
) -> tuple[int, bytes]:
    command = ["git"]
    if history:
        command.extend(["--no-replace-objects", "-c", "core.commitGraph=false"])
    command.extend(["-C", os.fspath(root), *args])
    env = os.environ.copy()
    if history:
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
        env["GIT_NO_LAZY_FETCH"] = "1"
    result = subprocess.run(
        command,
        input=input_bytes,
        capture_output=True,
        check=False,
        env=env,
    )
    if result.returncode not in allowed_returncodes:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise TransportGateError(f"git {' '.join(args)} failed: {detail}")
    return result.returncode, result.stdout


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return _run_git(root, *args, input_bytes=input_bytes)[1]


def _history_git(root: Path, *args: str) -> bytes:
    return _run_git(root, *args, history=True)[1]


def _index(root: Path) -> list[IndexEntry]:
    raw = _git(root, "ls-files", "-s", "-z")
    entries: list[IndexEntry] = []
    seen: set[str] = set()
    folded_seen: dict[tuple[str, ...], tuple[str, ...]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, separator, raw_path = record.partition(b"\t")
        fields = header.split()
        if not separator or len(fields) != 3:
            raise TransportGateError("malformed Git index entry")
        mode = fields[0].decode("ascii", "strict")
        stage = fields[2].decode("ascii", "strict")
        try:
            path = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise TransportGateError("tracked path is not valid UTF-8") from exc
        if stage != "0":
            raise TransportGateError(f"unmerged index entry: {path}")
        if mode not in ALLOWED_MODES:
            raise TransportGateError(f"unsupported Git mode {mode}: {path}")
        pure = _validate_portable_components(path, label="tracked path")
        if pure.is_absolute() or ".." in pure.parts or path in seen:
            raise TransportGateError(f"unsafe or duplicate tracked path: {path}")
        folded_parts = tuple(part.casefold().rstrip(" .") for part in pure.parts)
        if {".git", "git~1"}.intersection(folded_parts) or folded_parts[
            -1
        ] == ".gitmodules":
            raise TransportGateError(f"nested Git control path: {path}")
        original_parts = tuple(pure.parts)
        for length in range(1, len(folded_parts) + 1):
            folded_prefix = folded_parts[:length]
            original_prefix = original_parts[:length]
            collision = folded_seen.get(folded_prefix)
            if collision is not None and collision != original_prefix:
                raise TransportGateError(
                    "case-folding tracked path collision: "
                    f"{'/'.join(collision)!r} and {'/'.join(original_prefix)!r}"
                )
            folded_seen[folded_prefix] = original_prefix
        seen.add(path)
        entries.append(IndexEntry(mode=mode, oid=fields[1].decode("ascii"), path=path))
    return entries


def _audit_current_blobs(
    root: Path, entries: list[IndexEntry]
) -> dict[str, BlobSample]:
    path_hints: dict[str, str] = {}
    symlink_oids: set[str] = set()
    for entry in entries:
        path_hints.setdefault(entry.oid, entry.path)
        if entry.mode == "120000":
            symlink_oids.add(entry.oid)
    samples: dict[str, BlobSample] = {}
    total = 0
    symlink_bytes = 0
    with _CatFileBatch(root, history=False) as reader:
        for oid, path in path_hints.items():
            data = reader.read(oid, expected="blob", maximum=MAX_BLOB_BYTES)
            total += len(data)
            if total > MAX_CURRENT_TOTAL_BLOB_BYTES:
                raise TransportGateError(
                    "tracked blob data exceeds the repository audit limit"
                )
            _validate_blob_content(path, data)
            if oid in symlink_oids:
                if len(data) > MAX_SYMLINK_BYTES:
                    raise TransportGateError(f"symlink target is too long: {path}")
                symlink_bytes += len(data)
                if symlink_bytes > MAX_TOTAL_SYMLINK_BYTES:
                    raise TransportGateError(
                        "tracked symlink data exceeds the repository audit limit"
                    )
                samples[oid] = BlobSample(prefix=data, size=len(data))
    return samples


def _check_archive_suffix(path: str) -> None:
    lower = path.casefold()
    if any(lower.endswith(suffix) for suffix in ARCHIVE_SUFFIXES):
        raise TransportGateError(f"tracked archive or Git container: {path}")


def _validate_png_extent(data: bytes, *, path: str) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    offset = 8
    saw_iend = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise TransportGateError(f"malformed PNG content: {path}")
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise TransportGateError(f"malformed PNG content: {path}")
        chunk_type = data[offset + 4 : offset + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type):
            raise TransportGateError(f"malformed PNG chunk type: {path}")
        expected_crc = struct.unpack_from(">I", data, end - 4)[0]
        actual_crc = zlib.crc32(data[offset + 4 : end - 4]) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise TransportGateError(f"invalid PNG chunk checksum: {path}")
        offset = end
        if chunk_type == b"IEND":
            if length != 0:
                raise TransportGateError(f"malformed PNG IEND chunk: {path}")
            saw_iend = True
            break
    if not saw_iend:
        raise TransportGateError(f"PNG has no IEND chunk: {path}")
    if offset != len(data):
        raise TransportGateError(f"PNG has an appended payload: {path}")


def _validate_webp_extent(data: bytes, *, path: str) -> None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return
    declared_end = struct.unpack_from("<I", data, 4)[0] + 8
    if declared_end < len(data):
        raise TransportGateError(f"WebP has an appended payload: {path}")
    if declared_end != len(data):
        raise TransportGateError(f"truncated WebP content: {path}")
    offset = 12
    while offset < len(data):
        if len(data) - offset < 8:
            raise TransportGateError(f"malformed WebP chunk: {path}")
        length = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8 + length + (length & 1)
        if offset > len(data):
            raise TransportGateError(f"malformed WebP chunk: {path}")
    if offset != len(data):
        raise TransportGateError(f"malformed WebP content: {path}")


def _validate_ico_extent(data: bytes, *, path: str) -> None:
    if len(data) < 6 or data[:4] not in {b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"}:
        return
    count = struct.unpack_from("<H", data, 4)[0]
    directory_end = 6 + 16 * count
    if not count or directory_end > len(data):
        raise TransportGateError(f"malformed ICO content: {path}")
    image_end = directory_end
    for index in range(count):
        entry = 6 + 16 * index
        size, offset = struct.unpack_from("<II", data, entry + 8)
        if not size or offset < directory_end or offset + size > len(data):
            raise TransportGateError(f"malformed ICO image entry: {path}")
        image_end = max(image_end, offset + size)
    if image_end != len(data):
        raise TransportGateError(f"ICO has an appended payload: {path}")


def _tar_octal_value(field: bytes, *, empty_is_zero: bool = False) -> int | None:
    raw = field.strip(b" \0")
    if not raw:
        return 0 if empty_is_zero else None
    if any(byte < ord("0") or byte > ord("7") for byte in raw):
        return None
    return int(raw, 8)


def _tar_header_size(data: bytes, start: int) -> int | None:
    if start < 0 or start + 512 > len(data):
        return None
    header = data[start : start + 512]
    if header == b"\0" * 512:
        return None
    name = header[:100].split(b"\0", 1)[0]
    if not name or any(byte < 0x20 for byte in name):
        return None
    expected = _tar_octal_value(header[148:156])
    if expected is None:
        return None
    actual = sum(header[:148]) + 8 * ord(" ") + sum(header[156:])
    if actual != expected:
        return None
    return _tar_octal_value(header[124:136], empty_is_zero=True)


def _tar_archive_end(data: bytes, start: int) -> int | None:
    offset = start
    entries = 0
    for block_count in range(MAX_CONTAINER_BLOCKS):
        if offset + 1024 <= len(data) and data[offset : offset + 1024] == b"\0" * 1024:
            return offset + 1024 if entries else None
        size = _tar_header_size(data, offset)
        if size is None:
            return None
        entries += 1
        offset += 512 + ((size + 511) // 512) * 512
        if offset > len(data):
            return None
        if block_count == MAX_CONTAINER_BLOCKS - 1:
            return offset
    return None


def _contains_tar_archive(data: bytes) -> bool:
    if _tar_archive_end(data, 0) is not None:
        return True
    candidate_starts: set[int] = set()
    for position in _positions(data, b"ustar", start=258):
        candidate_starts.add(position - 257)
    checksum_fields = 0
    last_field_start = len(data) - 8
    next_field_start = 149
    for anchor in TAR_CHECKSUM_ANCHOR_PATTERN.finditer(data):
        first = max(next_field_start, anchor.start() - 7)
        last = min(last_field_start, anchor.end() - 1)
        for field_start in range(first, last + 1):
            if _tar_octal_value(data[field_start : field_start + 8]) is None:
                continue
            checksum_fields += 1
            if checksum_fields > MAX_CONTAINER_CANDIDATES:
                raise TransportGateError("too many candidate tar checksum fields")
            candidate_starts.add(field_start - 148)
        next_field_start = max(next_field_start, last + 1)
    plausible = 0
    for start in sorted(candidate_starts):
        if _tar_header_size(data, start) is None:
            continue
        plausible += 1
        if plausible > MAX_EMBEDDED_COMPRESSION_CANDIDATES:
            raise TransportGateError("too many plausible embedded tar archives")
        if _tar_archive_end(data, start) is not None:
            return True
    return False


def _positions(
    data: bytes,
    magic: bytes,
    *,
    start: int = 0,
    maximum: int = MAX_CONTAINER_CANDIDATES,
) -> Iterable[int]:
    position = start
    count = 0
    while True:
        position = data.find(magic, position)
        if position < 0:
            return
        count += 1
        if count > maximum:
            raise TransportGateError(f"too many candidate signatures for {magic.hex()}")
        yield position
        position += 1


def _contains_zip_structure(data: bytes) -> bool:
    """Recognize ZIPs even when a long preamble or postamble hides the EOCD."""

    zip64_eocds = tuple(_positions(data, b"PK\x06\x06"))
    for eocd in _positions(data, b"PK\x05\x06"):
        if eocd + 22 > len(data):
            continue
        (
            _disk,
            _central_disk,
            _disk_entries,
            total_entries,
            central_size,
            central_offset,
            comment_size,
        ) = struct.unpack_from("<4H2IH", data, eocd + 4)
        if eocd + 22 + comment_size > len(data):
            continue
        if total_entries == 0 and central_size == 0 and central_offset == 0:
            return True
        if (
            total_entries == 0xFFFF
            or central_size == 0xFFFFFFFF
            or central_offset == 0xFFFFFFFF
        ):
            locator = eocd - 20
            if (
                locator >= 0
                and data[locator : locator + 4] == b"PK\x06\x07"
                and zip64_eocds
                and zip64_eocds[0] < locator
            ):
                return True
            continue
        central_start = eocd - central_size
        archive_start = central_start - central_offset
        if (
            total_entries < 1
            or archive_start < 0
            or central_start < 0
            or central_start + 46 > eocd
            or data[central_start : central_start + 4] != b"PK\x01\x02"
        ):
            continue
        local_offset = struct.unpack_from("<I", data, central_start + 42)[0]
        local_start = archive_start + local_offset
        if (
            local_start >= 0
            and local_start + 30 <= central_start
            and data[local_start : local_start + 4] == b"PK\x03\x04"
        ):
            return True
    return False


def _zstd_frame_end(data: bytes, start: int) -> int | None:
    offset = start + 4
    if offset >= len(data):
        return None
    descriptor = data[offset]
    offset += 1
    if descriptor & 0x18:
        return None
    size_flag = descriptor >> 6
    single_segment = bool(descriptor & 0x20)
    if not single_segment:
        offset += 1
    dictionary_size = (0, 1, 2, 4)[descriptor & 0x03]
    content_size = (1 if single_segment else 0, 2, 4, 8)[size_flag]
    offset += dictionary_size + content_size
    if offset > len(data):
        return None
    for block_count in range(MAX_CONTAINER_BLOCKS):
        if offset + 3 > len(data):
            return None
        header = int.from_bytes(data[offset : offset + 3], "little")
        offset += 3
        last_block = bool(header & 1)
        block_type = (header >> 1) & 0x03
        block_size = header >> 3
        if block_type == 3 or block_size > 128 * 1024:
            return None
        payload_size = 1 if block_type == 1 else block_size
        offset += payload_size
        if offset > len(data):
            return None
        if last_block:
            if descriptor & 0x04:
                offset += 4
            return offset if offset <= len(data) else None
        if block_count == MAX_CONTAINER_BLOCKS - 1:
            return offset
    return None


def _contains_embedded_zstd(data: bytes) -> bool:
    return any(
        _zstd_frame_end(data, position) is not None
        for position in _positions(data, b"\x28\xb5\x2f\xfd", start=1)
    )


def _lz4_frame_end(data: bytes, start: int) -> int | None:
    offset = start + 4
    if offset + 3 > len(data):
        return None
    flags = data[offset]
    descriptor = data[offset + 1]
    if flags >> 6 != 1 or flags & 0x02 or descriptor & 0x8F:
        return None
    block_size_code = (descriptor >> 4) & 0x07
    maximum_block = {
        4: 64 * 1024,
        5: 256 * 1024,
        6: 1024 * 1024,
        7: 4 * 1024 * 1024,
    }.get(block_size_code)
    if maximum_block is None:
        return None
    offset += 2
    if flags & 0x08:
        offset += 8
    if flags & 0x01:
        offset += 4
    offset += 1  # Header checksum.
    if offset > len(data):
        return None
    for block_count in range(MAX_CONTAINER_BLOCKS):
        if offset + 4 > len(data):
            return None
        raw_size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if raw_size == 0:
            if flags & 0x04:
                offset += 4
            return offset if offset <= len(data) else None
        block_size = raw_size & 0x7FFFFFFF
        if not block_size or block_size > maximum_block:
            return None
        offset += block_size
        if flags & 0x10:
            offset += 4
        if offset > len(data):
            return None
        if block_count == MAX_CONTAINER_BLOCKS - 1:
            return offset
    return None


def _contains_embedded_lz4(data: bytes) -> bool:
    return any(
        _lz4_frame_end(data, position) is not None
        for position in _positions(data, b"\x04\x22\x4d\x18", start=1)
    )


def _contains_zstd_skippable_frame(data: bytes) -> bool:
    for marker_tail in _positions(data, b"\x2a\x4d\x18"):
        start = marker_tail - 1
        if start < 0 or data[start] not in range(0x50, 0x60):
            continue
        if start + 8 > len(data):
            continue
        payload_size = struct.unpack_from("<I", data, start + 4)[0]
        if start + 8 + payload_size <= len(data):
            return True
    return False


def _contains_legacy_lz4_frame(data: bytes) -> bool:
    candidate_bytes = 0
    for start in _positions(data, b"\x02\x21\x4c\x18"):
        offset = start + 4
        blocks = 0
        while offset + 4 <= len(data) and blocks < MAX_CONTAINER_BLOCKS:
            block_size = struct.unpack_from("<I", data, offset)[0]
            if not block_size or block_size > 8 * 1024 * 1024:
                break
            block_start = offset + 4
            block_end = block_start + block_size
            if block_end > len(data):
                break
            candidate_bytes += block_size
            if candidate_bytes > MAX_DECOMPRESSED_PROBE_BYTES:
                raise TransportGateError(
                    "legacy LZ4 candidates exceed the repository audit limit"
                )
            if _valid_lz4_block(data[block_start:block_end]):
                return True
            offset = block_end
            blocks += 1
    return False


def _valid_lz4_block(block: bytes) -> bool:
    """Validate one raw LZ4 block without allocating decompressed output."""

    offset = 0
    produced = 0
    for sequence_count in range(MAX_CONTAINER_BLOCKS):
        if offset >= len(block):
            return sequence_count > 0
        token = block[offset]
        offset += 1

        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if offset >= len(block):
                    return False
                extension = block[offset]
                offset += 1
                literal_length += extension
                if extension != 255:
                    break
        if literal_length > len(block) - offset:
            return False
        offset += literal_length
        produced += literal_length
        if offset == len(block):
            return True

        if offset + 2 > len(block):
            return False
        match_offset = struct.unpack_from("<H", block, offset)[0]
        offset += 2
        if not match_offset or match_offset > produced:
            return False

        match_length = (token & 0x0F) + 4
        if token & 0x0F == 15:
            while True:
                if offset >= len(block):
                    return False
                extension = block[offset]
                offset += 1
                match_length += extension
                if extension != 255:
                    break
        produced += match_length

    raise TransportGateError("legacy LZ4 block exceeds the sequence audit limit")


def _aligned_from(start: int, value: int, alignment: int) -> int:
    return start + ((value - start + alignment - 1) // alignment) * alignment


def _cpio_newc_end(data: bytes, start: int) -> int | None:
    offset = start
    for entry_count in range(MAX_CONTAINER_BLOCKS):
        if offset + 110 > len(data) or data[offset : offset + 6] not in {
            b"070701",
            b"070702",
        }:
            return None
        raw_fields = [
            data[offset + 6 + index * 8 : offset + 14 + index * 8]
            for index in range(13)
        ]
        if any(not re.fullmatch(rb"[0-9A-Fa-f]{8}", field) for field in raw_fields):
            return None
        fields = [int(field, 16) for field in raw_fields]
        file_size = fields[6]
        name_size = fields[11]
        if not name_size or name_size > MAX_PORTABLE_PATH_BYTES + 1:
            return None
        name_start = offset + 110
        name_end = name_start + name_size
        if name_end > len(data) or data[name_end - 1] != 0:
            return None
        name = data[name_start : name_end - 1]
        payload_start = _aligned_from(start, name_end, 4)
        payload_end = payload_start + file_size
        if payload_end > len(data):
            return None
        offset = _aligned_from(start, payload_end, 4)
        if name == b"TRAILER!!!":
            return offset
        if entry_count == MAX_CONTAINER_BLOCKS - 1:
            return offset
    return None


def _cpio_odc_end(data: bytes, start: int) -> int | None:
    offset = start
    for entry_count in range(MAX_CONTAINER_BLOCKS):
        if offset + 76 > len(data) or data[offset : offset + 6] != b"070707":
            return None
        octal_fields = (
            data[offset + 6 : offset + 48],
            data[offset + 48 : offset + 59],
            data[offset + 59 : offset + 65],
            data[offset + 65 : offset + 76],
        )
        if any(not re.fullmatch(rb"[0-7]+", field) for field in octal_fields):
            return None
        name_size = int(octal_fields[2], 8)
        file_size = int(octal_fields[3], 8)
        if not name_size or name_size > MAX_PORTABLE_PATH_BYTES + 1:
            return None
        name_start = offset + 76
        name_end = name_start + name_size
        if name_end > len(data) or data[name_end - 1] != 0:
            return None
        name = data[name_start : name_end - 1]
        offset = name_end + file_size
        if offset > len(data):
            return None
        if name == b"TRAILER!!!":
            return offset
        if entry_count == MAX_CONTAINER_BLOCKS - 1:
            return offset
    return None


def _cpio_binary_end(data: bytes, start: int, byte_order: str) -> int | None:
    offset = start
    format_string = f"{byte_order}13H"
    for entry_count in range(MAX_CONTAINER_BLOCKS):
        if offset + 26 > len(data):
            return None
        fields = struct.unpack_from(format_string, data, offset)
        if fields[0] != 0x71C7:
            return None
        name_size = fields[10]
        file_size = (fields[11] << 16) | fields[12]
        if not name_size or name_size > MAX_PORTABLE_PATH_BYTES + 1:
            return None
        name_start = offset + 26
        name_end = name_start + name_size
        if name_end > len(data) or data[name_end - 1] != 0:
            return None
        name = data[name_start : name_end - 1]
        payload_start = _aligned_from(start, name_end, 2)
        payload_end = payload_start + file_size
        if payload_end > len(data):
            return None
        offset = _aligned_from(start, payload_end, 2)
        if name == b"TRAILER!!!":
            return offset
        if entry_count == MAX_CONTAINER_BLOCKS - 1:
            return offset
    return None


def _contains_cpio_archive(data: bytes) -> bool:
    for magic, parser in (
        (b"070701", _cpio_newc_end),
        (b"070702", _cpio_newc_end),
        (b"070707", _cpio_odc_end),
    ):
        for start in _positions(data, magic):
            if parser(data, start) is not None:
                return True
    for magic, byte_order in ((b"\xc7\x71", "<"), (b"\x71\xc7", ">")):
        for start in _positions(data, magic):
            if _cpio_binary_end(data, start, byte_order) is not None:
                return True
    return False


def _contains_cabinet(data: bytes) -> bool:
    for start in _positions(data, b"MSCF\0\0\0\0"):
        if start + 36 > len(data):
            continue
        cabinet_size = struct.unpack_from("<I", data, start + 8)[0]
        files_offset = struct.unpack_from("<I", data, start + 16)[0]
        major_version = data[start + 25]
        if (
            major_version == 1
            and cabinet_size >= 36
            and files_offset < cabinet_size
            and start + cabinet_size <= len(data)
        ):
            return True
    return False


def _contains_rpm(data: bytes) -> bool:
    for start in _positions(data, b"\xed\xab\xee\xdb"):
        if start + 100 > len(data):
            continue
        major_version = data[start + 4]
        package_type = struct.unpack_from(">H", data, start + 6)[0]
        signature_header = data[start + 96 : start + 100]
        if (
            major_version == 3
            and package_type in {0, 1}
            and signature_header == b"\x8e\xad\xe8\x01"
        ):
            return True
    return False


def _contains_iso9660(data: bytes) -> bool:
    return any(position >= 16 * 2048 for position in _positions(data, b"\x01CD001\x01"))


def _contains_udif_dmg(data: bytes) -> bool:
    for start in _positions(data, b"koly"):
        if start + 512 > len(data):
            continue
        version, header_size = struct.unpack_from(">II", data, start + 4)
        if version == 4 and header_size == 512:
            return True
    return False


def _contains_embedded_gzip(data: bytes) -> bool:
    candidates = 0
    for position in _positions(data, b"\x1f\x8b", start=1):
        if position + 10 > len(data):
            continue
        if data[position + 2] != 8 or data[position + 3] & 0xE0:
            continue
        candidates += 1
        if candidates > MAX_EMBEDDED_COMPRESSION_CANDIDATES:
            raise TransportGateError("too many plausible embedded gzip streams")
        try:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            output = decompressor.decompress(
                data[position:], MAX_DECOMPRESSED_PROBE_BYTES
            )
        except zlib.error:
            continue
        if decompressor.eof or len(output) == MAX_DECOMPRESSED_PROBE_BYTES:
            return True
    return False


def _contains_embedded_bzip2(data: bytes) -> bool:
    candidates = 0
    for position in _positions(data, b"BZh", start=1):
        if (
            position + 4 > len(data)
            or data[position + 3 : position + 4] not in b"123456789"
        ):
            continue
        candidates += 1
        if candidates > MAX_EMBEDDED_COMPRESSION_CANDIDATES:
            raise TransportGateError("too many plausible embedded bzip2 streams")
        try:
            decompressor = bz2.BZ2Decompressor()
            output = decompressor.decompress(
                data[position:], max_length=MAX_DECOMPRESSED_PROBE_BYTES
            )
        except (OSError, EOFError):
            continue
        if decompressor.eof or len(output) == MAX_DECOMPRESSED_PROBE_BYTES:
            return True
    return False


def _contains_embedded_xz(data: bytes) -> bool:
    candidates = 0
    for position in _positions(data, b"\xfd7zXZ\x00", start=1):
        candidates += 1
        if candidates > MAX_EMBEDDED_COMPRESSION_CANDIDATES:
            raise TransportGateError("too many plausible embedded xz streams")
        try:
            decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
            output = decompressor.decompress(
                data[position:], max_length=MAX_DECOMPRESSED_PROBE_BYTES
            )
        except lzma.LZMAError:
            continue
        if decompressor.eof or len(output) == MAX_DECOMPRESSED_PROBE_BYTES:
            return True
    return False


def _validate_blob_content(path: str, data: bytes) -> None:
    if data.startswith(LFS_POINTER):
        raise TransportGateError(f"Git LFS pointer is not materialized: {path}")

    _validate_png_extent(data, path=path)
    _validate_webp_extent(data, path=path)
    _validate_ico_extent(data, path=path)

    for magic, label in MAGIC_PREFIXES:
        if data.startswith(magic):
            raise TransportGateError(f"{label} content is not allowed: {path}")
    if len(data) > 262 and data[257:262] == b"ustar":
        raise TransportGateError(f"tar archive content is not allowed: {path}")

    try:
        is_zip = zipfile.is_zipfile(io.BytesIO(data))
    except (OSError, ValueError):
        is_zip = False
    if is_zip or _contains_zip_structure(data):
        raise TransportGateError(f"ZIP archive with a preamble is not allowed: {path}")

    for magic, label in (
        (b"# v2 git bundle\n", "Git bundle with a preamble"),
        (b"# v3 git bundle\n", "Git bundle with a preamble"),
        (b"\xfftOc", "Git pack index with a preamble"),
    ):
        if data.find(magic, 1) >= 0:
            raise TransportGateError(f"{label} is not allowed: {path}")
    for position in _positions(data, b"PACK", start=1):
        if position + 32 > len(data):
            continue
        version = struct.unpack_from(">I", data, position + 4)[0]
        if version in {2, 3}:
            raise TransportGateError(f"Git pack with a preamble is not allowed: {path}")

    if _contains_tar_archive(data):
        raise TransportGateError(f"tar archive content is not allowed: {path}")

    for magic, label in (
        (b"7z\xbc\xaf'\x1c", "7z archive with a preamble"),
        (b"Rar!\x1a\x07", "RAR archive with a preamble"),
        (b"!<arch>\n", "ar archive with a preamble"),
    ):
        if data.find(magic, 1) >= 0:
            raise TransportGateError(f"{label} is not allowed: {path}")
    if _contains_embedded_gzip(data):
        raise TransportGateError(f"gzip archive with a preamble is not allowed: {path}")
    if _contains_embedded_bzip2(data):
        raise TransportGateError(
            f"bzip2 archive with a preamble is not allowed: {path}"
        )
    if _contains_embedded_xz(data):
        raise TransportGateError(f"xz archive with a preamble is not allowed: {path}")
    if _contains_embedded_zstd(data):
        raise TransportGateError(f"zstd archive with a preamble is not allowed: {path}")
    if _contains_embedded_lz4(data):
        raise TransportGateError(f"LZ4 archive with a preamble is not allowed: {path}")
    if _contains_zstd_skippable_frame(data):
        raise TransportGateError(f"zstd skippable frame is not allowed: {path}")
    if _contains_legacy_lz4_frame(data):
        raise TransportGateError(f"legacy LZ4 archive is not allowed: {path}")
    if _contains_cpio_archive(data):
        raise TransportGateError(f"cpio archive content is not allowed: {path}")
    if _contains_cabinet(data):
        raise TransportGateError(f"CAB archive content is not allowed: {path}")
    if _contains_rpm(data):
        raise TransportGateError(f"RPM package content is not allowed: {path}")
    if _contains_iso9660(data):
        raise TransportGateError(f"ISO9660 filesystem content is not allowed: {path}")
    if _contains_udif_dmg(data):
        raise TransportGateError(f"UDIF DMG content is not allowed: {path}")


def _resolve_symlink(
    path: str, by_path: dict[str, IndexEntry], samples: dict[str, BlobSample]
) -> str:
    visited: set[str] = set()
    current = path
    while by_path[current].mode == "120000":
        if current in visited:
            raise TransportGateError(f"symlink cycle: {path}")
        visited.add(current)
        sample = samples[by_path[current].oid]
        if sample.size > MAX_SYMLINK_BYTES or len(sample.prefix) != sample.size:
            raise TransportGateError(f"symlink target is too long: {current}")
        raw_target = sample.prefix
        try:
            target = raw_target.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise TransportGateError(f"symlink target is not UTF-8: {current}") from exc
        if not target or target.startswith("/"):
            raise TransportGateError(f"unsafe symlink target: {current}")
        try:
            _validate_portable_components(target, label="symlink target")
        except TransportGateError as exc:
            raise TransportGateError(
                f"unsafe symlink target: {current} ({exc})"
            ) from exc
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(current), target)
        )
        pure = PurePosixPath(resolved)
        folded_parts = {part.casefold().rstrip(" .") for part in pure.parts}
        if (
            resolved == ".."
            or resolved.startswith("../")
            or {".git", "git~1"}.intersection(folded_parts)
        ):
            raise TransportGateError(f"symlink escapes the repository: {current}")
        if resolved not in by_path:
            raise TransportGateError(f"symlink target is not a tracked file: {current}")
        current = resolved
    return current


def _history_git_path(root: Path, relative: str) -> Path:
    raw = _history_git(
        root,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        relative,
    )
    try:
        value = raw.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise TransportGateError("Git metadata path is not valid UTF-8") from exc
    if not value:
        raise TransportGateError(f"cannot resolve Git metadata path: {relative}")
    return Path(value)


def _reject_current_indirections() -> None:
    for variable in FORBIDDEN_CURRENT_ENV:
        if variable in os.environ:
            raise TransportGateError(
                f"current audit refuses repository-shaping environment: {variable}"
            )


def _reject_history_indirections(root: Path) -> None:
    for variable in FORBIDDEN_HISTORY_ENV:
        if variable in os.environ:
            raise TransportGateError(
                f"history audit refuses repository-shaping environment: {variable}"
            )

    shallow = _history_git(root, "rev-parse", "--is-shallow-repository").strip()
    if shallow != b"false":
        if shallow == b"true":
            raise TransportGateError("history audit refuses a shallow repository")
        raise TransportGateError("cannot determine whether repository is shallow")

    for relative, label in (
        ("info/grafts", "Git grafts"),
        ("objects/info/alternates", "Git object alternates"),
        ("objects/info/http-alternates", "Git HTTP object alternates"),
    ):
        metadata_path = _history_git_path(root, relative)
        if metadata_path.exists() or metadata_path.is_symlink():
            raise TransportGateError(f"history audit refuses {label}")

    replace_refs = _history_git(
        root, "for-each-ref", "--format=%(refname)", "refs/replace"
    )
    if replace_refs.strip():
        raise TransportGateError("history audit refuses Git replace refs")

    returncode, replace_config = _run_git(
        root,
        "config",
        "--show-origin",
        "--get-regexp",
        r"^core\.(usereplacerefs|alternaterefscommand)$",
        history=True,
        allowed_returncodes=frozenset({0, 1}),
    )
    if returncode == 0 or replace_config.strip():
        raise TransportGateError(
            "history audit refuses replace/alternate Git configuration"
        )


def _decode_oid(raw: bytes, *, hash_hex_length: int, label: str) -> str:
    try:
        oid = raw.decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise TransportGateError(f"invalid {label} object id") from exc
    if not re.fullmatch(rf"[0-9a-f]{{{hash_hex_length}}}", oid):
        raise TransportGateError(f"invalid {label} object id: {oid!r}")
    return oid


def _commit_links(
    oid: str, data: bytes, *, hash_hex_length: int
) -> tuple[str, tuple[str, ...], bytes]:
    headers, separator, message = data.partition(b"\n\n")
    first_line, _newline, _rest = headers.partition(b"\n")
    prefix = b"tree "
    if not separator or not first_line.startswith(prefix):
        raise TransportGateError(f"commit {oid} has no canonical root tree")
    tree_oid = _decode_oid(
        first_line[len(prefix) :],
        hash_hex_length=hash_hex_length,
        label=f"root tree in commit {oid}",
    )
    parents: list[str] = []
    for line in headers.splitlines()[1:]:
        if not line.startswith(b"parent "):
            continue
        parents.append(
            _decode_oid(
                line[len(b"parent ") :],
                hash_hex_length=hash_hex_length,
                label=f"parent in commit {oid}",
            )
        )
    return tree_oid, tuple(parents), message


def _tree_entries(
    oid: str,
    data: bytes,
    *,
    hash_bytes: int,
    hash_hex_length: int,
) -> tuple[TreeEntry, ...]:
    offset = 0
    entries: list[TreeEntry] = []
    seen: set[str] = set()
    folded_seen: dict[str, str] = {}
    while offset < len(data):
        space = data.find(b" ", offset)
        nul = data.find(b"\0", space + 1) if space >= 0 else -1
        if space <= offset or nul < 0 or nul + 1 + hash_bytes > len(data):
            raise TransportGateError(f"malformed Git tree object {oid}")
        raw_mode = data[offset:space]
        raw_name = data[space + 1 : nul]
        raw_oid = data[nul + 1 : nul + 1 + hash_bytes]
        offset = nul + 1 + hash_bytes
        try:
            mode = raw_mode.decode("ascii", "strict")
            name = raw_name.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise TransportGateError(f"tree {oid} contains a non-UTF-8 entry") from exc
        if mode in {"40000", "040000"}:
            mode = "040000"
        elif mode not in ALLOWED_MODES:
            raise TransportGateError(
                f"unsupported historical Git mode {mode}: tree {oid}/{name}"
            )
        pure = _validate_portable_components(name, label="historical path component")
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or len(pure.parts) != 1
            or pure.parts[0] != name
        ):
            raise TransportGateError(
                f"unsafe historical path component in tree {oid}: {name!r}"
            )
        folded = name.casefold().rstrip(" .")
        if folded in {".git", "git~1", ".gitmodules"}:
            raise TransportGateError(f"nested Git control path in tree {oid}: {name}")
        if name in seen:
            raise TransportGateError(
                f"duplicate historical path in tree {oid}: {name!r}"
            )
        collision = folded_seen.get(folded)
        if collision is not None and collision != name:
            raise TransportGateError(
                "case-folding historical path collision in tree "
                f"{oid}: {collision!r} and {name!r}"
            )
        if mode != "040000":
            _check_archive_suffix(name)
        entry_oid = raw_oid.hex()
        if len(entry_oid) != hash_hex_length:
            raise TransportGateError(f"invalid entry object id in tree {oid}")
        seen.add(name)
        folded_seen[folded] = name
        entries.append(TreeEntry(mode=mode, oid=entry_oid, name=name))
        if len(entries) > MAX_TREE_ENTRIES_PER_OBJECT:
            raise TransportGateError(
                f"tree {oid} exceeds the per-object entry audit limit"
            )
    return tuple(entries)


def _register_expected_type(
    expected: dict[str, str], oid: str, object_type: str
) -> None:
    previous = expected.get(oid)
    if previous is not None and previous != object_type:
        raise TransportGateError(
            f"Git object {oid} is referenced as both {previous} and {object_type}"
        )
    expected[oid] = object_type


def _snapshot_entries(
    root_tree: str,
    trees: dict[str, tuple[TreeEntry, ...]],
    *,
    remaining_budget: int,
) -> tuple[dict[str, IndexEntry], int]:
    by_path: dict[str, IndexEntry] = {}
    visited_paths = 0
    stack: list[tuple[str, str, frozenset[str]]] = [(root_tree, "", frozenset())]
    while stack:
        tree_oid, prefix, ancestors = stack.pop()
        if tree_oid in ancestors:
            raise TransportGateError(f"cycle in historical tree graph: {tree_oid}")
        if len(ancestors) >= MAX_HISTORY_TREE_DEPTH:
            raise TransportGateError(
                "historical tree depth exceeds the repository audit limit"
            )
        next_ancestors = ancestors | {tree_oid}
        for entry in trees[tree_oid]:
            path = f"{prefix}/{entry.name}" if prefix else entry.name
            if len(path.encode("utf-8")) > MAX_PORTABLE_PATH_BYTES:
                raise TransportGateError(
                    f"non-portable historical path is too long: {path!r}"
                )
            visited_paths += 1
            if (
                visited_paths > remaining_budget
                or visited_paths > MAX_HISTORY_PATHS_PER_SNAPSHOT
            ):
                raise TransportGateError(
                    "historical snapshot paths exceed the repository audit limit"
                )
            if entry.mode == "040000":
                stack.append((entry.oid, path, next_ancestors))
            else:
                by_path[path] = IndexEntry(mode=entry.mode, oid=entry.oid, path=path)
    return by_path, visited_paths


def verify_history(root: Path, rev: str) -> HistoryStats:
    root = root.resolve()
    _reject_history_indirections(root)

    object_format = _history_git(root, "rev-parse", "--show-object-format").strip()
    if object_format == b"sha1":
        hash_bytes = 20
    elif object_format == b"sha256":
        hash_bytes = 32
    else:
        raise TransportGateError(
            "unsupported Git object format: "
            f"{object_format.decode('ascii', 'replace')}"
        )
    hash_hex_length = hash_bytes * 2
    resolved = _history_git(
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{rev}^{{commit}}",
    ).strip()
    tip_oid = _decode_oid(
        resolved, hash_hex_length=hash_hex_length, label="history revision"
    )
    raw_commits = _history_git(
        root,
        "rev-list",
        f"--max-count={MAX_HISTORY_COMMITS + 1}",
        tip_oid,
    )
    commits = [
        _decode_oid(line, hash_hex_length=hash_hex_length, label="commit")
        for line in raw_commits.splitlines()
        if line
    ]
    if not commits or commits[0] != tip_oid:
        raise TransportGateError("history revision did not enumerate its tip commit")
    if len(commits) > MAX_HISTORY_COMMITS:
        raise TransportGateError("commit history exceeds the repository audit limit")
    commit_set = set(commits)
    if len(commit_set) != len(commits):
        raise TransportGateError("history traversal returned duplicate commits")

    root_tree_oids: list[str] = []
    raw_parent_oids: set[str] = set()
    with _CatFileBatch(root, history=True) as reader:
        for commit_oid in commits:
            commit = reader.read(
                commit_oid, expected="commit", maximum=MAX_COMMIT_BYTES
            )
            tree_oid, parent_oids, message = _commit_links(
                commit_oid, commit, hash_hex_length=hash_hex_length
            )
            _validate_blob_content(f"commit message {commit_oid}", message)
            root_tree_oids.append(tree_oid)
            raw_parent_oids.update(parent_oids)
    omitted_parents = raw_parent_oids - commit_set
    if omitted_parents:
        raise TransportGateError(
            "history traversal omitted a parent from raw commit data: "
            f"{min(omitted_parents)}"
        )
    unique_root_trees = tuple(dict.fromkeys(root_tree_oids))

    tree_cache: dict[str, tuple[TreeEntry, ...]] = {}
    expected_objects: dict[str, str] = {}
    blob_hints: dict[str, str] = {}
    symlink_oids: set[str] = set()
    tree_entries_count = 0
    pending = deque(unique_root_trees)
    scheduled_trees = set(unique_root_trees)
    for tree_oid in unique_root_trees:
        _register_expected_type(expected_objects, tree_oid, "tree")

    with _CatFileBatch(root, history=True) as reader:
        while pending:
            tree_oid = pending.popleft()
            if tree_oid in tree_cache:
                continue
            if len(tree_cache) >= MAX_HISTORY_TREES:
                raise TransportGateError(
                    "historical tree objects exceed the repository audit limit"
                )
            tree = reader.read(tree_oid, expected="tree", maximum=MAX_TREE_BYTES)
            entries = _tree_entries(
                tree_oid,
                tree,
                hash_bytes=hash_bytes,
                hash_hex_length=hash_hex_length,
            )
            tree_entries_count += len(entries)
            if tree_entries_count > MAX_HISTORY_TREE_ENTRIES:
                raise TransportGateError(
                    "historical tree entries exceed the repository audit limit"
                )
            tree_cache[tree_oid] = entries
            for entry in entries:
                object_type = "tree" if entry.mode == "040000" else "blob"
                _register_expected_type(expected_objects, entry.oid, object_type)
                if object_type == "tree":
                    if entry.oid not in scheduled_trees:
                        scheduled_trees.add(entry.oid)
                        pending.append(entry.oid)
                    continue
                if len(blob_hints) >= MAX_HISTORY_BLOBS and entry.oid not in blob_hints:
                    raise TransportGateError(
                        "historical blob objects exceed the repository audit limit"
                    )
                blob_hints.setdefault(entry.oid, f"tree {tree_oid}/{entry.name}")
                if entry.mode == "120000":
                    symlink_oids.add(entry.oid)

    symlink_samples: dict[str, BlobSample] = {}
    total_blob_bytes = 0
    total_symlink_bytes = 0
    with _CatFileBatch(root, history=True) as reader:
        for blob_oid, hint in sorted(blob_hints.items()):
            blob = reader.read(blob_oid, expected="blob", maximum=MAX_BLOB_BYTES)
            total_blob_bytes += len(blob)
            if total_blob_bytes > MAX_HISTORY_TOTAL_BLOB_BYTES:
                raise TransportGateError(
                    "historical blob data exceeds the repository audit limit"
                )
            _validate_blob_content(hint, blob)
            if blob_oid in symlink_oids:
                if len(blob) > MAX_SYMLINK_BYTES:
                    raise TransportGateError(f"symlink target is too long: {hint}")
                total_symlink_bytes += len(blob)
                if total_symlink_bytes > MAX_TOTAL_SYMLINK_BYTES:
                    raise TransportGateError(
                        "historical symlink data exceeds the repository audit limit"
                    )
                symlink_samples[blob_oid] = BlobSample(prefix=blob, size=len(blob))

    snapshot_paths = 0
    symlink_snapshots = 0
    for root_tree in unique_root_trees:
        by_path, visited = _snapshot_entries(
            root_tree,
            tree_cache,
            remaining_budget=MAX_HISTORY_SNAPSHOT_PATHS - snapshot_paths,
        )
        snapshot_paths += visited
        for entry in by_path.values():
            if entry.mode != "120000":
                continue
            symlink_snapshots += 1
            try:
                _resolve_symlink(entry.path, by_path, symlink_samples)
            except TransportGateError as exc:
                raise TransportGateError(
                    f"root tree {root_tree} has an unsafe symlink: {exc}"
                ) from exc

    return HistoryStats(
        commits=len(commits),
        root_trees=len(unique_root_trees),
        trees=len(tree_cache),
        blobs=len(blob_hints),
        snapshot_paths=snapshot_paths,
        symlink_snapshots=symlink_snapshots,
    )


def verify(root: Path) -> tuple[int, int]:
    _reject_current_indirections()
    root = root.resolve()
    entries = _index(root)
    for entry in entries:
        _check_archive_suffix(entry.path)
    samples = _audit_current_blobs(root, entries)
    by_path = {entry.path: entry for entry in entries}
    symlinks = 0

    for entry in entries:
        if entry.mode == "120000":
            symlinks += 1
            _resolve_symlink(entry.path, by_path, samples)

    return len(entries), symlinks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--history",
        metavar="REV",
        help="audit every commit/tree/blob reachable from REV",
    )
    args = parser.parse_args()
    try:
        if args.history is not None:
            stats = verify_history(Path(args.root), args.history)
        else:
            count, symlinks = verify(Path(args.root))
    except TransportGateError as exc:
        print(f"Repository transport violation: {exc}", file=sys.stderr)
        return 1
    if args.history is not None:
        print(
            "Repository history transport clean: "
            f"{stats.commits} commits, {stats.root_trees} distinct root trees, "
            f"{stats.trees} unique trees, {stats.blobs} unique blobs, "
            f"{stats.symlink_snapshots} safe symlink snapshot(s)"
        )
    else:
        print(
            f"Repository transport clean: {count} tracked paths, "
            f"{symlinks} safe symlink(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
