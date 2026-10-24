"""Build the finite camera-side retained launcher, offline only. No live CLI."""
from pathlib import Path
import struct
import tempfile

import armasm
import fpl_retained_relocation as runtime

SOURCE = Path(__file__).resolve().parent/'asm/fpl_retained_launch.S'


def build(*, cancel=False, sleep_reason=0, admission_provider=None):
    artifact = runtime.template(cancel=cancel, sleep_reason=sleep_reason)
    template, ws, cs = artifact
    offsets = runtime.reference_offsets(ws, cs)
    if any(struct.unpack_from('<I', template, o)[0] for o in offsets):
        raise ValueError('embedded template must have zero references')
    with tempfile.TemporaryDirectory() as directory:
        binary = Path(directory)/'runtime.bin'
        binary.write_bytes(template)
        defs = [f'RL_TEMPLATE="{binary}"', f'RL_OWNER_OFF={offsets[0]}',
                f'RL_REFS_OFF={offsets[1]}']
        if admission_provider is not None:
            if (not isinstance(admission_provider, int) or admission_provider % 4 or
                    not 0x40000000 <= admission_provider < 0x80000000):
                raise ValueError('diagnostic provider must be an explicit aligned resident ARM entry')
            defs.append(f'RL_ADMISSION_PROVIDER={admission_provider:#x}')
        body, syms = armasm.assemble(SOURCE, defs), armasm.symbols(SOURCE, defs)
    if (syms['entry'] != 0 or syms['image_end'] != len(body) or
            syms['embedded_image'] % 1024 or syms['result'] % 8 or
            syms['result']+32 > syms['embedded_image'] or
            body[syms['embedded_image']:] != template):
        raise ValueError('launcher image/result/template layout mismatch')
    return body, syms, artifact


def verify_staging(original, actual, syms, artifact):
    """Only result and six embedded reference words may change in staging."""
    if len(actual) != len(original):
        raise ValueError('short launcher readback')
    masked = bytearray(actual)
    offset = syms['result']
    masked[offset:offset+32] = original[offset:offset+32]
    for offset in runtime.reference_offsets(*artifact[1:]):
        offset += syms['embedded_image']
        masked[offset:offset+4] = original[offset:offset+4]
    if masked != original:
        raise ValueError('immutable launcher bytes changed')
