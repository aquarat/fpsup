#!/usr/bin/env python3
"""Read resident FPLS observations from DNGs, without rewriting their metadata.

The observation belongs to this DNG's notify, not necessarily its sensor frame.
Preroll, transition and restored frames therefore keep association=unknown.
"""
import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'projects/gyro2-sup'))
import fsg2
sys.path.insert(0,str(Path(__file__).resolve().parent))
from queue_binding import lookup_snapshot

TIMER_HZ=12000000

FIELDS=('magic','frame','inverse','bytes','requested','active','vd_count','trial',
        'timing04','timing20','seconds','timer5','last_vd_timer5','reason',
        'association','version')


def observation(data):
    _,maker=fsg2.maker_note(data)
    ty,count,off=maker[fsg2.GTAG]
    if ty!=7 or count not in (64,336,464,640) or off+count>len(data):raise ValueError('invalid FPLS extent')
    words=struct.unpack_from('<16I',data,off)
    if (words[0]!=0x534c5046 or words[1]==0 or words[2]!=(~words[1]&0xffffffff)
            or words[3]!=count or words[14:]!=(0,{64:1,336:2,464:3,640:4}[count])):
        raise ValueError('unwritten, corrupt or unsupported FPLS observation')
    result=dict(zip(FIELDS,words))
    result.update(sensor_timing_association='unknown',
                  interpretation='registers at DNG notify; not exposure/readout timing of this frame',
                  frame_rate_timecode='stock nominal metadata; not corrected')
    if count>=336:
        sequence,cursor,current,valid=struct.unpack_from('<4I',data,off+64)
        if valid not in (0,1):raise ValueError('invalid queue observation flags')
        raw=list(struct.iter_unpack('<4I',data[off+80:off+336]))
        # Ring positions are independent of DNG index. Only published entries
        # belong to this take. Preserve before-write timing at the transition.
        ring=[raw[i&15] for i in range(max(0,cursor-16),cursor)]
        result['queue']=dict(native_sequence=sequence, current_counter=current,
            valid=bool(valid), cursor=cursor,
            samples=[dict(zip(('native_counter','timing04_before','timer5','vd_ordinal'),r)) for r in ring],
            interpretation='native lookup result may be fallback; counter equality is not capture association')
    if count>=464:
        flags,key,cursor,reserved=struct.unpack_from('<4I',data,off+336)
        clock,seconds,tick,pending=struct.unpack_from('<4I',data,off+432)
        if (flags not in (0,1,3) or reserved or clock not in (0,1) or pending not in (0,32)
                or any(data[off+(448 if count==464 else 456):off+464]) or (clock and tick>=TIMER_HZ)
                or (flags==3 and not valid)):
            raise ValueError('invalid FPLS lookup/clock fields')
        result['lookup']=dict(key_valid=bool(flags&1),key=key if flags&1 else None,
            snapshot_valid=flags==3, capture_association=False,
            producer_timestamp=None, key_generation=None,
            native_lookup_at_consumer='unobserved')
        if flags==3:
            keys=struct.unpack_from('<10I',data,off+352)
            values=struct.unpack_from('<10I',data,off+392)
            snap=lookup_snapshot(key,keys,values,current,cursor)
            snap.update(keys=keys,values=values,agrees_with_native_result=snap['result']==sequence)
            result['lookup']['at_notify']=snap
        result['notify_clock']=dict(valid=bool(clock),seconds=seconds,ticks=tick,
            frequency_hz=TIMER_HZ,pending_rollover=bool(pending),
            domain='DNG notification; not capture or exposure')
    if count==640:
        trace=struct.unpack_from('<44I',data,off+464)
        status,overwritten,rejected,exhausted,lo,hi,evicted,reserved=trace[:8]
        if status not in (0,1,2) or exhausted not in (0,1) or reserved:
            raise ValueError('invalid producer trace header')
        result['producer_trace']=dict(joined=status==2,status=status,
            lookup_records_overwritten=overwritten,rejected_events=rejected,
            generation_exhausted=bool(exhausted),last_generation=(hi<<32)|lo,
            producer_records_evicted=evicted,
            domain='native queue publication/lookup; not sensor exposure or DMA completion')
        if status==2:
            l=trace[8:];p=l[20:]
            record,caller_sp=struct.unpack_from('<2I',data,off+448)
            kind=l[5]&7
            if (l[0]!=0x31545046 or not (l[1] or l[2]) or kind not in (1,2,4) or
                l[5]&~255 or l[5]&(16|64) or l[9]&~1023 or l[10]>10 or
                l[11] or l[13] or l[7]!=record or l[12]!=caller_sp or
                not flags&1 or not valid or l[3]!=key or l[4]!=sequence or
                (kind==1 and (l[10]>=10 or not l[9]&(1<<l[10]))) or
                (kind!=1 and l[10]!=10)):
                raise ValueError('invalid historical lookup record')
            def stamp(v):
                if v[0] not in (0,1) or (v[0] and v[2]>=TIMER_HZ):
                    raise ValueError('invalid producer/lookup clock')
                return dict(valid=bool(v[0]),seconds=v[1],ticks=v[2],frequency_hz=TIMER_HZ)
            actual=dict(ordinal=(l[2]<<32)|l[1],key=l[3],result=l[4],flags=l[5],
                status={1:'hit',2:'zero-value-fallback',4:'miss-fallback'}[kind],
                matched_slots=[i for i in range(10) if l[9]&(1<<i)],
                selected_slot=l[10] if kind==1 else None,
                before=stamp(l[14:17]),after=stamp(l[17:20]),producer=None)
            if kind==1 and not l[5]&8:
                if (p[0]!=0x31545046 or not (p[1] or p[2]) or p[3:6]!=(key,sequence,l[10]) or
                    p[15]&~128):raise ValueError('invalid historical producer generation')
                actual['producer']=dict(generation=(p[2]<<32)|p[1],key=p[3],native_value=p[4],
                    slot=p[5],before=stamp(p[6:9]),after=stamp(p[9:12]),
                    cpsr=p[12],task=p[13],caller=p[14],flags=p[15],
                    task_meaning='current TCB; in IRQ/FIQ mode this identifies the interrupted task',
                    time_meaning='interval bracketing native queue publication, not sensor capture')
            elif any(p):raise ValueError('fallback/stale lookup must not invent a producer')
            result['lookup']['actual']=actual
            result['lookup']['native_lookup_at_consumer']='captured at native lookup with per-task invocation handoff'
            if actual['producer']:
                result['lookup']['key_generation']=actual['producer']['generation']
                result['lookup']['producer_timestamp']={k:actual['producer'][k] for k in ('before','after','time_meaning')}
        elif any(trace[8:]):raise ValueError('unavailable producer trace contains a record')
    return result


