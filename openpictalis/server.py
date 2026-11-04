"""OpenPictalis local server.

Standard-library only. Serves the web UI on 127.0.0.1 and runs one image render at a
time as a child process (mflux, Draw Things CLI, or a custom command). No ML framework
is loaded here; every render is a short-lived process that frees its memory on exit.
"""
import base64, binascii, glob, json, mimetypes, os, re, secrets, shlex, shutil, signal, struct, subprocess, sys, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VERSION = '0.1.0'
HERE = Path(__file__).resolve().parent
WEB = HERE / 'web'
CATALOG = HERE / 'catalog.json'
MODES = ('generate', 'reference', 'transparent')
PORT = int(os.environ.get('OPENPICTALIS_PORT', '8788'))
TOKEN = secrets.token_urlsafe(32)


def default_home():
    if os.environ.get('OPENPICTALIS_HOME'): return Path(os.environ['OPENPICTALIS_HOME']).expanduser()
    if sys.platform == 'darwin': return Path.home() / 'Library/Application Support/OpenPictalis'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'openpictalis'


HOME = default_home()
os.environ['PATH'] = os.pathsep.join([str(HERE / 'bin'), str(Path.home() / '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '')])

MU = threading.RLock()
JOB = None
PROC = None
STOP = threading.Event()


# ---------- state ----------

def read_json(path, default):
    try: return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError): return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2))
    tmp.replace(path)


