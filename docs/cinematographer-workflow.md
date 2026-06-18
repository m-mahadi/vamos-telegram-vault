# Cinematographer Workflow Notes

These notes shaped the product decisions in Vamos Telegram Vault.

## Research Summary

Good video storage tools are not just "a folder with videos." They support the
full lifecycle: ingest, production, review, distribution, and archive. The
cinematographer-specific pain is that originals are large, hard to search, easy
to accidentally recompress, and often needed later from a different machine.

Key requirements:

- Preserve camera originals separately from preview/proxy/delivery versions.
- Capture metadata at ingest, not after the project becomes messy.
- Track project, shoot date, camera, lens, scene, location, people, rights,
  tags, notes, rating, favorites, and YouTube/editorial status.
- Use checksums where local files are involved.
- Keep a simple report/manifest for handoff and recovery.
- Support phone-first capture: shoot, send to Telegram, sync on PC, download
  only when editing, then delete local working copies when done.
- Provide a native desktop app as the main workflow, not just a browser report.
- Support persistent download lists and project/date/kind ZIP packs for editing
  handoff.
- Let metadata live in the app so creators do not have to rename or caption
  every Telegram message perfectly from a phone.
- Guide Telegram setup inside the app and open the official Telegram API page.
- Make remote deletion explicit and hard to do accidentally.
- Avoid pretending Telegram replaces a full 3-2-1 backup plan.

## Workflow This App Supports

### Phone To Telegram To PC

1. Shoot video on phone.
2. Send it to the private Telegram vault channel as a file/document whenever
   possible.
   - If the phone sends it as a normal compressed gallery video, Telegram may
     reduce quality before the app can sync it.
   - The app preserves and downloads the bytes Telegram has stored; it cannot
     restore quality lost before upload.
3. On PC:

```powershell
vamos-vault app
```

4. Let auto-sync pull the latest Telegram media into the catalog.
5. Add metadata in the app: project/folder, scene, location, camera, rights,
   tags, rating, favorite, and YouTube status.
6. Select clips and either add them to the download list or pack them directly.
7. Download/pack only what you need:

```powershell
vamos-vault pack --project "Vlog 001" --out "D:\Vlog Work" --name "Vlog 001 selects"
```

8. Edit in Premiere, Resolve, CapCut, etc.
9. Mark done and optionally delete the local PC copy:

```powershell
vamos-vault done "clip name or project" --notes "Used in final edit" --delete-local --yes
```

10. Only delete from Telegram when you truly do not need the remote archive:

```powershell
vamos-vault done "clip name or project" --delete-remote --yes
```

## Telegram Reality

Telegram is useful here because it gives generous cloud storage and fast
multi-device access. It is still bounded by per-file limits and account safety.

- Free users: up to 2 GB per uploaded file.
- Premium users: up to 4 GB per uploaded file.
- Use Telegram document/file sending for masters.
- Do not rely on Telegram as the only copy of irreplaceable paid work.

## Telegram Setup Details

### API credentials

Get `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from
<https://my.telegram.org/apps>:

1. Sign in with your Telegram phone number.
2. Create a new application (any name/short name is fine).
3. Copy the `api_id` and `api_hash` into `.env`.

These identify the app session. Keep them private.

### Why a user account, not Bot API

The Bot API caps bot uploads at roughly 20-50 MB per file, which is useless for
video masters. Authenticating as a user account (via Telethon) inherits the same
per-file limits a normal Telegram user gets: 2 GB free, 4 GB Premium. That is
why `vamos-vault auth` logs in as you and stores a session file under
`.vamos-vault/`.

### Private vault channel

Create a private Telegram channel (not a group), add only your own account, and
use its `@username`, private invite link, or numeric chat ID as the target. For
quick testing use `me` (Saved Messages).

### Original-quality uploads

- Phone: when sending a clip from a mobile Telegram client, choose **Send as
  file/document** so Telegram does not re-encode the video before storing it.
- PC: `vamos-vault upload` always sends Telegram documents with
  `force_document=True` and `supports_streaming=False`, so original bytes are
  preserved.

### Sync after phone uploads

After you send clips from your phone to the vault channel, run `vamos-vault sync`
on the PC. `sync` records Telegram message IDs and metadata into the local
SQLite catalog without downloading the video bodies, so you can browse hundreds
of clips and download only the few you need.

## Current Product Shape

- `app`: native desktop app for setup, sync, browse, metadata, queue, and packs.
- `upload`: PC source folder to Telegram, original-quality document mode.
- `sync`: Telegram channel to local catalog, ideal for phone uploads.
- `download`: remote Telegram original to PC.
- `metadata`: bulk local production metadata editor.
- `queue`: persistent download list.
- `pack`: download selected originals into project/date/kind folders and
  optional ZIP with metadata CSV/JSON.
- `done`: lifecycle closeout and optional local/remote deletion.
- `studio`: static HTML report/export.
- `manifest`: app-friendly JSON for future UI/app work.
- `summary`: project-level storage/runtime overview.
