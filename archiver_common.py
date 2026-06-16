"""Shared FEBUS archive paths, parsing, and reporting helpers."""

import re
import shutil
from collections import Counter
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path

# Paths to different storage places.
FTP_PATH = Path("/home/febus/ecenaris/OpticalFiber")
ARCHIVE_PATH = Path("/mnt/febus-archive")
DATA_PATH = Path("/home/febus/data")

# Limit on total managed FEBUS files in the FTP folder, in bytes.
FTP_LIMIT_SIZE_BYTES = 15_000_000_000

# Files older than this are removed from the local data folder.
DATA_FOLDER_EXPIRATION = timedelta(days=90)

SUPPORTED_SUFFIXES = (".bsl.h5", ".mtx.h5", ".bsl.csv", ".mtx.csv")
CHANNEL_PATTERN = re.compile(r"_(C\d+)_\d{4}-\d{2}-\d{2}T")


@dataclass(frozen=True)
class MeasurementFile:
    """Parsed metadata for one FEBUS output file."""

    source_path: Path
    filename: str
    prefix: str
    channel: str
    kind: str
    format: str
    size_bytes: int
    modified_time: datetime

    @classmethod
    def from_path(cls, path: Path) -> "MeasurementFile":
        """Build metadata from a supported FEBUS output path."""
        stat = path.stat()
        return cls(
            source_path=path,
            filename=path.name,
            prefix=path.name.split("_", 1)[0],
            channel=file_channel(path),
            kind=file_kind(path),
            format=file_format(path),
            size_bytes=stat.st_size,
            modified_time=datetime.fromtimestamp(stat.st_mtime),
        )

    def destination_path(self, root: Path) -> Path:
        """Build the type/prefix/channel destination path for this file."""
        return root / self.kind / self.prefix / self.channel / self.filename


@dataclass
class CopySummary:
    """Accumulate copy outcomes for one run."""

    discovered: int = 0
    affected_files: int = 0
    archive_counts: Counter | None = None
    data_counts: Counter | None = None
    ftp_counts: Counter | None = None
    failures: list[str] | None = None

    def __post_init__(self) -> None:
        """Initialize mutable summary fields."""
        self.archive_counts = self.archive_counts or Counter()
        self.data_counts = self.data_counts or Counter()
        self.ftp_counts = self.ftp_counts or Counter()
        self.failures = self.failures or []


@dataclass
class PruneSummary:
    """Accumulate prune outcomes for one run."""

    ftp_deleted_count: int = 0
    ftp_deleted_bytes: int = 0
    data_deleted_count: int = 0
    failures: list[str] | None = None

    def __post_init__(self) -> None:
        """Initialize mutable summary fields."""
        self.failures = self.failures or []


def is_supported_measurement(path: Path) -> bool:
    """Return whether the path name matches a supported FEBUS output."""
    return path.name.endswith(SUPPORTED_SUFFIXES)


def file_kind(path: Path) -> str:
    """Return the FEBUS measurement kind for a supported file."""
    if path.name.endswith((".bsl.h5", ".bsl.csv")):
        return "bsl"
    if path.name.endswith((".mtx.h5", ".mtx.csv")):
        return "mtx"
    raise ValueError(f"Unsupported file type: {path}")


def file_format(path: Path) -> str:
    """Return the storage format for a supported file."""
    if path.name.endswith(".h5"):
        return "h5"
    if path.name.endswith(".csv"):
        return "csv"
    raise ValueError(f"Unsupported file format: {path}")


def file_channel(path: Path) -> str:
    """Return the FEBUS channel token for a supported file."""
    match = CHANNEL_PATTERN.search(path.name)
    if match:
        return match.group(1)
    raise ValueError(f"Unsupported file channel: {path.name}")


def discover_files(home_dir: Path) -> list[MeasurementFile]:
    """Collect supported top-level home-directory measurement files."""
    # Only top-level measurement outputs are archived; subfolders are managed separately.
    files = sorted(
        [
            path
            for path in home_dir.iterdir()
            if path.is_file() and is_supported_measurement(path)
        ],
        key=lambda path: path.name,
    )
    return [MeasurementFile.from_path(path) for path in files]


def files_match(source: Path, destination: Path) -> bool:
    """Return whether destination already has the same file content metadata."""
    if not destination.exists():
        return False

    # copy2/move preserve mtime, so size+mtime avoids repeated transfers.
    source_stat = source.stat()
    destination_stat = destination.stat()
    return (
        source_stat.st_size == destination_stat.st_size
        and abs(source_stat.st_mtime - destination_stat.st_mtime) < 1.0
    )


