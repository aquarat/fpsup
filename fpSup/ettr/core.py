"""Exposure planning and RAW statistics, independent of camera APIs.

All EV values are log2 linear signal ratios. ISO is a nominal gain proxy, not
additional photon exposure. Callers supply *actual* frame exposure/readback;
plans are never assumed to have been applied. Aperture is immutable in a run.
"""
from dataclasses import dataclass
import math


def finite(value, name):
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return value


@dataclass(frozen=True)
class MeterConfig:
    reserve_ev: float = 0.5
    ignore_fraction: float = 0.001
    percentile: float = 0.5
    minimum_signal: float = 1e-6

    def __post_init__(self):
        for name, value in vars(self).items():
            finite(value, name)
        if not 0 <= self.reserve_ev <= 16 or not 0 <= self.ignore_fraction < 0.5:
            raise ValueError('reserve must be 0..16 EV; ignore fraction 0..<0.5')
        if not 0 < self.percentile < 1 or not 0 < self.minimum_signal < 1:
            raise ValueError('percentile and minimum_signal must be in (0,1)')


@dataclass(frozen=True)
class Channel:
    channel: int
    samples: int
    ignored_samples: int
    black: float
    white: float
    tail: float
    clipped_samples: int


@dataclass(frozen=True)
class Meter:
    channels: tuple
    tail: float
    brightness: float
    correction_ev: float | None
    clipping: bool
    valid_brightness: bool


def meter_raw(raw, colors, black, white, config=MeterConfig()):
    """Exact full-frame channel quantiles on *linearized*, undemosaiced RAW.

    colors is a CFA channel-index array, same shape as raw (keep G1/G2 separate).
    Levels index by channel, in the same linearized DN domain. No WB, gamma,
    subsampling or JPEG histogram. Ignore exactly floor(N*fraction) top samples
    independently in each channel, including already-clipped samples.
    """
    import numpy as np

    raw, colors = np.asarray(raw), np.asarray(colors)
    if raw.ndim != 2 or not raw.size or raw.shape != colors.shape:
        raise ValueError('nonempty 2D RAW and matching CFA map required')
    if not np.issubdtype(colors.dtype, np.integer):
        raise ValueError('CFA map must contain integer channel indices')
    if not np.isfinite(raw).all():
        raise ValueError('RAW contains nonfinite samples')
    ids = np.unique(colors)
    if len(ids) < 3 or ids.min() < 0 or ids.max() >= min(len(black), len(white)):
        raise ValueError('need at least three CFA channels and matching levels')
    channels, normalized = [], []
    for c in ids:
        lo, hi = float(black[c]), float(white[c])
        if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
            raise ValueError('white must exceed black for every channel')
        pixels = raw[colors == c].astype(np.float64)
        n = pixels.size
        ignored = math.floor(n * config.ignore_fraction)
        clipped = int(np.count_nonzero(pixels >= hi))
        pixels = np.clip((pixels-lo)/(hi-lo), 0, 1)
        tail = float(np.partition(pixels, n-ignored-1)[n-ignored-1])
        channels.append(Channel(int(c), n, ignored, lo, hi, tail, clipped))
        normalized.append(pixels)
    values = np.concatenate(normalized)
    k = max(0, math.ceil(values.size*config.percentile)-1)
    brightness = float(np.partition(values, k)[k])
    tail = max(c.tail for c in channels)
    correction = (-math.log2(tail)-config.reserve_ev
                  if tail > config.minimum_signal else None)
    return Meter(tuple(channels), tail, brightness, correction,
                 any(c.clipped_samples > c.ignored_samples for c in channels),
                 config.minimum_signal < brightness < 1)


@dataclass(frozen=True)
class Exposure:
    shutter_s: float
    iso: float
    aperture: float

    def __post_init__(self):
        for name, value in vars(self).items():
            if finite(value, name) <= 0:
                raise ValueError(f'{name} must be positive (Auto ISO is unsupported)')

    @property
    def signal_ev(self):
        # Sum logs to avoid overflow/underflow of products.
        return math.log2(self.shutter_s)+math.log2(self.iso)-math.log2(100)


