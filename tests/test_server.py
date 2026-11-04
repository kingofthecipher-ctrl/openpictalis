"""Engine-free tests. A fake 'command' model writes a small PNG so the full render path runs without a GPU."""
import json, os, shlex, struct, sys, tempfile, threading, time, unittest, urllib.request, zlib
from unittest.mock import patch
from pathlib import Path

TEST_HOME = tempfile.TemporaryDirectory(prefix='openpictalis test ')
HOME = TEST_HOME.name

def tearDownModule():
    TEST_HOME.cleanup()
os.environ['OPENPICTALIS_HOME'] = HOME
os.environ['OPENPICTALIS_PORT'] = '18788'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpictalis import server  # noqa: E402

FAKE = Path(HOME) / 'fake_engine.py'
FAKE.write_text('''import struct, sys, zlib
out = sys.argv[sys.argv.index("-o") + 1]
w, h = int(sys.argv[sys.argv.index("--w") + 1]), int(sys.argv[sys.argv.index("--h") + 1])
def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
raw = b"".join(b"\\0" + b"\\x10\\x20\\x30\\x00" * w for _ in range(h))
open(out, "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
for i in range(1, 4): print(f"{i}/3 [", flush=True)
''')
PNG_1PX = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg=='


def fake_model():
    return server.add_custom({'name': 'Fake', 'engine': 'command', 'modes': ['generate', 'reference', 'transparent'], 'steps': '4',
                              'template': shlex.join([sys.executable, str(FAKE), '--p', '{prompt}', '--w', '{width}', '--h', '{height}', '{refs}', '-o', '{output}'])})