DEFAULT_SETTINGS = {
    'output_dir': str(Path.home() / 'Pictures/OpenPictalis'),
    'drawthings_cli': '',
    'drawthings_models_dir': str(Path.home() / 'Library/Containers/com.liuliu.draw-things/Data/Documents/Models'),
    'lora_dir': str(HOME / 'LoRAs'),
    'realesrgan_cli': '',
    'realesrgan_models_dir': '',
    'hf_cache': str(Path(os.environ.get('HF_HUB_CACHE') or Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface')) / 'hub')),
}


def settings():
    return {**DEFAULT_SETTINGS, **read_json(HOME / 'settings.json', {})}


def save_settings(p):
    current = settings()
    for key in DEFAULT_SETTINGS:
        if key not in p: continue
        value = str(p[key]).strip()
        if value and not Path(value).expanduser().is_absolute(): raise ValueError(f'{key.replace("_", " ").capitalize()} must be a full path.')
        current[key] = str(Path(value).expanduser()) if value else ''
    if not current['output_dir']: raise ValueError('Choose an output folder.')
    out = Path(current['output_dir']); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=out): pass
    write_json(HOME / 'settings.json', {k: v for k, v in current.items() if v != DEFAULT_SETTINGS[k]})
    return current


# ---------- models ----------

def catalog():
    return json.loads(CATALOG.read_text())


def custom_models():
    return read_json(HOME / 'models.json', [])


def all_models():
    return [{**m, 'source': 'suggested'} for m in catalog()['models']] + [{**m, 'source': 'custom'} for m in custom_models()]


def find_model(ident):
    for m in all_models():
        if m['id'] == ident: return m
    raise ValueError('That model is not in the list. Choose another model.')


def drawthings_cli():
    configured = settings()['drawthings_cli']
    if configured: return configured if Path(configured).is_file() else None
    return shutil.which('draw-things-cli')


def lora_file(m):
    turbo = m.get('turbo')
    if not turbo: return None
    folders = [Path(settings()['lora_dir'])]
    if os.environ.get('OPENPICTALIS_LORA_DIR'): folders.insert(0, Path(os.environ['OPENPICTALIS_LORA_DIR']))
    files = [Path(f) for folder in folders for f in glob.glob(str(folder / turbo['file_glob']))]
    return max(files, key=lambda f: f.name) if files else None


def hf_cached(repo):
    folder = Path(settings()['hf_cache']) / ('models--' + repo.replace('/', '--')) / 'snapshots'
    return folder.is_dir() and any(folder.iterdir())


def download_note(m):
    size = m.get('download', '')
    return f'Weights download on first use ({size}).' if size.startswith('≈') else 'Weights download from Hugging Face on first use.'


def model_status(m):
    """Return (state, message). state: ready | download | missing."""
    engine = m.get('engine')
    if engine == 'mflux':
        commands = sorted(set(m.get('commands', {}).values()))
        missing = [c for c in commands if not shutil.which(c)]
        if missing: return 'missing', 'Install mflux: uv tool install --upgrade mflux'
        repo = m.get('repo')
        if repo and not hf_cached(repo): return 'download', download_note(m)
        return 'ready', 'Installed'
    if engine == 'drawthings':
        if not drawthings_cli(): return 'missing', 'Draw Things CLI not found. Set its path in Settings.'
        if not (Path(settings()['drawthings_models_dir']) / m['model']).is_file(): return 'missing', 'Model file not in the Draw Things models folder.'
        return 'ready', 'Installed'
    if engine == 'command':
        args = shlex.split(m.get('template', ''))
        if not args or not shutil.which(args[0]): return 'missing', 'Command not found.'
        return 'ready', 'Custom command'
    return 'missing', 'Unknown engine.'


def public_model(m):
    state, message = model_status(m)
    lora = lora_file(m)
    return {**m, 'status': state, 'status_text': message, 'turbo_available': bool(lora)}


def validate_custom(p):
    name = str(p.get('name', '')).strip()[:80]
    engine = p.get('engine')
    if not name: raise ValueError('Give the model a name.')
    if engine not in ('mflux', 'drawthings', 'command'): raise ValueError('Choose an engine.')
    modes = [m for m in MODES if m in (p.get('modes') or [])]
    if not modes: raise ValueError('Choose at least one mode.')
    entry = {'id': 'custom-' + uuid.uuid4().hex[:10], 'name': name, 'engine': engine, 'modes': modes,
             'size_unit': 16 if engine != 'drawthings' else 64, 'max_area': 4194304, 'max_refs': 10, 'negative': True,
             'links': {}, 'note': str(p.get('note', ''))[:300], 'tested': False, 'download': ''}
    for key in ('steps', 'guidance'):
        v = p.get(key)
        entry[key] = None if v in (None, '', 'auto') else (int(v) if key == 'steps' else float(v))
    link = str(p.get('link', '')).strip()
    if link:
        if not re.match(r'https?://', link): raise ValueError('Model link must start with https://')
        entry['links'] = {'weights': link}
    if engine == 'mflux':
        command = str(p.get('command', '')).strip()
        model = str(p.get('model', '')).strip()
        if not re.fullmatch(r'mflux-[a-z0-9.\-]+', command): raise ValueError('Enter an mflux command, for example mflux-generate-qwen-2.1-edit.')
        if not model: raise ValueError('Enter a model name, Hugging Face repo, or local path.')
        entry.update(commands={mode: command for mode in modes}, model=model)
        if re.fullmatch(r'[\w.\-]+/[\w.\-]+', model): entry['repo'] = model
        if p.get('base_model'): entry['base_model'] = str(p['base_model']).strip()
        if p.get('quantize'): entry['quantize'] = int(p['quantize'])
        if 'transparent' in modes: entry['transparent_prompt'] = 'This is an RGBA image with transparency. {prompt}. The image has alpha channel and the background is transparent.'
    elif engine == 'drawthings':
        model = str(p.get('model', '')).strip()
        if not model: raise ValueError('Enter the Draw Things model file, for example flux_2_klein_4b_q6p.ckpt.')
        entry['model'] = model
    else:
        template = str(p.get('template', '')).strip()
        if '{output}' not in template or '{prompt}' not in template: raise ValueError('The command template needs {prompt} and {output}.')
        shlex.split(template)
        entry['template'] = template
        entry['ref_flag'] = str(p.get('ref_flag', '--image')).strip() or '--image'
    return entry


def add_custom(p):
    entry = validate_custom(p)
    with MU:
        models = custom_models(); models.append(entry); write_json(HOME / 'models.json', models)
    return public_model({**entry, 'source': 'custom'})


def remove_custom(ident):
    with MU:
        models = custom_models()
        if not any(m['id'] == ident for m in models): raise ValueError('Only models you added can be removed.')
        write_json(HOME / 'models.json', [m for m in models if m['id'] != ident])
    return {'ok': True}


# ---------- upscalers ----------

def upscalers():
    return catalog().get('upscalers', [])


def find_upscaler(ident):
    for u in upscalers():
        if u['id'] == ident: return u
    raise ValueError('Choose an upscaler.')


def realesrgan_cli():
    configured = settings()['realesrgan_cli']
    if configured: return configured if Path(configured).is_file() else None
    return shutil.which('realesrgan-ncnn-vulkan')


def realesrgan_models():
    configured = settings()['realesrgan_models_dir']
    if configured: return Path(configured)
    cli = realesrgan_cli()
    if not cli: return None
    # The official release zip keeps weights in models/ beside the binary.
    for name in ('models', 'upscale-models'):
        if (Path(cli).parent / name).is_dir(): return Path(cli).parent / name
    return Path(cli).parent / 'models'


def upscaler_status(u):
    engine = u['engine']
    if engine == 'realesrgan':
        if not realesrgan_cli(): return 'missing', 'Real-ESRGAN not found. Download it, then set its path in Settings.'
        models = realesrgan_models()
        if not (models / (u['model'] + '.bin')).is_file(): return 'missing', f'{u["model"]}.bin is not in {models}.'
        return 'ready', 'Installed'
    if engine == 'mflux':
        if not shutil.which(u['command']): return 'missing', 'Install mflux: uv tool install --upgrade mflux'
        if u.get('repo') and not hf_cached(u['repo']): return 'download', download_note(u)
        return 'ready', 'Installed'
    if engine == 'sips':
        return ('ready', 'Built into macOS') if shutil.which('sips') else ('missing', 'Only available on macOS.')
    return 'missing', 'Unknown engine.'


def public_upscaler(u):
    state, message = upscaler_status(u)
    return {**u, 'status': state, 'status_text': message}


# ---------- library ----------

def records(): return read_json(HOME / 'library.json', [])


def public_item(item):
    return {**{k: v for k, v in item.items() if k != 'path'}, 'url': '/media/' + item['id'], 'filename': Path(item['path']).name}


def library():
    with MU: return [public_item(i) for i in records() if Path(i['path']).is_file()]


def find_item(ident):
    if not re.fullmatch('[a-f0-9]{32}', ident or ''): raise ValueError('Invalid image ID.')
    for i in records():
        if i['id'] == ident: return i
    raise ValueError('Image not found in the library.')


def png_info(path):
    """(width, height, has_alpha) from the PNG header, without Pillow."""
    with open(path, 'rb') as f: head = f.read(33)
    if head[:8] != b'\x89PNG\r\n\x1a\n': return None
    w, h, depth, color = struct.unpack('>IIBB', head[16:26])
    return w, h, color in (4, 6)


def save_output(src, info):
    if STOP.is_set(): raise RuntimeError('Stopped. Nothing was saved.')
    with MU:
        ident = uuid.uuid4().hex
        out = Path(settings()['output_dir']); out.mkdir(parents=True, exist_ok=True)
        dest = out / ('openpictalis-' + time.strftime('%Y%m%d-%H%M%S') + '-' + ident[:6] + '.png')
        shutil.copy2(src, dest)
        meta = png_info(dest)
        # Some engines always write RGBA; only Transparent renders are meant to have see-through pixels.
        if meta: info.update(width=meta[0], height=meta[1], alpha=meta[2] and (info.get('mode') == 'transparent' or info.pop('keep_alpha', False)))
        info.pop('keep_alpha', None)
        item = {**info, 'id': ident, 'path': str(dest), 'created': time.time()}
        items = records(); items.insert(0, item); write_json(HOME / 'library.json', items)
        return public_item(item)


def delete_items(ids):
    if not isinstance(ids, list): raise ValueError('Choose images to remove.')
    with MU:
        items = records(); keep = []
        for i in items:
            if i['id'] in ids:
                src = Path(i['path'])
                if src.is_file():
                    trash = src.parent / '.openpictalis-trash'; trash.mkdir(exist_ok=True)
                    shutil.move(str(src), str(trash / src.name))
            else: keep.append(i)
        write_json(HOME / 'library.json', keep)
    return library()


# ---------- rendering ----------

def integer(value, low, high, name):
    try: n = int(value)
    except (TypeError, ValueError): raise ValueError(f'{name} must be a whole number.')
    if not low <= n <= high: raise ValueError(f'{name} must be between {low} and {high}.')
    return n


def decode_image(data, path):
    if isinstance(data, str) and data.startswith('/media/'):
        with MU: item = find_item(data.split('/')[-1])
        shutil.copyfile(item['path'], path); return
    if not isinstance(data, str) or len(data) > 40 * 1024 * 1024 or not re.match(r'data:image/(png|jpeg|webp);base64,', data):
        raise ValueError('References must be PNG, JPEG or WebP images under 30 MB.')
    try: raw = base64.b64decode(data.split(',', 1)[1], validate=True)
    except binascii.Error: raise ValueError('A reference image could not be read.')
    if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff') or (raw[:4] == b'RIFF' and raw[8:12] == b'WEBP')):
        raise ValueError('A reference is not a supported image.')
    path.write_bytes(raw)


def build_command(m, mode, prompt, negative, w, h, seed, steps, guidance, refs, out, turbo):
    engine = m['engine']
    if engine == 'mflux':
        cmd = [shutil.which(m['commands'][mode]) or m['commands'][mode], '--model', m['model'], '--prompt', prompt,
               '--width', str(w), '--height', str(h), '--seed', str(seed), '--output', str(out)]
        if m.get('base_model'): cmd += ['--base-model', m['base_model']]
        if m.get('quantize'): cmd += ['--quantize', str(m['quantize'])]
        if negative and m.get('negative', True): cmd += ['--negative-prompt', negative]
        if turbo:
            lora = lora_file(m)
            cmd += [str(lora) if a == '{lora}' else a for a in m['turbo']['args']]
        if steps: cmd += ['--steps', str(steps)]
        if guidance is not None: cmd += ['--guidance', str(guidance)]
        if refs: cmd += ['--image-paths', *map(str, refs)]
        return cmd + list(m.get('extra_args', []))
    if engine == 'drawthings':
        cli = drawthings_cli()
        if not cli: raise ValueError('Draw Things CLI not found. Set its path in Settings.')
        cmd = [cli, 'generate', '--local', '--offline', '--no-download-missing', '--models-dir', settings()['drawthings_models_dir'],
               '--model', m['model'], '--disable-preview', '--prompt', prompt, '--width', str(w), '--height', str(h), '--seed', str(seed), '--output', str(out)]
        if negative: cmd += ['--negative-prompt', negative]
        if steps: cmd += ['--steps', str(steps)]
        if guidance is not None: cmd += ['--cfg', str(guidance)]
        if refs: cmd += ['--crop'] + [a for r in refs for a in ('--image', str(r))]
        return cmd
    values = dict(prompt=prompt, negative=negative, width=w, height=h, seed=seed, steps=steps or '', guidance='' if guidance is None else guidance, output=out)
    cmd = []
    for arg in shlex.split(m['template']):
        if arg == '{refs}': cmd += [a for r in refs for a in (m.get('ref_flag', '--image'), str(r))]
        else: cmd.append(arg.format(**values))
    return cmd


def stop_render():
    with MU:
        STOP.set(); p = PROC
    if not p: return
    try: os.killpg(p.pid, signal.SIGTERM)
    except ProcessLookupError: return
    try: p.wait(timeout=3)
    except subprocess.TimeoutExpired: pass
    try: os.killpg(p.pid, signal.SIGKILL)
    except ProcessLookupError: pass


def run(cmd):
    global PROC
    with MU:
        if STOP.is_set(): raise RuntimeError('Stopped before the render started.')
        PROC = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                                env={k: v for k, v in os.environ.items() if k != 'VIRTUAL_ENV'})
        p = PROC
    try:
        while True:
            chunk = os.read(p.stdout.fileno(), 4096)
            if not chunk: break
            text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', chunk.decode('utf-8', 'replace'))
            # mflux prints tqdm bars ("3/6 ["); the Draw Things CLI prints "[█] 63 %".
            steps = re.findall(r'(\d+)/(\d+) \[', text)
            percent = re.findall(r'(\d{1,3})\s*%', text)
            with MU:
                JOB['log'] = (JOB['log'] + text)[-8000:]
                if steps and int(steps[-1][1]): JOB['progress'] = int(steps[-1][0]) / int(steps[-1][1])
                elif percent: JOB['progress'] = min(int(percent[-1]), 100) / 100
            print(text, end='', flush=True)
        rc = p.wait()
        if STOP.is_set(): raise RuntimeError('Stopped. The render process was ended; nothing was saved.')
        if rc: raise RuntimeError(f'The engine exited with code {rc}. Open Details for its log.')
    finally:
        with MU: PROC = None
        p.stdout.close()
        if p.poll() is None:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            p.wait()


