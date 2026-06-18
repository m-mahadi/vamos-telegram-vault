# Vamos Telegram Vault

A Telegram-backed video archive for vloggers, cinematographers, and YouTubers.
It sends your original media files to a Telegram channel and keeps a local
SQLite catalog that future tools can search, export, and build on.

## The Quality Rule (zero compression)

Telegram only keeps your **exact, full-quality file when it is sent as a File /
Document.** Sent as a normal gallery "video", your phone re-encodes it *before* it
ever reaches Telegram — and nothing on a PC can recover that. So the one rule is:

> **Always send clips as a FILE, not as a video.**

Vamos makes this safe in three ways:

1. **PC uploads are always lossless.** The in-app **Upload** button (and
   `vamos-vault upload`) send everything as documents with `force_document=True`.
2. **Phone uploads are guided.** The app's **?** / "How to send lossless" guide
   shows the exact taps for iPhone and Android.
3. **Everything is flagged.** On sync, Vamos detects whether each clip arrived as
   a true original or was compressed, and tags it **ORIGINAL** (green) or
   **COMPRESSED** (amber) across the Shot Board, Catalog, inspector, and HTML
   report. A **Compressed** view in the sidebar lets you catch anything that
   slipped through and re-send it as a file.

The main upload path never exposes a casual video-preview mode, because this
vault is for master files, not degraded copies.

Practical meaning:

- Use it for original MP4, MOV, MXF, WAV, photos, and camera sidecar files.
- Uploaded files keep their original file bytes.
- When sending from phone, choose Telegram's file/document option when
  available. If you send as a normal gallery video, Telegram may optimize it
  before the vault can sync it.
- Telegram still has per-file upload limits: public Telegram docs describe 2 GB
  per file for free users and 4 GB for Premium users.
- Telegram storage is convenient and generous, but you should still keep at
  least one real backup outside Telegram.

## Why This Exists

I checked GitHub first. There are good generic tools:

- `caamer20/Telegram-Drive`: polished desktop drive app.
- `Nekmo/telegram-upload`: mature CLI uploader/downloader.
- `tgdrive/teldrive`: self-hosted Telegram drive service.
- `JohnySir/TG-Upload-v2`: GUI uploader with document/media modes.

Those tools are useful, but they are not shaped around a creator archive. Vamos
adds the missing production layer: project, shoot date, camera, lens, scene,
location, people, rights, rating, favorites, YouTube status, tags, notes, local
search, manifest export, Studio dashboard, and Telegram retrieval.

More detail: [docs/github-scan.md](docs/github-scan.md)

## What You Get

- One Windows desktop app (dark "editor" UI) for setup, Telegram sync, uploads,
  browsing, metadata, download list, and ZIP packaging.
- **In-app uploads:** add files or a whole shoot folder and archive originals to
  Telegram with progress — always lossless.
- **Lossless detection:** every clip is tagged ORIGINAL or COMPRESSED so you
  always know whether Telegram kept your full-quality file.
- **In-app guide** for sending lossless clips from iPhone/Android to Saved
  Messages, plus a one-screen onboarding banner until Telegram is connected.
- Guided Telegram setup inside the app, including a button that opens
  <https://my.telegram.org/apps>.
- Auto-sync from Telegram into the local catalog while the app is open.
- Thumbnail browsing for Telegram media when Telegram exposes a preview.
- Persistent download list for clips you want to work on later.
- Project/folder ZIP packs with original files plus `_vamos_metadata.csv` and
  `_vamos_metadata.json`.
- Original-quality Telegram uploads through your user account.
- Private channel or Saved Messages as the storage target.
- Local searchable SQLite catalog in `.vamos-vault/vault.db`.
- SHA-256 duplicate detection.
- CSV and JSON exports.
- Future-app manifest export.
- Offline Studio HTML dashboard for browsing/searching assets.
- Telegram sync for videos sent from your phone to the vault channel.
- Download command to retrieve originals from Telegram later.
- Done/delete workflow for local working copies and explicit remote cleanup.
- Dry-run mode before uploading a full shoot folder.

