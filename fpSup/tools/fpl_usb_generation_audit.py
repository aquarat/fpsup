#!/usr/bin/env python3
"""Offline generation-boundary observer; never installs firmware hooks."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import fpl_usb_wait_status_audit as wait
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                              UC_ARM_REG_R4, UC_ARM_REG_R7, UC_ARM_REG_SP,
                              UC_ARM_REG_LR, UC_ARM_REG_PC)

# fp L addresses. Both image fingerprints are checked before applying the
# bounded +3780 translation. These are observer locations, not patch proposals.
GLOBAL = {
    0xC01DF718: 'init-entry', 0xC01E3078: 'reset-entry',
    0xC01DFC98: 'stop-entry', 0xC01DFD68: 'alternate-stop-entry',
    0xC01E3778: 'teardown-entry', 0xC01E3D50: 'device-reset-branch',
    0xC01E3D3E: 'device-bit1-branch',
    0xC01E0B56: 'configuration-zero', 0xC01E0B8E: 'configuration-nonzero',
}
SITES = {
    0xC01DF8C2: 'init-buffer-pointer', 0xC01DF92C: 'init-event-pointer',
    0xC01DF94C: 'init-driver-buffer', 0xC01DF97A: 'init-DMA-TRB-pointer',
    0xC01DF98E: 'init-CPU-TRB-pointer', 0xC01DF9C2: 'init-aux-DMA-pointer',
    0xC01DF9D6: 'init-aux-CPU-pointer',
    0xC01E3094: 'reset-first-store', 0xC01E30B0: 'reset-configured-zero',
    0xC01E3110: 'reset-enabled-mask', 0xC01E314E: 'reset-memset-state',
    0xC01E3164: 'reset-memset-control-TRB',
    0xC01E317C: 'reset-memset-endpoint-status',
    0xC01E3188: 'reset-memset-resources-80',
    0xC01E3216: 'reset-type', 0xC01E322E: 'reset-direction',
    0xC01DFC80: 'run-DCTL', 0xC01DFCC8: 'stop-DCTL',
    0xC01DFD22: 'stop-config-flags', 0xC01DFD8C: 'alternate-stop-DCTL',
    0xC01DFBD2: 'platform-first-store',
    0xC01E3674: 'end-load-current-resource', 0xC01E368E: 'end-resource-80',
    0xC01E360E: 'end-EP0-resource-80', 0xC01E36A4: 'end-status2',
    0xC01E36B4: 'end-busy-zero', 0xC01E3752: 'end-wake-completion-bit',
    0xC01E3458: 'start-load-current-DMA-pointer',
    0xC01E346A: 'start-status1', 0xC01E331A: 'command-first-parameter',
    0xC01E3380: 'command-CMDACT', 0xC01E33B2: 'command-publish-resource',
    0xC01E3512: 'start-error-unwind-status0', 0xC01E3536: 'start-busy1',
    0xC01E0B60: 'configuration-zero-marker', 0xC01E0B64: 'configuration-zero-store',
    0xC01E0B9A: 'configuration-snapshot-mask',
    0xC01E0BA8: 'configuration-disable-DALEPENA',
    0xC01E0C54: 'configuration-publish-value', 0xC01E0C7A: 'configuration-callback',
}


class Ledger:
    """Host-only evidence ledger. Never writes emulated firmware state."""
    def __init__(self, delta=0, omit=()):
        self.delta, self.omit = delta, set(omit)
        self.epoch, self.serial = 0, 0
        self.active, self.tickets, self.events = {}, {}, []
        self.context = ('external', None)
        self.admit(1)
        self.admit(2)

    def admit(self, ep):
        self.serial += 1
        ticket = {'id': self.serial, 'ep': ep, 'epoch': self.epoch, 'state': 'active'}
        self.active[ep] = ticket['id']
        self.tickets[ticket['id']] = ticket
        return ticket['id']

    def close(self, reason, ep=None):
        if ep is None:
            self.epoch += 1
        for endpoint, tid in list(self.active.items()):
            if ep is None or ep == endpoint:
                self.tickets[tid]['state'] = 'invalid'
                del self.active[endpoint]

    def code(self, u, pc, size, _):
        site = pc - self.delta
        name = GLOBAL.get(site) or SITES.get(site)
        if site == 0xC01DFB98 and u.reg_read(UC_ARM_REG_R0) in (0, 1, 3):
            name = 'platform-destructive-entry'
        if site == 0xC01E35C8:
            ep = u.reg_read(UC_ARM_REG_R0)
            kind, tid = self.context
            current = self.active.get(ep)
            # The context is a synthetic caller ticket, NOT inferred from PC/LR.
            own = (kind == 'cleanup' and tid == current and tid is not None
                   and self.tickets[tid]['state'] == 'complete')
            name = 'own-completed-retirement' if own else 'endpoint-cancel-entry'
            if site not in self.omit:
                if own:
                    self.tickets[tid]['state'] = 'retired'
                    del self.active[ep]
                else:
                    self.close(name, ep)
        elif (site in GLOBAL or name == 'platform-destructive-entry') and site not in self.omit:
            self.close(name)
        if name:
            d = 0xC31E1610 + (0x1C00 if self.delta else 0)
            read = lambda a: struct.unpack('<I', u.mem_read(a, 4))[0]
            self.events.append({'pc': hex(pc), 'event': name, 'epoch': self.epoch,
                                'active': dict(self.active),
                                'configured_before': read(d+0x75C) & 255,
                                'ep1_resource_before': hex(read(d+0x828)),
                                'ep1_cpu_pointer_before': hex(read(d+0x58)),
                                'ep1_dma_pointer_before': hex(read(d+0x2C))})

    def attach(self, u):
        u.hook_add(UC_HOOK_CODE, self.code)


def observed_wait(image, profile, omit=(), **kwargs):
    """Reuse unchanged wait harness with an additional read-only code observer."""
    ledger = Ledger(wait.PROFILES[profile][3], omit)
    original = wait.Uc
    def factory(*args):
        u = original(*args)
        ledger.attach(u)
        return u
    wait.Uc = factory
    try:
        result = wait.run(image, profile, **kwargs)
    finally:
        wait.Uc = original
    return result, ledger


class Machine:
    """Synthetic environment, separate from the read-only Ledger observer."""
    def __init__(self, image, profile, nested=False, omit=()):
        self.delta = wait.PROFILES[profile][3]
        self.drv = 0xC31E1610 + wait.PROFILES[profile][4]
        self.profile, self.nested, self.time = profile, nested, 0
        self.u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for base, size in ((wait.BASE, 0x4000000), (0x21000000, 0x10000),
                           (0x30000000, 0x100000), (0x43000000, 0x2000000)):
            self.u.mem_map(base, size)
        self.u.mem_write(wait.BASE, image)
        self.ledger = Ledger(self.delta, omit)
        self.ledger.attach(self.u)
        self.writes, self.calls, self.injections = [], [], []
        self.inject = None
        self.trb, self.stack, self.stop = 0xC3F00000, 0xC3FE0000, 0xC3FF0000
        d = self.drv
        self.put(d, 0x1234)
        self.put(d + 12, 0x1235)
        self.put(d + 0x14, self.trb + 0x2000)
        for ep in range(7):
            self.put(d + 0x54 + ep*4, self.trb + ep*0x100)
            self.put(d + 0x28 + ep*4, 0x03F00000 + ep*0x100)
            for off, value in ((0, 1), (4, int(ep != 1)), (8, ep), (12, 1)):
                self.put(d + 0x678 + ep*16 + off, value)
            self.put(self.trb + ep*0x100 + 12, 1)
        for ep in range(14):
            self.put(d + 0x820 + ep*4, 7)
        for i in range(4):
            self.put(d + 0x44 + i*4, self.trb + 0x1000 + i*0x100)
        self.put(d + 0x75C, 1)
        self.put(d + 0x77C, 0x24)
        self.put(d + 0x674, 0x40000)
        self.put(d + 0x764, 1)
        self.put(d + 0x7F8, 1)
        self.put(0x2100C704, 0x80000000)
        self.put(0x2100C720, 0x24)
        self.put(0x2100C70C, 0x100000 if nested else 0)
        self.put(0x300B0000, 0x1C)
        self.global_base = 0xC2F24DF8 if profile == 'fpl' else 0xC2F165B8
        for off in (12, 16):
            self.put(self.global_base + off, 1)  # existing driver tasks
        self.put(self.global_base + 20, self.trb + 0x3000)
        self.put(0xC3032A8F if profile == 'fpl' else 0xC3032A93, 0)
        self.u.hook_add(UC_HOOK_CODE, self.hook)
        self.u.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def put(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def get(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def ret(self, value=0):
        self.u.reg_write(UC_ARM_REG_R0, value & 0xffffffff)
        self.u.reg_write(UC_ARM_REG_PC, self.u.reg_read(UC_ARM_REG_LR))

    def write(self, u, access, address, size, value, _):
        # Actual emulated stores, excluding stack. Stub memset writes are logged
        # separately at their call site; Unicorn mem_write is not a CPU store.
        if (self.drv-0x10 <= address < self.drv+0x900 or
                0x21000000 <= address < 0x21010000 or
                self.trb <= address < self.trb+0x4000):
            self.writes.append({'pc': hex(u.reg_read(UC_ARM_REG_PC)),
                                'address': hex(address), 'size': size, 'value': hex(value),
                                'epoch': self.ledger.epoch})

    def hook(self, u, pc, size, _):
        s = pc - self.delta
        if self.inject:
            self.inject(self, s)
        if pc == self.stop:
            u.emu_stop()
        elif pc in (0xC0015058, 0xC001510C):
            r = [u.reg_read(reg) for reg in wait.REGS]
            raw = (bytes([r[1] & 255])*r[2] if pc == 0xC0015058
                   else bytes(u.mem_read(r[1], r[2])))
            self.calls.append({'pc': hex(u.reg_read(UC_ARM_REG_LR) & ~1),
                               'stub': 'memset' if pc == 0xC0015058 else 'memcpy',
                               'destination': hex(r[0]), 'length': r[2], 'value': r[1]})
            u.mem_write(r[0], raw)
            self.ret(r[0])
        elif pc == 0xC0016B30:
            self.time += 101
            ptr = u.reg_read(UC_ARM_REG_R0)
            self.put(ptr, 0)
            self.put(ptr+4, self.time)
            self.ret()
        elif pc in (0xC00169C8, 0xC0016B9C, 0xC0016A7C,
                    0xC000FE08, 0xC000FAD8, 0xC000FCA0):
            self.calls.append({'stub': hex(pc), 'r0': u.reg_read(UC_ARM_REG_R0),
                               'r1': u.reg_read(UC_ARM_REG_R1)})
            self.ret()
        elif s in (0xC01F570C, 0xC01F555C, 0xC01F53D0,
                    0xC01DF9F0, 0xC01E14D8, 0xC01E3818,
                    0xC01E26A0, 0xC01E2B28):
            self.calls.append({'stub': hex(pc), 'r0': u.reg_read(UC_ARM_REG_R0)})
            self.ret()
        elif s == 0xC01E338C:
            physical = u.reg_read(UC_ARM_REG_R4)
            command = u.reg_read(UC_ARM_REG_R7)
            # Hardware response: command6 stays busy only in nested scenario;
            # nested command8 completes, permitting teardown to return.
            value = 0x400 if self.nested and command == 6 else 7 << 16
            self.put(0x2100C80C + physical*16, value)

    def run(self, entry, *args):
        u = self.u
        u.reg_write(UC_ARM_REG_SP, self.stack)
        u.reg_write(UC_ARM_REG_LR, self.stop)
        for reg, value in zip(wait.REGS, args):
            u.reg_write(reg, value)
        u.emu_start((entry+self.delta) | 1, self.stop, count=200000)
        assert u.reg_read(UC_ARM_REG_PC) == self.stop, 'instruction budget exhausted'
        assert u.reg_read(UC_ARM_REG_SP) == self.stack, 'unbalanced stack'
        return wait.signed(u.reg_read(UC_ARM_REG_R0))

    def export(self):
        return {'events': self.ledger.events, 'tickets': self.ledger.tickets,
                'writes': self.writes, 'stub_calls': self.calls,
                'synthetic_injections': self.injections}


def names(ledger):
    return [e['event'] for e in ledger.events]


def audit(image, profile):
    results = {}
    for name, kw in (
            ('normal-completion', {}),
            ('reset-plus-completion', {'flags': 0x10040000, 'device': 2}),
            ('cancel-clear', {'pre_end': True}),
            ('marker-without-history', {'flags': 0, 'syscall': -50, 'marker': 1}),
            ('masked-minus4', {'flags': 0x10000000, 'device': 1, 'marker': 1})):
        result, ledger = observed_wait(image, profile, **kw)
        if name == 'normal-completion':
            assert ledger.tickets[1]['state'] == 'active' and result['status'] == 0
        elif name == 'marker-without-history':
            # A marker set before observation cannot reconstruct past closes.
            assert ledger.tickets[1]['state'] == 'active' and result['status'] == -1
        else:
            assert ledger.tickets[1]['state'] == 'invalid'
        results[name] = {'wait': result, 'events': ledger.events,
                         'tickets': ledger.tickets}

    entries = {'end': (0xC01E35C8, 1), 'reset': (0xC01E3078,),
               'stop': (0xC01DFC98,), 'alternate-stop': (0xC01DFD68,),
               'platform-stop': (0xC01DFB98, 1), 'init': (0xC01DF718,),
               'start': (0xC01E3400, 2), 'nested-start': (0xC01E3400, 2)}
    for name, args in entries.items():
        m = Machine(image, profile, nested=name == 'nested-start')
        result = m.run(*args)
        n = names(m.ledger)
        if name == 'start':
            assert result == 0 and m.ledger.tickets[1]['state'] == 'active'
            assert m.get(m.drv+0x828) == 7
        else:
            assert m.ledger.tickets[1]['state'] == 'invalid', (name, n)
        if name == 'init':
            assert n.index('init-DMA-TRB-pointer') < n.index('reset-entry')
            assert m.get(m.drv+0x58) == m.drv-0xC0000000+0x40000000+0xC0
        if name == 'end':
            assert m.ledger.tickets[2]['state'] == 'active'
        if name == 'nested-start':
            assert result == -4
            assert n.index('command-CMDACT') < n.index('teardown-entry')
            assert n.index('teardown-entry') < n.index('start-error-unwind-status0')
            assert m.get(m.drv+0x704) == 0
        results[name] = {'return': result, **m.export()}

    m = Machine(image, profile)
    pointer = m.get(m.drv+0x58)
    m.run(0xC01E35C8, 1)
    assert m.get(m.drv+0x828) == 0x80
    second = m.ledger.admit(1)  # synthetic admission; no proven stock reopen
    m.run(0xC01E3400, 2)
    assert m.get(m.drv+0x828) == 7 and m.get(m.drv+0x58) == pointer
    assert m.ledger.tickets[second]['epoch'] == m.ledger.tickets[1]['epoch']
    results['same-pointer-resource-reuse'] = m.export()

    m = Machine(image, profile)
    m.run(0xC01DF718)
    first = m.get(m.drv+0x58)
    m.run(0xC01DF718)
    assert m.get(m.drv+0x58) == first
    assert names(m.ledger).count('init-entry') == 2
    results['repeated-init-same-pointer'] = m.export()

    for value in (0, 1):
        m = Machine(image, profile)
        setup = m.trb + 0x4000
        m.put(setup, 9 << 8 | value << 16)  # USB request9, wValue
        m.put(setup+4, 0)
        m.run(0xC01E0AE0, setup, 0)
        n = names(m.ledger)
        assert m.get(m.drv+0x75C) & 255 == value
        assert m.ledger.tickets[1]['state'] == 'invalid'
        if value:
            assert n.index('configuration-disable-DALEPENA') < n.index('endpoint-cancel-entry')
            assert n.index('endpoint-cancel-entry') < n.index('configuration-publish-value')
            disable = next(e for e in m.ledger.events
                           if e['event'] == 'configuration-disable-DALEPENA')
            assert disable['configured_before'] == 1
        results[f'configuration-{value}'] = m.export()

    # Entry observer versus already-loaded resource: inject a new submission
    # immediately before old EndTransfer invalidates the resource slot.
    m = Machine(image, profile)
    def end_race(machine, s):
        if s != 0xC01E368E:
            return
        machine.inject = None
        new = machine.ledger.admit(1)  # deliberately violates closed admission
        machine.put(machine.drv+0x828, 9)
        machine.injections.append({'pc': hex(s+machine.delta), 'new_ticket': new,
                                   'new_resource': 9, 'meaning': 'synthetic admission during close'})
    m.inject = end_race
    m.run(0xC01E35C8, 1)
    assert m.get(m.drv+0x828) == 0x80
    assert m.ledger.tickets[3]['state'] == 'active'  # observer cannot block race
    results['end-check-to-store-race'] = m.export()

    m = Machine(image, profile)
    def submit_race(machine, s):
        if s != 0xC01E331A:
            return
        machine.inject = None
        machine.ledger.close('synthetic external close before command parameters')
        machine.injections.append({'pc': hex(s+machine.delta),
                                   'meaning': 'synthetic close after admission, before MMIO'})
    m.inject = submit_race
    m.run(0xC01E3400, 2)
    assert m.ledger.tickets[1]['state'] == 'invalid'
    assert any(w['pc'] == hex(0xC01E3380+m.delta) and w['epoch'] > 0 for w in m.writes)
    results['close-does-not-prevent-command'] = m.export()

    # Successful old submission and external cancellation have the same entry.
    # Supplied ticket identity distinguishes them; firmware r0 only gives ep.
    m = Machine(image, profile)
    m.ledger.tickets[1]['state'] = 'complete'
    m.ledger.context = ('cleanup', 1)
    m.run(0xC01E35C8, 1)
    assert m.ledger.tickets[1]['state'] == 'retired'
    assert m.ledger.tickets[2]['state'] == 'active'
    results['own-completed-cleanup'] = m.export()

    m = Machine(image, profile)
    m.ledger.tickets[1]['state'] = 'complete'
    m.ledger.active.pop(1)
    new = m.ledger.admit(1)  # same lifecycle epoch, same endpoint and pointers
    assert m.ledger.tickets[1]['epoch'] == m.ledger.tickets[new]['epoch']
    m.ledger.context = ('cleanup', 1)
    m.run(0xC01E35C8, 1)
    assert m.ledger.tickets[new]['state'] == 'invalid'
    results['stale-cleanup-same-global-epoch'] = m.export()

    # Reopen while nested teardown unwinds: actual outer StartTransfer writes
    # status0 AFTER close. An entry-only observer cannot intercept that write.
    m = Machine(image, profile, nested=True)
    def unwind_race(machine, s):
        if s != 0xC01E3512:
            return
        machine.inject = None
        new = machine.ledger.admit(1)
        machine.put(machine.drv+0x704, 1)
        machine.injections.append({'pc': hex(s+machine.delta), 'new_ticket': new,
                                   'meaning': 'synthetic premature reopen before old unwind store'})
    m.inject = unwind_race
    m.run(0xC01E3400, 2)
    assert m.get(m.drv+0x704) == 0 and m.ledger.tickets[3]['state'] == 'active'
    results['nested-old-unwind-new-ticket'] = m.export()

    # Coverage mutations remove observer sites, never patch firmware.
    mutation_results = []
    for name, entry, omitted in (
            ('missing-end', (0xC01E35C8, 1), (0xC01E35C8,)),
            ('reset-only-init', (0xC01DF718,), (0xC01DF718,)),
            ('missing-alternate-stop', (0xC01DFD68,), (0xC01DFD68,)),
            ('late-config-close', (0xC01E0AE0,), (0xC01E0B8E,))):
        m = Machine(image, profile, omit=omitted)
        if name == 'late-config-close':
            setup = m.trb+0x4000
            m.put(setup, 0x00010900)
            m.put(setup+4, 0)
            m.run(*entry, setup, 0)
            target = 'configuration-disable-DALEPENA'
        else:
            m.run(*entry)
            target = {'missing-end': 'end-resource-80', 'reset-only-init': 'init-DMA-TRB-pointer',
                      'missing-alternate-stop': 'alternate-stop-DCTL'}[name]
        event = next(e for e in m.ledger.events if e['event'] == target)
        assert 1 in event['active'], (name, event)
        mutation_results.append({'mutation': name, 'unprotected_mutation': event})
    return {'scenarios': results, 'coverage_mutations_detected': mutation_results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=wait.ROOT)
    p.add_argument('--profile', choices=(*wait.PROFILES, 'both'), default='both')
    a = p.parse_args()
    output = {}
    for profile in wait.PROFILES if a.profile == 'both' else [a.profile]:
        directory, length, sha, _, _ = wait.PROFILES[profile]
        image = (a.root / directory / 'MAIN.bin').read_bytes()
        if len(image) != length or hashlib.sha256(image).hexdigest() != sha:
            p.error(f'{profile}: not audited official MAIN')
        output[profile] = {'sha256': sha, **audit(image, profile)}
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
