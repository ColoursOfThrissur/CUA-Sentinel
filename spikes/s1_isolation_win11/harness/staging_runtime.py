"""Phase A1 (M8 / CD-02): Dedicated Staging Runtime Setup and Verification.
Creates a hash-verified, immutable staging copy of the Python runtime.
Grants read/execute permissions solely to the specific container SID.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


class RuntimeProvenanceError(Exception):
    pass


class StagingRuntimeManager:
    def __init__(self, staging_dir: Path):
        self.staging_dir = staging_dir.resolve()
        self.manifest_path = self.staging_dir / "staging_manifest.json"

    def is_setup(self) -> bool:
        return (self.staging_dir / "python.exe").exists() and self.manifest_path.exists()

    def build_staging_runtime(self):
        """Creates the standalone staging runtime copy from sys.base_prefix."""
        print(f"[StagingRuntime] Building runtime in: {self.staging_dir}")
        base = Path(sys.base_prefix)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        # 1. Core Executables and DLLs
        for f in ["python.exe", "python3.dll", "python312.dll", "vcruntime140.dll", "vcruntime140_1.dll"]:
            src = base / f
            if src.exists():
                shutil.copy2(src, self.staging_dir / f)

        # 2. DLLs directory
        src_dlls = base / "DLLs"
        dst_dlls = self.staging_dir / "DLLs"
        dst_dlls.mkdir(exist_ok=True)
        if src_dlls.exists():
            for f in src_dlls.glob("*"):
                if f.is_file():
                    shutil.copy2(f, dst_dlls / f.name)

        # 3. Lib directory (standard library)
        src_lib = base / "Lib"
        dst_lib = self.staging_dir / "Lib"
        if not dst_lib.exists():
            # Copy standard library excluding site-packages to keep size minimal
            shutil.copytree(
                src_lib,
                dst_lib,
                ignore=shutil.ignore_patterns("site-packages", "test", "idle_test", "__pycache__"),
                dirs_exist_ok=True,
            )

        # 4. Copy cacert.pem for TLS validation
        try:
            import certifi
            cert_src = Path(certifi.where())
            if cert_src.exists():
                shutil.copy2(cert_src, self.staging_dir / "cacert.pem")
        except ImportError:
            pass

        # 5. Generate Manifest with SHA-256 hashes
        manifest = {}
        for root, _, files in os.walk(self.staging_dir):
            for file in files:
                if file.endswith((".exe", ".dll", ".pyd")):
                    fp = Path(root) / file
                    rel = fp.relative_to(self.staging_dir).as_posix()
                    h = hashlib.sha256(fp.read_bytes()).hexdigest()
                    manifest[rel] = h

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"[StagingRuntime] Manifest generated with {len(manifest)} verified binaries.")

    def verify_runtime_hash(self) -> bool:
        """Verifies every executable in the staging runtime against the manifest (AT-C-12)."""
        if not self.manifest_path.exists():
            raise RuntimeProvenanceError("Staging manifest not found.")

        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        for rel_path, expected_hash in manifest.items():
            fp = self.staging_dir / rel_path
            if not fp.exists():
                raise RuntimeProvenanceError(f"Missing runtime binary: {rel_path}")
            current_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
            if current_hash != expected_hash:
                raise RuntimeProvenanceError(
                    f"TAMPER DETECTED in {rel_path}! Expected {expected_hash}, got {current_hash}"
                )

        return True

    def grant_sid_access(self, sid_string: str):
        """Grants read/execute permissions strictly to the specific container SID."""
        cmd = f'icacls "{self.staging_dir}" /grant "*{sid_string}:(OI)(CI)RX" /T /Q'
        subprocess.run(cmd, shell=True, check=True)

    def revoke_sid_access(self, sid_string: str):
        """Revokes container SID permissions from the staging runtime."""
        cmd = f'icacls "{self.staging_dir}" /remove "*{sid_string}" /T /Q'
        subprocess.run(cmd, shell=True, check=True)

    @property
    def executable(self) -> Path:
        return self.staging_dir / "python.exe"
