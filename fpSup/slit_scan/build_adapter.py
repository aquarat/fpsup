"""Build the fp L page-only shared applier. Offline; no card/USB operations."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent/'uishare'
sys.path.insert(0, str(HERE.parent/'fp_usb_shell'))
import armasm
import fpl_ui_restore


def embedded(name, code, pointer=False):
    if len(code) % 4:
        raise ValueError('embedded ARM code must be word aligned')
    words = ','.join(hex(int.from_bytes(code[i:i+4], 'little')) for i in range(0, len(code), 4))
    signature = (f'const uint32_t *{name}(void)' if pointer else
                 f'uint32_t {name}(uint32_t *p __attribute__((unused)), uint32_t *b __attribute__((unused)))')
    prefix = 'adr r0, 1f\\n bx lr\\n 1: ' if pointer else ''
    return f'static __attribute__((naked,noinline)) {signature} {{ __asm__("{prefix}.word {words}"); }}\n'


def build(provider=None, *, runtime=False):
    layer_source = SHARED/'ui_strings.S'
    layer = armasm.assemble(layer_source)
    symbols = armasm.symbols(layer_source)
    guard = armasm.assemble(HERE.parent/'fp_usb_shell/asm/fpl_ui_guard.S', ['RUNTIME_ARGS=1'])
    restore = fpl_ui_restore.restore_code()
    if len(layer) > 0x800:
        raise ValueError('layer exceeds guarded entry reservation')
    with tempfile.TemporaryDirectory(prefix='slit-adapter-') as tmp:
        tree = Path(tmp)
        # Same unity strategy as uishare/build_section.py. ARM intra-text calls
        # use the existing armasm resolver, rather than a new linker.
        public = re.compile(r'^((?:const\s+)?(?:struct\s+\w+|u?int\w*_t|void|uintptr_t)'
                            r'\s*\**\s*(?:uis|uia)_\w+\s*\()', re.M)
        for name in ('ui_pool.h', 'ui_apply.h', 'ui_apply.c'):
            (tree/name).write_text(public.sub(r'static \1', (SHARED/name).read_text()))
        source = '#include <stdint.h>\n#define UIA_FPL_302 1\n'
        for name, value in dict(FPL_LAYER_BYTES=len(layer), FPL_RESTORE_BYTES=len(restore),
                                FPL_RESOLVE=symbols['resolve'], FPL_OWNS=symbols['owns'],
                                FPL_REMAIN=symbols['remain']).items():
            source += f'#define {name} {value}u\n'
        source += embedded('fpl_layer_image', layer, True)
        source += embedded('fpl_restore_image', restore, True)
        source += embedded('fpl_guard', guard)
        source += provider if provider is not None else (HERE/'fpl_pool.c').read_text()
        source += '\n#include "ui_apply.c"\n'
        if runtime:
            (tree/'controller.h').write_text((HERE/'controller.h').read_text())
            controller = (HERE/'controller.c').read_text()
            # The key callback remains an exported, runtime-addressed entry.
            for signature in ('uint32_t slit_init(', 'uint32_t slit_pump(', 'void slit_disable('):
                controller = controller.replace(signature, 'static '+signature)
                header = (tree/'controller.h').read_text().replace(signature, 'static '+signature)
                (tree/'controller.h').write_text(header)
            source += '\n'+controller+'\n'+(HERE/'runtime.c').read_text()
        source += 'uint32_t slit_apply(uintptr_t b, uint32_t n, struct uia_outcome *o) { return uia_apply(b,n,o); }\n'
        (tree/'unity.c').write_text(source)
        assembly = tree/'adapter.S'
        result = subprocess.run([shutil.which('clang') or 'clang', '-target', 'armv7-none-eabi',
            '-marm', '-mfloat-abi=soft', '-mfpu=none', '-fno-vectorize', '-fno-slp-vectorize',
            '-std=c11', '-O2', '-ffreestanding', '-fno-builtin', '-fno-jump-tables', '-fno-addrsig',
            '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
            '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-undefined-internal',
            '-Wno-unused-command-line-argument',
            '-g0', '-I', str(tree), '-S', str(tree/'unity.c'), '-o', str(assembly)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        _, _, sections = armasm._parse(armasm._compile(assembly))
        for name, (_, section) in sections.items():
            # The usual unused EH index may be discarded; code/data may not.
            if section[2] & 2 and section[5] and name not in ('.text', '.ARM.exidx'):
                raise ValueError(f'unsupported allocated section {name}')
        code, functions = armasm.assemble(assembly), armasm.symbols(assembly)
        return SimpleNamespace(code=code, functions=functions)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--runtime', action='store_true', help='include experimental draw-task coordinator/controller')
    args = p.parse_args()
    if args.out.exists(): p.error('output directory must be new')
    text = build(runtime=args.runtime)
    args.out.mkdir()
    (args.out/'adapter.bin').write_bytes(text.code)
    (args.out/'manifest.json').write_text(json.dumps(dict(bytes=len(text.code),
        sha256=hashlib.sha256(text.code).hexdigest(), functions=text.functions,
        camera_tested=False, controller_owner_included=args.runtime), indent=2)+'\n')