@dataclass(frozen=True)
class Limits:
    # Explicit actuator tables: defaults are illustrative, not a fp L capability map.
    shutters_s: tuple = tuple(1/d for d in (
        8000, 6400, 5000, 4000, 3200, 2500, 2000, 1600, 1250, 1000,
        800, 640, 500, 400, 320, 250, 200, 160, 125, 100, 80, 60, 50,
        40, 30, 25, 20, 15, 13, 10, 8, 6, 5, 4, 3, 2.5, 2, 1.6, 1.3,
        1)) + (1.3, 1.6, 2, 2.5, 3.2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30)
    isos: tuple = (100, 200, 400, 800, 1600, 3200)
    interval_s: float | None = None
    overhead_s: float = 2.0
    smoothing: float = 0.35
    hysteresis_ev: float = 0.12
    max_up_ev: float = 0.5
    max_down_ev: float = 2.0
    clip_recovery_ev: float = 1.0

    def __post_init__(self):
        for name in ('shutters_s', 'isos'):
            values = getattr(self, name)
            if not values or len(values) > 512 or any(not math.isfinite(v) or v <= 0 for v in values):
                raise ValueError(f'{name}: require 1..512 finite positive values')
            if tuple(sorted(set(values))) != tuple(values):
                raise ValueError(f'{name}: values must be unique and increasing')
        for name in ('overhead_s', 'smoothing', 'hysteresis_ev', 'max_up_ev',
                     'max_down_ev', 'clip_recovery_ev'):
            finite(getattr(self, name), name)
        if self.overhead_s < 0 or not 0 < self.smoothing <= 1 or self.hysteresis_ev < 0:
            raise ValueError('invalid overhead/smoothing/hysteresis')
        if min(self.max_up_ev, self.max_down_ev, self.clip_recovery_ev) <= 0:
            raise ValueError('step limits must be positive')
        if self.interval_s is not None:
            finite(self.interval_s, 'interval_s')
            if self.interval_s-self.overhead_s < self.shutters_s[0]:
                raise ValueError('interval leaves no feasible exposure')

    @property
    def usable_shutters(self):
        return tuple(s for s in self.shutters_s if self.interval_s is None or
                     s <= self.interval_s-self.overhead_s+1e-12)


@dataclass(frozen=True)
class Plan:
    exposure: Exposure
    requested_ev: float | None
    applied_ev: float
    photon_ev: float
    gain_ev: float
    residual_ev: float | None
    status: str


