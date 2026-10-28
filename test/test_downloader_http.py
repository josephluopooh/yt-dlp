#!/usr/bin/env python3

# Allow direct execution
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import http.server
import re
import tempfile
import threading

from test.helper import http_server_port, try_rm
from yt_dlp import YoutubeDL
from yt_dlp.downloader.dash import DashSegmentsFD
from yt_dlp.downloader.hls import HlsFD
from yt_dlp.downloader.http import HttpFD
from yt_dlp.utils._utils import _YDLLogger as FakeLogger

TEST_DIR = os.path.dirname(os.path.abspath(__file__))


TEST_SIZE = 10 * 1024


class HTTPTestRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_content_range(self, total=None):
        range_header = self.headers.get('Range')
        start = end = None
        if range_header:
            mobj = re.search(r'^bytes=(\d+)-(\d+)', range_header)
            if mobj:
                start = int(mobj.group(1))
                end = int(mobj.group(2))
        valid_range = start is not None and end is not None
        if valid_range:
            content_range = f'bytes {start}-{end}'
            if total:
                content_range += f'/{total}'
            self.send_header('Content-Range', content_range)
        return (end - start + 1) if valid_range else total

    def serve(self, range=True, content_length=True, last_modified=False):
        self.send_response(200)
        self.send_header('Content-Type', 'video/mp4')
        size = TEST_SIZE
        if range:
            size = self.send_content_range(TEST_SIZE)
        if content_length:
            self.send_header('Content-Length', size)
        if last_modified:
            self.send_header('Last-Modified', 'Wed, 21 Oct 2015 07:28:00 GMT')
        self.end_headers()
        self.wfile.write(b'#' * size)

    def do_GET(self):
        if self.path == '/regular':
            self.serve()
        elif self.path.startswith('/hls-frag-'):
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp2t')
            self.send_header('Content-Length', '64')
            self.end_headers()
            self.wfile.write(b'#' * 64)
        elif self.path == '/last-modified':
            self.serve(last_modified=True)
        elif self.path == '/no-content-length':
            self.serve(content_length=False)
        elif self.path == '/no-range':
            self.serve(range=False)
        elif self.path == '/no-range-no-content-length':
            self.serve(range=False, content_length=False)
        else:
            assert False


class TestHttpFD(unittest.TestCase):
    def setUp(self):
        self.httpd = http.server.HTTPServer(
            ('127.0.0.1', 0), HTTPTestRequestHandler)
        self.port = http_server_port(self.httpd)
        self.server_thread = threading.Thread(target=self.httpd.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

    def download(self, params, ep):
        params['logger'] = FakeLogger()
        ydl = YoutubeDL(params)
        downloader = HttpFD(ydl, params)
        filename = 'testfile.mp4'
        try_rm(filename)
        self.assertTrue(downloader.real_download(filename, {
            'url': f'http://127.0.0.1:{self.port}/{ep}',
        }), ep)
        self.assertEqual(os.path.getsize(filename), TEST_SIZE, ep)
        try_rm(filename)

    def tearDown(self):
        self.httpd.shutdown()
        self.server_thread.join()
        self.httpd.server_close()

    def test_fragment_filetime(self):
        for concurrent_fragments in (1, 2, 4):
            with self.subTest(concurrent_fragments=concurrent_fragments), tempfile.TemporaryDirectory() as tempdir:
                params = {
                    'logger': FakeLogger(), 'updatetime': True,
                    'concurrent_fragment_downloads': concurrent_fragments,
                }
                filename = os.path.join(tempdir, 'video.mp4')
                with YoutubeDL(params) as ydl:
                    self.assertTrue(DashSegmentsFD(ydl, params).real_download(filename, {
                        'url': f'http://127.0.0.1:{self.port}/manifest.mpd',
                        'protocol': 'http_dash_segments',
                        'fragments': [
                            {'url': f'http://127.0.0.1:{self.port}/{ep}'}
                            for ep in ('last-modified', 'last-modified', 'regular')
                        ],
                    }))
                self.assertEqual(os.path.getsize(filename), TEST_SIZE * 3)
                self.assertEqual(os.path.getmtime(filename), 1445412480)

    def test_hls_max_filesize(self):
        manifest = '#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-MEDIA-SEQUENCE:0\n'
        manifest += ''.join(f'#EXTINF:1,\nhls-frag-{index}\n' for index in range(3))
        manifest += '#EXT-X-ENDLIST\n'
        for concurrent_fragments in (1, 3):
            for limit, succeeds in ((32, False), (100, False), (128, False), (192, True)):
                with self.subTest(concurrent_fragments=concurrent_fragments, limit=limit), tempfile.TemporaryDirectory() as tempdir:
                    params = {
                        'logger': FakeLogger(), 'max_filesize': limit,
                        'concurrent_fragment_downloads': concurrent_fragments,
                    }
                    filename = os.path.join(tempdir, 'video.mp4')
                    with YoutubeDL(params) as ydl:
                        result = HlsFD(ydl, params).real_download(filename, {
                            'id': 'test', 'ext': 'mp4', 'url': f'http://127.0.0.1:{self.port}/playlist.m3u8',
                            'hls_media_playlist_data': manifest,
                        })
                    self.assertEqual(result, succeeds)
                    if succeeds:
                        self.assertEqual(os.path.getsize(filename), 192)
                    else:
                        self.assertFalse(os.path.exists(filename))
                        self.assertLessEqual(os.path.getsize(f'{filename}.part'), limit)
                        self.assertFalse(any('-Frag' in name for name in os.listdir(tempdir)))

    def test_dash_max_filesize(self):
        for concurrent_fragments in (1, 3):
            with self.subTest(concurrent_fragments=concurrent_fragments), tempfile.TemporaryDirectory() as tempdir:
                params = {
                    'logger': FakeLogger(), 'max_filesize': TEST_SIZE + 1,
                    'concurrent_fragment_downloads': concurrent_fragments,
                }
                filename = os.path.join(tempdir, 'video.mp4')
                with YoutubeDL(params) as ydl:
                    result = DashSegmentsFD(ydl, params).real_download(filename, {
                        'url': f'http://127.0.0.1:{self.port}/manifest.mpd',
                        'protocol': 'http_dash_segments',
                        'fragments': [{'url': f'http://127.0.0.1:{self.port}/regular'}] * 3,
                    })
                self.assertFalse(result)
                self.assertFalse(os.path.exists(filename))
                self.assertLessEqual(os.path.getsize(f'{filename}.part'), TEST_SIZE + 1)

    def download_all(self, params):
        for ep in ('regular', 'no-content-length', 'no-range', 'no-range-no-content-length'):
            self.download(params, ep)

    def test_regular(self):
        self.download_all({})

    def test_chunked(self):
        self.download_all({
            'http_chunk_size': 1000,
        })


if __name__ == '__main__':
    unittest.main()
