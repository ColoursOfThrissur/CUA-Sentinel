import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path("spikes/s1_isolation_win11/harness").resolve()))
from win_appcontainer import AppContainerRunner
from staging_runtime import StagingRuntimeManager

ws = Path("data/test_appcontainer_pipe_ws").resolve()
runner = AppContainerRunner("Sentinel.Spike.AppContainerPipeTest", ws)

runtime_mgr = StagingRuntimeManager(Path("spikes/s1_isolation_win11/staging_runtime"))
runtime_mgr.grant_sid_access(runner.sid_string)

pipe_suffix = f"test_ac_pipe_{int(time.time())}"
pipe_path = f"\\\\.\\pipe\\LOCAL\\{pipe_suffix}"

# S:(ML;;NW;;;LW) + Specific Container SID access
sddl = f"S:(ML;;NW;;;LW)D:(A;;0x12019b;;;SY)(A;;0x12019b;;;BA)(A;;0x12019b;;;{runner.sid_string})"

import ctypes
from ctypes import wintypes
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

p_sd = ctypes.c_void_p()
sd_size = wintypes.ULONG()
advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
    wintypes.LPCWSTR(sddl), 1, ctypes.byref(p_sd), ctypes.byref(sd_size)
)

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]

sec_attr = SECURITY_ATTRIBUTES()
sec_attr.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
sec_attr.lpSecurityDescriptor = p_sd.value
sec_attr.bInheritHandle = False

h_pipe = kernel32.CreateNamedPipeW(
    wintypes.LPCWSTR(pipe_path),
    0x00000003 | 0x00080000, # DUPLEX | FIRST_INSTANCE
    0x00000004 | 0x00000002 | 0x00000008, # MESSAGE | READMODE_MESSAGE | REJECT_REMOTE
    1, 65536, 65536, 5000, ctypes.byref(sec_attr)
)

print(f"Pipe created at {pipe_path} with handle: {h_pipe}")

def srv():
    kernel32.ConnectNamedPipe(h_pipe, None)
    buf = (ctypes.c_char * 1024)()
    bread = wintypes.DWORD()
    kernel32.ReadFile(h_pipe, buf, 1024, ctypes.byref(bread), None)
    print("Server received from AppContainer:", buf.raw[:bread.value])
    kernel32.WriteFile(h_pipe, b"PONG_FROM_HOST", 14, ctypes.byref(bread), None)
    kernel32.DisconnectNamedPipe(h_pipe)
    kernel32.CloseHandle(h_pipe)

t = threading.Thread(target=srv, daemon=True)
t.start()
time.sleep(0.2)

# Run client inside AppContainer
client_code = f"""
import time
with open(r'{pipe_path}', 'r+b', buffering=0) as f:
    f.write(b'PING_FROM_APPCONTAINER')
    resp = f.read(1024)
    print('CLIENT RECEIVED:', resp)
"""

res = runner.run_process([str(runtime_mgr.executable), "-c", client_code], timeout_sec=5.0)
print("APPCONTAINER CLIENT OUTPUT:", res["output"])
print("APPCONTAINER CLIENT EXIT:", res["exit_code"])

t.join(timeout=2.0)
runner.close()
runtime_mgr.revoke_sid_access(runner.sid_string)
kernel32.LocalFree(p_sd)
