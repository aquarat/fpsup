"""Behavioral tests using analytic RAW scenes and closed-loop simulations."""
from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np

from .core import Controller, Exposure, Limits, MeterConfig, deflicker, meter_raw
from .dng import crop_bounds, write_output, xmp


def scene(levels, size=20, black=(64, 128, 256, 512), white=(1064, 2128, 4256, 8512), config=MeterConfig()):
    colors = np.tile(np.array([[0, 1], [3, 2]]), (size, size))
    raw = np.empty(colors.shape)
    for c in range(4):
        raw[colors == c] = black[c]+levels[c]*(white[c]-black[c])
    return meter_raw(raw, colors, black, white, config)


class MeterTests(unittest.TestCase):
    def test_channel_calibration_and_red_highlight_protection(self):
        meter = scene((.8, .1, .1, .1))
        self.assertAlmostEqual(meter.tail, .8)
        self.assertAlmostEqual(meter.correction_ev, -math.log2(.8)-.5)
        self.assertAlmostEqual(meter.brightness, .1)
        self.assertLess(meter.correction_ev, 0)  # Averaging RGB would wrongly brighten.

    def test_green_planes_remain_independent(self):
        self.assertAlmostEqual(scene((.1, .1, .1, .9)).tail, .9)

    def test_exact_ignore_budget_includes_clipped_pixels(self):
        colors = np.tile(np.array([[0, 1], [3, 2]]), (10, 10))
        raw = np.full(colors.shape, 25.)
        raw[0, 0] = 100
        zero = meter_raw(raw, colors, [0]*4, [100]*4, MeterConfig(ignore_fraction=0))
        one = meter_raw(raw, colors, [0]*4, [100]*4, MeterConfig(ignore_fraction=.01))
        self.assertTrue(zero.clipping)
        self.assertEqual(zero.tail, 1)
        self.assertFalse(one.clipping)
        self.assertEqual(one.tail, .25)
        self.assertEqual(one.channels[0].ignored_samples, 1)
        raw[0, 2] = 100
        two = meter_raw(raw, colors, [0]*4, [100]*4, MeterConfig(ignore_fraction=.01))
        self.assertTrue(two.clipping)
        self.assertEqual(two.tail, 1)

    def test_small_highlight_not_lost_by_sampling(self):
        colors = np.tile(np.array([[0, 1], [3, 2]]), (100, 100))
        raw = np.ones(colors.shape)
        raw[193, 197] = 99
        meter = meter_raw(raw, colors, [0]*4, [100]*4, MeterConfig(ignore_fraction=0))
        self.assertEqual(meter.tail, .99)

    def test_black_frame_has_no_brightening_guess(self):
        meter = scene((0, 0, 0, 0))
        self.assertIsNone(meter.correction_ev)
        self.assertFalse(meter.valid_brightness)

    def test_invalid_raw_and_levels(self):
        colors = np.tile([[0, 1], [3, 2]], (2, 2))
        for raw, cfa, blacks, whites in [
            (np.zeros((2, 2)), colors, [0]*4, [1]*4),
            (np.full((4, 4), np.nan), colors, [0]*4, [1]*4),
            (np.zeros((4, 4)), colors, [1]*4, [1]*4),
            (np.zeros((4, 4)), colors, [0]*4, [math.inf]*4),
            (np.zeros((4, 4)), colors-1, [0]*4, [1]*4),
            (np.zeros((4, 4)), colors.astype(float), [0]*4, [1]*4),
        ]:
            with self.subTest(raw=raw, cfa=cfa), self.assertRaises(ValueError):
                meter_raw(raw, cfa, blacks, whites)

    def test_invalid_config(self):
        for kwargs in ({'ignore_fraction': -.1}, {'ignore_fraction': .5},
                       {'reserve_ev': math.nan}, {'percentile': 1}, {'minimum_signal': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                MeterConfig(**kwargs)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.limits = Limits(tuple(2**(n/3)/1000 for n in range(31)),
                             (100, 200, 400, 800), max_up_ev=1, smoothing=.5)
        self.current = Exposure(self.limits.shutters_s[9], 100, 2.8)

    def test_aperture_preserved_and_shutter_preferred_to_gain(self):
        plan = Controller(self.limits).plan(scene((.25,)*4), self.current, 0)
        self.assertEqual(plan.exposure.aperture, 2.8)
        self.assertEqual(plan.exposure.iso, 100)
        self.assertGreater(plan.photon_ev, 0)
        self.assertEqual(plan.gain_ev, 0)
        self.assertLessEqual(plan.applied_ev, 1+1e-9)

    def test_default_tables_allow_bounded_positive_progress(self):
        plan = Controller().plan(scene((.1,)*4), Exposure(1/1000, 100, 4), 0)
        self.assertTrue(0 < plan.applied_ev <= .5)

    def test_interval_budget_and_iso_ceiling(self):
        limits = replace(self.limits, interval_s=.1, overhead_s=.06)
        controller = Controller(limits)
        exposure = self.current
        for i in range(30):
            plan = controller.plan(scene((.001,)*4), exposure, i)
            exposure = plan.exposure
            self.assertLessEqual(exposure.shutter_s, .04)
            self.assertLessEqual(exposure.iso, 800)
        self.assertEqual(exposure.iso, 800)
        self.assertGreater(plan.residual_ev, 0)
        self.assertEqual(plan.status, 'limit_or_quantization_blocked')

    def test_clipping_bypasses_smoothing_and_is_bounded(self):
        controller = Controller(replace(self.limits, smoothing=.01))
        controller.plan(scene((.01,)*4), self.current, 0)
        plan = controller.plan(scene((1, .1, .1, .1)), self.current, 1)
        self.assertEqual(plan.status, 'clip_recovery')
        self.assertLessEqual(plan.applied_ev, -1+1e-9)
        self.assertGreaterEqual(plan.applied_ev, -2-1e-9)

    def test_old_bright_scene_never_commands_decrease_in_new_dark_scene(self):
        controller = Controller(replace(self.limits, smoothing=.01))
        controller.plan(scene((1,)*4), self.current, 0)
        plan = controller.plan(scene((.1,)*4), self.current, 1)
        self.assertGreaterEqual(plan.applied_ev, 0)

    def test_hysteresis_stops_near_target_oscillation(self):
        controller = Controller(self.limits)
        for i, error in enumerate((.02, -.02, .08, -.08)*5):
            level = 2**(-.5-error)
            plan = controller.plan(scene((level,)*4), self.current, i)
            self.assertEqual(plan.exposure, self.current)
            self.assertEqual(plan.status, 'stable')

    def test_closed_loop_constant_scene_converges_without_overshoot(self):
        controller = Controller(self.limits)
        exposure = self.current
        for i in range(30):
            level = .08*2**(exposure.signal_ev-self.current.signal_ev)
            plan = controller.plan(scene((level,)*4), exposure, i)
            self.assertLessEqual(level*2**plan.applied_ev, 2**(-.5)+1e-10)
            exposure = plan.exposure
        self.assertLessEqual(plan.residual_ev, 1/3+.001)
        self.assertGreaterEqual(plan.residual_ev, -.001)

    def test_no_assumed_application_or_integral_windup(self):
        controller = Controller(self.limits)
        plans = [controller.plan(scene((.08,)*4), self.current, i) for i in range(10)]
        self.assertEqual(len({p.exposure for p in plans}), 1)

    def test_stale_frames_and_aperture_changes_rejected(self):
        controller = Controller(self.limits)
        controller.plan(scene((.5,)*4), self.current, 5)
        for i, exposure in [(5, self.current), (3, self.current),
                            (6, replace(self.current, aperture=4))]:
            with self.subTest(i=i), self.assertRaises(ValueError):
                controller.plan(scene((.5,)*4), exposure, i)

    def test_unavailable_meter_holds_and_resets_filter(self):
        controller = Controller(self.limits)
        plan = controller.plan(scene((0,)*4), self.current, 0)
        self.assertEqual(plan.exposure, self.current)
        self.assertEqual(plan.status, 'meter_unavailable')
        self.assertIsNone(controller.target_ev)

    def test_invalid_actual_exposure_and_limits(self):
        for kwargs in ({'isos': (0, 100)}, {'shutters_s': (1, .5)},
                       {'interval_s': .01}, {'smoothing': 0}, {'max_up_ev': math.nan}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Limits(**kwargs)
        with self.assertRaises(ValueError):
            Controller(self.limits).plan(scene((.5,)*4), Exposure(.01, 125, 2.8), 0)
        with self.assertRaises(ValueError):
            Exposure(.1, 0, 2.8)

    def test_bounds_and_highlight_protection_over_scene_range(self):
        # Property-like sweep: independent photometric oracle, all supported ISOs.
        for iso in self.limits.isos:
            for level in (.002, .08, .2, .5, .7, .8, .95):
                current = replace(self.current, iso=iso)
                plan = Controller(self.limits).plan(scene((level,)*4), current, 0)
                self.assertTrue(-2-1e-9 <= plan.applied_ev <= 1+1e-9)
                self.assertEqual(plan.exposure.aperture, current.aperture)
                if plan.status not in ('stable', 'limit_or_quantization_blocked'):
                    self.assertLessEqual(level*2**plan.applied_ev, 2**(-.5)+1e-9)


class DeflickerTests(unittest.TestCase):
    def test_crop_uses_active_area_and_preserves_odd_origin(self):
        self.assertEqual(crop_bounds(dict(ActiveArea=(0, 0, 2170, 3856),
                                          DefaultCropOrigin=(8, 5),
                                          DefaultCropSize=(3840, 2160)), 2170, 3856),
                         (5, 8, 2165, 3848))
        self.assertEqual(crop_bounds(dict(ActiveArea=(10, 20, 110, 220),
                                          DefaultCropOrigin=(1, 1, 3, 1),
                                          DefaultCropSize=(100, 50)), 100, 200, 10, 20),
                         (3, 1, 53, 101))
        for tags in (dict(DefaultCropOrigin=(0, 0)),
                     dict(DefaultCropOrigin=(0, 0), DefaultCropSize=(201, 1)),
                     dict(DefaultCropOrigin=(1, 2, 0, 1), DefaultCropSize=(1, 1))):
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                crop_bounds(tags, 100, 200)

    def test_fixed_target_cancels_exposure_quantization(self):
        brightness = [.05, .1, .2, .1]
        exposures = [Exposure(t, 100, 4) for t in (.01, .02, .04, .02)]
        rows = deflicker(brightness, exposures)
        for b, row in zip(brightness, rows):
            self.assertAlmostEqual(b*2**row['correction_ev'], 1/16)

    def test_trend_preserves_slow_scene_ramp_and_removes_exposure_steps(self):
        exposures = [Exposure(.01*(2 if i%2 else 1), 100, 4) for i in range(11)]
        brightness = [.05*2**(.1*i)*(e.shutter_s/.01) for i, e in enumerate(exposures)]
        rows = deflicker(brightness, exposures, window=3)
        for i in range(1, 10):
            self.assertAlmostEqual(math.log2(brightness[i])+rows[i]['correction_ev'], -4+.1*i)

    def test_invalid_meter_and_aperture_fail(self):
        e = Exposure(.01, 100, 4)
        for brightness, exposures in [([0], [e]), ([1], [e]), ([math.nan], [e]),
                                       ([], []), ([.1, .1], [e]),
                                       ([.1, .1], [e, replace(e, aperture=8)])]:
            with self.subTest(brightness=brightness), self.assertRaises(ValueError):
                deflicker(brightness, exposures)
        with self.assertRaises(ValueError):
            deflicker([.1], [e], window=2)

    def test_correction_bound_is_explicit(self):
        row = deflicker([1e-8], [Exposure(.01, 100, 4)], max_correction_ev=3)[0]
        self.assertTrue(row['limited'])
        self.assertEqual(row['correction_ev'], 3)

    def test_xmp_sign_and_no_overwrite(self):
        xml = ET.fromstring(xmp(-1.25))
        desc = xml.find('.//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
        self.assertEqual(desc.attrib['{http://ns.adobe.com/camera-raw-settings/1.0/}Exposure2012'], '-1.250000')
        report = dict(frames=[dict(source='/source/foo.DNG', deflicker=dict(correction_ev=-1.25))])
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'out'
            write_output(out, report, True)
            before = (out/'000000-foo.xmp').read_bytes()
            with self.assertRaises(FileExistsError):
                write_output(out, report, True)
            self.assertEqual((out/'000000-foo.xmp').read_bytes(), before)

    def test_nonfinite_sidecar_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'out'
            with self.assertRaises(ValueError):
                write_output(out, dict(frames=[dict(source='x.DNG', value=math.nan)]))
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