def prepare(p):
    """Validate a render request. Returns everything render() needs, or raises ValueError."""
    m = find_model(p.get('model_id', ''))
    mode = p.get('mode', 'generate')
    if mode not in MODES: raise ValueError('Choose Image, Reference or Transparent.')
    if mode not in m['modes']: raise ValueError(f'{m["name"]} does not support {mode} mode. Pick another model.')
    state, message = model_status(m)
    if state == 'missing': raise ValueError(message)
    prompt = str(p.get('prompt', '')).strip()
    if not prompt: raise ValueError('Write a prompt first.')
    if len(prompt) > 8000: raise ValueError('The prompt is too long.')
    negative = str(p.get('negative', '')).strip()[:2000] if m.get('negative', True) else ''
    unit = m.get('size_unit', 16)
    w = integer(p.get('width', 1024), 256, 4096, 'Width'); h = integer(p.get('height', 1024), 256, 4096, 'Height')
    w, h = max(256, round(w / unit) * unit), max(256, round(h / unit) * unit)
    if w * h > m.get('max_area', 4194304): raise ValueError('That size is too large for this model. Choose a smaller size.')
    seed = integer(p['seed'], 0, 2**32 - 1, 'Seed') if str(p.get('seed', '')).strip() else secrets.randbelow(2**32)
    turbo = bool(p.get('turbo')) and bool(m.get('turbo'))
    if turbo and not lora_file(m): raise ValueError('Turbo LoRA file not found. Put it in the LoRA folder (Settings) or turn Turbo off.')
    if turbo: steps, guidance = m['turbo']['steps'], m['turbo']['guidance']
    else:
        steps = integer(p['steps'], 1, 150, 'Steps') if p.get('steps') else m.get('steps')
        guidance = float(p['guidance']) if p.get('guidance') not in (None, '') and m.get('guidance') is not None else m.get('guidance')
        if guidance is not None and not 0 <= guidance <= 30: raise ValueError('Guidance must be between 0 and 30.')
    refs = p.get('refs') or []
    if not isinstance(refs, list): raise ValueError('Invalid references.')
    if mode == 'reference' and not refs: raise ValueError('Add at least one reference image.')
    if mode != 'reference': refs = []
    if len(refs) > m.get('max_refs', 1): raise ValueError(f'{m["name"]} takes at most {m.get("max_refs", 1)} references.')
    if mode == 'transparent':
        prompt = m.get('transparent_prompt', '{prompt}').replace('{prompt}', prompt.rstrip('. '))
    return dict(m=m, mode=mode, prompt=prompt, user_prompt=str(p['prompt']).strip(), negative=negative, w=w, h=h, seed=seed, steps=steps, guidance=guidance, refs=refs, turbo=turbo)


