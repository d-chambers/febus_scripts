#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Prune managed FEBUS files from FTP and local data destinations."""

import argparse
from datetime import datetime

from archiver_common import (
    DATA_FOLDER_EXPIRATION,
    DATA_PATH,
    FTP_LIMIT_SIZE_BYTES,
    FTP_PATH,
    PruneSummary,
    print_failures,
    prune_expired_data,
    prune_ftp_to_limit,
    require_destination_roots,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Prune FEBUS archive destinations.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned deletes without removing files.",
    )
    return parser.parse_args()


def run_prune(dry_run: bool) -> PruneSummary:
    """Run the FEBUS prune workflow."""
    summary = PruneSummary()

    if not dry_run:
        require_destination_roots([DATA_PATH, FTP_PATH])

    # Only recognized FEBUS filenames are eligible for pruning.
    summary.ftp_deleted_count, summary.ftp_deleted_bytes = prune_ftp_to_limit(
        FTP_PATH, FTP_LIMIT_SIZE_BYTES, dry_run, summary.failures
    )
    summary.data_deleted_count = prune_expired_data(
        DATA_PATH, DATA_FOLDER_EXPIRATION, dry_run, summary.failures
    )
    return summary


def print_summary(summary: PruneSummary, started_at: datetime) -> None:
    """Print a concise prune run summary."""
    affected = summary.ftp_deleted_count + summary.data_deleted_count
    noun = "file" if affected == 1 else "files"
    print(f"[{started_at.isoformat(timespec='seconds')}] archiver pruned {affected} {noun}")
    print_failures(summary.failures)


def main() -> None:
    """Prune FEBUS archive destinations."""
    args = parse_args()
    started_at = datetime.now()
    summary = run_prune(args.dry_run)
    print_summary(summary, started_at)


if __name__ == "__main__":
    main()
