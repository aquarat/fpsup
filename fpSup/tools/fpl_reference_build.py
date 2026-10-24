#!/usr/bin/env python3
"""Offline, isolated fp reference reproduction; never operates a camera.

See ../docs/FPL_REFERENCE_BUILD.md. Source is read from an explicit git revision,
not the working tree. Firmware is only symlinked into the fresh output tree.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ('fpSup/fp_usb_shell/', 'fpSup/gyro/',
               'projects/gyro2-sup/', 'research/ui/tools/arm_text/')
RELEASE = 'fpSup/releases/fpsup-gyro2-v0.2.0/'
FIXTURES = (
    'projects/gyro-sup/captures/fpGFTest_pre_stage4_20260817_2207/CINEMA/A001_001/A001_001_20260817_000244.DNG',
    'projects/open-gate/test-build/og2k_3x3_20260924/A001_009/A001_009_20260924_000016.DNG',
    'projects/open-gate/captures/og3k120-defect-A001_182/A001_182_20260927_000001.DNG',
    'projects/usb-shell-sup/cards/20261006-v3-step2-lossless/fpSup/10LOSS.BIN',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(path):
    return {'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size}


def gyro_header(blob):
    if len(blob) < 32:
        raise ValueError('truncated Gyro2 header')
    magic, header, size, block, entry, ident, version, service = struct.unpack_from('<8I', blob)
    if (magic, header, size, entry, ident, version, service) != (
            0x31425346, 32, len(blob), 32, int.from_bytes(b'GYR2', 'little'), 6, 1):
        raise ValueError('unexpected Gyro2 release ABI/header')
    if block < size or size % 4 or block % 4:
        raise ValueError('invalid Gyro2 allocation/alignment')
    return dict(file=size, block=block, entry=entry, version=version, min_service=service)


def zig_arguments(args):
    """Translate Clang ARM spellings, selecting Thumb in Zig's target itself."""
    thumb = '-mthumb' in args
    out = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('-target', '--target'):
            i += 1
            target = args[i]
        elif arg.startswith('--target='):
            target = arg.split('=', 1)[1]
        else:
            out.append('-mcpu=cortex_a9' if arg == '-mcpu=cortex-a9' else arg)
            i += 1
            continue
        if target not in ('armv7-none-eabi', 'armv7a-none-eabi'):
            raise ValueError('unsupported reference target: ' + target)
        out += ['-target', ('thumb' if thumb else 'arm') + '-freestanding-eabi']
        i += 1
    # Freestanding text has no unwinder. Prevent its generation at compilation;
    # do not delete undefined symbols or rewrite the resulting ELF.
    return out + ['-fno-unwind-tables', '-fno-asynchronous-unwind-tables']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-rev', required=True)
    ap.add_argument('--fp-image', required=True, type=Path)
    ap.add_argument('--fpl-image', type=Path, help='fingerprint only; never used for fp builds')
    compiler = ap.add_mutually_exclusive_group(required=True)
    compiler.add_argument('--zig', type=Path)
    compiler.add_argument('--clang-dir', type=Path)
    ap.add_argument('--out', required=True, type=Path, help='must not already exist')
    a = ap.parse_args()
    revision = subprocess.check_output(['git', 'rev-parse', a.source_rev + '^{commit}'], cwd=ROOT, text=True).strip()
    images = {k: p.expanduser().resolve(strict=True) for k, p in
              [('fp', a.fp_image), ('fpl', a.fpl_image)] if p is not None}
    out = a.out.expanduser().resolve()
    if out.is_relative_to(ROOT):
        ap.error('--out must be outside the checkout (it contains external firmware symlinks)')
    out.mkdir(parents=True, exist_ok=False)
    tree = out / 'source'
    tree.mkdir()
    manifest = {'source_revision': revision, 'sources': {}, 'inputs': {}, 'steps': [],
                'driver': fingerprint(Path(__file__)), 'python': sys.version}
    def save():
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    def run(name, command, cwd=tree):
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        (out / (name + '.log')).write_text(result.stdout + result.stderr)
        step = {'name': name, 'command': command, 'returncode': result.returncode}
        count = re.search(r'Ran (\d+) tests?', result.stderr)
        if count:
            step['tests_run'] = int(count[1])
            skipped = re.search(r'skipped=(\d+)', result.stderr)
            step['skipped'] = int(skipped[1]) if skipped else 0
        manifest['steps'].append(step)
        save()
        return result.returncode == 0
    try:
        paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', revision], cwd=ROOT, text=True).splitlines()
        selected = [p for p in paths if
                    (p.startswith(SOURCE_DIRS) and Path(p).suffix in ('.py', '.S', '.h', '.c'))
                    or p in FIXTURES or p in (RELEASE + 'build.json', RELEASE + 'fpSup/40GYR2.BIN', 'fpSup/NOTICE', 'fpSup/LICENSE')]
        for name in selected:
            data = subprocess.check_output(['git', 'show', revision + ':' + name], cwd=ROOT)
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest['sources'][name] = {'sha256': digest(data), 'bytes': len(data)}
        manifest['missing_fixtures'] = sorted(set(FIXTURES) - set(selected))
        for key, image in images.items():
            manifest['inputs'][key] = fingerprint(image)
        # Imported build and test helpers expect different historical roots.
        for relative in ('out/MAIN_c0000000.bin', 'fpSup/out/MAIN_c0000000.bin'):
            link = tree / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(images['fp'])
        pins = json.loads((tree / RELEASE / 'build.json').read_text())
        for name, expected in pins['sources'].items():
            if manifest['sources'][name]['sha256'] != expected:
                raise ValueError('release source mismatch: ' + name)
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        if a.zig:
            zig = a.zig.expanduser().resolve(strict=True)
            bindir = out / 'bin'
            bindir.mkdir()
            wrapper = bindir / 'clang'
            driver = out / 'reference_driver.py'
            driver.write_bytes(Path(__file__).read_bytes())
            # Reuse this module's deliberately small argument adapter.
            wrapper.write_text('#!' + sys.executable + '\nimport runpy, os, sys\n'
                               + 'm = runpy.run_path(' + repr(str(driver)) + ')\n'
                               + 'os.execv(' + repr(str(zig)) + ', [' + repr(str(zig))
                               + ', "cc", *m["zig_arguments"](sys.argv[1:])])\n')
            wrapper.chmod(0o755)
            manifest['compiler'] = {'zig': fingerprint(zig),
                                    'version': subprocess.check_output([str(zig), 'version'], text=True).strip(),
                                    'adapter': 'zig_arguments; no ELF postprocessing'}
            manifest['compiler']['headers'] = {
                name: fingerprint(zig.parent / 'lib/include' / name)
                for name in ('stdint.h', 'stddef.h')}
        else:
            bindir = a.clang_dir.expanduser().resolve(strict=True)
            manifest['compiler'] = {'clang': fingerprint(bindir / 'clang')}
        env['PATH'] = str(bindir) + os.pathsep + env.get('PATH', '')
        manifest['compiler']['clang_version'] = subprocess.check_output([str(bindir / 'clang'), '--version'], env=env, text=True)
        import unicorn
        manifest['unicorn'] = {'version': unicorn.__version__, 'module': fingerprint(Path(unicorn.__file__))}
        save()
        ok = run('extractor', [sys.executable, '-B', 'research/ui/tools/arm_text/test_elf_text.py'])
        ok = run('gyro-build', [sys.executable, '-B', 'projects/gyro2-sup/build.py', '--out', str(out / 'gyro')]) and ok
        artifact = out / 'gyro/40GYR2.BIN'
        if artifact.exists():
            blob = artifact.read_bytes()
            manifest['gyro'] = dict(fingerprint(artifact), header=gyro_header(blob),
                                    release_equal=blob == (tree / RELEASE / 'fpSup/40GYR2.BIN').read_bytes(),
                                    release_manifest_equal=digest(blob) == pins['sha256'])
            ok = manifest['gyro']['release_equal'] and manifest['gyro']['release_manifest_equal'] and ok
        ok = run('gyro-tests', [sys.executable, '-B', '-m', 'unittest', '-v', 'test_gyr2'], tree / 'projects/gyro2-sup') and ok
        ok = run('gyro-mutation', [sys.executable, '-B', 'mutate.py', 'never writes the commit magic'], tree / 'projects/gyro2-sup') and ok
        # Retain and validate the actual unmodified C ELF, not just its extracted bytes.
        elf_dir = out / 'elf'
        elf_dir.mkdir()
        audit = ('import sys, pathlib, json, struct; '
                 'sys.path.insert(0, "fpSup/fp_usb_shell/v3"); import build_v3 as B; '
                 'p=pathlib.Path(sys.argv[1]); t=B.compile_c(p); '
                 'e=(p/"sloader.o").read_bytes(); '
                 'assert e[:7]==b"\\x7fELF\\x01\\x01\\x01"; '
                 'assert struct.unpack_from("<HH", e, 16)==(1,40); '
                 'assert t.functions["sl_boot"] & 1; '
                 '(p/"text.json").write_text(json.dumps({"functions":t.functions, '
                 '"text_bytes":len(t.code), "e_flags":struct.unpack_from("<I",e,36)[0]},indent=2))')
        ok = run('v3-elf', [sys.executable, '-B', '-c', audit, str(elf_dir)]) and ok
        ok = run('v3-build', [sys.executable, '-B', 'fpSup/fp_usb_shell/v3/build_v3.py', '--out', str(out / 'v3'), '--no-splash']) and ok
        ok = run('v3-tests', [sys.executable, '-B', '-m', 'unittest', '-v', 'v3.test_v3'], tree / 'fpSup/fp_usb_shell') and ok
        manifest['artifacts'] = {str(p.relative_to(out)): fingerprint(p)
                                 for directory in ('gyro', 'v3', 'elf')
                                 for p in (out / directory).rglob('*') if p.is_file()}
        manifest['success'] = ok
        save()
        return 0 if ok else 1
    except Exception as exc:
        manifest['error'] = str(exc)
        save()
        raise


if __name__ == '__main__':
    sys.exit(main())