class Controller:
    """A causal planner with absolute-target smoothing, no integral windup.

    Frame IDs must increase. Construct a new controller on mode/generation or
    aperture changes. An unavailable/dark meter holds rather than guessing.
    Decreases bypass smoothing; saturation requests bounded repeated recovery,
    because a clipped pixel does not encode how far above white the scene is.
    """
    def __init__(self, limits=Limits()):
        self.limits = limits
        self.last_frame = None
        self.aperture = None
        self.target_ev = None

    def plan(self, meter, current, frame_id):
        if not isinstance(frame_id, int) or frame_id < 0:
            raise ValueError('frame_id must be a nonnegative integer')
        if self.last_frame is not None and frame_id <= self.last_frame:
            raise ValueError('stale or repeated frame')
        if self.aperture is not None and current.aperture != self.aperture:
            raise ValueError('aperture changed; reset controller and re-meter')
        limits = self.limits
        if current.shutter_s not in limits.usable_shutters or current.iso not in limits.isos:
            raise ValueError('actual exposure is outside configured actuator/interval limits')
        error = meter.correction_ev
        if error is not None:
            finite(error, 'meter correction')
        self.last_frame, self.aperture = frame_id, current.aperture

        def result(next_exposure, status):
            delta = next_exposure.signal_ev-current.signal_ev
            return Plan(next_exposure, error, delta,
                        math.log2(next_exposure.shutter_s/current.shutter_s),
                        math.log2(next_exposure.iso/current.iso),
                        None if error is None else error-delta, status)

        if error is None:
            self.target_ev = None
            return result(current, 'meter_unavailable')
        if meter.clipping:
            error = min(error, -limits.clip_recovery_ev)
        desired = current.signal_ev+error
        if error < 0 or self.target_ev is None:
            self.target_ev = desired
        else:
            self.target_ev += limits.smoothing*(desired-self.target_ev)
        # Never let historical smoothing ask for more exposure than current highlights permit.
        filtered = min(self.target_ev, desired)-current.signal_ev
        # A prior bright scene must not command a decrease after this scene has
        # become darker. Hold until the smoothed target catches up instead.
        if error > 0:
            filtered = max(0, filtered)
        if not meter.clipping and abs(error) <= limits.hysteresis_ev:
            self.target_ev = current.signal_ev
            return result(current, 'stable')
        delta = max(-limits.max_down_ev, min(limits.max_up_ev, filtered))
        # Ignore tiny filtered steps; urgent negative errors are never held here.
        if delta >= 0 and delta <= limits.hysteresis_ev:
            return result(current, 'smoothing_hold')
        target = current.signal_ev+delta
        candidates = []
        for iso in limits.isos:
            for shutter in limits.usable_shutters:
                exposure = Exposure(shutter, iso, current.aperture)
                change = exposure.signal_ev-current.signal_ev
                if (-limits.max_down_ev-1e-10 <= change <= limits.max_up_ev+1e-10
                        and exposure.signal_ev <= target+1e-10
                        and (change <= 0 if delta < 0 else change >= 0)):
                    candidates.append(exposure)
        if not candidates:
            return result(current, 'limit_or_quantization_blocked')
        # Brightest non-overshooting pair, then lowest ISO/most photon exposure.
        best_ev = max(e.signal_ev for e in candidates)
        chosen = min((e for e in candidates if abs(e.signal_ev-best_ev) < 1e-10),
                     key=lambda e: e.iso)
        if chosen == current:
            status = 'limit_or_quantization_blocked'
        elif meter.clipping:
            status = 'clip_recovery'
        elif abs(chosen.signal_ev-target) > 1e-6:
            status = 'quantized_or_limited'
        else:
            status = 'adjust'
        return result(chosen, status)


def deflicker(brightness, exposures, *, target_ev=-4.0, window=1, max_correction_ev=6.0):
    """Return per-frame development corrections, never edits RAW data.

    window=1: ML-like fixed percentile target (flattens natural lighting changes).
    window>1: centered mean scene-EV trend after removing shutter/nominal ISO,
    anchored to the first scene sample and target. Preserves slow scene ramps,
    removes short flicker and exposure steps. Requires ordered, comparable frames.
    Camera gain transitions, composition changes and nonlinear developer curves
    require separate calibration; this is not a guarantee of flicker-free video.
    """
    if not brightness or len(brightness) != len(exposures):
        raise ValueError('nonempty, paired brightness/exposure sequence required')
    finite(target_ev, 'target_ev')
    finite(max_correction_ev, 'max_correction_ev')
    if max_correction_ev <= 0 or not isinstance(window, int) or window < 1 or window % 2 == 0:
        raise ValueError('positive correction bound and positive odd window required')
    if any(not math.isfinite(b) or not 0 < b < 1 for b in brightness):
        raise ValueError('deflicker percentile is black, clipped or invalid')
    if any(e.aperture != exposures[0].aperture for e in exposures):
        raise ValueError('aperture changed within sequence')
    measured = [math.log2(b) for b in brightness]
    scene = [v-e.signal_ev for v, e in zip(measured, exposures)]
    result = []
    radius = window//2
    for i, value in enumerate(measured):
        desired = target_ev
        if window > 1:
            local = scene[max(0, i-radius):min(len(scene), i+radius+1)]
            desired += sum(local)/len(local)-scene[0]
        correction = desired-value
        bounded = max(-max_correction_ev, min(max_correction_ev, correction))
        result.append(dict(correction_ev=bounded, requested_ev=correction,
                           limited=bounded != correction, target_ev=desired))
    return result