def render(job):
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='openpictalis-') as t:
        t = Path(t); out = t / 'output.png'; paths = []
        for n, data in enumerate(job['refs']):
            f = t / f'reference{n}.png'; decode_image(data, f); paths.append(f)
        cmd = build_command(job['m'], job['mode'], job['prompt'], job['negative'], job['w'], job['h'], job['seed'], job['steps'], job['guidance'], paths, out, job['turbo'])
        with MU: JOB['command'] = shlex.join(cmd)
        run(cmd)
        if not out.is_file() or out.stat().st_size == 0: raise RuntimeError('The engine finished but did not write an image.')
        info = {'mode': job['mode'], 'model_id': job['m']['id'], 'model': job['m']['name'], 'prompt': job['user_prompt'], 'negative': job['negative'],
                'seed': job['seed'], 'steps': job['steps'], 'guidance': job['guidance'], 'turbo': job['turbo'], 'refs': len(paths),
                'seconds': round(time.monotonic() - start)}
        return save_output(out, info)


def prepare_upscale(p):
    with MU: item = find_item(str(p.get('media_id', '')))
    u = find_upscaler(p.get('upscaler_id', ''))
    scale = integer(p.get('scale', 2), 2, 4, 'Scale')
    if scale not in u['scales']: raise ValueError(f'{u["name"]} supports {" or ".join(str(s) + "×" for s in u["scales"])}.')
    w, h = item['width'] * scale, item['height'] * scale
    if max(w, h) > u.get('max_side', 8192): raise ValueError(f'That would be {w} × {h}; {u["name"]} is limited to {u.get("max_side", 8192)} px. Choose a smaller scale.')
    state, message = upscaler_status(u)
    if state == 'missing': raise ValueError(message)
    return dict(kind='upscale', u=u, item=item, scale=scale, w=w, h=h)