def nominal_metadata(data):
    """Read actual stored values; never assume that an input still says 24 fps."""
    if data[:4]!=b'II*\0':raise ValueError('expected little-endian TIFF')
    root=struct.unpack_from('<I',data,4)[0]
    if root+2>len(data):return dict(available=False,reason='root IFD outside supplied prefix')
    entries=fsg2.ifd_entries(data,root)
    result=dict(available=True,interpretation='stored playback metadata, not measured capture timing')
    for tag,name,kind,n in ((51044,'frame_rate',10,1),(51043,'timecodes',1,8)):
        if tag not in entries:result[name]=None;continue
        ty,count,ptr=entries[tag]
        if (ty,count)!=(kind,n) or ptr+8>len(data):raise ValueError(f'invalid {name} extent/type')
        result[name]=list(struct.unpack_from('<ii',data,ptr)) if tag==51044 else data[ptr:ptr+8].hex()
        if tag==51044 and result[name][1]<=0:raise ValueError('invalid FrameRate denominator')
    return result


def timeline(frames):
    """Delivery timeline for ONE caller-selected take, in supplied frame order.

    Preserve missing frames, missing clocks, transitions and unknown capture
    identity. V1/v2 raw seconds/timer pairs lack pending-rollover evidence and
    are never promoted to timestamps. No DNG or standard timecode is rewritten.
    """
    rows=[];previous=None;origin=None;elapsed=None;segment=0
    for source,obs,nominal in frames:
        frame=obs['frame'];clock=obs.get('notify_clock',{})
        if previous and frame<=previous['frame']:
            raise ValueError('frames must increase within one take; duplicate/reset/reordered input')
        row=dict(source=source,frame=frame,nominal=nominal,capture_time=None,
                 exposure_association='unknown',notify_elapsed_ticks=None,
                 notify_interval_ticks=None,notify_rate_hz=None,
                 missing_frames_before=frame-previous['frame']-1 if previous else frame-1,
                 observed_state={k:obs[k] for k in ('requested','active','timing04','reason')},
                 lookup=obs.get('lookup'),clock_valid=bool(clock.get('valid')))
        state=row['observed_state']
        if previous and state!=previous['observed_state']:segment+=1
        row['observed_state_segment']=segment
        if not clock.get('valid'):
            row['timing_status']='unknown: no coherent notify clock'
            elapsed=None
        else:
            if origin is None and previous is None:origin=clock;elapsed=0
            if previous and previous['clock_valid']:
                prev_clock=previous['_clock']
                sec=(clock['seconds']-prev_clock['seconds'])&0xffffffff
                delta=sec*TIMER_HZ+clock['ticks']-prev_clock['ticks']
                # Reject backward/reset or >half-range ambiguity. No guessed wrap.
                if sec>=0x80000000 or delta<=0:
                    row['timing_status']='unknown: nonmonotonic/reset clock'
                    elapsed=None
                else:
                    row['notify_interval_ticks']=delta
                    if elapsed is not None:elapsed+=delta
                    contiguous=row['missing_frames_before']==0
                    row['timing_status']='notify interval' if contiguous else 'notify span across missing frames'
                    if contiguous:row['notify_rate_hz']=TIMER_HZ/delta
            else:
                row['timing_status']='notify origin' if previous is None else 'notify clock resumes; elapsed unknown'
            row['notify_elapsed_ticks']=elapsed
        row['_clock']=clock
        rows.append(row);previous=row
    for row in rows:row.pop('_clock')
    return dict(schema='fpls-notify-timeline-1',timebase_hz=TIMER_HZ,
                domain='DNG delivery notification, not sensor capture',
                standard_metadata_rewritten=False,frames=rows)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('dng',type=Path,nargs='+')
    p.add_argument('--timeline',action='store_true',help='one take in frame order; delivery timestamps only, preserve gaps and unknowns')
    a=p.parse_args()
    if a.timeline:
        rows=[]
        for f in a.dng:
            data=f.read_bytes();rows.append((str(f),observation(data),nominal_metadata(data)))
        print(json.dumps(timeline(rows),indent=2))
    else:print(json.dumps({str(f):observation(f.read_bytes()) for f in a.dng},indent=2))
