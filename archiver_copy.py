#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Move FEBUS outputs off home: bsl to data, archive and FTP; mtx to archive."""

import argparse
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from archiver_common import (
    ARCHIVE_MARKER_NAME,
    ARCHIVE_PATH,
    DATA_PATH,
    FTP_PATH,
    CopySummary,
    MeasurementFile,
    archive_is_mounted,
    copy_files,
    discover_files,
    files_match,
    print_failures,
    print_table,
    require_destination_roots,
)


MINIMUM_FILE_AGE = timedelta(hours=2)


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Move and copy FEBUS measurement files.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned moves/copies without writing files.",
    )
    parser.add_argument(
        "--show-table",
        action="store_true",
        help="Print the discovered file table.",
    )
    return parser.parse_args()


def moved_item(item: MeasurementFile, destination: Path) -> MeasurementFile:
    """Return metadata for a file after moving it to data."""
    return MeasurementFile.from_path(destination) if destination.exists() else item


def move_items(
    items: list[MeasurementFile],
    root: Path,
    dry_run: bool,
    failures: list[str],
) -> tuple[list[MeasurementFile], set[str]]:
    """Move home files into one destination tree."""
    data_items: list[MeasurementFile] = []
    moved_files: set[str] = set()

    for item in items:
        destination = item.destination_path(root)
        if files_match(item.source_path, destination):
            data_items.append(moved_item(item, destination))
            continue

        if destination.exists():
            failures.append(
                f"move blocked by different existing file: {item.source_path} -> {destination}"
            )
            continue

        if dry_run:
            data_items.append(item)
            moved_files.add(item.filename)
            continue

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.source_path), str(destination))
            data_items.append(MeasurementFile.from_path(destination))
            moved_files.add(item.filename)
        except OSError as exc:
            failures.append(f"move failed: {item.source_path} -> {destination}: {exc}")

    return data_items, moved_files


def run_copy(home_dir: Path, dry_run: bool) -> CopySummary:
    """Run the FEBUS move and copy workflow."""
    summary = CopySummary()
    items = discover_files(home_dir, summary.failures)
    summary.discovered = len(items)
    cutoff = datetime.now() - MINIMUM_FILE_AGE
    items = [item for item in items if item.modified_time <= cutoff]

    if not dry_run:
        require_destination_roots([DATA_PATH, FTP_PATH])

    # Home only has room for the lightweight bsl files; heavy mtx goes to the
    # archive drive and is never kept locally.
    bsl_items = [item for item in items if item.kind == "bsl"]
    mtx_items = [item for item in items if item.kind != "bsl"]

    data_items, moved_files = move_items(
        bsl_items, DATA_PATH, dry_run, summary.failures
    )
    affected_files: set[str] = set(moved_files)

    if dry_run or archive_is_mounted(ARCHIVE_PATH):
        summary.archive_counts, archive_affected = copy_files(
            data_items, ARCHIVE_PATH, dry_run, summary.failures
        )
        _, archived_mtx = move_items(mtx_items, ARCHIVE_PATH, dry_run, summary.failures)
        summary.archive_counts["moved" if not dry_run else "would_move"] = len(
            archived_mtx
        )
        affected_files.update(archive_affected)
        affected_files.update(archived_mtx)
    else:
        # Leave mtx in home rather than move it somewhere unmounted.
        summary.failures.append(
            f"archive skipped: volume not mounted, no {ARCHIVE_MARKER_NAME} "
            f"in {ARCHIVE_PATH}"
        )

    # FTP carries only the lightweight BSL files.
    summary.ftp_counts, ftp_affected = copy_files(
        data_items, FTP_PATH, dry_run, summary.failures
    )
    summary.data_counts["moved" if not dry_run else "would_move"] = len(moved_files)
    affected_files.update(ftp_affected)
    summary.affected_files = len(affected_files)
    return summary


def print_summary(summary: CopySummary, started_at: datetime) -> None:
    """Print a concise copy run summary."""
    noun = "file" if summary.affected_files == 1 else "files"
    print(
        f"[{started_at.isoformat(timespec='seconds')}] "
        f"archiver copied {summary.affected_files} {noun}"
    )
    print_failures(summary.failures)


def main() -> None:
    """Move and copy FEBUS measurement files."""
    args = parse_args()
    started_at = datetime.now()
    home_dir = Path(__file__).resolve().parents[1]
    items = discover_files(home_dir)

    if args.show_table:
        print_table(items)

    summary = run_copy(home_dir, args.dry_run)
    print_summary(summary, started_at)


if __name__ == "__main__":
    main()
