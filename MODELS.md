# Models

OpenPictalis does not ship model weights. Each model below is run by an engine you install, and its weights download from Hugging Face (or the Draw Things model list) the first time you use it. Swap between them any time from the **Model** menu; the **Models** dialog shows what is installed, what will download, and each model's links.

The list lives in [`openpictalis/catalog.json`](openpictalis/catalog.json). Pull requests that add well-tested models are welcome.

## Suggested models

### Qwen-Image 2.1 · 4-bit (default)

- Weights: https://huggingface.co/OsaurusAI/Qwen-Image-2.1-mflux-4bit (about 10.6 GB)
- Original: https://huggingface.co/Qwen/Qwen-Image-2.1
- Modes: Image, Reference (up to 10), Transparent
- Engine: `mflux-generate-qwen-2.1-edit`
- License: Qwen Research License. Read it before any commercial use.
- Tested on an M2 Max with 32 GB. Runs with `--low-ram` and tiled VAE decoding by default.

Transparent mode uses Qwen-Image 2.1's RGBA VAE. The app adds the model's recommended wording ("This is an RGBA image with transparency… the background is transparent") around your prompt and saves a PNG with an alpha channel.

**Turbo LoRA (optional):** [Viggle/Qwen-Image-2.1-viggle-turbo](https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo). Download `Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r256.safetensors` (1.3 GB) into the LoRA folder from Settings. With Turbo on, renders use 6 steps and guidance 1. Requires mflux 0.22 or newer.

### Qwen-Image 2.1 · 8-bit

- Weights: https://huggingface.co/OsaurusAI/Qwen-Image-2.1-mflux-8bit (about 18.5 GB)
- Same modes and license as 4-bit. Better fidelity; 48 GB of memory or more is suggested. Not yet tested by the maintainers.

### FLUX.2 Klein 4B

- Weights: https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- Modes: Image, Reference (up to 4)
- License: Apache-2.0
- Two ways to run it:
  - **Draw Things CLI** (tested): install the model in [Draw Things](https://drawthings.ai) or point Settings at a folder containing `flux_2_klein_4b_q6p.ckpt`, and install `draw-things-cli` from the [community releases](https://github.com/drawthingsai/draw-things-community/releases). About 10–15 s for a 512 px image on an M2 Max once loaded.
  - **mflux** (`mflux-generate-flux2` / `mflux-generate-flux2-edit`, quantized to 8-bit).

### Z-Image Turbo

- Weights: https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- Mode: Image. About 9 steps, no guidance.
- License: Apache-2.0

### Qwen-Image-Edit 2511

- Weights: https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- Mode: Reference (up to 3)
- License: Apache-2.0. Quantized to 4-bit on load.

### Ming-Image 0.1 Design

- Weights: https://huggingface.co/inclusionAI/Ming-Image-0.1-Design
- Modes: Image, Transparent (native RGBA output; good for logos and stickers)
- License: MIT

## Upscalers

Open any image and press **Upscale**. The upscaled copy is saved as a new library image; the original is kept.

### Real-ESRGAN x4plus (recommended)

- Project: https://github.com/xinntao/Real-ESRGAN · Download: https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0 (`realesrgan-ncnn-vulkan-20220424-macos.zip`, 52 MB; Linux and Windows builds too)
- 4× model; 2× runs at 4× and scales down. Keeps transparency. Up to 8192 px.
- License: BSD-3-Clause
- Tested on an M2 Max: 1024 → 2048 px in about 30 s, alpha preserved. Uses 64 px tiles and one thread to keep memory low.

### Real-ESRGAN x4plus Anime

- Docs: https://github.com/xinntao/Real-ESRGAN/blob/master/docs/anime_model.md
- Same binary and zip (`realesrgan-x4plus-anime` in `models/`). For flat-colour art, logos and stickers.

### SeedVR2 3B

- Weights: https://huggingface.co/ByteDance-Seed/SeedVR2-3B (run by `mflux-upscale-seedvr2`; downloads on first use)
- Diffusion super-resolution that creates new detail. Slower and needs more memory; output has no transparency. Up to 4096 px.
- License: Apache-2.0. Not yet tested by the maintainers.

### Simple resize

- macOS `sips` resampling. Instant, keeps transparency, adds no detail.

## Engines

| Engine | Install | Notes |
|---|---|---|
| [mflux](https://github.com/mflux-community/mflux) | `uv tool install --upgrade mflux` | MLX on Apple Silicon. OpenPictalis finds its commands on `PATH` or in `~/.local/bin`. |
| [Draw Things CLI](https://github.com/drawthingsai/draw-things-community/releases) | Download `draw-things-cli`, then set its path in Settings or put it on `PATH` | Runs Draw Things `.ckpt` models offline. GPL-3.0. |
| Custom command | Anything that writes a PNG | See below. Works on Linux and Windows too. |

## Custom models

Open **Models → Add a model**. Three kinds:

- **mflux:** an mflux command (for example `mflux-generate-qwen-2.1-edit`) plus a model alias, Hugging Face repo, or local path. Optional base model and quantization. Use this for fine-tunes and other mflux-supported models.
- **Draw Things CLI:** a model file name from your Draw Things models folder.
- **Custom command:** a command template for any generator. Placeholders:

  | Placeholder | Value |
  |---|---|
  | `{prompt}` `{negative}` | Prompt text (passed as one argument) |
  | `{width}` `{height}` | Size in pixels |
  | `{seed}` `{steps}` `{guidance}` | Settings (`{steps}`/`{guidance}` are empty on "auto") |
  | `{output}` | PNG path the command must write |
  | `{refs}` | Expands to `--image a.png --image b.png …` (flag configurable) |

  Example (diffusers script): `python3 /path/gen.py --prompt {prompt} --width {width} --height {height} --seed {seed} {refs} --out {output}`

Custom models are saved in `models.json` in the app's data folder, not in the repository.
