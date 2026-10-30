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

FIELDS=('magic','frame','inverse','bytes','requested','active','vd_count','trial',
        'timing04','timing20','seconds','timer5','last_vd_timer5','reason',
        'association','version')


def observation(data):
    _,maker=fsg2.maker_note(data)
    ty,count,off=maker[fsg2.GTAG]
    if ty!=7 or count!=64 or off+count>len(data):raise ValueError('invalid FPLS extent')
    words=struct.unpack_from('<16I',data,off)
    if (words[0]!=0x534c5046 or words[1]==0 or words[2]!=(~words[1]&0xffffffff)
            or words[3]!=64 or words[14:]!=(0,1)):
        raise ValueError('unwritten, corrupt or unsupported FPLS observation')
    result=dict(zip(FIELDS,words))
    result.update(sensor_timing_association='unknown',
                  interpretation='registers at DNG notify; not exposure/readout timing of this frame',
                  frame_rate_timecode='stock nominal metadata; not corrected')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('dng',type=Path,nargs='+')
    a=p.parse_args()
    print(json.dumps({str(f):observation(f.read_bytes()) for f in a.dng},indent=2))
