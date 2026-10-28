#!/usr/bin/env python3

import concurrent.futures
import os
import tempfile
import threading
import unittest

from yt_dlp import YoutubeDL
from yt_dlp.downloader.fragment import FragmentFD
from yt_dlp.utils._utils import _YDLLogger as FakeLogger


class TestFragmentFD(unittest.TestCase):
    def test_stdout_fragments_do_not_collide(self):
        barrier = threading.Barrier(2)

        class FakeDownloader:
            params = {'continuedl': False}

            def __init__(self, payload, wait_for_other=True):
                self.payload = payload
                self.wait_for_other = wait_for_other

            def download(self, filename, info_dict):
                with open(filename, 'wb') as stream:
                    stream.write(self.payload)
                if self.wait_for_other:
                    barrier.wait(timeout=5)
                return True, True

        with tempfile.TemporaryDirectory() as tempdir, YoutubeDL({'logger': FakeLogger()}) as ydl:
            old_cwd = os.getcwd()
            os.chdir(tempdir)
            try:
                fd = FragmentFD(ydl, {})

                def download(payload, tmpfilename='-'):
                    ctx = {'tmpfilename': tmpfilename, 'fragment_index': 1,
                           'dl': FakeDownloader(payload, wait_for_other=tmpfilename == '-')}
                    self.assertTrue(fd._download_fragment(ctx, 'https://example.invalid/fragment', {}))
                    return ctx['fragment_filename_sanitized'], fd._read_fragment(ctx)

                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(download, b'A' * 64)
                    second = pool.submit(download, b'B' * 64)
                    first_name, first_data = first.result()
                    second_name, second_data = second.result()

                self.assertEqual(first_data, b'A' * 64)
                self.assertEqual(second_data, b'B' * 64)
                self.assertNotEqual(first_name, second_name)

                regular_name, regular_data = download(b'C' * 64, 'video.mp4.part')
                self.assertEqual(regular_name, 'video.mp4.part-Frag1')
                self.assertEqual(regular_data, b'C' * 64)
            finally:
                os.chdir(old_cwd)


if __name__ == '__main__':
    unittest.main()
