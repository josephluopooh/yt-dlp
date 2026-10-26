#!/usr/bin/env python3

# Allow direct execution
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yt_dlp.utils._jsruntime import DenoJsRuntime


class TestDenoJsRuntime(unittest.TestCase):
    def test_version_with_startup_warning(self):
        for warning in ('', 'Failed getting cwd: No such file or directory (os error 2)\n'):
            with self.subTest(warning=warning), patch(
                'yt_dlp.utils._jsruntime._get_exe_version_output',
                return_value=(
                    f'{warning}deno 2.9.1 (stable, release, x86_64-unknown-linux-gnu)\n'
                    'v8 14.9.207.2-rusty\ntypescript 6.0.3\n'
                ),
            ):
                info = DenoJsRuntime('deno').info
                self.assertEqual(info.version, '2.9.1')
                self.assertEqual(info.version_tuple, (2, 9, 1))
                self.assertTrue(info.supported)


if __name__ == '__main__':
    unittest.main()
