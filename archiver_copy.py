#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Move FEBUS outputs to data, then copy them to archive and FTP."""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from archiver_common import (
    ARCHIVE_PATH,
    DATA_PATH,
    FTP_PATH,
    CopySummary,
    MeasurementFile,
    copy_files,
    discover_files,
    files_match,
    print_failures,
    print_table,
    require_destination_roots,
)


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


def move_to_data(
    items: list[MeasurementFile],
    dry_run: bool,
    failures: list[str],
) -> tuple[list[MeasurementFile], set[str]]:
    """Move home files into the local data tree."""
    data_items: list[MeasurementFile] = []
    moved_files: set[str] = set()

    for item in items:
        destination = item.destination_path(DATA_PATH)
        if files_match(item.source_path, destination):
            data_items.append(moved_item(item, destination))
            continue

        if destination.exists():
            failures.append(
                f"move blocked by different existing data file: {item.source_path} -> {destination}"
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
    items = discover_files(home_dir)
    summary = CopySummary(discovered=len(items))

    if not dry_run:
        require_destination_roots([DATA_PATH, FTP_PATH])

    data_items, moved_files = move_to_data(items, dry_run, summary.failures)

    # FTP carries only the lightweight BSL files; archive keeps everything.
    bsl_items = [item for item in data_items if item.kind == "bsl"]
    affected_files: set[str] = set(moved_files)
    archive_affected: set[str] = set()
    if dry_run or ARCHIVE_PATH.exists():
        summary.archive_counts, archive_affected = copy_files(
            data_items, ARCHIVE_PATH, dry_run, summary.failures
        )
    else:
        summary.failures.append(
            f"archive skipped: destination root does not exist: {ARCHIVE_PATH}"
        )
    summary.ftp_counts, ftp_affected = copy_files(
        bsl_items, FTP_PATH, dry_run, summary.failures
    )
    summary.data_counts["moved" if not dry_run else "would_move"] = len(moved_files)
    affected_files.update(archive_affected)
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
