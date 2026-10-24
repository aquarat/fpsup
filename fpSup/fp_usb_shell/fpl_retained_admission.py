"""Offline parsing of an opt-in diagnostic reservation; no transport or reset.

The provider owns boot attestation. Bytes alone never authorize activation.
Read the reservation twice around the owned result/identity snapshot; the caller
must independently establish current boot, native identity and startup state.
"""
import struct

MAGIC = 0x5241444D
VERSION = 1
SLOT_SIZE = 64


def candidate(before, after, *, slot, epoch, current_boot_verified=False):
    """Validate reservation before any owner read; returns no call authority."""
    if not current_boot_verified:
        raise ValueError('independent current-boot ownership evidence required')
    if (not 0x44400000 <= slot <= 0x46400100-SLOT_SIZE or slot % 8 or
            not 0 < epoch <= 0xffffffff):
        raise ValueError('invalid reservation identity')
    if len(before) != SLOT_SIZE or before != after:
        raise ValueError('unstable or short reservation')
    w = struct.unpack('<16I', before)
    if w[:3] != (MAGIC, VERSION, epoch) or any(w[12:]):
        raise ValueError('reservation ABI/epoch/reserved words invalid')
    state, result = w[3], w[4:12]
    if state != 3:
        raise ValueError('instance not returned; retain reservation without dereferencing owner')
    phase, owner, address, cls, duplicate, size, wrapper_phase, reserved = result
    if (phase != 6 or cls or reserved or size != 0x10000 or
            owner != address or owner != duplicate or owner % 0x10000 or
            not 0x44400000 <= owner <= 0x46400100-size or
            (owner < slot+SLOT_SIZE and slot < owner+size) or wrapper_phase != 2):
        raise ValueError('invalid retained descriptor/result')
    return dict(owner=owner, slot=slot, epoch=epoch, created_unattached=True,
                activation_authorized=False, native_start_verified=False)


def discover(before, after, *, slot, epoch, current_boot_verified=False,
             owned_result=None, owned_identity=None):
    report = candidate(before, after, slot=slot, epoch=epoch,
                       current_boot_verified=current_boot_verified)
    if owned_result != before[16:48]:
        raise ValueError('owned result mismatch')
    if owned_identity != struct.pack('<4I', MAGIC, VERSION, slot, epoch):
        raise ValueError('owned identity mismatch')
    return report