def copy_file(item: MeasurementFile, destination_root: Path, dry_run: bool) -> str:
    """Copy one file unless it already exists unchanged."""
    destination = item.destination_path(destination_root)
    if files_match(item.source_path, destination):
        return "skipped"

    if dry_run:
        return "would_copy"

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(item.source_path, destination)
    return "copied"


def copy_files(
    items: list[MeasurementFile],
    destination_root: Path,
    dry_run: bool,
    failures: list[str],
) -> tuple[Counter, set[str]]:
    """Copy measurement files into one destination root."""
    counts: Counter = Counter()
    affected_files: set[str] = set()
    for item in items:
        try:
            result = copy_file(item, destination_root, dry_run)
            counts[result] += 1
            if result in {"copied", "would_copy"}:
                affected_files.add(item.filename)
        except OSError as exc:
            counts["failed"] += 1
            failures.append(
                f"copy failed: {item.source_path} -> {destination_root}: {exc}"
            )
    return counts, affected_files


def require_destination_roots(paths: list[Path]) -> None:
    """Stop execution if any required destination root is missing."""
    missing = [path for path in paths if not path.exists()]
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise SystemExit(f"Destination root does not exist:\n{formatted}")


def managed_files(root: Path) -> list[Path]:
    """Return recognized FEBUS files under a managed root directory."""
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and is_supported_measurement(path)
    ]


def prune_ftp_to_limit(
    root: Path,
    limit_bytes: int,
    dry_run: bool,
    failures: list[str],
) -> tuple[int, int]:
    """Delete oldest managed FTP files until the folder is under the byte limit."""
    files = managed_files(root)
    total_size = sum(path.stat().st_size for path in files)
    deleted_count = 0
    deleted_bytes = 0

    # Remove oldest files first so recent BSL outputs stay available on FTP.
    for path in sorted(files, key=lambda file_path: file_path.stat().st_mtime):
        if total_size <= limit_bytes:
            break

        size = path.stat().st_size
        try:
            if not dry_run:
                path.unlink()
        except OSError as exc:
            failures.append(f"ftp prune failed: {path}: {exc}")
            continue

        total_size -= size
        deleted_count += 1
        deleted_bytes += size

    return deleted_count, deleted_bytes


def prune_expired_data(
    root: Path,
    expiration: timedelta,
    dry_run: bool,
    failures: list[str],
) -> int:
    """Delete managed local data files older than the expiration period."""
    cutoff = datetime.now() - expiration
    deleted_count = 0

    for path in managed_files(root):
        modified_time = datetime.fromtimestamp(path.stat().st_mtime)
        if modified_time >= cutoff:
            continue

        try:
            if not dry_run:
                path.unlink()
        except OSError as exc:
            failures.append(f"data prune failed: {path}: {exc}")
            continue

        deleted_count += 1

    return deleted_count


def print_table(items: list[MeasurementFile]) -> None:
    """Print discovered measurements as a fixed-width table."""
    columns = [field.name for field in fields(MeasurementFile)]
    rows = [
        {
            "source_path": str(item.source_path),
            "filename": item.filename,
            "prefix": item.prefix,
            "channel": item.channel,
            "kind": item.kind,
            "format": item.format,
            "size_bytes": str(item.size_bytes),
            "modified_time": item.modified_time.isoformat(sep=" ", timespec="seconds"),
        }
        for item in items
    ]
    widths = {
        column: max(len(column), *(len(row[column]) for row in rows))
        if rows
        else len(column)
        for column in columns
    }
    print(" ".join(column.rjust(widths[column]) for column in columns))
    for row in rows:
        print(" ".join(row[column].rjust(widths[column]) for column in columns))


def print_copy_counts(label: str, counts: Counter) -> None:
    """Print copy counts for one destination."""
    print(
        f"{label}: "
        f"copied={counts['copied']}, "
        f"skipped={counts['skipped']}, "
        f"would_copy={counts['would_copy']}, "
        f"failed={counts['failed']}"
    )


def print_failures(failures: list[str]) -> None:
    """Print recoverable failures from a run."""
    if not failures:
        return
    print(f"Failures: {len(failures)}")
    for failure in failures:
        print(f"  - {failure}")
