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
import struct
import sys
import tempfile

from build_adapter import build, HERE, armasm, fpl_ui_restore
import menu

SHELL = HERE.parent/'fp_usb_shell'

def pack_block(data):
    """Private launcher LZ: literal (0..127)+1, match (128..255)-125 + u16 distance.

    No shared format/loader change. The decoder bounds both source and output.
    Only this opt-in launcher's menu image is encoded; owned FPUI is identical.
    """
    out=bytearray(); pending=bytearray(); positions={}; i=0
    def flush():
        if pending:out.append(len(pending)-1);out.extend(pending);pending.clear()
    while i<len(data):
        key=data[i:i+4]; best=0; distance=0
        for at in positions.get(key, [])[-16:]:
            if i-at>65535:continue
            n=4
            while n<130 and i+n<len(data) and data[at+n]==data[i+n]:n+=1
            if n>best:best=n;distance=i-at
        n=best if best>=4 else 1
        if best>=4:
            flush();out.append(128+best-3);out.extend(struct.pack('<H',distance))
        else:
            pending.append(data[i])
            if len(pending)==128:flush()
        for at in range(i,i+n):
            k=data[at:at+4]
            if len(k)==4:positions.setdefault(k,[]).append(at)
        i+=n
    flush()
    return bytes(out)


def payload(fp_main, fpl_main, recording=False, queue_observation=False, lookup_observation=False,
            producer_observation=False):
    if producer_observation and not lookup_observation:
        raise ValueError('producer observation requires lookup observation')
    if queue_observation:
        import queue_binding
        queue_binding.audit(fpl_ui_restore.CAMERA.verify_main(fpl_main))
        if producer_observation:
            queue_binding.audit_producer(fpl_ui_restore.CAMERA.verify_main(fpl_main))
    text = build(runtime=True, boot=True, recording=recording, queue_observation=queue_observation,
                 lookup_observation=lookup_observation, producer_observation=producer_observation)
    block, _, _ = menu.build(fp_main, fpl_main)
    source = SHELL/'asm/fpl_ui_draw.S'
    defines = ['RELOCATABLE=1', 'CALLBACK=1']
    wrapper, symbols = armasm.assemble(source, defines), armasm.symbols(source, defines)
    if len(wrapper) > 0x800 or len(text.code) > 0x5000 or len(block) > 0x7c00:
        raise ValueError('owned wrapper/runtime/FPUI reservations exceeded')
    regions = [(0x0000, 0x2c if producer_observation else 0x24, 'descriptor/result'), (0x0400, 0x400, 'drawing state'),
               (0x1000, len(wrapper), 'drawing code'), (0x2000, 40, 'drawing vtable'),
               (0x3000, len(text.code), 'runtime code'), (0x8000, 0x400, 'runtime state'),
               (0x8400, len(block), 'FPUI')]
    if recording:
        regions += [(0x1800, 16, 'Vd veneer'),
                     (0x2400, 0x480 if producer_observation else 0x3d0 if lookup_observation else 0x350 if queue_observation else 0x240, 'GTAG state/source')]
    regions.sort()
    for i, (start, size, name) in enumerate(regions):
        if start & 3 or size & 3 or start+size > 0x10000 or (
                i and regions[i-1][0]+regions[i-1][1] > start):
            raise ValueError(f'owned extent overlap/alignment/bounds: {name}')
    with tempfile.TemporaryDirectory(prefix='slit-launch-') as tmp:
        path = Path(tmp)/'resident.bin'
        extra=b''; packed=block
        if producer_observation:
            from build_producer_trace import build as trace_build
            trace=trace_build(); extra=trace.code; packed=pack_block(block)
        path.write_bytes(wrapper+text.code+packed+bytes((-len(packed))%4)+extra)
        defines = [f'OWNED_IMAGE="{path}"', f'WRAPPER_BYTES={len(wrapper)}',
                   f'RUNTIME_BYTES={len(text.code)}', f'BLOCK_BYTES={len(block)}',
                   f'DRAW_OBSERVE={symbols["observe"]}']
        defines += [f'{name.upper()}={text.functions[name]}' for name in ('slit_boot', 'slit_tick', 'slit_key')]
        if recording: defines += [f'SLIT_VD={text.functions["slit_vd"]}']
        if producer_observation:
            defines += ['PRODUCER_TRACE=1',f'PACKED_BLOCK_BYTES={len(packed)}',
                        f'TRACE_BYTES={len(extra)}']
            defines += [f'TRACE_{name.upper()}={trace.functions[name]}'
                        for name in ('pt_writer','pt_lookup','pt_export','guard')]
        code = armasm.assemble(HERE/'launch.S', defines)
        launch = armasm.symbols(HERE/'launch.S', defines)
    info=dict(runtime_functions=text.functions, draw_symbols=symbols,
                      launch_symbols=launch, runtime_bytes=len(text.code), wrapper_bytes=len(wrapper),
                       fpui_bytes=len(block), owned_bytes=0x10000, owned_regions=regions)
    if producer_observation:
        info.update(trace_functions=trace.functions,trace_bytes=len(extra),packed_fpui_bytes=len(packed),
                    total_owned_bytes=0x20000,trace_regions=[(0,20,'descriptor/guard'),
                    (0x400,0x400,'admission parameters'),(0x1000,len(extra),'trace/guard code'),
                    (0x4000,16000,'500 saved task frames'),(0x8000,20012,'bounded trace state')])
        for at,n,name in info['trace_regions']:
            if at+n>0x10000:raise ValueError('trace owned reservation exceeded: '+name)
        for (at,n,_),(next_at,_,_) in zip(info['trace_regions'],info['trace_regions'][1:]):
            if at+n>next_at:raise ValueError('trace owned regions overlap')
    return code,info


