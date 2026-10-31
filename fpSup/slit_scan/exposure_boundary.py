"""fp L 3.02 persistence seams and explicit non-admission. Offline only.

No installer, USB, allocation, callback registration or journal modification.
The controller is compiled independently for native-instruction tests, never
embedded in a card. Do not treat its modeled task serialization as native proof.
"""
from pathlib import Path
import struct

BASE = 0xC0000000
PROVIDER = 0xC31ACF94
VTABLE = 0xC07381A8
CALLBACK_OBJECT = 0xC31AB174
CALLBACK_VTABLE = 0xC0733A30
BLOCKERS = (
    'native property busy+0x10 silently drops reentrant restoration setters',
    'prepare imports a prior snapshot; restoring live values before it is insufficient',
    'native ordinary/forced walkers and shell save do not honor a defer/refusal result',
    'no proved common exclusion for property notifications, snapshot import/export and persistence',
)


def require_admitted():
    raise ValueError('resident exposure is not admitted: ' + '; '.join(BLOCKERS))


def audit(image):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    checks = (
        (0xC0055330, 'add', 'r1, r1, #0x10'),
        (0xC0055338, 'blx', 'r1'),
        (0xC00555CC, 'add', 'r1, r1, #0x2c'),
        (0xC00555E8, 'bl', '#0xc0055760'),
        (0xC0089CD0, 'str', 'r1, [r4, #8]'),
        (0xC008651C, 'bl', '#0xc0086cc0'),
        (0xC0086D0C, 'bl', '#0xc0014dac'),
        (0xC0086E1C, 'bl', '#0xc0014dac'),
        (0xC0086D24, 'bl', '#0xc0014dac'),
        (0xC0086E34, 'bl', '#0xc0014dac'),
        (0xC0086EC8, 'bl', '#0xc00102d0'),
        (0xC0086ECC, 'mov', 'r1, r5'),
        (0xC00B1300, 'add', 'r2, r2, sb'),
        (0xC00B13C4, 'add', 'r2, r2, #0x990'),
        (0xC009C9A4, 'str', 'r8, [ip]'),
        (0xC009C9AC, 'str', 'r8, [ip, #4]'),
        (0xC00862D4, 'bl', '#0xc0085cd8'),
        (0xC0085D74, 'bl', '#0xc0014dac'),
        (0xC0064A88, 'ldrb', 'ip, [r4, #0x10]'),
        (0xC0064A94, 'b', '#0xc0064b28'),
        (0xC0064B1C, 'bl', '#0xc0075788'),
        (0xC0064B24, 'strb', 'ip, [r4, #0x10]'),
        (0xC0023BE4, 'blx', 'r2'),
        (0xC0023BE8, 'add', 'r6, r6, #4'),
        (0xC0023EBC, 'blx', 'r2'),
        (0xC0023EC0, 'add', 'r7, r7, #4'),
        (0xC03FAC1C, 'bl', '#0xc0055320'),
        (0xC03FAC20, 'ldr', 'r1, [r4]'),
    )
    for at, mnemonic, operands in checks:
        row = list(md.disasm(image[at-BASE:at-BASE+4], at))
        if len(row) != 1 or (row[0].mnemonic, row[0].op_str) != (mnemonic, operands):
            raise ValueError(f'exposure boundary differs at {at:08x}')
    for offset, fn in ((0x10,0xC0086228),(0x28,0xC0085BB0),(0x2c,0xC0086508)):
        if struct.unpack_from('<I',image,VTABLE-BASE+offset)[0] != fn:
            raise ValueError('persistence provider vtable differs')
    return dict(provider=hex(PROVIDER), vtable=hex(VTABLE), vtable_bytes=0x90,
                admitted=False, blockers=BLOCKERS,
                instructions=[dict(address=hex(a), mnemonic=m, operands=o) for a,m,o in checks])
