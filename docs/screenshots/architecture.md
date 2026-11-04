# Architecture

`openpictalis/server.py` is a standard-library HTTP server bound to loopback. It serves `openpictalis/web/index.html`, local fonts, and SVG assets. The browser reads `/api/config` to initialize the UI; mutations require the per-launch `X-Token` and an allowed Host and Origin.

The model catalog describes engines, modes, arguments, sizes, and upstream links. Custom models and settings live in the user's application data directory. Rendering starts an external command as an argument list in a new process group, never through a shell. Only one render is active. Stop terminates the process group. Generated files are copied into the selected output directory and indexed in the local library.

The Swift wrapper starts the bundled Python source and embeds the UI in WKWebView. It needs Python 3.10 or newer at runtime; Python and ML engines are not bundled. The default browser opens upstream model links. The wrapper and built-in simple-resize upscaler require macOS. Other platforms may run the server with a suitable custom command engine; they are not validated GPU targets.

The service is intended for the local user. It is not a multi-user server and should not be exposed through port forwarding, a proxy, or a public tunnel.

## Repository layout

- `openpictalis/`: backend, catalog, web UI, and licensed fonts.
- `macos/`: native launcher and app build script.
- `tests/`: engine-free command, HTTP, and render tests.
- `docs/brand/`: design assets; see its README for roles and usage.
- `.github/`: CI, dependency update configuration, and contribution templates.
