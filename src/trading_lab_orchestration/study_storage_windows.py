"""Local NTFS publication for the synthetic study. No path-based cleanup."""

import ctypes
import os
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

READ = 0x80000000
WRITE = 0x40000000
DELETE = 0x10000
CREATE_NEW = 1
OPEN_EXISTING = 3
SHARE_READ = 1
SHARE_WRITE = 2
DIRECTORY = 0x10
REPARSE = 0x400
NO_FOLLOW = 0x00200000
WRITE_THROUGH = 0x80000000


class FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME),
        ("written", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


class UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.USHORT),
        ("maximum_length", wintypes.USHORT),
        ("buffer", wintypes.LPWSTR),
    ]


class ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.ULONG),
        ("root", wintypes.HANDLE),
        ("name", ctypes.POINTER(UnicodeString)),
        ("attributes", wintypes.ULONG),
        ("security_descriptor", ctypes.c_void_p),
        ("security_qos", ctypes.c_void_p),
    ]


class IoStatusBlock(ctypes.Structure):
    _fields_ = [("status_or_pointer", ctypes.c_void_p), ("information", ctypes.c_size_t)]


def _bind(name, result, *args):
    function = getattr(ctypes.WinDLL("kernel32", use_last_error=True), name)
    function.argtypes = args
    function.restype = result
    return function


