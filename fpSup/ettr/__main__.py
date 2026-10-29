"""python -m fpSup.ettr: offline RAW metering, planning and sidecar generation."""
import argparse
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path

from .core import Controller, Limits, MeterConfig, deflicker
from .dng import analyze, write_output


def numbers(text):
    try:
        return tuple(float(Fraction(v)) for v in text.split(','))
    except (ValueError, ZeroDivisionError) as error:
        raise argparse.ArgumentTypeError('use comma-separated numbers/fractions') from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dng', type=Path, nargs='+', help='chronological sequence, in supplied order')
    parser.add_argument('--reserve-ev', type=float, default=.5)
    parser.add_argument('--ignore-fraction', type=float, default=.001, help='fraction, not percent')
    parser.add_argument('--percentile', type=float, default=.5)
    parser.add_argument('--target-ev', type=float, default=-4)
    parser.add_argument('--trend-window', type=int, default=1, help='1=fixed target, odd >1=scene trend')
    parser.add_argument('--max-correction-ev', type=float, default=6)
    parser.add_argument('--deflicker', action='store_true', help='compute post-processing corrections')
    parser.add_argument('--shutters', type=numbers, help='enable planning with explicit supported seconds, ascending')
    parser.add_argument('--isos', type=numbers, help='enable planning with explicit supported ISO values, ascending')
    parser.add_argument('--interval', type=float, help='start-to-start seconds')
    parser.add_argument('--overhead', type=float, default=2, help='reserved readout/write/meter/settling seconds')
    parser.add_argument('--max-up-ev', type=float, default=.5)
    parser.add_argument('--max-down-ev', type=float, default=2)
    parser.add_argument('--output', type=Path, help='create NEW directory with report/JSON sidecars')
    parser.add_argument('--xmp', action='store_true', help='also emit development hints (requires --deflicker --output)')
    args = parser.parse_args(argv)
    if bool(args.shutters) != bool(args.isos):
        parser.error('--shutters and --isos are required together')
    if args.xmp and not (args.output and args.deflicker):
        parser.error('--xmp requires --output and --deflicker')
    if args.interval is not None and not args.shutters:
        parser.error('--interval requires explicit planning tables')
    try:
        config = MeterConfig(args.reserve_ev, args.ignore_fraction, args.percentile)
        controller = None
        if args.shutters:
            controller = Controller(Limits(args.shutters, args.isos, args.interval,
                                           args.overhead, max_up_ev=args.max_up_ev,
                                           max_down_ev=args.max_down_ev))
        frames, meters, exposures = [], [], []
        for i, path in enumerate(args.dng):
            frame, meter, exposure = analyze(path, config)
            if controller:
                frame['next_exposure_plan'] = asdict(controller.plan(meter, exposure, i))
            frames.append(frame)
            meters.append(meter)
            exposures.append(exposure)
        if args.deflicker:
            if not all(m.valid_brightness for m in meters):
                raise ValueError('deflicker percentile is below minimum signal or clipped')
            corrections = deflicker([m.brightness for m in meters], exposures,
                                    target_ev=args.target_ev, window=args.trend_window,
                                    max_correction_ev=args.max_correction_ev)
            for frame, correction in zip(frames, corrections):
                frame['deflicker'] = correction
        report = dict(schema='fpsup-ettr-offline-v1', status='offline-only; no camera integration',
                      meter_config=asdict(config),
                      limits=asdict(controller.limits) if controller else None,
                      deflicker_config=(dict(target_ev=args.target_ev, window=args.trend_window,
                                            max_correction_ev=args.max_correction_ev)
                                        if args.deflicker else None), frames=frames)
        if args.output:
            write_output(args.output, report, args.xmp)
        else:
            print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f'ETTR: {error}\n')


if __name__ == '__main__':
    main()