## Open The App

Use the single launcher in the project root:

```text
Vamos Vault.lnk
```

Or from a terminal:

```powershell
cd D:\vamos-telegram-vault
vamos-vault app
```

The app is the normal workflow. There is one user-facing launcher: `Vamos Vault.lnk`.
If you build the standalone executable (see **Build The Windows App** below), you
can launch `dist\Vamos Vault.exe` directly with no Python install.

Inside the app:

1. Click **Open Telegram API Page**.
2. Sign in at Telegram, create an app, and copy `api_id` and `api_hash`.
3. Paste them into the app.
4. Set target to `me` for Saved Messages, or paste your private vault channel.
5. Click **Save Settings**.
6. Click **Connect Account** and enter your phone/code when prompted.
7. Click **Sync Now**, or leave **Auto sync** on.

## Install

> Prefer the standalone executable? Skip this section, grab `Vamos Vault.exe`
> from the [GitHub Releases](../../releases) page (or build it yourself, see
> **Build The Windows App**), and run it next to a `vault.json`.

Running from source needs Python 3.10+:

```powershell
cd path\to\vamos-telegram-vault
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
```

To also run the test suite, install the dev extras:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

Then create your env file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with your Telegram API values (see the next section).

## Build The Windows App

To produce a standalone `.exe` that runs without a Python install:

```powershell
python -m pip install -e ".[build]"
python packaging\build_exe.py          # single-file dist\Vamos Vault.exe
python packaging\build_exe.py --onedir # faster-starting folder build
```

The executable is written to `dist\` (git-ignored). Keep it next to a
`vault.json`, or distribute it as a GitHub Release asset.

## Telegram Setup, Explained

Vamos Vault talks to Telegram through your **personal user account**, not the
Bot API. That choice is deliberate and matters for a media archive.

### 1. Get `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`

These come from Telegram itself, not from a bot.

1. Open <https://my.telegram.org/apps> in a browser and sign in with your
   Telegram phone number.
2. Click **Create new application**.
3. Fill in any app name and short name (these do not matter for personal use).
4. Copy the **App api_id** and **App api_hash** values.
5. Paste them into `.env`:

   ```text
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
   ```

Keep these private. They identify your app session, and together with your
session file they can act on your Telegram account.

### 2. Why a user account, not a Bot API token?

Telegram Bot API limits uploads from bots to roughly **20 MB per file** for most
bots and **50 MB** even for hosted bots. That is useless for a video archive.

When you authenticate as a **user account** through the Telegram client API
(Telethon in this app), the same generous per-file limits that apply to a normal
Telegram user apply to uploads:

- **Free Telegram account:** up to **2 GB** per uploaded file.
- **Telegram Premium account:** up to **4 GB** per uploaded file.

That is why `vamos-vault auth` logs in as you and stores a local session file in
`.vamos-vault/`. The Bot API is not the right path for original video masters.

### 3. Create a private Telegram vault channel

Recommended setup:

1. In Telegram, create a **new channel** (not a group). Name it something like
   `Monir Vlog Raw Vault`.
2. Set it to **Private**.
3. Add only your own account. Add a collaborator only if you intentionally want
   them to see every raw clip.
4. Use one of these as the vault target:
   - A public-style `@username` if you gave the channel one (not recommended for
     a private vault).
   - The private invite link (`https://t.me/+abcdef...`).
   - A numeric chat ID your Telegram session can resolve.
   - For quick testing, use Saved Messages with the target `me`.

Initialize the vault:

```powershell
vamos-vault init --target "@your_private_channel_username"
```

For a private channel without a username, use the private invite link or a
numeric ID. For quick testing:

```powershell
vamos-vault init --target "me"
```

If you have Telegram Premium:

