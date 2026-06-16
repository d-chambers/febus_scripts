from pathlib import Path

import pytest

from archiver_common import MeasurementFile, file_channel


def measurement_path(tmp_path: Path, filename: str) -> Path:
    path = tmp_path / filename
    path.write_text("measurement data")
    return path


@pytest.mark.parametrize(
    ("filename", "channel"),
    [
        ("cement-base_C1_2026-06-15T10.40.58+0200.bsl.h5", "C1"),
        ("cement-base_C2_2026-06-15T10.40.58+0200.mtx.csv", "C2"),
        ("cement-base_C12_2026-06-15T10.40.58+0200.mtx.h5", "C12"),
    ],
)
def test_file_channel_parses_channel_before_timestamp(
    tmp_path: Path, filename: str, channel: str
) -> None:
    path = measurement_path(tmp_path, filename)

    assert file_channel(path) == channel


def test_destination_path_includes_channel_after_prefix(tmp_path: Path) -> None:
    path = measurement_path(
        tmp_path, "cement-base_C2_2026-06-15T10.40.58+0200.bsl.h5"
    )
    item = MeasurementFile.from_path(path)

    assert item.destination_path(Path("/archive")) == Path(
        "/archive/bsl/cement-base/C2/cement-base_C2_2026-06-15T10.40.58+0200.bsl.h5"
    )


def test_file_channel_rejects_missing_channel_before_timestamp(tmp_path: Path) -> None:
    path = measurement_path(
        tmp_path, "cement-base_2026-06-15T10.40.58+0200.bsl.h5"
    )

    with pytest.raises(ValueError, match="Unsupported file channel"):
        MeasurementFile.from_path(path)