def build_card(fp_main, fpl_main, out, debug=False, recording=False, queue_observation=False, exposure=False, lookup_observation=False,
               producer_observation=False):
    if exposure:
        from exposure_boundary import require_admitted
        require_admitted()  # before reading images, creating output or packaging
    image = fpl_ui_restore.CAMERA.verify_main(fpl_main)
    code, info = payload(fp_main, fpl_main, recording, queue_observation, lookup_observation, producer_observation)
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
        sections=fpl_ui_restore.stock_sections(image)
        if producer_observation:
            sections += [(at,image[at-0xC0000000:at-0xC0000000+4])
                         for at in (0xC031EBF8,0xC031EBFC,0xC031EC58,0xC031EC5C)]
        for address, data in sections:
            p = Path(tmp)/f'{address:08x}.bin'; p.write_bytes(data)
            args += ['--also-bin', f'{address}:{p}']
        subprocess.run(args, check=True)
    info.update(camera='fp-l-3.02', main_sha256=fpl_ui_restore.CAMERA.main_sha256,
                debug_shell=debug, camera_tested=False, recording_backend=recording,
                queue_observation=queue_observation,
                lookup_observation=lookup_observation,
                producer_observation=producer_observation,
                 admission='stock draw vtable and six string words before stage2 journal'+
                          ('; empty early-Vd slot' if recording else '')+
                          ('; four stock producer/lookup words; single CPU and whole-leaf saved-PC exclusion' if producer_observation else ''),
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
    p.add_argument('--queue-observation', action='store_true', help='FPLS v2 native sequence/Vd measurement; no metadata correction')
    p.add_argument('--lookup-observation', action='store_true', help='FPLS v3 exact consumer key, notify-time queue snapshot and coherent notify clock; requires --queue-observation')
    p.add_argument('--producer-observation', action='store_true', help='experimental owned native queue/lookup trace; requires --lookup-observation')
    p.add_argument('--exposure', action='store_true', help='reserved; refuses until native persistence/quiescence is qualified')
    a = p.parse_args()
    print(json.dumps(build_card(a.fp_main, a.fpl_main, a.out, a.debug, a.recording, a.queue_observation, a.exposure, a.lookup_observation, a.producer_observation), indent=2))
