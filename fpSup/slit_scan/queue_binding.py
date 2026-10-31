"""Bounded official-image checks for FPLS v2's native sequence measurement.

No USB or installation. These are instruction/dataflow facts, not a claim that
the two hardware IRQs have a fixed phase or that lookup fallback is identity.
"""
import hashlib
import struct

BASE = 0xC0000000
COUNTER_OWNER = 0xC343B6C4
COUNTER = COUNTER_OWNER+0x10
GUARD = COUNTER_OWNER+0x194
POOL_VTABLE = 0xC07333D4
POOL_SEQUENCE = 0x4004
WINDOWS = (
    (0xC031EBF8,0x60),       # buffer-key -> next counter, ten-entry ring
    (0xC031EC58,0x70),       # key lookup, greatest value, current-counter fallback
    (0xC0053CB0,0x28),       # DataPool pair getter: pool+4, pool+4004
    (0xC038C8BC,0x64),       # buffer key -> native lookup -> pool -> notify
    (0xC03193A0,0x30),       # counter advance, separate native interrupt
    (0xC0325798,0x38),       # native counter dispatch installs in second IRQ
    (0xC0075FE8,0x20),       # stock ordinary-shutdown menu save callback
    (0xC0076058,0x14),       # ordinary-list registration, not forced
    (0xC0320D00,0x10),       # first producer: capture descriptor+38
    (0xC0320DB0,0x20),       # subsequent producer retains input r1 in r4
    (0xC03210E8,0x10),       # subsequent producer: unchanged buffer argument
    (0xC03208B4,0x08),       # same first key supplied to native buffer programming
    (0xC0320E6C,0x08),       # same subsequent key supplied to buffer programming
    (0xC0053028,0xC8),       # native consumer caller's saved record and return PC
    (0xC0053618,0x70),       # synchronous Subject walk, saved caller return PC
    (0xC0011568,0x3C),       # timer/IRQ MMIO publication
    (0xC0029120,0xD0),       # native coherent seconds/counter, pending rollover
)


def audit(image):
    import capstone
    md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM)
    def ins(at,mnemonic,operands):
        row=list(md.disasm(image[at-BASE:at-BASE+4],at))
        if len(row)!=1 or (row[0].mnemonic,row[0].op_str)!=(mnemonic,operands):
            raise ValueError(f'native queue/save seam differs at {at:08x}')
    for at,mnemonic,operands in (
        (0xC031EC10,'str','r4, [r3, r2]'),
        (0xC031EC1C,'ldr','r2, [ip, #0x10]'),
        (0xC031EC24,'add','r2, r2, #1'),
        (0xC031EC28,'str','r2, [r5, r3]'),
        (0xC031EC3C,'cmp','r2, #0xa'),
        (0xC031EC78,'cmp','r4, r5'),
        (0xC031EC84,'ldr','r5, [r6, r3, lsl #2]'),
        (0xC031ECB0,'ldr','r2, [ip, #0x10]'),
        (0xC0053CC0,'movw','r3, #0x4004'),
        (0xC038C8E0,'ldr','r1, [r5, #0x4c]'),
        (0xC038C8E4,'bl','#0xc0310c58'),
        (0xC038C8EC,'str','r0, [r2]'),
        (0xC038C918,'bl','#0xc0053028'),
        (0xC03193B8,'add','r1, r0, #1'),
        (0xC03193C0,'bl','#0xc031e2e8'),
        (0xC0320D00,'ldr','r1, [r6, #0x38]'),
        (0xC0320D08,'bl','#0xc031ebf8'),
        (0xC0320DC0,'mov','r4, r1'),
        (0xC03210E8,'mov','r1, r4'),
        (0xC03210F0,'bl','#0xc031ebf8'),
        (0xC03208B4,'ldr','r0, [r6, #0x38]'),
        (0xC03208B8,'blx','#0xc062e4c0'),
        (0xC0320E6C,'mov','r0, r4'),
        (0xC0320E70,'blx','#0xc062e4c0'),
        (0xC0053028,'push','{r4, r5, r6, r7, sl, fp, lr}'),
        (0xC005302C,'sub','sp, sp, #0xc'),
        (0xC00530C4,'bl','#0xc0053618'),
        (0xC0053618,'push','{r4, r5, r6, r7, sl, lr}'),
        (0xC005365C,'blx','r2'),
        (0xC0011578,'movt','r2, #0x2d81'),
        (0xC0011598,'movw','r2, #0x80'),
        (0xC001159C,'movt','r2, #0x2d81'),
        (0xC0029178,'add','r0, r5, #1'),
        (0xC00291BC,'cmp','r0, r1'),
        (0xC00291C8,'bl','#0xc0029120'),
        (0xC0075FF8,'bl','#0xc0055588'),
        (0xC0076000,'bl','#0xc0055320'),
        (0xC0076060,'mov','r2, #0'),
        (0xC0076064,'bl','#0xc0024038'),
    ): ins(at,mnemonic,operands)
    if struct.unpack_from('<I',image,POOL_VTABLE+0x1c-BASE)[0]!=0xC0053CB0:
        raise ValueError('native DataPool pair vtable differs')
    return dict(windows=[dict(address=hex(at),bytes=n,
        sha256=hashlib.sha256(image[at-BASE:at-BASE+n]).hexdigest(),
        instructions=[f'{i.address:08x}: {i.mnemonic} {i.op_str}'
                      for i in md.disasm(image[at-BASE:at-BASE+n],at)]) for at,n in WINDOWS],
        counter=hex(COUNTER),guard=hex(GUARD),pool_sequence=POOL_SEQUENCE,
        capture_association=False,exposure_restore_boundary_proved=False)