def render_upscale(job):
    start = time.monotonic(); u, item = job['u'], job['item']
    w, h = str(job['w']), str(job['h'])
    with tempfile.TemporaryDirectory(prefix='openpictalis-up-') as t:
        t = Path(t); src = t / 'source.png'; out = t / 'upscaled.png'
        shutil.copyfile(item['path'], src)
        if u['engine'] == 'realesrgan':
            raw = t / 'native.png'
            # Small tiles and one worker thread keep GPU memory low; no TTA passes.
            cmds = [[realesrgan_cli(), '-i', str(src), '-o', str(raw), '-m', str(realesrgan_models()), '-n', u['model'],
                     '-s', str(u['native_scale']), '-t', '64', '-j', '1:1:1', '-f', 'png']]
            if job['scale'] != u['native_scale']: cmds.append(['sips', '-s', 'format', 'png', '-z', h, w, str(raw), '--out', str(out)])
            else: out = raw
        elif u['engine'] == 'mflux':
            cmds = [[shutil.which(u['command']), '--model', u['model'], '--image-path', str(src), '--resolution', f'{job["scale"]}x',
                     '--seed', '42', '--output', str(out), *u.get('extra_args', [])]]
        else:
            cmds = [['sips', '-s', 'format', 'png', '-z', h, w, str(src), '--out', str(out)]]
        with MU: JOB['command'] = '\n'.join(shlex.join(c) for c in cmds)
        for cmd in cmds: run(cmd)
        if not out.is_file() or out.stat().st_size == 0: raise RuntimeError('The upscaler finished but did not write an image.')
        info = {k: item[k] for k in ('prompt', 'negative', 'model_id', 'model', 'seed') if k in item}
        info.update(mode='upscale', source_mode=item.get('mode'), upscaler=u['name'], scale=job['scale'], parent_id=item['id'],
                    keep_alpha=bool(item.get('alpha')) and u.get('alpha', False), seconds=round(time.monotonic() - start))
        return save_output(out, info)


