# Contributing

Thanks for helping. OpenPictalis aims to stay small: a standard-library Python server, one HTML file, and a JSON model catalog.

## Setup

```bash
git clone https://github.com/kingofthecipher-ctrl/openpictalis.git
cd openpictalis
python3 -m openpictalis --open     # run the app
python3 -m unittest discover -s tests   # run the tests (no GPU needed)
```

## Guidelines

- **No new Python dependencies** in the server. Engines are separate programs.
- **UI changes** follow the brand in `docs/brand/`: Ground `#0B0C10`, Panel `#12141A`, Line `#23262F`; accents Amber `#FFB547`, Rose `#FF5C8A`, Indigo `#6C7CFF`, Teal `#2FD6C5`; Bricolage Grotesque for display, IBM Plex Mono for controls and values.
- **Adding a model** to `openpictalis/catalog.json`: include a working Hugging Face link, the license, which modes it supports, and set `"tested": true` only if you have rendered all of its modes yourself. Mention your hardware in the pull request.
- Never commit model weights, LoRAs, engine binaries, or generated images.
- Keep pull requests focused and include a screenshot for visible changes.
