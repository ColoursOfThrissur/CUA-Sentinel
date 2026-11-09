"""Windows AppContainer runner for Spike S1 Candidate 1b and 1c."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)

# Win32 Constants
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
INFINITE = 0xFFFFFFFF


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", wintypes.HANDLE),
        ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class AppContainerRunner:
    def __init__(self, profile_name: str, workspace_path: Path):
        self.profile_name = profile_name
        self.workspace_path = workspace_path
        self.sid_handle = None
        self.sid_string = None
        self._init_profile()

    def _init_profile(self):
        # Clean up any existing profile with this name
        userenv.DeleteAppContainerProfile(wintypes.LPCWSTR(self.profile_name))

        sid_ptr = wintypes.HANDLE()
        hr = userenv.CreateAppContainerProfile(
            wintypes.LPCWSTR(self.profile_name),
            wintypes.LPCWSTR(self.profile_name),
            wintypes.LPCWSTR(self.profile_name),
            None,
            0,
            ctypes.byref(sid_ptr),
        )
        if hr != 0:
            raise ctypes.WinError(hr)

        self.sid_handle = sid_ptr

        str_sid = wintypes.LPWSTR()
        advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(str_sid))
        self.sid_string = str_sid.value
        kernel32.LocalFree(str_sid)

        # Grant Full Control on workspace to this specific AppContainer SID
        self._grant_workspace_dacl()

    def _grant_workspace_dacl(self):
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        # Use icacls to grant permissions to the container SID on the workspace folder
        cmd = f'icacls "{self.workspace_path}" /grant "*{self.sid_string}:(OI)(CI)F" /T /Q'
        subprocess.run(cmd, shell=True, check=True)

    def set_loopback_exemption(self, enable: bool = True):
        flag = "-a" if enable else "-d"
        cmd = f'CheckNetIsolation.exe LoopbackExempt {flag} -p="{self.sid_string}"'
        subprocess.run(cmd, shell=True, check=True)

    def run_process(
        self,
        cmd_args: list[str],
        timeout_sec: float = 30.0,
        job_object=None,
        sanitize_env: bool = True,
    ) -> dict:
        # Create stdout/stderr pipes
        sa = ctypes.c_void_p()
        h_read_pipe = wintypes.HANDLE()
        h_write_pipe = wintypes.HANDLE()

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL),
            ]

        sec_attr = SECURITY_ATTRIBUTES()
        sec_attr.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sec_attr.bInheritHandle = True
        sec_attr.lpSecurityDescriptor = None

        if not kernel32.CreatePipe(
            ctypes.byref(h_read_pipe),
            ctypes.byref(h_write_pipe),
            ctypes.byref(sec_attr),
            0,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        kernel32.SetHandleInformation(h_read_pipe, HANDLE_FLAG_INHERIT, 0)

        # Build attribute list with AppContainer capabilities
        sec_cap = SECURITY_CAPABILITIES()
        sec_cap.AppContainerSid = self.sid_handle
        sec_cap.Capabilities = None
        sec_cap.CapabilityCount = 0
        sec_cap.Reserved = 0

        attr_size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
        attr_buffer = (ctypes.c_char * attr_size.value)()
        p_attr_list = ctypes.cast(attr_buffer, ctypes.c_void_p)
        kernel32.InitializeProcThreadAttributeList(p_attr_list, 1, 0, ctypes.byref(attr_size))

        if not kernel32.UpdateProcThreadAttribute(
            p_attr_list,
            0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(sec_cap),
            ctypes.sizeof(sec_cap),
            None,
            None,
        ):
            kernel32.CloseHandle(h_read_pipe)
            kernel32.CloseHandle(h_write_pipe)
            raise ctypes.WinError(ctypes.get_last_error())

        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdOutput = h_write_pipe
        si.StartupInfo.hStdError = h_write_pipe
        si.lpAttributeList = p_attr_list

        pi = PROCESS_INFORMATION()

        cmd_line = subprocess.list2cmdline(cmd_args)
        cmd_buffer = ctypes.create_unicode_buffer(cmd_line)

        # Environment Sanitization
        orig_env = os.environ.copy()
        if sanitize_env:
            # Note: LOCALAPPDATA is strictly required by Windows AppContainer CreateProcessW,
            # otherwise CreateProcessW fails with WinError 203 (ERROR_ENVVAR_NOT_FOUND).
            safe_keys = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "LOCALAPPDATA", "USERPROFILE", "COMSPEC"}
            for k in list(os.environ.keys()):
                if k.upper() not in safe_keys:
                    os.environ.pop(k, None)
            os.environ["TEMP"] = str(self.workspace_path)
            os.environ["TMP"] = str(self.workspace_path)

        success = kernel32.CreateProcessW(
            None,
            cmd_buffer,
            None,
            None,
            True,  # inherit handles for stdout pipe
            EXTENDED_STARTUPINFO_PRESENT,
            None,
            wintypes.LPCWSTR(str(self.workspace_path)),
            ctypes.byref(si.StartupInfo),
            ctypes.byref(pi),
        )

        if sanitize_env:
            os.environ.clear()
            os.environ.update(orig_env)

        # Close write end in parent
        kernel32.CloseHandle(h_write_pipe)

        if not success:
            err = ctypes.get_last_error()
            kernel32.CloseHandle(h_read_pipe)
            kernel32.DeleteProcThreadAttributeList(p_attr_list)
            raise ctypes.WinError(err)

        if job_object:
            job_object.assign_process(pi.hProcess)

        # Read output
        output_chunks = []
        read_buf = (ctypes.c_char * 4096)()
        bytes_read = wintypes.DWORD()

        # Wait for process with timeout
        wait_res = kernel32.WaitForSingleObject(pi.hProcess, int(timeout_sec * 1000))
        timed_out = wait_res == 0x00000102  # WAIT_TIMEOUT

        if timed_out:
            if job_object:
                job_object.terminate(99)
            else:
                kernel32.TerminateProcess(pi.hProcess, 99)

        while True:
            ok = kernel32.ReadFile(
                h_read_pipe,
                read_buf,
                ctypes.sizeof(read_buf),
                ctypes.byref(bytes_read),
                None,
            )
            if not ok or bytes_read.value == 0:
                break
            output_chunks.append(read_buf.raw[: bytes_read.value])

        kernel32.CloseHandle(h_read_pipe)

        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)
        kernel32.DeleteProcThreadAttributeList(p_attr_list)

        raw_output = b"".join(output_chunks).decode("utf-8", errors="replace")

        return {
            "exit_code": exit_code.value,
            "timed_out": timed_out,
            "output": raw_output,
            "pid": pi.dwProcessId,
        }

    def close(self):
        if self.sid_handle:
            advapi32.FreeSid(self.sid_handle)
            self.sid_handle = None
        userenv.DeleteAppContainerProfile(wintypes.LPCWSTR(self.profile_name))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