def worker(job):
    try:
        media = render_upscale(job) if job.get('kind') == 'upscale' else render(job)
        with MU: JOB.update(status='done', media=media, progress=1)
    except Exception as e:
        with MU: JOB.update(status='stopped' if STOP.is_set() else 'error', error=str(e))
    finally:
        with MU: JOB['elapsed'] = round(time.monotonic() - JOB['started'])


def start_job(p, kind='render'):
    global JOB
    job = prepare_upscale(p) if kind == 'upscale' else prepare(p)
    name = job['u']['name'] if kind == 'upscale' else job['m']['name']
    with MU:
        if JOB and JOB['status'] == 'running': raise ValueError('A render is already running. Stop it or wait.')
        Path(settings()['output_dir']).mkdir(parents=True, exist_ok=True)
        STOP.clear()
        JOB = {'id': uuid.uuid4().hex, 'status': 'running', 'started': time.monotonic(), 'elapsed': 0, 'progress': 0,
               'log': f'Loading {name}…\n', 'model': name, 'mode': 'upscale' if kind == 'upscale' else job['mode'],
               'width': job['w'], 'height': job['h'], 'seed': job.get('seed'), 'steps': job.get('steps')}
        threading.Thread(target=worker, args=(job,), daemon=True).start()
        return dict(JOB)


