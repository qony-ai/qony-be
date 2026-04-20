from __future__ import annotations

import os
from pathlib import Path
import shutil


def upload_file(local_path: str, *, key: str) -> str:
    public_base = os.getenv("S3_PUBLIC_BASE_URL")
    if public_base:
        return f"{public_base.rstrip('/')}/{key.lstrip('/')}"

    target_root = Path("/tmp/qony-exports")
    target_root.mkdir(parents=True, exist_ok=True)
    target_path = target_root / key
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local_path, target_path)
    return str(target_path)
