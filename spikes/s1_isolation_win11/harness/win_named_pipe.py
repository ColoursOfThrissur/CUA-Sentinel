"""Win32 Named Pipe server and client wrapper with container SID DACL for Phase A3.
Enforces first-pipe-instance, rejects remote clients, and grants access ONLY to the container SID.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# Win32 Pipe Constants
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
SDDL_REVISION_1 = 1


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


ConvertStringSecurityDescriptorToSecurityDescriptorW = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.ULONG),
]
ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL

CreateNamedPipeW = kernel32.CreateNamedPipeW
CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
]
CreateNamedPipeW.restype = wintypes.HANDLE

ConnectNamedPipe = kernel32.ConnectNamedPipe
ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
ConnectNamedPipe.restype = wintypes.BOOL

DisconnectNamedPipe = kernel32.DisconnectNamedPipe
DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
DisconnectNamedPipe.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

GetNamedPipeClientProcessId = kernel32.GetNamedPipeClientProcessId
GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
GetNamedPipeClientProcessId.restype = wintypes.BOOL


class NamedPipeServer:
    def __init__(self, pipe_name: str, container_sid: str, expected_pid: int | None = None):
        self.pipe_name = f"\\\\.\\pipe\\{pipe_name}"
        self.container_sid = container_sid
        self.expected_pid = expected_pid
        self.pipe_handle = None
        self._p_sd = ctypes.c_void_p()
        self._create_pipe()

    def _create_pipe(self):
        # Ordered DACL: Allow specific container SID first, Deny AC (All other AppContainers), Allow WD for tier 1
        # S:(ML;;NW;;;LW) allows Low-Integrity / AppContainer writes
        sddl = f"S:(ML;;NW;;;LW)D:(A;;GA;;;{self.container_sid})(D;;GA;;;AC)(A;;GA;;;WD)"
        sd_size = wintypes.ULONG()

        ok = ConvertStringSecurityDescriptorToSecurityDescriptorW(
            wintypes.LPCWSTR(sddl),
            SDDL_REVISION_1,
            ctypes.byref(self._p_sd),
            ctypes.byref(sd_size),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

        sec_attr = SECURITY_ATTRIBUTES()
        sec_attr.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sec_attr.lpSecurityDescriptor = self._p_sd.value
        sec_attr.bInheritHandle = False

        open_mode = (
            PIPE_ACCESS_DUPLEX
            | FILE_FLAG_FIRST_PIPE_INSTANCE
        )
        pipe_mode = (
            PIPE_TYPE_MESSAGE
            | PIPE_READMODE_MESSAGE
            | PIPE_WAIT
            | PIPE_REJECT_REMOTE_CLIENTS
        )

        self.pipe_handle = CreateNamedPipeW(
            wintypes.LPCWSTR(self.pipe_name),
            open_mode,
            pipe_mode,
            1,  # max instances = 1 (squatting defense)
            65536,  # out buffer
            65536,  # in buffer
            5000,  # timeout ms
            ctypes.byref(sec_attr),
        )

        if self.pipe_handle == INVALID_HANDLE_VALUE or not self.pipe_handle:
            err = ctypes.get_last_error()
            kernel32.LocalFree(self._p_sd)
            raise ctypes.WinError(err)

    def wait_for_connection(self) -> bool:
        ok = ConnectNamedPipe(self.pipe_handle, None)
        if not ok:
            err = ctypes.get_last_error()
            if err == 535:  # ERROR_PIPE_CONNECTED
                pass
            else:
                raise ctypes.WinError(err)

        # Verify client PID if expected_pid is configured
        if self.expected_pid:
            client_pid = self.get_client_pid()
            if client_pid != self.expected_pid:
                DisconnectNamedPipe(self.pipe_handle)
                raise PermissionError(f"Client PID mismatch: expected {self.expected_pid}, got {client_pid}")

        return True

    def get_client_pid(self) -> int:
        pid = wintypes.ULONG()
        ok = GetNamedPipeClientProcessId(self.pipe_handle, ctypes.byref(pid))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return pid.value

    def read_message(self) -> str:
        buf = (ctypes.c_char * 65536)()
        bytes_read = wintypes.DWORD()
        ok = kernel32.ReadFile(
            self.pipe_handle,
            buf,
            ctypes.sizeof(buf),
            ctypes.byref(bytes_read),
            None,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw[: bytes_read.value].decode("utf-8", errors="replace")

    def write_message(self, message: str):
        data = message.encode("utf-8")
        bytes_written = wintypes.DWORD()
        ok = kernel32.WriteFile(
            self.pipe_handle,
            data,
            len(data),
            ctypes.byref(bytes_written),
            None,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.pipe_handle and self.pipe_handle != INVALID_HANDLE_VALUE:
            DisconnectNamedPipe(self.pipe_handle)
            CloseHandle(self.pipe_handle)
            self.pipe_handle = None
        if self._p_sd:
            kernel32.LocalFree(self._p_sd)
            self._p_sd = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
