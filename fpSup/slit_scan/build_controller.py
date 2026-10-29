"""Compile relocation-free ARM controller text; no camera or card IO."""
import importlib.util
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def build(source=None):
    helper = HERE.parents[1]/'research/ui/tools/arm_text/elf_text.py'
    spec = importlib.util.spec_from_file_location('slit_checked_elf', helper)
    elf = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = elf
    spec.loader.exec_module(elf)
    with tempfile.TemporaryDirectory(prefix='slit-controller-') as tmp:
        obj = Path(tmp)/'controller.o'
        src = Path(tmp)/'controller.c'
        src.write_text(source if source is not None else (HERE/'controller.c').read_text())
        subprocess.run([shutil.which('clang') or 'clang', '-target', 'armv7-none-eabi',
                        '-marm', '-mfloat-abi=soft', '-mfpu=none',
                        '-fno-vectorize', '-fno-slp-vectorize',
                        '-std=c11', '-O2', '-ffreestanding', '-fno-builtin',
                        '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                        '-Wall', '-Wextra', '-Werror', '-I', str(HERE), '-c', str(src),
                        '-o', str(obj)], check=True, capture_output=True, text=True)
        return elf.load_text(obj)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output directory must be new')
    text = build()
    args.out.mkdir()
    (args.out/'controller.bin').write_bytes(text.code)
    (args.out/'manifest.json').write_text(json.dumps(dict(
        bytes=len(text.code), sha256=hashlib.sha256(text.code).hexdigest(),
        functions=text.functions, camera_tested=False, installer_included=False), indent=2)+'\n')