class CatalogTests(unittest.TestCase):
    def test_catalog_entries_are_complete(self):
        cat = server.catalog()
        ids = [m['id'] for m in cat['models']]
        self.assertEqual(len(ids), len(set(ids)))
        for m in cat['models']:
            self.assertIn(m['engine'], cat['engines'])
            self.assertTrue(set(m['modes']) <= set(server.MODES), m['id'])
            self.assertTrue(m['links'] and all(u.startswith('https://') for u in m['links'].values()), m['id'])
            if m['engine'] == 'mflux':
                self.assertTrue(set(m['modes']) <= set(m['commands']), m['id'])
        for u in cat['upscalers']:
            self.assertIn(u['engine'], ('realesrgan', 'mflux', 'sips'))
            self.assertTrue(set(u['scales']) <= {2, 4}, u['id'])

    def test_mflux_command(self):
        m = server.find_model('qwen-image-2.1-4bit')
        cmd = server.build_command(m, 'reference', 'make it blue', 'blurry', 1024, 768, 7, 30, 4.0, [Path('/r.png')], Path('/o.png'), False)
        self.assertEqual(cmd[cmd.index('--model') + 1], 'OsaurusAI/Qwen-Image-2.1-mflux-4bit')
        self.assertEqual(cmd[cmd.index('--image-paths') + 1], '/r.png')
        self.assertEqual(cmd[cmd.index('--negative-prompt') + 1], 'blurry')
        self.assertIn('--low-ram', cmd)

    def test_drawthings_command(self):
        m = server.find_model('flux2-klein-4b-drawthings')
        self.patch_cli = patch.object(server, 'drawthings_cli', return_value='/bin/dt')
        self.patch_cli.start()
        self.addCleanup(self.patch_cli.stop)
        cmd = server.build_command(m, 'reference', 'p', '', 512, 512, 1, 4, 1.0, [Path('/a.png'), Path('/b.png')], Path('/o.png'), False)
        self.assertEqual(cmd[:2], ['/bin/dt', 'generate'])
        self.assertEqual([cmd[i + 1] for i, a in enumerate(cmd) if a == '--image'], ['/a.png', '/b.png'])
        self.assertNotIn('--negative-prompt', cmd)


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m = fake_model()

    def setUp(self):
        ready = patch.object(server, 'model_status', return_value=('ready', ''))
        ready.start()
        self.addCleanup(ready.stop)

    def test_requires_prompt(self):
        with self.assertRaisesRegex(ValueError, 'prompt'): server.prepare({'model_id': self.m['id'], 'prompt': ' '})

    def test_reference_needs_image(self):
        with self.assertRaisesRegex(ValueError, 'reference'): server.prepare({'model_id': self.m['id'], 'mode': 'reference', 'prompt': 'x'})

    def test_size_snaps_to_unit(self):
        job = server.prepare({'model_id': self.m['id'], 'prompt': 'x', 'width': 1000, 'height': 700, 'seed': 5})
        self.assertEqual((job['w'], job['h'], job['seed']), (992, 704, 5))

    def test_mode_must_be_supported(self):
        with self.assertRaisesRegex(ValueError, 'does not support'):
            server.prepare({'model_id': 'z-image-turbo', 'mode': 'transparent', 'prompt': 'x'})

    def test_transparent_prompt_wrapping(self):
        self.patch_status = patch.object(server, 'model_status', return_value=('ready', ''))
        self.patch_status.start()
        self.addCleanup(self.patch_status.stop)
        job = server.prepare({'model_id': 'qwen-image-2.1-4bit', 'mode': 'transparent', 'prompt': 'a fox.'})
        self.assertTrue(job['prompt'].startswith('This is an RGBA image with transparency. a fox.'))

    def test_custom_model_validation(self):
        with self.assertRaisesRegex(ValueError, 'output'): server.validate_custom({'name': 'x', 'engine': 'command', 'modes': ['generate'], 'template': 'gen {prompt}'})
        with self.assertRaisesRegex(ValueError, 'mflux command'): server.validate_custom({'name': 'x', 'engine': 'mflux', 'modes': ['generate'], 'command': 'rm -rf', 'model': 'a/b'})


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = fake_model()
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        server.PORT = cls.httpd.server_port
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        server.save_settings({'output_dir': str(Path(HOME) / 'out')})

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None, token=True, headers=None):
        req = urllib.request.Request(f'http://127.0.0.1:{server.PORT}{path}', method='POST' if body is not None else 'GET',
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json', **({'X-Token': server.TOKEN} if token else {}), **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r: return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e: return e.code, e.read()

    def test_post_needs_token(self):
        self.assertEqual(self.call('/api/stop', {}, token=False)[0], 403)

    def test_foreign_host_is_rejected(self):
        self.assertEqual(self.call('/api/config', headers={'Host': 'attacker.example'})[0], 403)

    def test_foreign_origin_is_rejected_with_valid_token(self):
        self.assertEqual(self.call('/api/stop', {}, headers={'Origin': 'https://attacker.example'})[0], 403)

    def test_invalid_token_is_rejected(self):
        self.assertEqual(self.call('/api/stop', {}, headers={'X-Token': 'invalid'})[0], 403)

    def test_bundled_assets_are_served(self):
        for path in ['/assets/logo.svg', '/assets/fonts/OFL-Bricolage.txt', '/assets/fonts/BricolageGrotesque.woff2']:
            self.assertEqual(self.call(path)[0], 200, path)

    def test_render_reference_and_library(self):
        code, body = self.call('/api/render', {'model_id': self.m['id'], 'mode': 'reference', 'prompt': 'test', 'width': 256, 'height': 256, 'refs': [PNG_1PX]})
        self.assertEqual(code, 202, body)
        for _ in range(100):
            job = json.loads(self.call('/api/job')[1])
            if job['status'] != 'running': break
            time.sleep(0.05)
        self.assertEqual(job['status'], 'done', job.get('error'))
        media = job['media']
        self.assertEqual((media['width'], media['height'], media['alpha'], media['refs']), (256, 256, False, 1))
        code, png = self.call(media['url'])
        self.assertEqual((code, png[:4]), (200, b'\x89PNG'))
        library = json.loads(self.call('/api/library')[1])
        self.assertEqual(library[0]['id'], media['id'])
        self.assertEqual(json.loads(self.call('/api/delete', {'ids': [media['id']]})[1]), [])

    def test_upscale_validation(self):
        server.save_settings({'output_dir': str(Path(HOME) / 'out')})
        item = server.save_output(self.png(64, 48), {'mode': 'generate'})
        with self.assertRaisesRegex(ValueError, 'Choose an upscaler'): server.prepare_upscale({'media_id': item['id'], 'upscaler_id': 'nope'})
        with self.assertRaisesRegex(ValueError, 'Scale'): server.prepare_upscale({'media_id': item['id'], 'upscaler_id': 'resize', 'scale': 8})
        big = server.save_output(self.png(3000, 16), {'mode': 'generate'})
        with self.assertRaisesRegex(ValueError, 'limited'): server.prepare_upscale({'media_id': big['id'], 'upscaler_id': 'resize', 'scale': 4})

    @unittest.skipUnless(sys.platform == 'darwin', 'sips is macOS only')
    def test_simple_resize_upscale(self):
        item = server.save_output(self.png(64, 48), {'mode': 'transparent'})
        code, body = self.call('/api/upscale', {'media_id': item['id'], 'upscaler_id': 'resize', 'scale': 2})
        self.assertEqual(code, 202, body)
        for _ in range(100):
            job = json.loads(self.call('/api/job')[1])
            if job['status'] != 'running': break
            time.sleep(0.05)
        self.assertEqual(job['status'], 'done', job.get('error'))
        m = job['media']
        self.assertEqual((m['width'], m['height'], m['mode'], m['scale'], m['parent_id'], m['alpha']), (128, 96, 'upscale', 2, item['id'], True))

    def png(self, w, h):
        path = Path(HOME) / f'src-{w}x{h}.png'
        def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        raw = b''.join(b'\0' + b'\x10\x20\x30\x00' * w for _ in range(h))
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
        return path

    def test_unknown_media_is_rejected(self):
        self.assertEqual(self.call('/media/' + 'a' * 32)[0], 400)
        self.assertEqual(self.call('/assets/../server.py')[0], 404)


if __name__ == '__main__':
    unittest.main()
