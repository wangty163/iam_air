"""Extract Link Living client credentials from a user-supplied IAM APK."""

from __future__ import annotations

import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_APK_BYTES = 200 * 1024 * 1024
MAX_DEX_BYTES = 100 * 1024 * 1024
MAX_DEX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_DEX_FILES = 20
MAX_TABLE_ITEMS = 1_000_000
TARGET_CLASS = "Lcom/ixingoo/xingou/common/XingooConstants;"
TARGET_FIELDS = frozenset({"APP_KEY", "APP_SECRET"})
DEX_NAME_PATTERN = re.compile(r"^classes(?:\d+)?\.dex$")


class IamAirApkError(Exception):
    """The supplied APK cannot provide IAM application credentials."""


@dataclass(frozen=True, slots=True)
class IamAppCredentials:
    """Credentials recovered from an APK and kept only in memory."""

    app_key: str = field(repr=False)
    app_secret: str = field(repr=False)


def extract_app_credentials(apk_path: str | Path) -> IamAppCredentials:
    """Extract IAM's Link Living client credentials from a local official APK."""
    path = Path(apk_path).expanduser()
    try:
        size = path.stat().st_size
    except OSError as err:
        raise IamAirApkError("IAM APK is not readable") from err
    if not path.is_file() or size <= 0 or size > MAX_APK_BYTES:
        raise IamAirApkError("IAM APK has an invalid size")

    try:
        with zipfile.ZipFile(path) as apk:
            dex_entries = sorted(
                (
                    info
                    for info in apk.infolist()
                    if DEX_NAME_PATTERN.fullmatch(info.filename)
                ),
                key=lambda info: info.filename,
            )
            if not dex_entries:
                raise IamAirApkError("IAM APK contains no DEX files")
            if (
                len(dex_entries) > MAX_DEX_FILES
                or sum(info.file_size for info in dex_entries) > MAX_DEX_TOTAL_BYTES
            ):
                raise IamAirApkError("IAM APK contains too much DEX data")
            for info in dex_entries:
                if info.file_size <= 0 or info.file_size > MAX_DEX_BYTES:
                    raise IamAirApkError("IAM APK contains an invalid DEX file")
                credentials = _DexCredentials(apk.read(info)).extract()
                if credentials is not None:
                    return credentials
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError) as err:
        raise IamAirApkError("IAM APK cannot be opened") from err
    raise IamAirApkError("IAM application credentials were not found in the APK")


