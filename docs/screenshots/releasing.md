# First public release

Target repository: https://github.com/kingofthecipher-ctrl/openpictalis

## Preparation

- Keep the staging repository private while reviewing assets and testing.
- Verify logo, brand images, and screenshot redistribution rights. Font notices are bundled separately.
- Review the catalog's existing `tested` flags against reproducible engine versions and hardware. They were supplied with the original project; preparation tests use a fake engine and do not validate model output.
- Run `python3 -m unittest discover -s tests -v`.
- Run `python3 -m build` and `python3 -m twine check dist/*`.
- Install the wheel into a clean virtual environment. From outside the checkout, import the server, load the catalog, and check the bundled UI, logo, fonts, and notices.
- Build with `bash macos/build-app.sh` on Apple Silicon; launch and test Image, Reference, Transparent, PNG export, Stop, and one upscale on supported hardware.
- Test on a clean Mac with Python 3.10+. The app is ad-hoc signed, not notarized; do not describe it as a one-click installer with no prerequisites.
- Scan the final Git tree for secrets and local data. No weights, reference uploads, library files, or engine binaries should be tracked.

## GitHub setup

- Repository description: Local image generation and editing for Qwen and compatible open models.
- Suggested topics: `image-generation`, `image-editing`, `qwen`, `mflux`, `mlx`, `macos`, `python`, `local-ai`.
- Upload `docs/brand/social-preview.png` as the social preview.
- Verify CI passes on GitHub, including Linux/macOS, package installation, and native build.
- Enable private vulnerability reporting when available; SECURITY.md links to the Security tab.
- Add a main-branch protection rule when the account plan permits it.
- Make the repository public when release review is complete, then create a v0.1.0 prerelease using the changelog. Do not publish binaries without clean-machine validation and a clear Python prerequisite.

No PyPI publishing or release upload is automated. CI builds test artifacts only.