if os.name == "nt":
    import msvcrt

    create_file = _bind(
        "CreateFileW",
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    close_handle = _bind("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    get_info = _bind(
        "GetFileInformationByHandle", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(FileInfo)
    )
    set_info = _bind(
        "SetFileInformationByHandle",
        wintypes.BOOL,
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    drive_type = _bind("GetDriveTypeW", wintypes.UINT, wintypes.LPCWSTR)
    dos_device = _bind(
        "QueryDosDeviceW", wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD
    )
    volume_info = _bind(
        "GetVolumeInformationW",
        wintypes.BOOL,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )

    ntdll = ctypes.WinDLL("ntdll")
    nt_create = ntdll.NtCreateFile
    nt_create.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    nt_create.restype = wintypes.LONG
    status_to_error = ntdll.RtlNtStatusToDosError
    status_to_error.argtypes = [wintypes.LONG]
    status_to_error.restype = wintypes.ULONG


def reserved_name(part):
    check = getattr(os.path, "isreserved", None)
    return check(part) if check is not None else Path(part).is_reserved()


def local_path(path):
    if os.name != "nt":
        raise ValueError("Study storage requires local Windows NTFS")
    path = Path(path).absolute()
    if (
        len(path.drive) != 2
        or path.drive[1] != ":"
        or any(
            part in {".", ".."} or part.endswith((".", " ")) or ":" in part or reserved_name(part)
            for part in path.parts[1:]
        )
    ):
        raise ValueError("Study storage requires a canonical local drive path")
    device = ctypes.create_unicode_buffer(1024)
    filesystem = ctypes.create_unicode_buffer(32)
    if (
        drive_type(path.anchor) != 3
        or not dos_device(path.drive, device, len(device))
        or not device.value.startswith("\\Device\\HarddiskVolume")
        or not volume_info(path.anchor, None, 0, None, None, None, filesystem, len(filesystem))
        or filesystem.value != "NTFS"
    ):
        raise ValueError("Study storage requires a fixed local NTFS volume")
    return path


def _open(path, access, share, mode, flags=0):
    handle = create_file(str(path), access, share, None, mode, flags | NO_FOLLOW, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _info(handle, *, directory=False):
    info = FileInfo()
    if not get_info(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if (
        info.attributes & REPARSE
        or bool(info.attributes & DIRECTORY) != directory
        or (not directory and info.links != 1)
    ):
        raise ValueError("Expected ordinary NTFS evidence without links or reparse points")
    return info


def _open_no_reparse(path, access, share, disposition, *, is_directory=False):
    # OBJ_DONT_REPARSE requires the kernel to reject reparse traversal, including intermediate
    # components. In particular, the first creation in an empty directory cannot follow a
    # mount point attached in place after the directory was opened.
    native_path = "\\??\\" + str(path)
    size = len(native_path.encode("utf-16-le"))
    if size > 65532:
        raise ValueError("Study evidence path exceeds NT path limit")
    name = UnicodeString(size, size + 2, native_path)
    obj = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes), None, ctypes.pointer(name), 0x1040, None, None
    )  # OBJ_DONT_REPARSE | OBJ_CASE_INSENSITIVE
    handle = wintypes.HANDLE()
    io_status = IoStatusBlock()
    options = 0x20 | (0x1 if is_directory else 0x40)
    status = nt_create(
        ctypes.byref(handle),
        access | 0x100000,
        ctypes.byref(obj),
        ctypes.byref(io_status),
        None,
        0,
        share,
        disposition,
        options,
        None,
        0,
    )
    if status == -1073740533:  # STATUS_REPARSE_POINT_ENCOUNTERED (0xC000050B)
        raise ValueError("Study path encountered a reparse point")
    if status < 0:
        raise ctypes.WinError(status_to_error(status))
    return handle.value


@contextmanager
def directory(path, *, create=False, fresh=False, occupy=False):
    # OPEN/CREATE/OPEN_IF here are NT dispositions, distinct from CreateFileW modes.
    handle = _open_no_reparse(
        path,
        READ,
        SHARE_READ | SHARE_WRITE,
        2 if fresh else 3 if create else 1,
        is_directory=True,
    )
    try:
        _info(handle, directory=True)
        with ExitStack() as stack:
            if occupy:
                # NTFS prohibits attaching a mount point to a nonempty directory. Keep this
                # entry live and deny deleting it until the last named operation completes.
                stack.enter_context(exclusive_lock(path / ".study-anchor"))
            yield
    finally:
        close_handle(handle)


@contextmanager
def pinned_root(path):
    path = local_path(path)
    if len(path.parts) < 2:
        raise ValueError("Study storage requires a dedicated root directory")
    with ExitStack() as stack:
        for segment in reversed(path.parents):
            stack.enter_context(directory(segment, create=segment.parent != segment))
        stack.enter_context(directory(path, create=True))
        yield path


@contextmanager
def exclusive_lock(path):
    try:
        handle = _open_no_reparse(path, READ, 0, 3)
    except OSError as exc:
        if exc.winerror == 32:
            raise ValueError("Another study owns the OS lock") from exc
        raise
    try:
        _info(handle)
        yield
    finally:
        close_handle(handle)


def read(path, limit):
    handle = _open(path, READ, SHARE_READ, OPEN_EXISTING)
    with _stream(handle, "rb") as stream:
        info = _info(handle)
        size = (info.size_high << 32) | info.size_low
        if size >= limit:
            raise ValueError("Expected a bounded regular evidence file")
        raw = stream.read(limit)
        if len(raw) != size:
            raise OSError("Evidence size changed during capture")
        return raw


def _stream(handle, mode):
    try:
        flags = os.O_BINARY | os.O_NOINHERIT | (os.O_RDWR if "+" in mode else 0)
        fd = msvcrt.open_osfhandle(handle, flags)
    except OSError:
        close_handle(handle)
        raise
    return os.fdopen(fd, mode)


def _rename(handle, path):
    target = str(path).encode("utf-16-le") + b"\x00\x00"

    class RenameInfo(ctypes.Structure):
        _fields_ = [
            ("replace", wintypes.DWORD),
            ("root", wintypes.HANDLE),
            ("length", wintypes.DWORD),
            ("name", ctypes.c_byte * len(target)),
        ]

    entry = RenameInfo()
    entry.length = len(target) - 2
    ctypes.memmove(ctypes.addressof(entry) + RenameInfo.name.offset, target, len(target))
    if not set_info(handle, 3, ctypes.byref(entry), ctypes.sizeof(entry)):
        raise ctypes.WinError(ctypes.get_last_error())


def publish(path, raw, limit):
    """Publish exactly one file under an already pinned directory, without replacement."""
    if len(raw) >= limit:
        raise ValueError("Evidence exceeds publication limit")
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    handle = _open(temp, READ | WRITE | DELETE, 0, CREATE_NEW, WRITE_THROUGH)
    with _stream(handle, "w+b") as stream:
        promoting = False
        try:
            _info(handle)
            if stream.write(raw) != len(raw):
                raise OSError("Incomplete evidence write")
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            if stream.read(limit) != raw:
                raise OSError("Temporary evidence does not match the captured bytes")
            _info(handle)
            promoting = True
            _rename(handle, path)
        finally:
            if not promoting:
                # Only the acquired object is marked for removal, never a path reopened by name.
                disposition = ctypes.c_ubyte(1)
                if not set_info(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                    raise ctypes.WinError(ctypes.get_last_error())
