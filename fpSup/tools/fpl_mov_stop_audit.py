#!/usr/bin/env python3
"""Offline MOV stop forwarding, worker ordering and close-wrapper audit."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint, instructions, normalized

BINDINGS = [(name, addr+0x24B0, addr, size, True) for name, addr, size in [
    ('mailbox_init', 0xC070C188, 0x42),
    ('stop_request', 0xC070D5F8, 0x60),
    ('command_poll', 0xC070D922, 0x48),
    ('stop_gate', 0xC070D9EE, 0x10),
    ('forward', 0xC070DCB8, 0x58),
    ('finalize_message', 0xC070E148, 0x50),
    ('exit_message', 0xC070E198, 0x50),
    ('writer', 0xC070E318, 0x1D2),
    ('finalizer_suffix', 0xC070EF1C, 0x50),
]] + [(name, addr+0x24C0, addr, size, False) for name, addr, size in [
    ('transfer_and_source_close', 0xC06AFEF0, 0xB8),
    ('close_callback', 0xC06AFC58, 0x58),
    ('close_slot', 0xC06AF9E0, 0x30),
]] + [('file_release', 0xC0366020, 0xC0366238, 0x40, False)]


def check(ok, msg):
    if not ok:
        raise ValueError(msg)


def static(fp, fpl):
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    rows = []
    for name, a, b, size, thumb in BINDINGS:
        left, right = instructions(fp, a, size, thumb), instructions(fpl, b, size, thumb)
        check([normalized(i, a, size) for i in left] ==
              [normalized(i, b, size) for i in right], name)
        rows.append(dict(name=name, fp=hex(a), fpl=hex(b), bytes=size,
                         isa='Thumb' if thumb else 'ARM',
                         differences=[dict(offset=hex(x.address-a), fp=x.op_str, fpl=y.op_str)
                                      for x,y in zip(left,right) if x.op_str != y.op_str]))
    return rows


def run(data, started=True, state=2, pools=(1,1,1), send_error=0,
        writer_send_errors=(0,0),
        remainder_error=False, finalize_error=False, transfer_ok=True,
        release_return=0, phase='pipeline', mutation=None):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, (len(data)+4095)&~4095, UC_PROT_READ | UC_PROT_EXEC)
    u.mem_write(BASE, data)
    u.mem_map(0xC302C000, 0x2000)
    u.mem_map(0xC38D0000, 0x10000)
    ram, config, source = 0x10000000, 0xC38D5D7C, 0x10002000
    u.mem_map(ram, 0x40000)
    stack, end = ram+0x3E000, ram+0x3F000
    callback, cleanup, release, transfer = [end+n for n in (4,8,12,16)]
    manager, vtable = ram+0x6000, ram+0x7000
    if mutation:
        addr, value, width = mutation
        u.mem_write(addr, value.to_bytes(width, 'little'))
    def put(a,v): u.mem_write(a, struct.pack('<I', v&0xFFFFFFFF))
    def get(a): return struct.unpack('<I', u.mem_read(a,4))[0]
    def ret(v=0):
        u.reg_write(UC_ARM_REG_R0, v&0xFFFFFFFF)
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
    put(0xC302CFF8, 101)
    put(0xC302CFFC, 102)
    put(config+0x54, callback)
    put(config+0x78, cleanup)
    put(config+0x68, 0xC06AFC58)
    put(config+0x70, 0xC06AFEF0)
    put(config+0x1A4, 1)
    for i in (1,2):
        put(manager+0x64+12*i, ram+0x9000+i*0x100)
        put(ram+0x9004+i*0x100, vtable)
    put(vtable+8, release)
    put(vtable+0x38, transfer)
    queues, log, visited = {101: [], 102: []}, [], []
    available = list(pools)
    alloc = ram+0x10000
    stopped, stop_at, boundary = False, set(), ''
    ranges = [(b,b+s) for _,_,b,s,_ in BINDINGS] + [
        (0xC070C2E0,0xC070C314), (0xC03666D0,0xC0366720)]
    def code(uc, pc, size, _):
        nonlocal alloc, stopped, boundary
        visited.append(pc)
        if pc == end or pc in stop_at:
            stopped, boundary = True, hex(pc)
            uc.emu_stop()
            return
        args = [uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if pc == 0xC0015058:
            uc.mem_write(args[0], bytes([args[1]&255])*args[2]); ret(args[0])
        elif pc == 0xC001510C:
            uc.mem_write(args[0],bytes(uc.mem_read(args[1],args[2]))); ret(args[0])
        elif pc == 0xC070D658: ret(state)
        elif pc == 0xC070D670: log.append(['engine_state',args[0]]); ret()
        elif pc == 0xC071BF28: ret(available.pop(0) if available else 1)
        elif pc == 0xC071BE20:
            size = 8 if args[0] == config+0x80 else 24
            # request uses the same pool's global address C38D5DFC = config+80.
            uc.mem_write(alloc,bytes(uc.mem_read(args[1],size)))
            addr, alloc = alloc, alloc+0x100
            ret(addr)
        elif pc == 0xC01F55C8:
            check(args[0] in queues, 'mailbox identity')
            cmd = get(args[1]+4)
            error = send_error if args[0] == 101 else writer_send_errors[cmd-2]
            log.append(['send',args[0],cmd,error])
            if not error: queues[args[0]].append(args[1])
            ret(error)
        elif pc == 0xC01F53F4:
            check(args[0] in queues, 'receive mailbox identity')
            if queues[args[0]]:
                addr = queues[args[0]].pop(0)
                put(args[1],addr); log.append(['receive',args[0],get(addr+4)]); ret()
            elif args[2] == 0xFFFFFFFF:
                stopped, boundary = True, 'would_block'
                uc.emu_stop()
            else: ret(-50)
        elif pc in (0xC070D178,0xC070D538):
            put(args[0], source if pc == 0xC070D178 else config); ret()
        elif pc == 0xC070DEC8: log.append(['acquisition_stop_mock']); ret()
        elif pc == 0xC070C218: ret(0x10)  # injected other-task status, NOT established quiescence
        elif pc == callback: log.append(['engine_notification',args[0]]); ret()
        elif pc == cleanup: log.append(['error_cleanup_mock']); ret()
        elif pc == 0xC070EAF0:
            log.append(['remainder_write_mock',int(remainder_error)])
            if remainder_error: put(args[3],get(args[3])|4)
            ret(int(remainder_error))
        elif pc == 0xC070ED80:
            log.append(['finalizer_mock',int(finalize_error)])
            if finalize_error: put(args[2],get(args[2])|8)
            ret(int(finalize_error))
        elif pc == 0xC070EFC0:
            log.append(['error_peer_stop_mock']); ret()
        elif pc == 0xC01F52D4:
            log.append(['task_exit_mock']); stopped, boundary = True, 'task_exit'; uc.emu_stop()
        elif pc in (0xC071BEC8,0xC0019DC0,0xC0019FD8,0xC06B28F8): ret()
        elif pc == 0xC06AF708: ret(manager)
        elif pc == 0xC06AF988: ret(manager+0x64+12*args[1])
        elif pc == transfer:
            log.append(['file_virtual_38',int(transfer_ok)]); ret(int(transfer_ok))
        elif pc == release:
            log.append(['file_release_virtual_8',hex(args[0]),args[1],release_return]); ret(release_return)
        else: check(any(a<=pc<b for a,b in ranges),f'unmodelled edge {pc:x}')
    u.hook_add(UC_HOOK_CODE,code)
    def execute(pc,args=(),stops=()):
        nonlocal stopped,stop_at,boundary
        stopped,stop_at,boundary = False,set(stops),''
        u.reg_write(UC_ARM_REG_CPSR,0x13)
        u.reg_write(UC_ARM_REG_SP,stack)
        u.reg_write(UC_ARM_REG_LR,end)
        for reg,val in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):
            u.reg_write(reg,val)
        u.emu_start(pc,end+0x20,count=5000)
        check(stopped,'instruction budget')
        return u.reg_read(UC_ARM_REG_R0)
    if phase == 'finalizer':
        u.reg_write(UC_ARM_REG_R4,config)
        u.reg_write(UC_ARM_REG_R5,0)
        u.reg_write(UC_ARM_REG_R7,config)
        u.reg_write(UC_ARM_REG_R6,ram+0xA000)
        put(stack+4,2)
        execute(0xC070EF1D,stops=(0xC070EF6A,))
        return dict(phase=phase,transfer_ok=transfer_ok,release_return=release_return,
                    log=log,source_slot=get(manager+0x70),destination_slot=get(manager+0x7C),
                    flags=get(ram+0xA000),visited=[hex(p) for p in visited])
    result=execute(0xC070D5F9)
    if queues[101]:
        u.reg_write(UC_ARM_REG_R7,config)
        put(stack+0xC,config)
        put(stack+0x1C,int(started))
        execute(0xC070D923,stops=(0xC070D96A,))
        execute(0xC070D9EF,stops=(0xC070D9FE,0xC070DC80))
    # A sequential FIFO scheduler model; start writer even with empty Q2 to expose a wait.
    execute(0xC070E319)
    return dict(phase=phase,started=started,state=state,pools=list(pools),send_error=send_error,
                remainder_error=remainder_error,finalize_error=finalize_error,
                writer_send_errors=list(writer_send_errors),
                request_return=result,log=log,boundary=boundary,
                visited=[hex(p) for p in visited])


def validate(row):
    log=row['log']
    if row['phase']=='finalizer':
        check(row['source_slot']==0,'source release')
        check((row['destination_slot']==0)==row['transfer_ok'],'destination release ordering')
        check(bool(row['flags']&8)==(not row['transfer_ok']),'transfer failure flag')
        check(sum(e[0]=='file_release_virtual_8' for e in log)==(2 if row['transfer_ok'] else 1),'close count')
        releases=[e for e in log if e[0]=='file_release_virtual_8']
        check([e[1] for e in releases]==(['0x10009100','0x10009200'] if row['transfer_ok'] else ['0x10009100']),
              'source then destination release')
        check(all(e[2]==3 for e in releases),'release argument')
        check(log[0][0]=='file_virtual_38','file operation before release')
        check(any(e[0]=='error_cleanup_mock' for e in log)==(not row['transfer_ok']),
              'finalizer cleanup condition')
        return
    permitted=row['state']==2 and bool(row['pools'][0])
    check(row['request_return']==(0 if permitted else 1),'request acceptance')
    sent=[(e[1],e[2]) for e in log if e[0]=='send']
    expect=[(101,1)] if permitted else []
    forward=permitted and not row['send_error'] and row['started']
    if forward:
        expect += [(102,c) for c,p in zip((2,3),row['pools'][1:]) if p]
    check(sent==expect,'queue/command forwarding')
    writer2=forward and bool(row['pools'][1]) and not row['writer_send_errors'][0]
    writer3=forward and bool(row['pools'][2]) and not row['writer_send_errors'][1]
    failure=writer2 and (row['remainder_error'] or row['finalize_error'])
    raw=[e[1] for e in log if e[0]=='engine_notification']
    check(raw==(([4] if forward else [])+([2 if failure else 1] if writer3 or failure else [])),
          'notification ordering/status')
    if writer2:
        check(any(e[0]=='remainder_write_mock' for e in log),'message 2 remainder')
        check(any(e[0]=='finalizer_mock' for e in log)==(not row['remainder_error']),'message 2 finalizer')
    if writer3 and not failure:
        idx=next(i for i,e in enumerate(log) if e[:3]==['receive',102,3])
        check(not writer2 or any(e[0]=='finalizer_mock' for e in log[:idx]),'finalize before exit receipt')
    check(row['boundary']==('task_exit' if writer3 or failure else 'would_block'),
          'writer termination boundary')
    if writer2 and not row['remainder_error'] and (writer3 or failure):
        final = next(i for i,e in enumerate(log) if e[0]=='finalizer_mock')
        terminal = next(i for i,e in enumerate(log) if e[0]=='engine_notification' and e[1]!=4)
        check(final < terminal,'finalizer before terminal notification')


def self_test(data):
    cases=[{},dict(started=False),dict(state=1),dict(pools=(0,1,1)),
           dict(pools=(1,0,1)),dict(pools=(1,1,0)),dict(send_error=-1),
           dict(remainder_error=True),dict(finalize_error=True),
           dict(writer_send_errors=(-1,0)),dict(writer_send_errors=(0,-1))]
    cases += [dict(phase='finalizer',transfer_ok=t,release_return=r) for t in (False,True) for r in (0,1)]
    rows=[run(data,**case) for case in cases]
    for row in rows: validate(row)
    mutations=[('stop command',(0xC070D626,0x2000,2),{}),
               ('finalize command',(0xC070E168,0x2103,2),{}),
               ('exit command',(0xC070E1B8,0x2102,2),{}),
               ('start latch',(0xC070D954,0x910D,2),{}),
               ('terminal status',(0xC070E4B8,0x2000,2),{}),
               ('source clearing',(0xC036626C,0xE3A01001,4),dict(phase='finalizer'))]
    rejected=[]
    for name,mutation,case in mutations:
        try: validate(run(data,mutation=mutation,**case))
        except ValueError as exc:
            check(not str(exc).startswith('unmodelled'),'mutation escaped CFG')
            rejected.append(dict(name=name,assertion=str(exc)))
        else: raise ValueError('undetected mutation '+name)
    return rows,rejected


def main():
    root=Path.home()/'.local/share/fpsup/firmware'
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp',type=Path,default=root/'FP__V502/MAIN.bin')
    p.add_argument('--fpl',type=Path,default=root/'FPL_V302/MAIN.bin')
    p.add_argument('--self-test',action='store_true')
    args=p.parse_args();fp,fpl=args.fp.read_bytes(),args.fpl.read_bytes()
    bindings=static(fp,fpl)
    cases,negative=self_test(fpl) if args.self_test else ([],[])
    print(json.dumps(dict(hardware_tested=False,correspondences=bindings,cases=cases,negative=negative,
        fingerprints={n:dict(bytes=len(d),sha256=hashlib.sha256(d).hexdigest()) for n,d in [('fp',fp),('fpl',fpl)]},
        summary=dict(correspondences=len(bindings),cases=len(cases),mutations=len(negative)),
        limitations=['Sequential mocked FIFO scheduler, not a concurrency proof',
                     'Writer IO mocked; finalizer tail separately executes real callback wrappers',
                     'No physical flush or durable storage completion established']),indent=2))


if __name__=='__main__': main()
