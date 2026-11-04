# Security

OpenPictalis is a local app. The server:

- binds to `127.0.0.1` only and rejects requests whose `Host` is not `127.0.0.1` or `localhost`;
- requires a random per-launch token on every state-changing request, and rejects cross-origin requests;
- runs engines as child processes with arguments passed as a list (no shell);
- reads reference images only as PNG, JPEG or WebP, up to 30 MB each.

**Custom command models run whatever command you enter**, with your user permissions. Only add commands you trust.

Model weights are downloaded by the engines (mflux, Draw Things) from Hugging Face, not by OpenPictalis.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Report a vulnerability" under the Security tab) instead of a public issue. We aim to reply within a week.
