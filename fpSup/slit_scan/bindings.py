"""fp L recording-binding research: no USB on import.

The shell's native getter chains, not GUI summary variables. Status addresses
derive from C00178D8 -> C0017AC8 and C040FDA8. Recording is a BYTE; adjacent
bytes are unrelated status flags. Live acceptance is recorded separately.
"""
GETTERS = {'format': 0xC00594C8, 'quality': 0xC0059560,
           'size': 0xC0059690, 'rate': 0xC0059728}
SETTINGS = 0xC0055120
RECORDING = 0xC30338CC
APP = 0xC3033A40
EXPOSURE = {'mode': (0xC00559D8,0xC0055A10),
            'shutter': (0xC0055BA0,0xC0055BE8),
            'iso': (0xC0056158,0xC0056190)}


def exposure_probe_source(param, field=None, values=()):
    """Finite task-context native exposure call followed by all three getters.

    Shutter uses the native structure-return ABI (r0=out, r1=settings).
    No retained pointer. The caller saves originals durably and restores them;
    this is NOT suitable for an IRQ or the shared shutdown's masked section.
    """
    def call(fn):
        return f'movw ip, #{fn&65535}\nmovt ip, #{fn>>16}\nblx ip\n'
    body=call(SETTINGS)+'mov r5, r0\nstr r0, [r4, #4]\n'
    if field is not None:
        if field not in EXPOSURE or len(values)!=(2 if field=='shutter' else 1):
            raise ValueError('explicit native setter arguments required')
        if any(type(v) is not int or not 0<=v<=65535 for v in values):
            raise ValueError('bounded unsigned native values required')
        body+='mov r0, r5\n'+''.join(f'movw r{i+1}, #{v}\n' for i,v in enumerate(values))
        body+=f'mov r{len(values)+1}, #1\n'+call(EXPOSURE[field][0])
    body+='mov r0, r5\n'+call(EXPOSURE['mode'][1])+'str r0, [r4, #8]\n'
    body+='add r0, r4, #12\nmov r1, r5\n'+call(EXPOSURE['shutter'][1])
    body+='mov r0, r5\n'+call(EXPOSURE['iso'][1])+'str r0, [r4, #20]\n'
    return f'''.syntax unified
.arm
.text
.global entry
entry:
push {{r4-r6, lr}}
movw r4, #{param&65535}
movt r4, #{param>>16}
mov r0, #1
str r0, [r4]
{body}
mov r0, #2
str r0, [r4]
pop {{r4-r6, pc}}
'''


def probe_source(param, getter=None):
    """Finite call; caller reserves/readbacks staging and publishes D/I.

    No native setters, callbacks or retained pointers. getter=None first proves
    the trivial initialized status-view accessor.
    """
    call = (f'movw r3, #{SETTINGS & 65535}\nmovt r3, #{SETTINGS >> 16}\nblx r3\n'
            f'str r0, [r4, #4]\nmovw r3, #{getter & 65535}\n'
            f'movt r3, #{getter >> 16}\nblx r3' if getter is not None else
            'movw r0, #0x3830\nmovt r0, #0xc303\n'
            'movw r3, #0x7ac8\nmovt r3, #0xc001\nblx r3')
    return f'''.syntax unified
.arm
.text
.global entry
entry:
push {{r4, lr}}
movw r4, #{param & 65535}
movt r4, #{param >> 16}
mov r0, #1
str r0, [r4]
{call}
str r0, [r4, #8]
mov r0, #2
str r0, [r4]
pop {{r4, pc}}
'''
