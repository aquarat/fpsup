/* fp L 3.02 observer-only binding. Evidence: audit_observer.py and
 * fpSup/docs/FPL_GYRO2_BINDINGS.md. This is not an installable sup profile.
 * Capacity and sampling cadence are explicit experiment inputs, not calibration. */
#if !defined(GYR2_SAMPLE_HZ) || !defined(GYR2_TAG_CAPACITY) || !defined(GYR2_FRAME_CALLBACK)
#error "observer probe requires sample Hz, tag capacity and an owned frame callback"
#endif
.equ F_SUBJECT,     0xC0054E28
.equ F_ATTACH,      0xC00CF208
.equ SUBJ_SLOTS,    9
.equ DP_EVENT,      0x40
.equ DP_BUILDER,    0x2C
.equ EV_TAKE_TYPE,  3
.equ EV_BUILD,      0
.equ EV_SERIALIZED, 2
.equ EV_FRAME,      3
.equ TEMPLATE_PTR,  0xC358E9E8
.equ TEMPLATE_LEN,  0xC358E9E4
.equ F_ADD_TAG,     0xC00B6B20
.equ IFD_MAKERNOTE, 5
.equ F_RATE,       0xC00C6378
.equ GTAG_MAX,     GYR2_TAG_CAPACITY
.equ GTAG_FRAMES,  4
.equ HZ,          GYR2_SAMPLE_HZ
