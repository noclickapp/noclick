"""The volume backend's file operations on the local backend (directories
under NOCLICK_HOME): a listing with sizes and times, one level or everything
below a folder; removing a file or a folder, refusing a non-empty folder
without ``recursive``; copying one file into folders that don't exist yet."""

import pytest

from utils.volume_backend import LocalVolumeBackend, VolumeDirectoryNotEmpty, VolumeFileNotFound


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("NOCLICK_HOME", str(tmp_path))
    return LocalVolumeBackend()


async def test_list_entries_gives_sizes_one_level_or_all_below(backend):
    await backend.write_file("v", "raw/orders.csv", b"id,total\n")
    await backend.write_file("v", "raw/2026/a.json", b"[]")
    top = await backend.list_entries("v", "/")
    assert [(e["path"], e["type"]) for e in top["entries"]] == [("raw", "dir")]
    raw = await backend.list_entries("v", "raw")
    assert [(e["path"], e["type"], e["size"]) for e in raw["entries"]] == [("raw/2026", "dir", 0),
                                                                           ("raw/orders.csv", "file", 9)]
    assert all(isinstance(e["mtime"], int) for e in raw["entries"])
    everything = await backend.list_entries("v", "/", recursive=True)
    assert [e["path"] for e in everything["entries"]] == ["raw", "raw/2026", "raw/2026/a.json", "raw/orders.csv"]
    assert (await backend.list_entries("v", "missing"))["exists"] is False
    assert (await backend.list_entries("nothing", "/"))["exists"] is False


async def test_remove_path_and_copy_file(backend):
    await backend.write_file("v", "raw/orders.csv", b"1")
    await backend.write_file("v", "raw/b.csv", b"2")
    with pytest.raises(VolumeDirectoryNotEmpty):
        await backend.remove_path("v", "raw")
    await backend.copy_file("v", "raw/orders.csv", "archive/2026/orders.csv")
    chunks = await backend.iter_file("v", "archive/2026/orders.csv")
    assert b"".join([c async for c in chunks]) == b"1"
    with pytest.raises(VolumeFileNotFound):
        await backend.copy_file("v", "raw/nope.csv", "x.csv")
    await backend.remove_path("v", "raw/b.csv")
    await backend.remove_path("v", "raw", recursive=True)
    await backend.remove_path("v", "never-there")
    assert [e["path"] for e in (await backend.list_entries("v", "/"))["entries"]] == ["archive"]
