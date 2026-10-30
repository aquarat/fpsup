#!/usr/bin/env python3
"""Build ordinary fp L 3.02 native-menu development cards; never deploy.

Default: no USB worker or USB patches. --debug carries the existing reviewed
shell for evidence collection. Both install the same retained menu runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from build_adapter import build, HERE, armasm, fpl_ui_restore
import menu

SHELL = HERE.parent/'fp_usb_shell'


def payload(fp_main, fpl_main, recording=False):
    text = build(runtime=True, boot=True, recording=recording)
    block, _, _ = menu.build(fp_main, fpl_main)
    source = SHELL/'asm/fpl_ui_draw.S'
    defines = ['RELOCATABLE=1', 'CALLBACK=1']
    wrapper, symbols = armasm.assemble(source, defines), armasm.symbols(source, defines)
    if len(wrapper) > 0x800 or len(text.code) > 0x5000 or len(block) > 0x7c00:
        raise ValueError('owned wrapper/runtime/FPUI reservations exceeded')
    regions = [(0x0000, 0x24, 'descriptor/result'), (0x0400, 0x400, 'drawing state'),
               (0x1000, len(wrapper), 'drawing code'), (0x2000, 40, 'drawing vtable'),
               (0x3000, len(text.code), 'runtime code'), (0x8000, 0x400, 'runtime state'),
               (0x8400, len(block), 'FPUI')]
    if recording:
        regions += [(0x1800, 16, 'Vd veneer'), (0x2400, 0x240, 'GTAG state/source')]
    regions.sort()
    for i, (start, size, name) in enumerate(regions):
        if start & 3 or size & 3 or start+size > 0x10000 or (
                i and regions[i-1][0]+regions[i-1][1] > start):
            raise ValueError(f'owned extent overlap/alignment/bounds: {name}')
    with tempfile.TemporaryDirectory(prefix='slit-launch-') as tmp:
        path = Path(tmp)/'resident.bin'
        path.write_bytes(wrapper+text.code+block)
        defines = [f'OWNED_IMAGE="{path}"', f'WRAPPER_BYTES={len(wrapper)}',
                   f'RUNTIME_BYTES={len(text.code)}', f'BLOCK_BYTES={len(block)}',
                   f'DRAW_OBSERVE={symbols["observe"]}']
        defines += [f'{name.upper()}={text.functions[name]}' for name in ('slit_boot', 'slit_tick', 'slit_key')]
        if recording: defines += [f'SLIT_VD={text.functions["slit_vd"]}']
        code = armasm.assemble(HERE/'launch.S', defines)
        launch = armasm.symbols(HERE/'launch.S', defines)
    return code, dict(runtime_functions=text.functions, draw_symbols=symbols,
                     launch_symbols=launch, runtime_bytes=len(text.code), wrapper_bytes=len(wrapper),
                      fpui_bytes=len(block), owned_bytes=0x10000, owned_regions=regions)


def build_card(fp_main, fpl_main, out, debug=False, recording=False):
    image = fpl_ui_restore.CAMERA.verify_main(fpl_main)
    code, info = payload(fp_main, fpl_main, recording)
    if out.exists():
        raise ValueError('output directory must be new')
    out.mkdir(parents=True)
    (out/'launch.bin').write_bytes(code)
    args = [sys.executable, '-B', str(SHELL/'build_autorun.py'), '--camera', 'fp-l-3.02',
            '--fpl-shell', '--fpl-ui-boot', '--loader', '--no-four-box-bar', '--no-fast-echo',
            '--no-ep-patches', '--main', str(fpl_main), '--out', str(out/'card/AutoRun.txt'),
            '--boot-bin', f'{out}/launch.bin:0']
    if not debug: args += ['--no-shell']
    if recording: args += ['--fpl-slit-recording']
    with tempfile.TemporaryDirectory(prefix='slit-sites-') as tmp:
        for address, data in fpl_ui_restore.stock_sections(image):
            p = Path(tmp)/f'{address:08x}.bin'; p.write_bytes(data)
            args += ['--also-bin', f'{address}:{p}']
        subprocess.run(args, check=True)
    info.update(camera='fp-l-3.02', main_sha256=fpl_ui_restore.CAMERA.main_sha256,
                debug_shell=debug, camera_tested=False, recording_backend=recording,
                admission='stock draw vtable and six string words before stage2 journal'+
                          ('; empty early-Vd slot' if recording else ''),
                artifacts={str(p.relative_to(out)): dict(bytes=p.stat().st_size,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in (out/'launch.bin', out/'card/AutoRun.txt', out/'card/fpSup.BIN')})
    (out/'manifest.json').write_text(json.dumps(info, indent=2)+'\n')
    return info


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp-main', type=Path, required=True)
    p.add_argument('--fpl-main', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--debug', action='store_true')
    p.add_argument('--recording', action='store_true', help='experimental resident UHD/8-bit/24 recording backend')
    a = p.parse_args()
    print(json.dumps(build_card(a.fp_main, a.fpl_main, a.out, a.debug, a.recording), indent=2))
