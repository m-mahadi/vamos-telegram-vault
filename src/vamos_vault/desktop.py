from __future__ import annotations

import asyncio
import os
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, StringVar, filedialog, messagebox, simpledialog
import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - app still works without thumbnails
    Image = None
    ImageTk = None

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from .config import FREE_FILE_LIMIT_BYTES, PREMIUM_FILE_LIMIT_BYTES, load_config, resolve_data_path, telegram_credentials, write_config
from .db import VaultDB
from .media import format_bytes, format_duration, normalize_tags
from .reports import build_manifest, enrich_assets_for_display, write_studio_html
from .telegram_client import TelegramConfigError, delete_message
from .thumbnails import ensure_thumbnail_for_asset, thumbnail_backend_label
from .workflows import create_download_package, create_remote_preview_thumbnail, db_from_config, merge_tags, sync_remote_catalog


API_URL = "https://my.telegram.org/apps"
AUTOSYNC_MS = 5 * 60 * 1000


def _update_env_file(path: Path, values: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    comments: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                comments.append(line)
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = value.strip()
    existing.update({key: value.strip() for key, value in values.items() if value.strip()})
    lines = comments or [
        "# Telegram client API credentials from https://my.telegram.org/apps",
        "# Keep this file private.",
    ]
    for key in ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_TARGET", "VAMOS_VAULT_DB"]:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
    for key, value in existing.items():
        if key not in {"TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_TARGET", "VAMOS_VAULT_DB"}:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    for key, value in existing.items():
        os.environ[key] = value


def _row_text(row: dict, key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)




class DownloadJobDialog(tk.Toplevel):
    def __init__(self, app: "VamosDesktopApp", rows: list[dict], *, default_name: str, make_zip: bool, title: str):
        super().__init__(app.root)
        self.app = app
        self.rows = rows
        self.make_zip = BooleanVar(value=make_zip)
        self.open_after = BooleanVar(value=True)
        self.result: dict[str, object] | None = None
        self.title(title)
        self.geometry("620x380")
        self.transient(app.root)
        self.grab_set()

        total_bytes = sum(int(row.get("size_bytes") or 0) for row in rows)
        action = "ZIP export" if make_zip else "editing download"
        base_folder = app.base_dir / ("packs" if make_zip else "downloads")
        base_folder.mkdir(exist_ok=True)

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=title, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text=f"{len(rows)} original file(s), {format_bytes(total_bytes)}. Vamos will preserve original Telegram bytes.",
            wraplength=560,
        ).pack(anchor="w", pady=(6, 16))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Save into").grid(row=0, column=0, sticky="w", pady=6)
        self.out_var = StringVar(value=str(base_folder))
        ttk.Entry(form, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", padx=(12, 8), pady=6)
        ttk.Button(form, text="Browse", command=self._browse).grid(row=0, column=2, pady=6)

        ttk.Label(form, text="Working folder").grid(row=1, column=0, sticky="w", pady=6)
        self.name_var = StringVar(value=default_name)
        ttk.Entry(form, textvariable=self.name_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=6)

        ttk.Checkbutton(form, text="Create ZIP package", variable=self.make_zip).grid(
            row=2, column=1, sticky="w", padx=(12, 0), pady=(10, 0)
        )
        ttk.Checkbutton(form, text="Open folder when complete", variable=self.open_after).grid(
            row=3, column=1, sticky="w", padx=(12, 0), pady=(6, 0)
        )

        ttk.Label(
            outer,
            text=(
                "Folder layout: Project / Shoot date / Kind. "
                "ZIP exports also include _vamos_metadata.csv and _vamos_metadata.json."
            ),
            foreground="#667085",
            wraplength=560,
        ).pack(anchor="w", pady=(18, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=f"Start {action}", command=self._start).pack(side="right", padx=(0, 8))

    def _browse(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder", initialdir=self.out_var.get())
        if folder:
            self.out_var.set(folder)

    def _start(self) -> None:
        out = Path(self.out_var.get().strip())
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Download", "Give the working folder a name.")
            return
        self.result = {
            "out_dir": out,
            "name": name,
            "make_zip": self.make_zip.get(),
            "open_after": self.open_after.get(),
        }
        self.destroy()

class TelegramSetupDialog(tk.Toplevel):
    def __init__(self, app: "VamosDesktopApp"):
        super().__init__(app.root)
        self.app = app
        self.title("Connect Telegram")
        self.geometry("640x420")
        self.transient(app.root)
        self.grab_set()

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Connect your Telegram vault", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Vamos uses your Telegram user account so it can store original video files. "
                "Create a Telegram API app once, paste the values here, then connect your account."
            ),
            wraplength=580,
        ).pack(anchor="w", pady=(8, 16))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        fields = [
            ("API ID", app.api_id_var, False),
            ("API Hash", app.api_hash_var, True),
            ("Vault target", app.target_var, False),
        ]
        for row, (label, var, secret) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=6)
            entry = ttk.Entry(form, textvariable=var, show="*" if secret else "")
            entry.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=6)
        ttk.Checkbutton(form, text="Telegram Premium 4 GB file limit", variable=app.premium_var).grid(
            row=3, column=1, sticky="w", padx=(12, 0), pady=(6, 0)
        )

        help_box = ttk.Frame(outer)
        help_box.pack(fill="x", pady=(18, 0))
        ttk.Button(help_box, text="Open Telegram API Page", command=app.open_api_page).pack(side="left")
        ttk.Label(help_box, text="Use target 'me' for Saved Messages, or paste a private channel link/username.").pack(
            side="left", padx=(12, 0)
        )

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(24, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Save + Connect Account", command=self._connect).pack(side="right", padx=(0, 8))

    def _save(self) -> None:
        if self.app.save_settings():
            self.destroy()

    def _connect(self) -> None:
        if self.app.save_settings():
            self.destroy()
            self.app.connect_account(skip_save=True)

class FinishJobDialog(tk.Toplevel):
    def __init__(self, app: "VamosDesktopApp", rows: list[dict]):
        super().__init__(app.root)
        self.app = app
        self.rows = rows
        self.result: dict[str, object] | None = None
        self.delete_local = BooleanVar(value=False)
        self.delete_remote = BooleanVar(value=False)
        self.open_downloads = BooleanVar(value=False)
        self.note_var = StringVar(value="")
        self.title("Finish footage")
        self.geometry("620x430")
        self.transient(app.root)
        self.grab_set()

        total_bytes = sum(int(row.get("size_bytes") or 0) for row in rows)
        downloaded = sum(1 for row in rows if row.get("downloaded_path") and Path(str(row["downloaded_path"])).exists())
        remote = sum(1 for row in rows if row.get("telegram_message_id") and row.get("status") != "remote-deleted")

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Finish footage", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                f"{len(rows)} asset(s), {format_bytes(total_bytes)}. "
                f"{downloaded} local copy/copies found, {remote} Telegram archive item(s)."
            ),
            wraplength=560,
        ).pack(anchor="w", pady=(6, 16))

        ttk.Label(outer, text="Completion note").pack(anchor="w")
        ttk.Entry(outer, textvariable=self.note_var).pack(fill="x", pady=(6, 12))

        ttk.Checkbutton(
            outer,
            text="Delete downloaded PC copies after marking done",
            variable=self.delete_local,
        ).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(
            outer,
            text="Delete the Telegram archive messages too",
            variable=self.delete_remote,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            outer,
            text=(
                "Telegram deletion is permanent for this vault message. "
                "Leave it off if you still want Telegram to be the long-term archive."
            ),
            foreground="#667085",
            wraplength=560,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(
            outer,
            text="Open downloads folder after finish",
            variable=self.open_downloads,
        ).pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(24, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Mark Done", command=self._finish).pack(side="right", padx=(0, 8))

    def _finish(self) -> None:
        if self.delete_remote.get() and not messagebox.askyesno(
            "Delete Telegram archive?",
            "Delete the selected Telegram archive message(s) after marking done?",
            parent=self,
        ):
            return
        self.result = {
            "note": self.note_var.get().strip(),
            "delete_local": self.delete_local.get(),
            "delete_remote": self.delete_remote.get(),
            "open_downloads": self.open_downloads.get(),
        }
        self.destroy()


class MetadataDialog(tk.Toplevel):
    def __init__(self, app: "VamosDesktopApp", rows: list[dict]):
        super().__init__(app.root)
        self.app = app
        self.rows = rows
        self.result: dict[str, object | None] | None = None
        self.title(f"Edit metadata for {len(rows)} asset(s)")
        self.geometry("560x620")
        self.transient(app.root)
        self.grab_set()

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="Leave a field blank to keep existing values. Use the clear checkbox to erase that field.",
            wraplength=520,
        ).pack(anchor="w", pady=(0, 10))

        self.vars: dict[str, StringVar] = {}
        self.clear_vars: dict[str, BooleanVar] = {}
        form = ttk.Frame(outer)
        form.pack(fill="both", expand=True)
        fields = [
            ("project", "Project / folder"),
            ("shoot_date", "Shoot date"),
            ("camera", "Camera"),
            ("lens", "Lens"),
            ("tags", "Replace tags"),
            ("append_tags", "Append tags"),
            ("asset_kind", "Kind"),
            ("scene", "Scene"),
            ("location", "Location"),
            ("people", "People"),
            ("rights", "Rights"),
            ("rating", "Rating 1-5"),
            ("youtube_status", "YouTube status"),
            ("notes", "Notes"),
        ]
        first = rows[0] if len(rows) == 1 else {}
        for index, (key, label) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=4)
            var = StringVar(value=_row_text(first, key) if key != "append_tags" else "")
            self.vars[key] = var
            entry = ttk.Entry(form, textvariable=var)
            entry.grid(row=index, column=1, sticky="ew", pady=4, padx=(8, 8))
            clear_var = BooleanVar(value=False)
            self.clear_vars[key] = clear_var
            if key != "append_tags":
                ttk.Checkbutton(form, text="clear", variable=clear_var).grid(row=index, column=2, sticky="w")
        form.columnconfigure(1, weight=1)

        self.favorite_var = StringVar(value="")
        fav = ttk.Frame(outer)
        fav.pack(fill="x", pady=(8, 0))
        ttk.Label(fav, text="Favorite").pack(side="left")
        ttk.Combobox(
            fav,
            textvariable=self.favorite_var,
            values=["keep", "yes", "no"],
            state="readonly",
            width=10,
        ).pack(side="left", padx=(10, 0))
        self.favorite_var.set("keep")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply Metadata", command=self._apply).pack(side="right", padx=(0, 8))

    def _apply(self) -> None:
        updates: dict[str, object | None] = {}
        append_tags = self.vars["append_tags"].get().strip()
        for key, var in self.vars.items():
            if key == "append_tags":
                continue
            if self.clear_vars[key].get():
                updates[key] = None
                continue
            value = var.get().strip()
            if not value:
                continue
            if key == "tags":
                updates[key] = normalize_tags(value)
            elif key == "rating":
                try:
                    rating = int(value)
                except ValueError:
                    messagebox.showerror("Metadata", "Rating must be a number from 1 to 5.")
                    return
                if not 1 <= rating <= 5:
                    messagebox.showerror("Metadata", "Rating must be from 1 to 5.")
                    return
                updates[key] = rating
            else:
                updates[key] = value
        fav = self.favorite_var.get()
        if fav == "yes":
            updates["favorite"] = 1
        elif fav == "no":
            updates["favorite"] = 0
        self.result = updates
        self.append_tags = append_tags
        self.destroy()


