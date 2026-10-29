import unittest

import numpy as np
from fpl_scan_measure import compare


class ScanMeasure(unittest.TestCase):
    def test_recovers_scan_difference_with_shared_geometric_slant(self):
        h, w, period, hz = 300, 800, 160, 2
        y, x = np.mgrid[:h, :w]
        def target(scan, phase):
            return 100 + 80*np.cos(2*np.pi*(x/period - hz*scan*y/(h-1)) + .003*y + phase)
        result = compare(target(.04, .2), target(.24, 1.7), period=period,
                         crop=(0, 0, w, h), speed=.5)
        self.assertAlmostEqual(result['signed_scan_difference_ms'], 200, delta=.2)
        # A wrong target speed must change the measurement, not silently pass.
        wrong = compare(target(.04, .2), target(.24, 1.7), period=period,
                        crop=(0, 0, w, h), speed=1)
        self.assertAlmostEqual(wrong['signed_scan_difference_ms'], 100, delta=.2)

    def test_blank_and_too_small_images_rejected(self):
        blank = np.ones((100, 500))
        for crop in [(0, 0, 500, 100), (0, 0, 50, 100)]:
            with self.assertRaises(ValueError):
                compare(blank, blank, period=100, crop=crop)


if __name__ == '__main__':
    unittest.main()