```powershell
vamos-vault init --target "@your_private_channel_username" --premium
```

`--premium` raises the per-file size check from 2 GB to 4 GB so the app will
not refuse files that Telegram Premium can actually accept.

### 4. Authenticate once

```powershell
vamos-vault auth
```

This opens a Telegram login flow in the terminal. Your local session is saved
under `.vamos-vault/`. You only do this once per machine.

### 5. Send phone videos as files, not gallery videos

When you shoot on your phone and send the clip to the vault channel from a
mobile Telegram client, choose **Send as file / document** when Telegram offers
the option. On iOS this is the "file" attachment type; on Android it is the
"file/document" picker.

Why this matters: when you send a video as a normal gallery message, some
Telegram clients re-encode or optimize it before upload. The vault can only
download the bytes Telegram is storing. It cannot undo compression that happened
before the file reached Telegram.

For PC uploads, `vamos-vault upload` already sends everything as a Telegram
document/file with `force_document=True` and `supports_streaming=False`, so the
original bytes are preserved.

### 6. Run `sync` after sending phone videos

After you send clips from your phone to the vault channel, switch to your PC and
run:

```powershell
vamos-vault sync --project "Vlog 001" --tags "phone,raw"
```

`sync` reads the latest Telegram messages from the vault channel and writes them
into the local SQLite catalog. It does not download the video bodies; it just
records the message ID, size, caption metadata, and link so you can browse
hundreds of clips locally and download only the few you actually need.

## Upload A Shoot

Dry run first:

```powershell
vamos-vault upload "D:\Vlogs\Day 01" `
  --project "Dhaka street vlog" `
  --shoot-date 2026-06-17 `
  --camera "Sony FX30" `
  --lens "18-50mm" `
  --asset-kind original `
  --scene "evening walk" `
  --location "Dhanmondi" `
  --people "Monir" `
  --rights "owned footage" `
  --rating 4 `
  --favorite `
  --youtube-status selected `
  --tags "broll,street,day01" `
  --notes "Good opening sequence" `
  --dry-run
```

Upload for real:

```powershell
vamos-vault upload "D:\Vlogs\Day 01" `
  --project "Dhaka street vlog" `
  --shoot-date 2026-06-17 `
  --camera "Sony FX30" `
  --lens "18-50mm" `
  --asset-kind original `
  --scene "evening walk" `
  --location "Dhanmondi" `
  --people "Monir" `
  --rights "owned footage" `
  --rating 4 `
  --favorite `
  --youtube-status selected `
  --tags "broll,street,day01" `
  --notes "Good opening sequence"