def lookup_snapshot(key, keys, values, current, cursor):
    """Exact native unsigned lookup semantics, at the snapshot's time only.

    A native value is a counter label, not an independently observed generation.
    In particular max(value) is not the newest slot across counter wrap.
    """
    if (len(keys) != 10 or len(values) != 10 or not 0 <= cursor < 10 or
            any(not isinstance(v, int) or not 0 <= v <= 0xffffffff
                for v in (key, current, *keys, *values))):
        raise ValueError('invalid native queue snapshot')
    matched = [i for i, k in enumerate(keys) if k == key]
    greatest = max((values[i] for i in matched), default=0)
    return dict(key=key, matching_slots=matched,
                selected_slots=[i for i in matched if values[i] == greatest] if greatest else [],
                status='hit' if greatest else 'zero-value-fallback' if matched else 'miss-fallback',
                result=greatest or current, cursor=cursor,
                key_generation='unproved; native values are counter+1, not unique generations',
                native_lookup_at_consumer='unobserved; this is recomputed at notify')


def audit_producer(image):
    """Exact displaced replay and finite native leaves for the owned trace.

    Programming is conditional on channel flags and precedes queue publication.
    Neither that MMIO store nor this audit identifies a sensor phase.
    """
    import capstone
    checks=((0xC031EBF8,0x60,False),(0xC031EC58,0x70,False),
            (0xC0310C58,0x24,False),(0xC062E4C0,0xAC,True),
            (0xC062D430,0x30,True),(0xC062D8D8,0x1C,True),
            (0xC0320E58,0x20,False),(0xC037F990,0x50,False),
            (0xC031966C,0x24,False),(0xC0121DE8,0x18,True))
    rows=[]
    for at,n,thumb in checks:
        md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB if thumb else capstone.CS_MODE_ARM)
        ins=list(md.disasm(image[at-BASE:at-BASE+n],at))
        if at in (0xC031EBF8,0xC031EC58):
            push='{r4, r5}' if at==0xC031EBF8 else '{r4, r5, r6}'
            if [(i.mnemonic,i.op_str) for i in ins[:2]]!=[('push',push),('mov','ip, r0')]:
                raise ValueError('producer displaced prologue differs')
            if any(i.mnemonic in ('bl','blx','svc','cpsie') for i in ins):
                raise ValueError('native leaf is not a finite noncalling masked continuation')
        rows.append(dict(address=hex(at),bytes=n,thumb=thumb,
            sha256=hashlib.sha256(image[at-BASE:at-BASE+n]).hexdigest(),
            instructions=[f'{i.address:08x}: {i.mnemonic} {i.op_str}' for i in ins]))
    if struct.unpack_from('<I',image,0xC062E4E8-BASE)[0]!=0x1378F8C4:
        raise ValueError('native DMA destination store differs')
    return dict(windows=rows,publication='native software key/value ring',
        programming='conditional DMA destination register 30182380, then software alternating buffer slots',
        sensor_phase_association=False,
        context='producer CPSR/current TCB/LR retained per publication; lookup requires exact SVC caller stack')
