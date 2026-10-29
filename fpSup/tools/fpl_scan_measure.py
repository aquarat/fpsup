#!/usr/bin/env python3
"""Measure relative scan time from a fixed-camera moving-bar target.

Input: two DNG frames of tools/slit-scan-target in Bars mode, identical framing
and speed. Positive/negative scan times depend on motion direction. The target
has four bars per screen width, so --speed 0.5 means 2 pattern cycles/second.
Fit a complex horizontal harmonic on each image row, unwrap phase vertically,
then compare its slope between baseline and trial. Static perspective cancels
only approximately; output is evidence, not automatic optical acceptance.

Requires numpy and rawpy (scoped analysis-venv). Crop must contain only the
screen and enough of the pattern; avoid the center crosshair. --period is the
bar spacing in ORIGINAL DNG pixels, measured from an image row, not guessed
from the camera raster width. Camera and target must not move between frames.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def phase_fit(image, *, period, crop):
    x0, y0, x1, y1 = crop
    h, w = image.shape
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h and period > 4):
        raise ValueError('invalid crop or period')
    if x1-x0 < 2*period or y1-y0 < 32:
        raise ValueError('crop needs at least two bar periods and 32 rows')
    area = np.asarray(image[y0:y1, x0:x1], dtype=float)
    # Row DC and tapered window reduce brightness and crop-edge sensitivity.
    area -= np.mean(area, axis=1, keepdims=True)
    weights = np.hanning(area.shape[1])
    wave = np.exp(-2j*np.pi*np.arange(x0, x1)/period)
    coefficient = (area*weights) @ wave
    amplitude = np.abs(coefficient)
    if not np.isfinite(amplitude).all() or np.max(amplitude) <= 0:
        raise ValueError('no measurable pattern')
    valid = amplitude > .2*np.median(amplitude)
    if np.count_nonzero(valid) < .9*len(valid):
        raise ValueError('too many rows lack bar contrast')
    phase = np.unwrap(np.angle(coefficient))
    y = np.arange(y0, y1, dtype=float)
    slope, intercept = np.polyfit(y[valid], phase[valid], 1, w=amplitude[valid])
    residual = phase-(slope*y+intercept)
    return dict(radians_per_row=float(slope), intercept=float(intercept),
                rms_phase_error=float(np.sqrt(np.mean(residual[valid]**2))),
                median_amplitude=float(np.median(amplitude)),
                valid_rows=int(np.count_nonzero(valid)), rows=len(valid))


def compare(baseline, trial, *, period, crop, speed=.5):
    if baseline.shape != trial.shape or speed == 0 or not np.isfinite(speed):
        raise ValueError('matching rasters and nonzero finite target speed required')
    before = phase_fit(baseline, period=period, crop=crop)
    after = phase_fit(trial, period=period, crop=crop)
    slope = after['radians_per_row']-before['radians_per_row']
    return dict(baseline=before, trial=after, target_widths_per_second=speed,
                target_cycles_per_second=4*speed, crop=crop, period_pixels=period,
                signed_scan_difference_ms=float(-slope*(baseline.shape[0]-1)/(2*np.pi*4*speed)*1000),
                interpretation='relative full-image scan estimate; requires fixed framing, '
                'known target speed, consistent phase and inspection for display artifacts')


def read_dng(path):
    import rawpy
    with rawpy.imread(str(path)) as raw:
        # Average each 2x2 CFA cell to suppress Bayer phase without demosaicing.
        a = raw.raw_image_visible.astype(float)
        h, w = a.shape
        a = a[:h//2*2, :w//2*2]
        return a.reshape(h//2, 2, w//2, 2).mean(axis=(1, 3))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('trial', type=Path)
    p.add_argument('--period', type=float, required=True)
    p.add_argument('--crop', type=int, nargs=4, required=True, metavar=('X0', 'Y0', 'X1', 'Y1'))
    p.add_argument('--speed', type=float, default=.5)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    a, b = read_dng(args.baseline), read_dng(args.trial)
    result = compare(a, b, period=args.period/2,
                     crop=tuple(v//2 for v in args.crop), speed=args.speed)
    result['input_files'] = [str(args.baseline), str(args.trial)]
    text = json.dumps(result, indent=2)
    if args.out:
        with args.out.open('x') as f:
            f.write(text+'\n')
    print(text)


if __name__ == '__main__':
    main()