class VamosDesktopApp:
    def __init__(self, root: tk.Tk, base_dir: Path):
        self.root = root
        self.base_dir = base_dir
        self.root.title("Vamos Vault")
        self.root.geometry("1280x780")
        self.config = load_config(base_dir)
        self.assets: list[dict] = []
        self.preview_image = None
        self.sync_running = False
        self.thumbnail_running = False
        self.last_output_path: Path | None = None
        self.last_zip_path: Path | None = None

        self.search_var = StringVar()
        self.project_var = StringVar(value="")
        self.status_var = StringVar(value="")
        self.auto_sync_var = BooleanVar(value=True)
        self.status_text = StringVar(value="Ready")
        self.target_var = StringVar(value=self.config["telegram"]["target"])
        api_id, api_hash = telegram_credentials()
        self.api_id_var = StringVar(value=str(api_id or ""))
        self.api_hash_var = StringVar(value=api_hash or "")
        self.premium_var = BooleanVar(value=int(self.config["vault"]["max_file_bytes"]) > FREE_FILE_LIMIT_BYTES)
        self.thumb_status = StringVar(value=thumbnail_backend_label())

        self._build_ui()
        self.refresh_assets()
        self.root.after(1200, self.maybe_auto_sync)


    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.configure(bg="#f4f6f8")
        self.root.title("Vamos Vault")
        icon_path = self.base_dir / "assets" / "vamos-vault.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Subtle.TLabel", foreground="#667085")

        header = ttk.Frame(self.root, padding=(14, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="Vamos Vault", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.header_status = StringVar(value="")
        ttk.Label(header, textvariable=self.header_status, style="Subtle.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0))
        ttk.Button(header, text="Sync Now", command=self.sync_now, style="Accent.TButton").grid(row=0, column=2, padx=(8, 0))
        ttk.Checkbutton(header, text="Auto sync", variable=self.auto_sync_var).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(header, text="Telegram Setup", command=self.open_setup_dialog).grid(row=0, column=4, padx=(8, 0))
        ttk.Label(header, textvariable=self.thumb_status, style="Subtle.TLabel").grid(row=0, column=5, sticky="e", padx=(8, 0))

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        nav = ttk.Frame(main, padding=(0, 0, 10, 0), width=220)
        nav.grid_propagate(False)
        nav.rowconfigure(1, weight=1)
        nav.columnconfigure(0, weight=1)
        ttk.Label(nav, text="Library", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.nav_list = tk.Listbox(nav, width=28, height=18, activestyle="none", exportselection=False)
        self.nav_list.grid(row=1, column=0, sticky="nsew")
        self.nav_list.bind("<<ListboxSelect>>", lambda _e: self.on_nav_select())
        ttk.Button(nav, text="Open Downloads", command=self.open_downloads_folder).grid(row=2, column=0, sticky="ew", pady=(10, 0))
        main.add(nav, weight=1)

        center = ttk.Frame(main)
        center.rowconfigure(3, weight=1)
        center.columnconfigure(0, weight=1)
        main.add(center, weight=4)

        cards = ttk.Frame(center)
        cards.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for i in range(4):
            cards.columnconfigure(i, weight=1)
        self.card_total = StringVar(value="0 assets")
        self.card_remote = StringVar(value="0 remote")
        self.card_queue = StringVar(value="0 in download list")
        self.card_storage = StringVar(value="0 B")
        for idx, (label, var) in enumerate([
            ("Library", self.card_total),
            ("Cloud", self.card_remote),
            ("Download list", self.card_queue),
            ("Storage", self.card_storage),
        ]):
            frame = ttk.LabelFrame(cards, text=label, padding=10)
            frame.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 6, 0))
            ttk.Label(frame, textvariable=var, font=("Segoe UI", 12, "bold")).pack(anchor="w")

        toolbar = ttk.Frame(center)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Search").grid(row=0, column=0, sticky="w")
        ttk.Entry(toolbar, textvariable=self.search_var).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Label(toolbar, text="Project").grid(row=0, column=2, sticky="w")
        self.project_combo = ttk.Combobox(toolbar, textvariable=self.project_var, state="readonly", width=24)
        self.project_combo.grid(row=0, column=3, padx=(8, 8))
        ttk.Label(toolbar, text="Status").grid(row=0, column=4, sticky="w")
        self.status_combo = ttk.Combobox(toolbar, textvariable=self.status_var, state="readonly", width=18)
        self.status_combo.grid(row=0, column=5, padx=(8, 0))

        actions = ttk.Frame(center)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        action_defs = [
            ("Download", self.download_selected, "Accent.TButton"),
            ("Download View", self.download_filtered, "TButton"),
            ("Export ZIP", self.export_zip_selected, "Accent.TButton"),
            ("Export View", self.export_zip_filtered, "TButton"),
            ("Metadata", self.edit_metadata, "TButton"),
            ("Add", self.add_selected_to_queue, "TButton"),
            ("Add View", self.add_filtered_to_queue, "TButton"),
            ("Remove", self.remove_selected_from_queue, "TButton"),
            ("Open File", self.open_selected_download, "TButton"),
            ("Preview", self.fetch_selected_previews, "TButton"),
            ("Finish", self.finish_selected, "Accent.TButton"),
            ("Select View", self.select_visible, "TButton"),
        ]
        action_columns = 5
        for col in range(action_columns):
            actions.columnconfigure(col, weight=1, uniform="actions")
        for index, (label, command, style_name) in enumerate(action_defs):
            ttk.Button(actions, text=label, command=command, style=style_name).grid(
                row=index // action_columns,
                column=index % action_columns,
                sticky="ew",
                padx=(0 if index % action_columns == 0 else 6, 0),
                pady=(0 if index < action_columns else 6, 0),
            )

        self.library_tabs = ttk.Notebook(center)
        self.library_tabs.grid(row=3, column=0, sticky="nsew", pady=(0, 8))

        shot_board = ttk.Frame(self.library_tabs)
        shot_board.rowconfigure(0, weight=1)
        shot_board.columnconfigure(0, weight=1)
        self.library_tabs.add(shot_board, text="Shot Board")
        self.gallery_canvas = tk.Canvas(shot_board, highlightthickness=0, background="#f8fafc")
        self.gallery_canvas.grid(row=0, column=0, sticky="nsew")
        gallery_scroll_y = ttk.Scrollbar(shot_board, orient="vertical", command=self.gallery_canvas.yview)
        gallery_scroll_y.grid(row=0, column=1, sticky="ns")
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll_y.set)
        self.gallery_frame = ttk.Frame(self.gallery_canvas)
        self.gallery_window = self.gallery_canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")
        self.gallery_frame.bind("<Configure>", lambda _e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.bind("<Configure>", self.on_gallery_resize)
        self.gallery_images: list[object] = []
        self._gallery_columns = 0

        catalog = ttk.Frame(self.library_tabs)
        catalog.rowconfigure(0, weight=1)
        catalog.columnconfigure(0, weight=1)
        self.library_tabs.add(catalog, text="Catalog")
        columns = ("file", "project", "date", "tags", "size", "duration", "status", "rating")
        self.tree = ttk.Treeview(catalog, columns=columns, show="headings", selectmode="extended")
        headings = {
            "file": "File",
            "project": "Project",
            "date": "Shoot",
            "tags": "Tags",
            "size": "Size",
            "duration": "Dur",
            "status": "Status",
            "rating": "Rate",
        }
        widths = {"file": 300, "project": 170, "date": 92, "tags": 190, "size": 88, "duration": 70, "status": 104, "rating": 58}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=54)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(catalog, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        right = ttk.Frame(main, padding=(12, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        main.add(right, weight=2)
        self.root.after(250, lambda pane=main: self.set_initial_panes(pane))
        self.preview_label = ttk.Label(right, text="Select footage", anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.detail = tk.Text(right, height=24, wrap="word", relief="flat")
        self.detail.grid(row=1, column=0, sticky="nsew")
        self.queue_label = ttk.Label(right, text="Download list: 0", style="Subtle.TLabel")
        self.queue_label.grid(row=2, column=0, sticky="w", pady=(10, 4))
        self.job_status = StringVar(value="No download running.")
        self.job_progress = tk.DoubleVar(value=0)
        ttk.Label(right, textvariable=self.job_status, style="Subtle.TLabel", wraplength=360).grid(
            row=3, column=0, sticky="ew", pady=(0, 6)
        )
        ttk.Progressbar(right, variable=self.job_progress, maximum=100).grid(row=4, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(right, text="Download List For Editing", command=self.download_queue).grid(row=5, column=0, sticky="ew")
        ttk.Button(right, text="Export Download List ZIP", command=self.pack_queue).grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(right, text="Open Last Download", command=self.open_last_output).grid(row=7, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(right, text="Open Last ZIP", command=self.open_last_zip).grid(row=8, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(right, text="Clear Download List", command=self.clear_queue).grid(row=9, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(right, text="Finish Selected Footage", command=self.finish_selected).grid(row=10, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(right, text="Open HTML Report", command=self.open_studio_report).grid(row=11, column=0, sticky="ew", pady=(8, 0))

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_text).grid(row=0, column=0, sticky="w")

        self.search_var.trace_add("write", lambda *_: self.populate_tree())
        self.project_combo.bind("<<ComboboxSelected>>", lambda _e: self.populate_tree())
        self.status_combo.bind("<<ComboboxSelected>>", lambda _e: self.populate_tree())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_selection())
        self.active_nav: tuple[str, str | None] = ("all", None)
        self.nav_items: list[tuple[str, str | None]] = []
    def set_initial_panes(self, pane: ttk.PanedWindow) -> None:
        try:
            pane.sashpos(0, 220)
            pane.sashpos(1, max(820, self.root.winfo_width() - 460))
        except tk.TclError:
            pass

    def db(self) -> VaultDB:
        self.config = load_config(self.base_dir)
        return db_from_config(self.config, self.base_dir)


    def needs_metadata(self, row: dict) -> bool:
        return not (row.get("project") and row.get("tags") and row.get("rights"))

    def refresh_nav(self, projects: list[str]) -> None:
        current = getattr(self, "active_nav", ("all", None))
        self.nav_items = [
            ("all", None),
            ("remote", None),
            ("needs", None),
            ("queue", None),
            ("downloaded", None),
            ("done", None),
        ] + [("project", project) for project in projects]
        labels = {
            ("all", None): f"All footage ({len(self.assets)})",
            ("remote", None): f"Telegram archive ({sum(1 for row in self.assets if row.get('status') == 'remote')})",
            ("needs", None): f"Needs metadata ({sum(1 for row in self.assets if self.needs_metadata(row))})",
            ("queue", None): f"Download list ({len(getattr(self, 'queued_shas', set()))})",
            ("downloaded", None): f"Downloaded ({getattr(self, 'downloaded_count', 0)})",
            ("done", None): f"Done ({getattr(self, 'done_count', 0)})",
        }
        self.nav_list.delete(0, "end")
        selected_index = 0
        for index, item in enumerate(self.nav_items):
            if item[0] == "project":
                label = f"Project: {item[1]}"
            else:
                label = labels[item]
            self.nav_list.insert("end", label)
            if item == current:
                selected_index = index
        self.nav_list.selection_clear(0, "end")
        self.nav_list.selection_set(selected_index)
        self.nav_list.activate(selected_index)
        self.active_nav = self.nav_items[selected_index]

    def on_nav_select(self) -> None:
        selection = self.nav_list.curselection()
        if not selection:
            return
        self.active_nav = self.nav_items[int(selection[0])]
        self.project_var.set("")
        self.populate_tree()

    def update_connection_header(self) -> None:
        api_id, api_hash = telegram_credentials()
        target = self.config["telegram"]["target"]
        if api_id and api_hash:
            self.header_status.set(f"Connected setup - target {target}")
        else:
            self.header_status.set("Telegram setup needed")

    def open_setup_dialog(self) -> None:
        TelegramSetupDialog(self)

    def open_api_page(self) -> None:
        webbrowser.open(API_URL)
        self.status_text.set("Opened Telegram API page. Create an app, then paste api_id and api_hash here.")

    def save_settings(self) -> bool:
        api_id = self.api_id_var.get().strip()
        api_hash = self.api_hash_var.get().strip()
        target = self.target_var.get().strip() or "me"
        if not api_id or not api_hash:
            messagebox.showwarning("Telegram setup", "Paste both API ID and API Hash first.")
            return False
        _update_env_file(
            self.base_dir / ".env",
            {
                "TELEGRAM_API_ID": api_id,
                "TELEGRAM_API_HASH": api_hash,
                "TELEGRAM_TARGET": target,
            },
        )
        write_config(
            self.base_dir,
            target=target,
            premium=self.premium_var.get(),
            database=self.config["vault"]["database"],
        )
        self.config = load_config(self.base_dir)
        self.status_text.set("Settings saved. Now click Connect Account.")
        return True

    async def _connect_async(self, phone: str, code_callback, password_callback) -> None:
        api_id, api_hash = telegram_credentials()
        if not api_id or not api_hash:
            raise TelegramConfigError("Save API ID and API Hash first.")
        session_path = resolve_data_path(self.base_dir, f".vamos-vault/{self.config['telegram']['session_name']}")
        client = TelegramClient(str(session_path), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            code = code_callback()
            if not code:
                await client.disconnect()
                raise TelegramConfigError("No login code entered.")
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = password_callback()
                if not password:
                    await client.disconnect()
                    raise TelegramConfigError("Two-step password required.")
                await client.sign_in(password=password)
        await client.disconnect()


    def connect_account(self, skip_save: bool = False) -> None:
        if not skip_save and not self.save_settings():
            return
        phone = simpledialog.askstring("Telegram login", "Enter your Telegram phone number with country code:", parent=self.root)
        if not phone:
            return

        def code_callback() -> str | None:
            return simpledialog.askstring("Telegram login", "Paste the login code Telegram sent you:", parent=self.root)

        def password_callback() -> str | None:
            return simpledialog.askstring("Telegram login", "Enter your Telegram two-step password:", parent=self.root, show="*")

        try:
            asyncio.run(self._connect_async(phone, code_callback, password_callback))
        except Exception as exc:
            messagebox.showerror("Telegram login", str(exc))
            return
        self.status_text.set("Telegram account connected. Sync can run now.")
        self.update_connection_header()
        messagebox.showinfo("Telegram login", "Telegram account connected.")
        self.sync_now()
    def refresh_assets(self) -> None:
        db = self.db()
        try:
            self.assets = [dict(row) for row in db.all_assets()]
            queued = [dict(row) for row in db.queued_assets()]
            self.queued_shas = {row["sha256"] for row in queued}
        finally:
            db.close()
        self.downloaded_count = sum(1 for row in self.assets if row.get("status") == "downloaded")
        self.done_count = sum(1 for row in self.assets if row.get("status") == "done")
        self.remote_deleted_count = sum(1 for row in self.assets if row.get("status") == "remote-deleted")
        projects = sorted({row.get("project") or "" for row in self.assets if row.get("project")})
        self.project_combo["values"] = [""] + projects
        self.status_combo["values"] = [""] + sorted({row.get("status") or "" for row in self.assets if row.get("status")})
        self.refresh_nav(projects)
        total_bytes = sum(int(row.get("size_bytes") or 0) for row in self.assets)
        remote = sum(1 for row in self.assets if row.get("telegram_message_id") and row.get("status") != "remote-deleted")
        self.card_total.set(f"{len(self.assets)} assets")
        self.card_remote.set(f"{remote} in Telegram")
        self.card_queue.set(f"{len(self.queued_shas)} queued")
        self.card_storage.set(format_bytes(total_bytes))
        self.queue_label.config(text=f"Download list: {len(self.queued_shas)}")
        self.update_connection_header()
        self.populate_tree()

    def filtered_assets(self) -> list[dict]:
        query = self.search_var.get().strip().lower()
        project = self.project_var.get()
        status = self.status_var.get()
        nav_kind, nav_value = getattr(self, "active_nav", ("all", None))
        rows = []
        for row in self.assets:
            if nav_kind == "project" and row.get("project") != nav_value:
                continue
            if nav_kind == "needs" and not self.needs_metadata(row):
                continue
            if nav_kind == "queue" and row.get("sha256") not in getattr(self, "queued_shas", set()):
                continue
            if nav_kind == "remote" and row.get("status") != "remote":
                continue
            if nav_kind == "downloaded" and row.get("status") != "downloaded":
                continue
            if nav_kind == "done" and row.get("status") != "done":
                continue
            if project and row.get("project") != project:
                continue
            if status and row.get("status") != status:
                continue
            hay = " ".join(
                _row_text(row, key)
                for key in ["filename", "project", "tags", "notes", "scene", "location", "people", "camera", "lens", "youtube_status"]
            ).lower()
            if query and query not in hay:
                continue
            rows.append(row)
        return rows



    def populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        visible = self.filtered_assets()
        for row in visible:
            tags = row.get("tags") or ""
            markers = []
            if row.get("sha256") in getattr(self, "queued_shas", set()):
                markers.append("queued")
            if row.get("status") == "downloaded":
                markers.append("downloaded")
            if row.get("status") == "done":
                markers.append("done")
            if row.get("status") == "remote-deleted":
                markers.append("remote deleted")
            marker = " [" + ", ".join(markers) + "]" if markers else ""
            self.tree.insert(
                "",
                "end",
                iid=row["sha256"],
                values=(
                    (row.get("filename") or "") + marker,
                    row.get("project") or "",
                    row.get("shoot_date") or "",
                    tags,
                    format_bytes(int(row.get("size_bytes") or 0)),
                    format_duration(row.get("duration_seconds")),
                    row.get("status") or "",
                    f"{row.get('rating')}/5" if row.get("rating") else "",
                ),
            )
        self.render_storyboard(visible)
        self.status_text.set(f"Showing {len(visible)} of {len(self.assets)} assets")
        self.ensure_local_thumbnails()

    def ensure_local_thumbnails(self) -> None:
        if self.thumbnail_running:
            return
        rows = [
            row
            for row in self.assets
            if not row.get("thumbnail_path")
            and row.get("downloaded_path")
            and Path(str(row.get("downloaded_path"))).exists()
        ]
        if not rows:
            return
        self.thumbnail_running = True

        def worker() -> None:
            changed = 0
            db = self.db()
            try:
                for row in rows[:100]:
                    thumbnail_path = ensure_thumbnail_for_asset(self.base_dir, row)
                    if thumbnail_path:
                        db.set_thumbnail_path(row["sha256"], thumbnail_path)
                        changed += 1
            finally:
                db.close()
                self.thumbnail_running = False
            if changed:
                self.root.after(0, self.refresh_assets)

        threading.Thread(target=worker, daemon=True).start()

    def on_gallery_resize(self, event: tk.Event) -> None:
        if not hasattr(self, "gallery_window"):
            return
        self.gallery_canvas.itemconfigure(self.gallery_window, width=event.width)
        columns = self.gallery_columns_for_width(event.width)
        if columns != getattr(self, "_gallery_columns", 0):
            self._gallery_columns = columns
            self.render_storyboard(self.filtered_assets())

    def gallery_columns_for_width(self, width: int) -> int:
        return max(1, min(5, max(1, width) // 245))

    def render_storyboard(self, rows: list[dict]) -> None:
        if not hasattr(self, "gallery_frame"):
            return
        for child in self.gallery_frame.winfo_children():
            child.destroy()
        self.gallery_images = []
        width = self.gallery_canvas.winfo_width() if hasattr(self, "gallery_canvas") else 900
        columns = getattr(self, "_gallery_columns", 0) or self.gallery_columns_for_width(width)
        self._gallery_columns = columns
        for index, row in enumerate(rows[:80]):
            card = tk.Frame(self.gallery_frame, bg="#ffffff", bd=1, relief="solid", padx=8, pady=8)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=6, pady=6)
            preview = self.thumbnail_label(card, row, max_size=(206, 122), text_width=28, text_height=7)
            preview.pack(fill="x")
            name = row.get("filename") or "untitled"
            tk.Label(card, text=name[:30], width=30, anchor="w", bg="#ffffff", fg="#101828").pack(anchor="w", pady=(6, 0))
            flags = []
            if row.get("sha256") in getattr(self, "queued_shas", set()):
                flags.append("QUEUED")
            if row.get("status") == "downloaded":
                flags.append("DOWNLOADED")
            if row.get("status") == "done":
                flags.append("DONE")
            if row.get("status") == "remote-deleted":
                flags.append("REMOTE DELETED")
            if row.get("thumbnail_path") and Path(str(row.get("thumbnail_path"))).exists():
                flags.append("PREVIEW")
            meta_parts = [
                row.get("project") or "No project",
                row.get("shoot_date") or "No date",
                format_duration(row.get("duration_seconds")),
                format_bytes(int(row.get("size_bytes") or 0)),
            ]
            meta = "  |  ".join(str(part) for part in meta_parts if part)
            tk.Label(card, text=meta[:38], width=30, anchor="w", bg="#ffffff", fg="#667085").pack(anchor="w")
            badge = "  ".join(flags) if flags else (row.get("status") or "catalog")
            tk.Label(card, text=str(badge)[:32], width=30, anchor="w", bg="#ffffff", fg="#175cd3").pack(anchor="w", pady=(3, 0))
            for widget in [card, preview, *card.winfo_children()]:
                widget.bind("<Button-1>", lambda _e, sha=row["sha256"]: self.select_asset(sha))
        if not rows:
            ttk.Label(self.gallery_frame, text="No footage in this view. Sync Telegram or adjust filters.").grid(row=0, column=0, sticky="w", padx=12, pady=12)

    def thumbnail_label(
        self,
        parent: tk.Widget,
        row: dict,
        *,
        max_size: tuple[int, int] = (138, 82),
        text_width: int = 19,
        text_height: int = 5,
    ) -> tk.Widget:
        thumb = row.get("thumbnail_path")
        if thumb and Path(str(thumb)).exists() and Image is not None and ImageTk is not None:
            try:
                with Image.open(str(thumb)) as image:
                    image.thumbnail(max_size)
                    photo = ImageTk.PhotoImage(image)
                self.gallery_images.append(photo)
                return ttk.Label(parent, image=photo)
            except Exception:
                pass  # Fall back to a text tile if the thumbnail is unreadable.
        kind = "VIDEO" if (row.get("codec") or "").startswith("video/") else "FILE"
        hint = "DOWNLOAD\nFOR PREVIEW" if kind == "VIDEO" and not row.get("downloaded_path") else kind
        label = tk.Label(parent, text=hint, width=text_width, height=text_height, bg="#e5e7eb", fg="#475467", relief="solid", bd=1)
        return label

    def select_asset(self, sha: str) -> None:
        if self.tree.exists(sha):
            self.tree.selection_set(sha)
            self.tree.see(sha)
            self.show_selection()

    def selected_rows(self) -> list[dict]:
        selected = set(self.tree.selection())
        by_sha = {row["sha256"]: row for row in self.assets}
        return [by_sha[sha] for sha in selected if sha in by_sha]

    def select_visible(self) -> None:
        items = self.tree.get_children()
        self.tree.selection_set(items)
        self.status_text.set(f"Selected {len(items)} visible assets.")
        self.show_selection()



    def show_selection(self) -> None:
        rows = self.selected_rows()
        if not rows:
            self.preview_label.config(text="Select footage", image="")
            self.detail.delete("1.0", "end")
            return
        row = rows[0]
        self.show_preview(row)
        total_bytes = sum(int(item.get("size_bytes") or 0) for item in rows)
        queue_state = "yes" if row.get("sha256") in getattr(self, "queued_shas", set()) else "no"
        downloaded = row.get("downloaded_path") or ""
        details = [
            f"Selected: {len(rows)} asset(s), {format_bytes(total_bytes)}",
            f"First item queued: {queue_state}",
            "",
            f"File: {row.get('filename') or ''}",
            f"Project: {row.get('project') or ''}",
            f"Shoot date: {row.get('shoot_date') or ''}",
            f"Scene: {row.get('scene') or ''}",
            f"Location: {row.get('location') or ''}",
            f"Camera: {row.get('camera') or ''}",
            f"Lens: {row.get('lens') or ''}",
            f"Tags: {row.get('tags') or ''}",
            f"Rights: {row.get('rights') or ''}",
            f"YouTube: {row.get('youtube_status') or ''}",
            f"Status: {row.get('status') or ''}",
            f"Telegram message: {row.get('telegram_message_id') or ''}",
            f"Downloaded path: {downloaded}",
            "",
            "Download Selected writes originals to an editing folder.",
            "Export Selected ZIP writes originals plus metadata CSV/JSON.",
            "Open Downloaded reveals the local copy if it already exists.",
            "Fetch Preview creates a thumbnail for old Telegram items that have no preview.",
            "Finish marks footage done and can clean local or Telegram copies.",
            "",
            row.get("notes") or "",
        ]
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(details))
    def show_preview(self, row: dict) -> None:
        thumb = row.get("thumbnail_path")
        if not thumb or not Path(str(thumb)).exists() or Image is None or ImageTk is None:
            self.preview_label.config(text=row.get("filename") or "No preview", image="")
            return
        try:
            with Image.open(str(thumb)) as image:
                image.thumbnail((340, 220))
                self.preview_image = ImageTk.PhotoImage(image)
            self.preview_label.config(image=self.preview_image, text="")
        except Exception:
            self.preview_label.config(text=row.get("filename") or "No preview", image="")

    def sync_now(self) -> None:
        if self.sync_running:
            return
        self.sync_running = True
        self.status_text.set("Syncing Telegram...")

        def worker() -> None:
            try:
                config = load_config(self.base_dir)
                rows = sync_remote_catalog(config, self.base_dir, limit=200, project="Inbox", tags="phone,raw", thumbnails=True)
                self.root.after(0, lambda: self.status_text.set(f"Synced {len(rows)} Telegram media items."))
                self.root.after(0, self.refresh_assets)
            except Exception as exc:
                self.root.after(0, lambda error=exc: messagebox.showerror("Sync", str(error)))
                self.root.after(0, lambda: self.status_text.set("Sync failed. Check Telegram setup."))
            finally:
                self.sync_running = False

        threading.Thread(target=worker, daemon=True).start()

    def maybe_auto_sync(self) -> None:
        if self.auto_sync_var.get():
            api_id, api_hash = telegram_credentials()
            if api_id and api_hash:
                self.sync_now()
        self.root.after(AUTOSYNC_MS, self.maybe_auto_sync)

    def edit_metadata(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Metadata", "Select one or more assets first.")
            return
        dialog = MetadataDialog(self, rows)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        db = self.db()
        try:
            if getattr(dialog, "append_tags", ""):
                for row in rows:
                    updates = dict(dialog.result)
                    updates["tags"] = merge_tags(row.get("tags"), dialog.append_tags)
                    db.update_metadata([row["sha256"]], updates)
            else:
                db.update_metadata([row["sha256"] for row in rows], dialog.result)
        finally:
            db.close()
        self.refresh_assets()
        self.status_text.set(f"Updated metadata for {len(rows)} assets.")

    def add_selected_to_queue(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Download list", "Select one or more assets first.")
            return
        self._add_rows_to_queue(rows)

    def add_filtered_to_queue(self) -> None:
        rows = self.filtered_assets()
        if not rows:
            messagebox.showinfo("Download list", "No visible assets to add.")
            return
        if not messagebox.askyesno("Download list", f"Add all {len(rows)} visible assets to the download list?"):
            return
        self._add_rows_to_queue(rows)

    def _add_rows_to_queue(self, rows: list[dict]) -> None:
        db = self.db()
        try:
            db.add_to_queue([row["sha256"] for row in rows])
        finally:
            db.close()
        self.refresh_assets()
        self.status_text.set(f"Added {len(rows)} assets to the download list.")




    def remove_selected_from_queue(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Download list", "Select one or more assets first.")
            return
        db = self.db()
        try:
            removed = db.remove_from_queue([row["sha256"] for row in rows])
        finally:
            db.close()
        self.refresh_assets()
        self.status_text.set(f"Removed {removed} asset(s) from the download list.")

    def clear_queue(self) -> None:
        if not getattr(self, "queued_shas", set()):
            messagebox.showinfo("Download list", "The download list is already empty.")
            return
        if not messagebox.askyesno("Download list", "Clear the entire download list?"):
            return
        db = self.db()
        try:
            removed = db.clear_queue()
        finally:
            db.close()
        self.refresh_assets()
        self.status_text.set(f"Cleared {removed} asset(s) from the download list.")

    def download_queue(self) -> None:
        db = self.db()
        try:
            rows = [dict(row) for row in db.queued_assets()]
        finally:
            db.close()
        self._pack_rows(rows, "download-list", make_zip=False, title="Download list for editing")

    def open_selected_download(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Downloaded file", "Select an asset first.")
            return
        path = Path(str(rows[0].get("downloaded_path") or ""))
        if not path.exists():
            messagebox.showinfo("Downloaded file", "This asset has not been downloaded on this PC yet.")
            return
        self.open_path(path.parent)

    def open_last_output(self) -> None:
        path = self.last_output_path
        if not path or not Path(path).exists():
            messagebox.showinfo("Last download", "No completed download folder yet.")
            return
        self.open_path(Path(path))

    def open_last_zip(self) -> None:
        path = self.last_zip_path
        if not path or not Path(path).exists():
            messagebox.showinfo("Last ZIP", "No completed ZIP export yet.")
            return
        self.open_path(Path(path).parent)

    def finish_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Finish footage", "Select one or more assets first.")
            return
        dialog = FinishJobDialog(self, rows)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        note = str(dialog.result.get("note") or "")
        delete_local = bool(dialog.result.get("delete_local"))
        delete_remote = bool(dialog.result.get("delete_remote"))
        open_downloads = bool(dialog.result.get("open_downloads"))
        self.status_text.set(f"Finishing {len(rows)} asset(s)...")
        self.job_status.set(f"Finishing {len(rows)} asset(s).")

        def worker() -> None:
            done_count = 0
            local_deleted = 0
            remote_deleted = 0
            errors: list[str] = []
            config = load_config(self.base_dir)
            db = self.db()
            try:
                for row in rows:
                    try:
                        changed = db.mark_done(row["sha256"], notes=note or None)
                        done_count += 1
                        if delete_local:
                            path = Path(str(changed["downloaded_path"] or ""))
                            if path.exists() and path.is_file():
                                path.unlink()
                                local_deleted += 1
                            db.clear_downloaded_path(row["sha256"])
                        if delete_remote and changed["telegram_message_id"] is not None:
                            asyncio.run(delete_message(config, self.base_dir, message_id=int(changed["telegram_message_id"])))
                            db.mark_remote_deleted(row["sha256"])
                            remote_deleted += 1
                    except Exception as exc:
                        errors.append(f"{row.get('filename') or row['sha256']}: {exc}")
            finally:
                db.close()

            summary = (
                f"Done: {done_count}. "
                f"Local deleted: {local_deleted}. "
                f"Telegram deleted: {remote_deleted}."
            )
            self.root.after(0, self.refresh_assets)
            self.root.after(0, lambda: self.job_status.set(summary if not errors else summary + f" Errors: {len(errors)}."))
            self.root.after(0, lambda: self.status_text.set("Ready"))
            if open_downloads:
                self.root.after(0, self.open_downloads_folder)
            if errors:
                self.root.after(0, lambda: messagebox.showerror("Finish footage", "\n".join(errors[:8])))
            else:
                self.root.after(0, lambda: messagebox.showinfo("Finish footage", summary))

        threading.Thread(target=worker, daemon=True).start()

    def fetch_selected_previews(self) -> None:
        rows = [
            row
            for row in self.selected_rows()
            if not row.get("thumbnail_path") and row.get("telegram_message_id")
        ]
        if not rows:
            messagebox.showinfo("Fetch preview", "Select remote videos or files that do not already have thumbnails.")
            return
        total_bytes = sum(int(row.get("size_bytes") or 0) for row in rows)
        if not messagebox.askyesno(
            "Fetch preview",
            (
                f"Create thumbnails for {len(rows)} item(s)?\n\n"
                f"Vamos will temporarily download {format_bytes(total_bytes)} to make preview frames, "
                "then delete the temporary originals."
            ),
        ):
            return
        self.status_text.set("Fetching preview thumbnails...")

        def progress(filename: str, received: int, total_bytes: int) -> None:
            label = f"Preview {filename}: {format_bytes(received)} / {format_bytes(total_bytes)}"
            self.root.after(0, lambda value=label: self.status_text.set(value))

        def worker() -> None:
            made = 0
            try:
                config = load_config(self.base_dir)
                for row in rows:
                    thumbnail = create_remote_preview_thumbnail(
                        config,
                        self.base_dir,
                        row,
                        progress_callback=progress,
                        status_callback=lambda msg: self.root.after(0, lambda m=msg: self.status_text.set(m)),
                    )
                    if thumbnail:
                        made += 1
                self.root.after(0, self.refresh_assets)
                self.root.after(0, lambda: messagebox.showinfo("Fetch preview", f"Created {made} thumbnail(s)."))
            except Exception as exc:
                self.root.after(0, lambda error=exc: messagebox.showerror("Fetch preview failed", str(error)))
            finally:
                self.root.after(0, lambda: self.status_text.set("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    def _pack_rows(self, rows: list[dict], default_name: str, *, make_zip: bool, title: str) -> None:
        if not rows:
            messagebox.showinfo(title, "Nothing selected.")
            return
        dialog = DownloadJobDialog(self, rows, default_name=default_name, make_zip=make_zip, title=title)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        out = dialog.result["out_dir"]
        name = str(dialog.result["name"])
        make_zip = bool(dialog.result["make_zip"])
        open_after = bool(dialog.result["open_after"])
        self.status_text.set(f"{title} started...")
        self.job_status.set(f"{title}: preparing {len(rows)} original file(s).")
        self.job_progress.set(0)
        job_total_bytes = max(1, sum(int(row.get("size_bytes") or 0) for row in rows))
        progress_by_file: dict[str, int] = {}

        def set_progress(percent: float) -> None:
            self.job_progress.set(max(0, min(100, percent)))

        def progress(filename: str, received: int, total_bytes: int) -> None:
            key = filename or "current"
            progress_by_file[key] = int(received or 0)
            total_received = min(job_total_bytes, sum(progress_by_file.values()))
            percent = (total_received / job_total_bytes) * 100
            label = f"{filename}: {format_bytes(received)} / {format_bytes(total_bytes)}"
            self.root.after(0, lambda value=label: self.status_text.set(value))
            self.root.after(0, lambda value=label: self.job_status.set("Downloading original: " + value))
            self.root.after(0, lambda value=percent: set_progress(value))

        def job_status(message: str) -> None:
            self.root.after(0, lambda m=message: self.status_text.set(m))
            self.root.after(0, lambda m=message: self.job_status.set(m))

        def worker() -> None:
            try:
                result = create_download_package(
                    load_config(self.base_dir),
                    self.base_dir,
                    rows,
                    out_dir=Path(out),
                    name=name,
                    make_zip=make_zip,
                    layout="project-date-kind",
                    progress_callback=progress,
                    status_callback=job_status,
                )
                self.last_output_path = result.folder
                self.last_zip_path = result.zip_path
                self.root.after(0, lambda: set_progress(100))
                self.root.after(0, self.refresh_assets)
                if result.zip_path:
                    message = f"Editing folder:\n{result.folder}\n\nZIP package:\n{result.zip_path}"
                else:
                    message = f"Editing folder:\n{result.folder}"
                self.root.after(0, lambda: self.job_status.set(f"{title} complete: {len(result.rows)} file(s) ready in {result.folder}."))
                self.root.after(0, lambda: messagebox.showinfo(f"{title} complete", message))
                if open_after:
                    self.root.after(0, lambda: self.open_path(result.folder))
            except Exception as exc:
                self.root.after(0, lambda: set_progress(0))
                self.root.after(0, lambda error=exc: self.job_status.set(f"{title} failed: {error}"))
                self.root.after(0, lambda error=exc: messagebox.showerror(f"{title} failed", str(error)))
            finally:
                self.root.after(0, lambda: self.status_text.set("Ready"))

        threading.Thread(target=worker, daemon=True).start()
    def download_selected(self) -> None:
        rows = self.selected_rows()
        default = rows[0].get("project") if rows else "selected-footage"
        self._pack_rows(rows, default or "selected-footage", make_zip=False, title="Download for editing")

    def download_filtered(self) -> None:
        rows = self.filtered_assets()
        default = rows[0].get("project") if rows else "visible-footage"
        self._pack_rows(rows, default or "visible-footage", make_zip=False, title="Download visible")

    def export_zip_selected(self) -> None:
        rows = self.selected_rows()
        default = rows[0].get("project") if rows else "selected-footage"
        self._pack_rows(rows, default or "selected-footage", make_zip=True, title="Export ZIP")

    def export_zip_filtered(self) -> None:
        rows = self.filtered_assets()
        default = rows[0].get("project") if rows else "visible-footage"
        self._pack_rows(rows, default or "visible-footage", make_zip=True, title="Export visible ZIP")

    def pack_selected(self) -> None:
        self.export_zip_selected()

    def pack_filtered(self) -> None:
        self.export_zip_filtered()

    def pack_queue(self) -> None:
        db = self.db()
        try:
            rows = [dict(row) for row in db.queued_assets()]
        finally:
            db.close()
        self._pack_rows(rows, "download-list", make_zip=True, title="Export download list ZIP")

    def open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))
        except OSError:
            webbrowser.open(path.resolve().as_uri())

    def open_downloads_folder(self) -> None:
        target = self.base_dir / "downloads"
        target.mkdir(exist_ok=True)
        self.open_path(target)

    def open_studio_report(self) -> None:
        db = self.db()
        try:
            assets = enrich_assets_for_display([dict(row) for row in db.all_assets()])
            manifest = build_manifest(config=self.config, stats=db.stats(), assets=assets)
            path = write_studio_html(self.base_dir / ".vamos-vault" / "studio" / "index.html", manifest)
        finally:
            db.close()
        webbrowser.open(path.resolve().as_uri())


def main() -> None:
    try:
        root = tk.Tk()
        app = VamosDesktopApp(root, Path.cwd())
        root.update_idletasks()
        root.deiconify()
        root.lift()
        try:
            root.attributes("-topmost", True)
            root.after(1200, lambda: root.attributes("-topmost", False))
        except tk.TclError:
            pass
        root.focus_force()
        root.mainloop()
    except Exception as exc:
        log_dir = Path.cwd() / ".vamos-vault"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "app-error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            messagebox.showerror("Vamos Vault could not start", f"{exc}\n\nDetails were written to:\n{log_path}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()