class _DexCredentials:
    """Minimal DEX reader for one constants class and its static initializer."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._strings: dict[int, str] = {}

    def extract(self) -> IamAppCredentials | None:
        """Return credentials when this DEX owns the IAM constants class."""
        if len(self._data) < 0x70 or not self._data.startswith(b"dex\n"):
            raise IamAirApkError("IAM APK contains a malformed DEX file")

        self._table(0x38, 4)
        type_count, type_offset = self._table(0x40, 4)
        field_count, field_offset = self._table(0x50, 8)
        method_count, method_offset = self._table(0x58, 8)
        class_count, class_offset = self._table(0x60, 32)

        target_type = next(
            (
                index
                for index in range(type_count)
                if self._string(self._u32(type_offset + index * 4)) == TARGET_CLASS
            ),
            None,
        )
        if target_type is None:
            return None

        target_fields: dict[int, str] = {}
        for index in range(field_count):
            offset = field_offset + index * 8
            if self._u16(offset) != target_type:
                continue
            name = self._string(self._u32(offset + 4))
            if name in TARGET_FIELDS:
                target_fields[index] = name
        if set(target_fields.values()) != TARGET_FIELDS:
            raise IamAirApkError("IAM APK constants class is incomplete")

        clinit_method = next(
            (
                index
                for index in range(method_count)
                if self._u16(method_offset + index * 8) == target_type
                and self._string(self._u32(method_offset + index * 8 + 4)) == "<clinit>"
            ),
            None,
        )
        if clinit_method is None:
            raise IamAirApkError("IAM APK constants initializer is missing")

        class_data_offset = next(
            (
                self._u32(class_offset + index * 32 + 24)
                for index in range(class_count)
                if self._u32(class_offset + index * 32) == target_type
            ),
            None,
        )
        if not class_data_offset:
            raise IamAirApkError("IAM APK constants class has no bytecode")

        code_offset = self._find_method_code(class_data_offset, clinit_method)
        if not code_offset:
            raise IamAirApkError("IAM APK constants initializer has no bytecode")

        values = self._extract_static_strings(code_offset, target_fields)
        app_key = values.get("APP_KEY")
        app_secret = values.get("APP_SECRET")
        if (
            not app_key
            or not app_secret
            or app_key == app_secret
            or len(app_key) < 6
            or len(app_secret) < 12
        ):
            raise IamAirApkError("IAM APK application credentials are invalid")
        return IamAppCredentials(app_key=app_key, app_secret=app_secret)

    def _table(self, header_offset: int, item_size: int) -> tuple[int, int]:
        count = self._u32(header_offset)
        offset = self._u32(header_offset + 4)
        if count > MAX_TABLE_ITEMS:
            raise IamAirApkError("IAM APK DEX table is too large")
        self._require(offset, count * item_size)
        return count, offset

    def _find_method_code(self, offset: int, target_method: int) -> int | None:
        static_fields, offset = self._uleb128(offset)
        instance_fields, offset = self._uleb128(offset)
        direct_methods, offset = self._uleb128(offset)
        virtual_methods, offset = self._uleb128(offset)

        for _ in range(static_fields + instance_fields):
            _, offset = self._uleb128(offset)
            _, offset = self._uleb128(offset)

        method_index = 0
        for _ in range(direct_methods):
            method_delta, offset = self._uleb128(offset)
            method_index += method_delta
            _, offset = self._uleb128(offset)
            code_offset, offset = self._uleb128(offset)
            if method_index == target_method:
                return code_offset

        for _ in range(virtual_methods):
            _, offset = self._uleb128(offset)
            _, offset = self._uleb128(offset)
            _, offset = self._uleb128(offset)
        return None

    def _extract_static_strings(
        self, code_offset: int, target_fields: dict[int, str]
    ) -> dict[str, str]:
        self._require(code_offset, 16)
        instruction_count = self._u32(code_offset + 12)
        instruction_offset = code_offset + 16
        self._require(instruction_offset, instruction_count * 2)
        instructions = [
            self._u16(instruction_offset + index * 2)
            for index in range(instruction_count)
        ]

        values: dict[str, str] = {}
        for index, instruction in enumerate(instructions):
            opcode = instruction & 0xFF
            register = instruction >> 8
            if opcode == 0x1A and index + 3 < len(instructions):
                string_index = instructions[index + 1]
                next_index = index + 2
            elif opcode == 0x1B and index + 4 < len(instructions):
                string_index = instructions[index + 1] | (instructions[index + 2] << 16)
                next_index = index + 3
            else:
                continue

            put_instruction = instructions[next_index]
            if (put_instruction & 0xFF) != 0x69 or put_instruction >> 8 != register:
                continue
            field_index = instructions[next_index + 1]
            field_name = target_fields.get(field_index)
            if field_name:
                values[field_name] = self._string(string_index)
        return values

    def _string(self, index: int) -> str:
        if index in self._strings:
            return self._strings[index]
        string_count = self._u32(0x38)
        string_offset = self._u32(0x3C)
        if index >= string_count:
            raise IamAirApkError("IAM APK DEX string index is invalid")
        data_offset = self._u32(string_offset + index * 4)
        _, value_offset = self._uleb128(data_offset)
        end = self._data.find(b"\0", value_offset, value_offset + 65536)
        if end < 0:
            raise IamAirApkError("IAM APK DEX string is unterminated")
        try:
            value = self._data[value_offset:end].decode("utf-8")
        except UnicodeDecodeError as err:
            raise IamAirApkError("IAM APK DEX string is invalid") from err
        self._strings[index] = value
        return value

    def _uleb128(self, offset: int) -> tuple[int, int]:
        value = 0
        for shift in range(0, 35, 7):
            self._require(offset, 1)
            byte = self._data[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value, offset
        raise IamAirApkError("IAM APK DEX integer is invalid")

    def _u16(self, offset: int) -> int:
        self._require(offset, 2)
        return struct.unpack_from("<H", self._data, offset)[0]

    def _u32(self, offset: int) -> int:
        self._require(offset, 4)
        return struct.unpack_from("<I", self._data, offset)[0]

    def _require(self, offset: int, size: int) -> None:
        if offset < 0 or size < 0 or offset + size > len(self._data):
            raise IamAirApkError("IAM APK contains a truncated DEX file")
