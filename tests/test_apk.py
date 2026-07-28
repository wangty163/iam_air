"""Tests for local-only IAM APK credential extraction."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from custom_components.iam_air.apk import IamAirApkError, extract_app_credentials


def _uleb128(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        output.append(byte)
        if not value:
            return bytes(output)


def _fake_dex() -> bytes:
    strings = (
        "Lcom/ixingoo/xingou/common/XingooConstants;",
        "Ljava/lang/String;",
        "APP_KEY",
        "APP_SECRET",
        "<clinit>",
        "fake-app-key",
        "fake-app-secret",
    )
    string_ids_offset = 0x70
    type_ids_offset = string_ids_offset + len(strings) * 4
    field_ids_offset = type_ids_offset + 2 * 4
    method_ids_offset = field_ids_offset + 2 * 8
    class_defs_offset = method_ids_offset + 8
    class_data_offset = class_defs_offset + 32
    code_offset = 0xE0

    data = bytearray(code_offset)
    data[:8] = b"dex\n035\0"
    struct.pack_into("<I", data, 0x24, 0x70)
    struct.pack_into("<I", data, 0x28, 0x12345678)
    struct.pack_into("<II", data, 0x38, len(strings), string_ids_offset)
    struct.pack_into("<II", data, 0x40, 2, type_ids_offset)
    struct.pack_into("<II", data, 0x50, 2, field_ids_offset)
    struct.pack_into("<II", data, 0x58, 1, method_ids_offset)
    struct.pack_into("<II", data, 0x60, 1, class_defs_offset)

    struct.pack_into("<2I", data, type_ids_offset, 0, 1)
    struct.pack_into("<HHI", data, field_ids_offset, 0, 1, 2)
    struct.pack_into("<HHI", data, field_ids_offset + 8, 0, 1, 3)
    struct.pack_into("<HHI", data, method_ids_offset, 0, 0, 4)
    struct.pack_into(
        "<8I",
        data,
        class_defs_offset,
        0,
        0,
        0xFFFFFFFF,
        0,
        0xFFFFFFFF,
        0,
        class_data_offset,
        0,
    )

    class_data = b"\0\0\1\0\0\0" + _uleb128(code_offset)
    data[class_data_offset : class_data_offset + len(class_data)] = class_data
    code = struct.pack(
        "<4H2I9H",
        1,
        0,
        0,
        0,
        0,
        9,
        0x001A,
        5,
        0x0069,
        0,
        0x001A,
        6,
        0x0069,
        1,
        0x000E,
    )
    data.extend(code)

    string_offsets: list[int] = []
    for value in strings:
        string_offsets.append(len(data))
        encoded = value.encode()
        data.extend(_uleb128(len(value)))
        data.extend(encoded)
        data.append(0)
    for index, offset in enumerate(string_offsets):
        struct.pack_into("<I", data, string_ids_offset + index * 4, offset)

    struct.pack_into("<I", data, 0x20, len(data))
    struct.pack_into(
        "<II",
        data,
        0x68,
        len(data) - class_data_offset,
        class_data_offset,
    )
    return bytes(data)


def test_extract_credentials_without_exposing_them(tmp_path: Path) -> None:
    """Matching client credentials come from a local APK and stay out of repr."""
    apk_path = tmp_path / "official-app.zip"
    with zipfile.ZipFile(apk_path, "w") as apk:
        apk.writestr("classes4.dex", _fake_dex())

    credentials = extract_app_credentials(apk_path)

    assert credentials.app_key == "fake-app-key"
    assert credentials.app_secret == "fake-app-secret"
    assert "fake-app-key" not in repr(credentials)
    assert "fake-app-secret" not in repr(credentials)


def test_reject_non_apk(tmp_path: Path) -> None:
    """A non-ZIP file cannot be treated as an official APK."""
    path = tmp_path / "not-an-apk.bin"
    path.write_bytes(b"not an apk")

    with pytest.raises(IamAirApkError):
        extract_app_credentials(path)
