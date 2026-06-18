# Prompt For GLM 5.2

You are improving the UI/UX of an existing Python project named Vamos Telegram
Vault at `D:\vamos-telegram-vault`.

## Product Goal

Make this the cleanest possible Telegram-backed media vault for a solo vlogger,
cinematographer, or YouTuber.

The core workflow is:

1. User shoots video on phone.
2. User sends the video to a private Telegram vault channel.
3. On PC, the app syncs Telegram messages into a local catalog.
4. User searches/browses the catalog.
5. User downloads only the clips needed for editing.
6. User marks work done and optionally deletes local working copies.
7. Telegram remains the remote storage layer unless the user explicitly deletes
   remote messages.

## Hard Requirements

- Preserve original quality. Do not add any UI path that uploads masters as
  compressed Telegram videos. Archive uploads must remain Telegram
  document/file mode.
- Keep remote deletion explicit and guarded. Never make destructive cleanup a
  casual one-click default.
- Do not remove CLI functionality. Improve the Studio UI and app ergonomics
  around the existing commands and manifest.
- Respect the current Python package structure.
- Add tests where practical.
- Keep setup simple for Windows.

## Existing Capabilities

Commands:

- `vamos-vault init`
- `vamos-vault auth`
- `vamos-vault doctor`
- `vamos-vault upload`
- `vamos-vault sync`
- `vamos-vault download`
- `vamos-vault done`
- `vamos-vault list`
- `vamos-vault find`
- `vamos-vault summary`
- `vamos-vault export`
- `vamos-vault manifest`
- `vamos-vault studio`

Important files:

- `src/vamos_vault/cli.py`
- `src/vamos_vault/db.py`
- `src/vamos_vault/telegram_client.py`
- `src/vamos_vault/reports.py`
- `src/vamos_vault/media.py`
- `README.md`
- `docs/cinematographer-workflow.md`

## UI Direction

Improve the generated offline Studio dashboard first. It currently comes from
`src/vamos_vault/reports.py`.

Make it feel like a serious creator tool, not a landing page:

- Dense but clean media-management dashboard.
- First screen should be the usable vault, not marketing copy.
- Prioritize scan speed, search, filters, lifecycle status, and download/use
  decisions.
- Use a restrained neutral UI with one accent color.
- No decorative blobs, big hero sections, or card-heavy marketing layout.
- Make mobile and desktop layouts robust.
- Text must not overlap or overflow.

## Features To Add To The UI

Add as many of these as are sensible within the current architecture:

- Dashboard counters: total assets, remote-only, downloaded, done, storage,
  runtime, favorites.
- Filters: project, status, asset kind, camera, rating, favorite, YouTube status.
- Search across filename, project, scene, location, people, tags, notes.
- Clear lifecycle labels: remote, downloaded, done, remote-deleted.
- Row details drawer or expandable row showing Telegram link, local downloaded
  path, SHA/content hash, rights, people, notes.
- Copyable CLI commands for each asset:
  - download this clip
  - mark done
  - delete local copy
  - delete remote copy with warning
- Project view grouping clips by project and shoot date.
- "Needs metadata" view for files with missing project/tags/rights.
- "Ready to edit" view for downloaded clips.
- "Remote archive" view for clips safely in Telegram but not local.
- "Favorites/selects" view.
- Export buttons should show what CLI command to run.

## Seamless Telegram Setup UX

Improve docs/UI copy around:

- API ID/API hash from `https://my.telegram.org/apps`
- why user account auth is required
- why bot token is not enough for large original files
- private channel recommendation
- Premium 4 GB limit vs free 2 GB limit
- upload as document/file for quality
- run `sync` after sending phone videos to Telegram

## Verification

Before finishing:

- Run unit tests.
- Compile Python files.
- Install editable package in a temporary `.venv` and smoke-test:
  - `vamos-vault --help`
  - `vamos-vault upload --help`
  - `vamos-vault studio`
  - `vamos-vault manifest`
- Confirm no `.venv`, `__pycache__`, or egg-info is left in the repo.

## Output

Return:

- summary of UI changes
- files changed
- tests run
- any limitations or follow-up recommendations