```

Supported files include common video, audio, photo, and camera raw extensions.
Folders are scanned recursively by default.

## Phone To Telegram To PC

This is the main vlog workflow:

1. Shoot on your phone.
2. Send the video to your private Telegram vault channel as a file/document when
   the Telegram client gives that option. This matters for quality.
3. On PC, sync the latest Telegram media into the catalog:

```powershell
vamos-vault sync --project "Vlog 001" --tags "phone,raw"
```

4. Browse/search:

```powershell
vamos-vault app
```

5. In the app, select clips and use **Add To Download List** or
   **Pack Selected ZIP**.

CLI equivalent:

```powershell
vamos-vault pack --project "Vlog 001" --out "D:\Vlog Work" --name "Vlog 001 selects"
```

6. When the edit is done, mark the clips complete. To delete only the local PC
   working copy:

```powershell
vamos-vault done "Vlog 001" --notes "Used in final edit" --delete-local --yes
```

7. Only when you truly want to remove the Telegram archive copy too:

```powershell
vamos-vault done "clip name or project" --delete-remote --yes
```

Remote deletion is guarded on purpose. Telegram is acting as the storage layer,
so deleting from Telegram is final unless you have another backup.

## Browse The Vault

Desktop app:

```powershell
vamos-vault app
```

Terminal:

```powershell
vamos-vault list --limit 20
vamos-vault find "street"
vamos-vault summary
```

Offline Studio dashboard:

```powershell
vamos-vault studio --open
```

This generates:

```text
.vamos-vault/studio/index.html
```

The Studio is a single static HTML file generated from your SQLite catalog. It
opens directly in your browser with no server. It is now a report/export surface;
the desktop app is the main working surface.

First screen is the vault itself:

- **Counters:** total assets, remote-only, downloaded, done, remote-deleted,
  uploaded, favorites, needs-metadata, total storage, total runtime.
- **Quick filters:** All, Remote archive, Ready to edit, Done, Favorites,
  Needs metadata, Remote-deleted.
- **Filters:** project, status, asset kind, camera, rating (incl. unrated),
  YouTube status, favorite, and group-by project/shoot-date.
- **Search** across filename, project, scene, location, people, tags, notes,
  camera, lens, rights, and SHA.
- **Expandable rows** showing Telegram link, downloaded local path, SHA-256 and
  content SHA, resolution, codec, all production metadata, rights, people, and
  notes.
- **Copyable CLI snippets** per asset: download this clip, mark done, delete
  local copy, delete remote copy (with warning text). The destructive commands
  are shown for copy/paste only; they are never executed from the browser.
- **Project grouping** by project or shoot date with collapsible sections.
- **Status labels:** `remote`, `downloaded`, `done`, `remote-deleted`,
  `uploaded`, `dry-run`, `cataloged`.

Status meanings:

- `remote` — in Telegram, cataloged by `sync`, no local download yet.
- `uploaded` — uploaded from this PC by `upload`, original still on disk.
- `downloaded` — downloaded from Telegram to this PC, not yet marked done.
- `done` — work complete.
- `remote-deleted` — Telegram message was deleted; catalog row kept for audit.
- `dry-run` — `upload --dry-run` cataloged it without uploading.
- `cataloged` — cataloged locally, upload pending.

## Export For Future Apps

CSV/JSON:

```powershell
vamos-vault export --format csv --out exports\vamos-catalog.csv
vamos-vault export --format json --out exports\vamos-catalog.json
```

Future-app manifest:

```powershell
vamos-vault manifest --out exports\vamos-manifest.json
```

That manifest is the handoff format for anything we build later: a web app,
editor dashboard, YouTube planning board, or review workflow.

## Retrieve Originals

Download by SHA, filename, project, tag, scene, or location:

```powershell
vamos-vault download "Dhaka street vlog" --out "D:\Recovered Footage" --limit 5
```

The command uses the Telegram message IDs stored in the local catalog.

## Metadata, Download Lists, And ZIP Packs

Telegram is bad at production metadata, so Vamos keeps metadata locally. You do
not have to rename files in Telegram.

Bulk metadata from the app:

- Select one or more rows.
- Click **Edit Metadata**.
- Set project/folder, shoot date, camera, lens, scene, location, people, rights,
  tags, rating, favorite, and YouTube status.
- Use **Select Visible**, **Add Visible To List**, or **Pack Visible ZIP** after
  filtering by project/search/status when you want to work on whole folders or
  batches without selecting every row manually.

CLI examples:

```powershell
vamos-vault metadata "PXL_20260322" --project "Dhaka Vlog 001" --append-tags "broll,street" --rights "owned" --yes
vamos-vault metadata --project-filter "Inbox" --project "Dhaka Vlog 001" --camera "Pixel" --yes
```

Persistent download list:

```powershell
vamos-vault queue add --project "Dhaka Vlog 001"
vamos-vault queue list
vamos-vault queue pack --out "D:\Vlog Work" --name "Dhaka Vlog 001"
```

Direct project ZIP:

```powershell
vamos-vault pack --project "Dhaka Vlog 001" --out "D:\Vlog Work" --name "Dhaka Vlog 001"
```

ZIP packs contain the original Telegram files with no recompression, organized
by project/date/kind, plus `_vamos_metadata.csv` and `_vamos_metadata.json` for
editing handoff and recovery.

## Lifecycle Commands

```powershell
vamos-vault app        # native desktop app
vamos-vault sync       # Telegram channel -> local catalog
vamos-vault download   # Telegram original -> PC
vamos-vault metadata   # edit local production metadata
vamos-vault queue      # persistent download list
vamos-vault pack       # selected project/folder ZIP pack
vamos-vault done       # mark complete, optionally delete local/remote copy
vamos-vault summary    # project totals
vamos-vault studio     # local HTML report/export
vamos-vault manifest   # app-friendly JSON export
```

## Doctor

```powershell
vamos-vault doctor
```

Checks config, API env values, database path, max file size, and whether
`ffprobe` is available for duration/resolution metadata.

## Notes

- Keep `.env` and `.vamos-vault/` private.
- Do not delete the private Telegram channel unless you have another backup.
- Do not manually delete Telegram vault messages unless you are prepared for the
  local catalog to point at missing remote media.
- Oversized files are skipped before upload. Export, trim, split, or compress
  intentionally in your editing workflow.

Research-backed workflow notes: [docs/cinematographer-workflow.md](docs/cinematographer-workflow.md)

GLM 5.2 UI prompt: [docs/glm-5.2-ui-prompt.md](docs/glm-5.2-ui-prompt.md)

## Desktop Workflow Notes

- The app opens to a creator workspace, not a raw file list.
- Use the left Library panel for All Footage, Telegram Archive, Needs Metadata, Download List, and Projects.
- **Download Selected** writes original files into an organized working folder.
- **Export Selected ZIP** writes original files plus `_vamos_metadata.csv` and `_vamos_metadata.json`.
- Telegram API credentials are hidden inside **Telegram Setup** instead of living on the main screen.
- The app window and launcher shortcut use the Vamos Vault icon in `assets/vamos-vault.ico`.

### Storyboard Browsing

The desktop app includes a Storyboard strip above the table. Filter by project, status, or search, then use the thumbnails to pick footage visually before downloading or exporting. This keeps the app usable when the vault grows past a small list of files.

### Clear Download Jobs

**Download Selected** and **Download Visible** open a job dialog that shows file count and total size, lets you choose the editing folder name, and preserves original Telegram bytes. **Export ZIP** uses the same dialog but also creates a ZIP package and metadata sheets.

### Download list management

The desktop app now supports adding selected footage to the download list, removing selected items from it, clearing the whole list, downloading the list into an editing folder, or exporting it as a ZIP. Downloaded clips are marked in both the table and Storyboard.


## Video thumbnails

- Sync first asks Telegram for lightweight media previews.
- Downloads and editing packages generate a local poster frame for videos and stills, then save it in the catalog.
- Future `vamos-vault upload` sends originals as Telegram documents for full quality and attaches the generated poster as the Telegram thumbnail when the decoder is available.
- If a video is remote-only and Telegram did not provide a preview, Vamos shows a download-for-preview tile because it cannot decode a frame until the original bytes are local.


### Fetch Preview for old Telegram videos

If an older remote-only Telegram video has no thumbnail, select it in the desktop app and press **Fetch Preview**. Vamos temporarily downloads the original, extracts a poster frame, stores only the thumbnail, and deletes the temporary original.


## Shot Board

The desktop app opens on a visual Shot Board instead of a raw table. Use the board to browse thumbnails, queue footage, fetch missing previews, and select clips. The Catalog tab keeps the detailed spreadsheet-style list for power filtering and audit work.


## Finish footage

The desktop app includes a **Finish** workflow for selected clips. It marks footage done, can add a completion note, can delete downloaded PC copies, and can optionally delete the Telegram archive message when you are truly finished with that file.


## Download progress

The desktop app shows a persistent download progress bar, current file status, and **Open Last Download** / **Open Last ZIP** buttons after package jobs complete.
