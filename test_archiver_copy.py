import os
import time
from pathlib import Path

import archiver_copy
from archiver_common import ARCHIVE_MARKER_NAME


def measurement_path(tmp_path: Path, filename: str, age_seconds: int) -> Path:
    path = tmp_path / filename
    path.write_text("measurement data")
    modified_time = time.time() - age_seconds
    os.utime(path, (modified_time, modified_time))
    return path


def mounted_archive(root: Path) -> Path:
    """Build an archive root that carries the mounted-volume marker."""
    root.mkdir()
    (root / ARCHIVE_MARKER_NAME).write_text("marker")
    return root


def test_run_copy_processes_only_files_at_least_two_hours_old(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    ftp_root = tmp_path / "ftp"
    archive_root = tmp_path / "archive"
    data_root.mkdir()
    ftp_root.mkdir()
    mounted_archive(archive_root)
    monkeypatch.setattr(archiver_copy, "DATA_PATH", data_root)
    monkeypatch.setattr(archiver_copy, "FTP_PATH", ftp_root)
    monkeypatch.setattr(archiver_copy, "ARCHIVE_PATH", archive_root)
    old_file = measurement_path(
        tmp_path,
        "cement-base_C1_2026-06-15T10.40.58+0200.bsl.h5",
        age_seconds=2 * 60 * 60 + 1,
    )
    young_file = measurement_path(
        tmp_path,
        "cement-base_C2_2026-06-15T10.40.58+0200.bsl.h5",
        age_seconds=2 * 60 * 60 - 1,
    )

    summary = archiver_copy.run_copy(tmp_path, dry_run=False)

    assert summary.affected_files == 1
    assert not old_file.exists()
    assert young_file.exists()
    assert (
        data_root
        / "bsl/cement-base/C1/cement-base_C1_2026-06-15T10.40.58+0200.bsl.h5"
    ).exists()
    assert (
        archive_root
        / "bsl/cement-base/C1/cement-base_C1_2026-06-15T10.40.58+0200.bsl.h5"
    ).exists()
    assert (
        ftp_root
        / "bsl/cement-base/C1/cement-base_C1_2026-06-15T10.40.58+0200.bsl.h5"
    ).exists()
    assert not (
        data_root
        / "bsl/cement-base/C2/cement-base_C2_2026-06-15T10.40.58+0200.bsl.h5"
    ).exists()


def test_run_copy_moves_mtx_to_archive_without_keeping_it_in_data(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    ftp_root = tmp_path / "ftp"
    archive_root = tmp_path / "archive"
    data_root.mkdir()
    ftp_root.mkdir()
    mounted_archive(archive_root)
    monkeypatch.setattr(archiver_copy, "DATA_PATH", data_root)
    monkeypatch.setattr(archiver_copy, "FTP_PATH", ftp_root)
    monkeypatch.setattr(archiver_copy, "ARCHIVE_PATH", archive_root)
    mtx_file = measurement_path(
        tmp_path,
        "cement-base_C1_2026-06-15T10.40.58+0200.mtx.h5",
        age_seconds=2 * 60 * 60 + 1,
    )
    relative = "mtx/cement-base/C1/cement-base_C1_2026-06-15T10.40.58+0200.mtx.h5"

    summary = archiver_copy.run_copy(tmp_path, dry_run=False)

    assert summary.affected_files == 1
    assert not mtx_file.exists()
    assert (archive_root / relative).exists()
    assert not (data_root / relative).exists()
    assert not (ftp_root / relative).exists()


def test_run_copy_leaves_mtx_in_place_when_archive_root_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    ftp_root = tmp_path / "ftp"
    archive_root = tmp_path / "archive"
    data_root.mkdir()
    ftp_root.mkdir()
    monkeypatch.setattr(archiver_copy, "DATA_PATH", data_root)
    monkeypatch.setattr(archiver_copy, "FTP_PATH", ftp_root)
    monkeypatch.setattr(archiver_copy, "ARCHIVE_PATH", archive_root)
    mtx_file = measurement_path(
        tmp_path,
        "cement-base_C1_2026-06-15T10.40.58+0200.mtx.h5",
        age_seconds=2 * 60 * 60 + 1,
    )

    summary = archiver_copy.run_copy(tmp_path, dry_run=False)

    # Without the archive drive there is nowhere safe to put mtx, so it waits.
    assert mtx_file.exists()
    assert not archive_root.exists()
    assert any("archive skipped" in failure for failure in summary.failures)


def test_run_copy_skips_archive_when_the_mount_marker_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    ftp_root = tmp_path / "ftp"
    archive_root = tmp_path / "archive"
    data_root.mkdir()
    ftp_root.mkdir()
    # A bare automount directory: it exists, but the volume is not mounted.
    archive_root.mkdir()
    monkeypatch.setattr(archiver_copy, "DATA_PATH", data_root)
    monkeypatch.setattr(archiver_copy, "FTP_PATH", ftp_root)
    monkeypatch.setattr(archiver_copy, "ARCHIVE_PATH", archive_root)
    mtx_file = measurement_path(
        tmp_path,
        "cement-base_C1_2026-06-15T10.40.58+0200.mtx.h5",
        age_seconds=2 * 60 * 60 + 1,
    )

    summary = archiver_copy.run_copy(tmp_path, dry_run=False)

    assert mtx_file.exists()
    assert list(archive_root.iterdir()) == []
    assert any("archive skipped" in failure for failure in summary.failures)