def job_state():
    with MU:
        if not JOB: return {'status': 'idle'}
        data = dict(JOB)
        if data['status'] == 'running': data['elapsed'] = round(time.monotonic() - data['started'])
        return data


def config():
    cat = catalog()
    return {'version': VERSION, 'token': TOKEN, 'settings': settings(), 'models': [public_model(m) for m in all_models()],
            'engines': cat['engines'], 'upscalers': [public_upscaler(u) for u in upscalers()], 'library': library(), 'job': job_state()}


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data, ctype='application/json', headers=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError): pass

    def local(self):
        return self.headers.get('Host', '') in (f'127.0.0.1:{PORT}', f'localhost:{PORT}')

    def do_GET(self):
        if not self.local(): return self.reply(403, {'error': 'Local requests only.'})
        url = urlsplit(self.path); path = url.path
        try:
            if path in ('/', '/index.html'): return self.reply(200, (WEB / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            if path.startswith('/assets/'):
                f = (WEB / path.lstrip('/')).resolve()
                if WEB not in f.parents or not f.is_file(): return self.reply(404, {'error': 'Not found.'})
                return self.reply(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
            if path == '/api/health': return self.reply(200, {'app': 'openpictalis', 'version': VERSION})
            if path == '/api/config': return self.reply(200, config())
            if path == '/api/models': return self.reply(200, [public_model(m) for m in all_models()])
            if path == '/api/job': return self.reply(200, job_state())
            if path == '/api/library': return self.reply(200, library())
            if path.startswith('/media/'):
                with MU: item = find_item(path.split('/')[-1])
                f = Path(item['path'])
                headers = {'Content-Disposition': f'attachment; filename="{f.name}"'} if parse_qs(url.query).get('download') == ['1'] else {}
                return self.reply(200, f.read_bytes(), 'image/png', headers)
            return self.reply(404, {'error': 'Not found.'})
        except Exception as e: return self.reply(400, {'error': str(e)})

    def do_POST(self):
        origin = self.headers.get('Origin')
        if not self.local() or (origin and origin not in (f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}')) or self.headers.get('X-Token') != TOKEN:
            return self.reply(403, {'error': 'Reload the page to reconnect.'})
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if not 0 <= n <= 120 * 1024 * 1024: raise ValueError('Request is too large.')
            p = json.loads(self.rfile.read(n) or b'{}'); path = urlsplit(self.path).path
            if path == '/api/render': return self.reply(202, start_job(p))
            if path == '/api/upscale': return self.reply(202, start_job(p, 'upscale'))
            if path == '/api/stop': stop_render(); return self.reply(200, {'ok': True})
            if path == '/api/settings':
                with MU:
                    if JOB and JOB['status'] == 'running': raise ValueError('Wait for the render to finish before changing settings.')
                    return self.reply(200, save_settings(p))
            if path == '/api/models': return self.reply(200, add_custom(p))
            if path == '/api/models/remove': return self.reply(200, remove_custom(p.get('id')))
            if path == '/api/delete': return self.reply(200, delete_items(p.get('ids')))
            return self.reply(404, {'error': 'Not found.'})
        except Exception as e: return self.reply(400, {'error': str(e)})

    def log_message(self, *args): pass


def main():
    HOME.mkdir(parents=True, exist_ok=True)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: (stop_render(), os._exit(0)))
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'OpenPictalis {VERSION} · http://127.0.0.1:{PORT}', flush=True)
    if '--open' in sys.argv and sys.platform == 'darwin': subprocess.Popen(['open', f'http://127.0.0.1:{PORT}'])
    server.serve_forever()


if __name__ == '__main__':
    main()
