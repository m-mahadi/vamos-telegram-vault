# GitHub Scan

Date: 2026-06-17

Goal: find existing Telegram-backed storage projects before building a tool for
vlog/video archive workflows.

## Shortlist

| Project | What it does well | Why not use it directly |
| --- | --- | --- |
| `caamer20/Telegram-Drive` | Mature desktop app, Tauri/Rust/React, drag/drop, file explorer, streaming, channels as folders. | Strong generic drive. Heavy base for a focused vlogger metadata workflow. |
| `Nekmo/telegram-upload` | Mature Python CLI, personal Telegram account, 2 GB free / 4 GB Premium uploads, captions, thumbnails, download. | Excellent uploader, but no production catalog, shoot metadata, or YouTube-style archive exports. |
| `tgdrive/teldrive` | Self-hosted drive/service approach with responsible-use guidance. | Broader server app; more infrastructure than needed for a private creative archive. |
| `JohnySir/TG-Upload-v2` | GUI uploader, document/media modes, thumbnail generation, progress. | Uploader-first, not an archive/catalog workflow. Small repo surface. |
| `khrj/teledrive` | Folder watch and Saved Messages backup. | Older Electron backup model, not tailored to video production metadata. |

## Decision

Build a focused local tool from scratch, using Telethon directly. This keeps the
surface small and optimizes for:

- private channel as destination
- original-quality document uploads
- SHA-256 duplicate protection
- camera/lens/project/shoot-date/tags/notes
- local SQLite catalog
- CSV/JSON export for editing and YouTube production planning
- clear oversized-file checks instead of automatic limit bypassing

