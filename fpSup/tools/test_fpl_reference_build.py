"""Reference-build contract checks; actual compiler/emulator tests run in the driver."""
import struct
import unittest

import fpl_reference_build as R


class ReferenceContract(unittest.TestCase):
    def test_thumb_target_is_selected_by_target_not_only_mthumb(self):
        args = R.zig_arguments(['--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb'])
        self.assertEqual(args[:3], ['-target', 'thumb-freestanding-eabi', '-mcpu=cortex_a9'])
        self.assertIn('-fno-unwind-tables', args)
        self.assertIn('-fno-asynchronous-unwind-tables', args)

    def test_existing_assembly_target_stays_arm(self):
        self.assertEqual(R.zig_arguments(['-target', 'armv7-none-eabi', '-c', 'gyr2.S'])[:4],
                         ['-target', 'arm-freestanding-eabi', '-c', 'gyr2.S'])

    def test_unknown_target_is_refused(self):
        with self.assertRaises(ValueError):
            R.zig_arguments(['--target=aarch64-linux-gnu'])

    def test_release_header_and_corruptions(self):
        words = [0x31425346, 32, 36, 60880, 32, int.from_bytes(b'GYR2', 'little'), 6, 1]
        blob = struct.pack('<8I', *words) + b'\0' * 4
        self.assertEqual(R.gyro_header(blob)['block'], 60880)
        for index, value in ((0, 0), (1, 28), (2, 40), (3, 32), (3, 60881),
                             (4, 33), (5, 0), (6, 5), (7, 4)):
            changed = words.copy()
            changed[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                R.gyro_header(struct.pack('<8I', *changed) + b'\0' * 4)

    def test_truncated_header_is_refused(self):
        with self.assertRaises(ValueError):
            R.gyro_header(b'FSB1')


if __name__ == '__main__':
    unittest.main()
