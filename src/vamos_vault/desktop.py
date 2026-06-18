from __future__ import annotations

import asyncio
import json
import os
import threading
import time
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

from .config import FREE_FILE_LIMIT_BYTES, load_config, resolve_data_path, telegram_credentials, write_config
from .db import VaultDB
from .media import format_bytes, format_duration, normalize_tags
from .reports import build_manifest, enrich_assets_for_display, write_studio_html
from .telegram_client import TelegramConfigError, delete_message
from .thumbnails import ensure_thumbnail_for_asset, thumbnail_backend_label
from .workflows import (
    create_download_package,
    create_remote_preview_thumbnail,
    db_from_config,
    merge_tags,
    sync_remote_catalog,
    upload_paths,
)


API_URL = "https://my.telegram.org/apps"
AUTOSYNC_MS = 3 * 60 * 1000
FOCUS_SYNC_COOLDOWN = 60.0  # seconds; sync on window refocus, but not more often than this

# ---------------------------------------------------------------------------
# Design tokens — a calm dark "editor" palette videographers feel at home in.
# ---------------------------------------------------------------------------
BG = "#0f1115"
SURFACE = "#171a21"
SURFACE_2 = "#1e222b"
SURFACE_3 = "#262b36"
BORDER = "#2a2f3a"
BORDER_2 = "#3a414f"
TEXT = "#e6e8ec"
MUTED = "#9aa3b2"
FAINT = "#6b7280"
ACCENT = "#2dd4bf"
ACCENT_DK = "#0d9488"
ACCENT_INK = "#03110d"
GOOD = "#34d399"
GOOD_BG = "#0f2a20"
WARN = "#fbbf24"
WARN_BG = "#332708"
BAD = "#f87171"
BAD_BG = "#3a1414"
INFO = "#60a5fa"
INFO_BG = "#102338"

FONT = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_MD = ("Segoe UI", 11)
FONT_BD = ("Segoe UI", 10, "bold")
FONT_H1 = ("Segoe UI", 16, "bold")
FONT_H2 = ("Segoe UI", 13, "bold")
FONT_BADGE = ("Segoe UI", 8, "bold")

STATUS_BADGES = {
    "remote": (INFO, INFO_BG),
    "uploaded": (GOOD, GOOD_BG),
    "downloaded": (ACCENT, "#0c2b27"),
    "done": (GOOD, GOOD_BG),
    "remote-deleted": (BAD, BAD_BG),
    "dry-run": (WARN, WARN_BG),
    "cataloged": (MUTED, SURFACE_3),
}


def apply_theme(root: tk.Tk) -> None:
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=TEXT, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT)
    style.configure("Faint.TLabel", background=BG, foreground=FAINT, font=FONT_SM)
    style.configure("H1.TLabel", background=BG, foreground=TEXT, font=FONT_H1)
    style.configure("H2.TLabel", background=BG, foreground=TEXT, font=FONT_H2)

    style.configure(
        "TButton",
        background=SURFACE_3,
        foreground=TEXT,
        bordercolor=BORDER_2,
        lightcolor=SURFACE_3,
        darkcolor=SURFACE_3,
        relief="flat",
        focusthickness=0,
        focuscolor=SURFACE_3,
        padding=(12, 7),
        font=FONT_BD,
    )
    style.map(
        "TButton",
        background=[("active", SURFACE_2), ("pressed", SURFACE_2), ("disabled", SURFACE)],
        foreground=[("disabled", FAINT)],
    )
    style.configure("Primary.TButton", background=ACCENT_DK, foreground=ACCENT_INK)
    style.map(
        "Primary.TButton",
        background=[("active", ACCENT), ("pressed", ACCENT), ("disabled", SURFACE_2)],
        foreground=[("disabled", FAINT)],
    )
    style.configure("Danger.TButton", background="#7f1d1d", foreground="#fee2e2")
    style.map("Danger.TButton", background=[("active", "#b91c1c"), ("disabled", SURFACE)])
    style.configure("Ghost.TButton", background=SURFACE, foreground=MUTED, bordercolor=BORDER)
    style.map(
        "Ghost.TButton",
        background=[("active", SURFACE_2)],
        foreground=[("active", TEXT), ("disabled", FAINT)],
    )

    style.configure(
        "TEntry",
        fieldbackground=SURFACE_3,
        foreground=TEXT,
        bordercolor=BORDER_2,
        lightcolor=BORDER_2,
        darkcolor=BORDER_2,
        insertcolor=TEXT,
        padding=6,
    )
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE_3,
        background=SURFACE_3,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER_2,
        lightcolor=BORDER_2,
        darkcolor=BORDER_2,
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE_3)],
        foreground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DK)
    root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_INK)

    style.configure("TCheckbutton", background=BG, foreground=TEXT, focuscolor=BG)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", TEXT)])
    style.configure("Card.TCheckbutton", background=SURFACE, foreground=TEXT)
    style.map("Card.TCheckbutton", background=[("active", SURFACE)])

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        borderwidth=0,
        rowheight=30,
        font=FONT,
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_2,
        foreground=MUTED,
        relief="flat",
        font=FONT_SM,
        padding=(8, 8),
    )
    style.map("Treeview.Heading", background=[("active", SURFACE_2)])
    style.map("Treeview", background=[("selected", "#123b35")], foreground=[("selected", TEXT)])

    style.configure("TNotebook", background=BG, bordercolor=BORDER, borderwidth=0)
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(18, 9), font=FONT_BD, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", TEXT)])

    style.configure(
        "Accent.Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=SURFACE_3,
        bordercolor=SURFACE_3,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )

    style.configure(
        "Vertical.TScrollbar",
        background=SURFACE_2,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", BORDER_2)])
    style.configure("TPanedwindow", background=BG)


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


def quality_badge_args(lossless: object) -> tuple[str, str, str] | None:
    """Return (text, fg, bg) for the lossless/compressed badge, or None if unknown."""
    if lossless is None or lossless == "":
        return None
    if int(lossless) == 1:
        return ("ORIGINAL", GOOD, GOOD_BG)
    return ("COMPRESSED", WARN, WARN_BG)


def make_badge(parent: tk.Widget, text: str, fg: str, bg: str) -> tk.Label:
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=FONT_BADGE, padx=7, pady=2)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class HelpDialog(tk.Toplevel):
    """Scrollable getting-started guide — setup, lossless, finding footage, metadata."""

    def __init__(self, app: "VamosDesktopApp"):
        super().__init__(app.root)
        self.app = app
        self.title("Getting started — Vamos Vault")
        self.geometry("720x700")
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()

        # Footer stays pinned at the bottom.
        footer = tk.Frame(self, bg=SURFACE)
        footer.pack(side="bottom", fill="x")
        self.dont_show = BooleanVar(value=app.welcome_hidden())
        ttk.Checkbutton(
            footer, text="Don't show this automatically (always available via the ? button)",
            variable=self.dont_show, style="Card.TCheckbutton",
        ).pack(side="left", padx=16, pady=12)
        ttk.Button(footer, text="Close", style="Primary.TButton", command=self._close).pack(side="right", padx=16, pady=12)

        # Scrollable body.
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        wrap = tk.Frame(body, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="Getting started", font=FONT_H1, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            wrap,
            text="Store full-quality footage on Telegram and pull it back to edit. Here is the whole flow.",
            font=FONT_SM, bg=BG, fg=MUTED,
        ).pack(anchor="w", pady=(6, 14))

        self._card(wrap, "1 · Connect Telegram", [
            "Click Setup in the top bar (or the button below).",
            "Open the Telegram API page, sign in, create an app, copy api_id + api_hash.",
            "Paste them, pick where to store clips (Saved Messages = “me”, or a private channel),",
            "    then Save + Connect and enter the login code Telegram sends you.",
        ])
        ttk.Button(wrap, text="Open Telegram setup", style="Primary.TButton",
                   command=lambda: (self.destroy(), app.open_setup_dialog())).pack(anchor="w", pady=(0, 12))

        tk.Label(
            wrap,
            text="2 · Send clips with ZERO compression",
            font=FONT_H2, bg=BG, fg=TEXT,
        ).pack(anchor="w", pady=(4, 2))
        tk.Label(
            wrap,
            text="Telegram only keeps your exact file when it is sent as a FILE. Sent as a normal video,\n"
            "your phone compresses it before it reaches Telegram — nothing on the PC can undo that.",
            font=FONT_SM, bg=BG, fg=MUTED, justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self._card(wrap, "On iPhone", [
            "Open Telegram → Saved Messages (or your private vault channel).",
            "Tap the paperclip / attachment icon → File, then pick your clip.",
            "If it is only in Photos: select it, tap the … (More) menu → “Send as File”.",
            "Send. It uploads at full original quality.",
        ])
        self._card(wrap, "On Android", [
            "Open Telegram → Saved Messages (or your private vault channel).",
            "Tap the paperclip / attachment icon → File, then pick your clip.",
            "Or, in the Gallery picker, tap the ⋮ menu → “Send as file”.",
            "Send. It uploads at full original quality.",
        ])
        self._card(wrap, "From this PC", [
            "Click Upload in the top bar, add files or a whole shoot folder, and send.",
            "PC uploads are always sent as files, so they are always lossless.",
        ])

        self._card(wrap, "3 · Find your footage fast", [
            "Search by name, project, tag, scene, location, or person.",
            "Use the left sidebar: Originals, Compressed, Telegram archive, Downloaded, Done, Projects.",
            "Sort (newest first by default, or name / size / rating) and Group by project or shoot date.",
            "Every clip is tagged ORIGINAL (green) or COMPRESSED (amber) at a glance.",
        ])

        self._card(wrap, "4 · Add metadata (nothing is renamed on Telegram)", [
            "Select clips → Metadata to set project, tags, camera, scene, rating, etc. — stored locally.",
            "Uploading from this PC writes all of that into the Telegram caption automatically.",
            "From your phone, just type a caption when you send the clip — Vamos reads it on sync:",
            "      • #hashtags become tags",
            "      • lines like  Project: Dhaka Vlog   Scene: rooftop   Tags: street  fill those fields",
            "      • any other text becomes searchable notes",
        ])

        self._card(wrap, "5 · Download & finish", [
            "Select clips → Download for editing to pull the originals into a folder.",
            "Export ZIP also writes a metadata sheet for handoff.",
            "When you are done, Finish marks them complete and can clean up local or Telegram copies.",
        ])

        tip = tk.Frame(wrap, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        tip.pack(fill="x", pady=(8, 0))
        tk.Label(tip, text="How to tell it worked", font=FONT_BD, bg=SURFACE, fg=ACCENT).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(
            tip,
            text="A clip sent as a file keeps its real name (e.g. IMG_1234.MOV) and Vamos tags it ORIGINAL.\n"
            "A compressed one arrives as “Video” and is tagged COMPRESSED — open the Compressed view\n"
            "in the sidebar to find and re-send anything that slipped through.",
            font=FONT_SM, bg=SURFACE, fg=MUTED, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 12))

    def _card(self, parent: tk.Widget, title: str, steps: list[str]) -> None:
        card = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", pady=(0, 10))
        tk.Label(card, text=title, font=FONT_BD, bg=SURFACE, fg=TEXT).pack(anchor="w", padx=12, pady=(10, 4))
        for step in steps:
            tk.Label(card, text=f"•  {step}", font=FONT_SM, bg=SURFACE, fg=MUTED, justify="left").pack(anchor="w", padx=14, pady=1)
        tk.Frame(card, bg=SURFACE, height=8).pack()

    def _close(self) -> None:
        self.app.set_welcome_hidden(self.dont_show.get())
        self.destroy()


class UploadDialog(tk.Toplevel):
    def __init__(self, app: "VamosDesktopApp"):
        super().__init__(app.root)
        self.app = app
        self.paths: list[Path] = []
        self.result: dict[str, object] | None = None
        self.title("Upload originals to Telegram")
        self.geometry("640x640")
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(wrap, text="Upload originals", font=FONT_H1, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            wrap,
            text="Files are sent to Telegram as documents — original bytes, no compression, no loss.",
            font=FONT_SM,
            bg=BG,
            fg=MUTED,
        ).pack(anchor="w", pady=(4, 12))

        picker = tk.Frame(wrap, bg=BG)
        picker.pack(fill="x")
        ttk.Button(picker, text="Add files", command=self._add_files).pack(side="left")
        ttk.Button(picker, text="Add folder", command=self._add_folder).pack(side="left", padx=(8, 0))
        ttk.Button(picker, text="Remove selected", style="Ghost.TButton", command=self._remove).pack(side="left", padx=(8, 0))
        self.count_label = tk.Label(picker, text="0 files", font=FONT_SM, bg=BG, fg=MUTED)
        self.count_label.pack(side="right")

        list_frame = tk.Frame(wrap, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        list_frame.pack(fill="both", expand=True, pady=(8, 12))
        self.listbox = tk.Listbox(
            list_frame,
            bg=SURFACE,
            fg=TEXT,
            selectbackground=ACCENT_DK,
            selectforeground=ACCENT_INK,
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            height=6,
        )
        self.listbox.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=sb.set)

        form = tk.Frame(wrap, bg=BG)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        self.vars: dict[str, StringVar] = {}
        fields = [
            ("project", "Project"),
            ("shoot_date", "Shoot date"),
            ("camera", "Camera"),
            ("lens", "Lens"),
            ("scene", "Scene"),
            ("location", "Location"),
            ("tags", "Tags (comma)"),
            ("rating", "Rating 1-5"),
        ]
        for i, (key, label) in enumerate(fields):
            r, c = divmod(i, 2)
            tk.Label(form, text=label, font=FONT_SM, bg=BG, fg=MUTED).grid(row=r * 2, column=c * 2, sticky="w", padx=(0, 8), pady=(6, 0))
            var = StringVar()
            self.vars[key] = var
            ttk.Entry(form, textvariable=var).grid(row=r * 2 + 1, column=c * 2, columnspan=2 if c == 0 else 1, sticky="ew", padx=(0, 12))
        # Stretch entries cleanly across two columns.
        for child in form.grid_slaves():
            if isinstance(child, ttk.Entry):
                child.grid_configure(columnspan=1, sticky="ew")

        notes_row = tk.Frame(wrap, bg=BG)
        notes_row.pack(fill="x", pady=(10, 0))
        tk.Label(notes_row, text="Notes", font=FONT_SM, bg=BG, fg=MUTED).pack(anchor="w")
        self.notes_var = StringVar()
        ttk.Entry(notes_row, textvariable=self.notes_var).pack(fill="x", pady=(4, 0))

        toggles = tk.Frame(wrap, bg=BG)
        toggles.pack(fill="x", pady=(12, 0))
        self.favorite = BooleanVar(value=False)
        self.dry_run = BooleanVar(value=False)
        ttk.Checkbutton(toggles, text="Mark as favorite", variable=self.favorite).pack(side="left")
        ttk.Checkbutton(toggles, text="Dry run (catalog only, no upload)", variable=self.dry_run).pack(side="left", padx=(16, 0))

        buttons = tk.Frame(wrap, bg=BG)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Start upload", style="Primary.TButton", command=self._start).pack(side="right", padx=(0, 8))

    def _refresh_list(self) -> None:
        self.listbox.delete(0, "end")
        for p in self.paths:
            self.listbox.insert("end", str(p))
        self.count_label.config(text=f"{len(self.paths)} item(s)")

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(title="Choose media files", parent=self)
        for f in files:
            p = Path(f)
            if p not in self.paths:
                self.paths.append(p)
        self._refresh_list()

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose a shoot folder", parent=self)
        if folder:
            p = Path(folder)
            if p not in self.paths:
                self.paths.append(p)
        self._refresh_list()

    def _remove(self) -> None:
        for index in reversed(self.listbox.curselection()):
            del self.paths[int(index)]
        self._refresh_list()

    def _start(self) -> None:
        if not self.paths:
            messagebox.showinfo("Upload", "Add at least one file or folder first.", parent=self)
            return
        rating_text = self.vars["rating"].get().strip()
        rating = None
        if rating_text:
            try:
                rating = int(rating_text)
            except ValueError:
                messagebox.showerror("Upload", "Rating must be a number 1-5.", parent=self)
                return
            if not 1 <= rating <= 5:
                messagebox.showerror("Upload", "Rating must be 1-5.", parent=self)
                return
        self.result = {
            "paths": list(self.paths),
            "project": self.vars["project"].get().strip() or None,
            "shoot_date": self.vars["shoot_date"].get().strip() or None,
            "camera": self.vars["camera"].get().strip() or None,
            "lens": self.vars["lens"].get().strip() or None,
            "scene": self.vars["scene"].get().strip() or None,
            "location": self.vars["location"].get().strip() or None,
            "tags": self.vars["tags"].get().strip() or None,
            "rating": rating,
            "notes": self.notes_var.get().strip() or None,
            "favorite": self.favorite.get(),
            "dry_run": self.dry_run.get(),
        }
        self.destroy()


class DownloadJobDialog(tk.Toplevel):
    def __init__(self, app: "VamosDesktopApp", rows: list[dict], *, default_name: str, make_zip: bool, title: str):
        super().__init__(app.root)
        self.app = app
        self.rows = rows
        self.make_zip = BooleanVar(value=make_zip)
        self.open_after = BooleanVar(value=True)
        self.result: dict[str, object] | None = None
        self.title(title)
        self.geometry("620x360")
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()

        total_bytes = sum(int(row.get("size_bytes") or 0) for row in rows)
        action = "ZIP export" if make_zip else "download"
        base_folder = app.base_dir / ("packs" if make_zip else "downloads")
        base_folder.mkdir(exist_ok=True)

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(outer, text=title, font=FONT_H1, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            outer,
            text=f"{len(rows)} original file(s), {format_bytes(total_bytes)}. Original Telegram bytes are preserved.",
            font=FONT_SM,
            bg=BG,
            fg=MUTED,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(6, 16))

        form = tk.Frame(outer, bg=BG)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Save into", font=FONT_SM, bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w", pady=6)
        self.out_var = StringVar(value=str(base_folder))
        ttk.Entry(form, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", padx=(12, 8), pady=6)
        ttk.Button(form, text="Browse", style="Ghost.TButton", command=self._browse).grid(row=0, column=2, pady=6)

        tk.Label(form, text="Folder name", font=FONT_SM, bg=BG, fg=MUTED).grid(row=1, column=0, sticky="w", pady=6)
        self.name_var = StringVar(value=default_name)
        ttk.Entry(form, textvariable=self.name_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=6)

        ttk.Checkbutton(outer, text="Create ZIP package (+ metadata sheets)", variable=self.make_zip).pack(anchor="w", pady=(12, 0))
        ttk.Checkbutton(outer, text="Open folder when complete", variable=self.open_after).pack(anchor="w", pady=(6, 0))

        tk.Label(
            outer,
            text="Layout: Project / Shoot date / Kind.",
            font=FONT_SM,
            bg=BG,
            fg=FAINT,
        ).pack(anchor="w", pady=(14, 0))

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=f"Start {action}", style="Primary.TButton", command=self._start).pack(side="right", padx=(0, 8))

    def _browse(self) -> None:
        folder = filedialog.askdirectory(title="Choose output folder", initialdir=self.out_var.get())
        if folder:
            self.out_var.set(folder)

    def _start(self) -> None:
        out = Path(self.out_var.get().strip())
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Download", "Give the folder a name.", parent=self)
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
        self.geometry("660x560")
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=22, pady=20)
        tk.Label(outer, text="Connect your Telegram vault", font=FONT_H1, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            outer,
            text="Vamos uses your own Telegram account so it can store full-size video files\n"
            "(2 GB free / 4 GB Premium per file). You only do this once.",
            font=FONT_SM,
            bg=BG,
            fg=MUTED,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        steps = tk.Frame(outer, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        steps.pack(fill="x", pady=(0, 16))
        for i, text in enumerate(
            [
                "Click “Open Telegram API page” below and sign in with your phone number.",
                "Click “Create new application”, type any app name, and create it.",
                "Copy the App api_id and App api_hash and paste them here.",
                "Pick where to store clips, then Save + Connect.",
            ],
            start=1,
        ):
            tk.Label(steps, text=f"{i}.  {text}", font=FONT_SM, bg=SURFACE, fg=MUTED, justify="left").pack(anchor="w", padx=12, pady=(8 if i == 1 else 1, 0))
        tk.Frame(steps, bg=SURFACE, height=8).pack()

        ttk.Button(outer, text="Open Telegram API page", style="Primary.TButton", command=app.open_api_page).pack(anchor="w")

        form = tk.Frame(outer, bg=BG)
        form.pack(fill="x", pady=(16, 0))
        form.columnconfigure(1, weight=1)
        rows = [("API ID", app.api_id_var, False), ("API Hash", app.api_hash_var, True), ("Store clips in", app.target_var, False)]
        for r, (label, var, secret) in enumerate(rows):
            tk.Label(form, text=label, font=FONT_SM, bg=BG, fg=MUTED).grid(row=r * 2, column=0, sticky="w", pady=(8, 0))
            ttk.Entry(form, textvariable=var, show="*" if secret else "").grid(row=r * 2 + 1, column=0, columnspan=2, sticky="ew")
        tk.Label(
            form,
            text="Store clips in: type  me  for Saved Messages, or paste a private channel link / @username.",
            font=FONT_SM,
            bg=BG,
            fg=FAINT,
            justify="left",
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(form, text="I have Telegram Premium (4 GB per file)", variable=app.premium_var).grid(row=7, column=0, sticky="w", pady=(10, 0))

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Save + Connect", style="Primary.TButton", command=self._connect).pack(side="right", padx=(0, 8))

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
        self.geometry("620x440")
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()

        total_bytes = sum(int(row.get("size_bytes") or 0) for row in rows)
        downloaded = sum(1 for row in rows if row.get("downloaded_path") and Path(str(row["downloaded_path"])).exists())
        remote = sum(1 for row in rows if row.get("telegram_message_id") and row.get("status") != "remote-deleted")

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(outer, text="Finish footage", font=FONT_H1, bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(
            outer,
            text=f"{len(rows)} asset(s), {format_bytes(total_bytes)}. {downloaded} local copy/copies, {remote} Telegram item(s).",
            font=FONT_SM,
            bg=BG,
            fg=MUTED,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(6, 14))

        tk.Label(outer, text="Completion note", font=FONT_SM, bg=BG, fg=MUTED).pack(anchor="w")
        ttk.Entry(outer, textvariable=self.note_var).pack(fill="x", pady=(4, 12))

        ttk.Checkbutton(outer, text="Delete downloaded PC copies after marking done", variable=self.delete_local).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(outer, text="Delete the Telegram archive messages too", variable=self.delete_remote).pack(anchor="w", pady=(6, 0))
        tk.Label(
            outer,
            text="Telegram deletion is permanent. Leave it off to keep Telegram as your backup.",
            font=FONT_SM,
            bg=BG,
            fg=BAD,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(outer, text="Open downloads folder after finish", variable=self.open_downloads).pack(anchor="w", pady=(12, 0))

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(20, 0))
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Mark done", style="Primary.TButton", command=self._finish).pack(side="right", padx=(0, 8))

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
        self.append_tags = ""
        self.title(f"Edit metadata for {len(rows)} asset(s)")
        self.geometry("560x640")
        self.configure(bg=BG)
        self.transient(app.root)
        self.grab_set()

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(
            outer,
            text="Leave a field blank to keep it. Tick clear to erase that field.",
            font=FONT_SM,
            bg=BG,
            fg=MUTED,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        self.vars: dict[str, StringVar] = {}
        self.clear_vars: dict[str, BooleanVar] = {}
        form = tk.Frame(outer, bg=BG)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
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
            tk.Label(form, text=label, font=FONT_SM, bg=BG, fg=MUTED).grid(row=index, column=0, sticky="w", pady=4)
            var = StringVar(value=_row_text(first, key) if key != "append_tags" else "")
            self.vars[key] = var
            ttk.Entry(form, textvariable=var).grid(row=index, column=1, sticky="ew", pady=4, padx=(8, 8))
            clear_var = BooleanVar(value=False)
            self.clear_vars[key] = clear_var
            if key != "append_tags":
                ttk.Checkbutton(form, text="clear", variable=clear_var).grid(row=index, column=2, sticky="w")

        self.favorite_var = StringVar(value="keep")
        fav = tk.Frame(outer, bg=BG)
        fav.pack(fill="x", pady=(8, 0))
        tk.Label(fav, text="Favorite", font=FONT_SM, bg=BG, fg=MUTED).pack(side="left")
        ttk.Combobox(fav, textvariable=self.favorite_var, values=["keep", "yes", "no"], state="readonly", width=10).pack(side="left", padx=(10, 0))

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Cancel", style="Ghost.TButton", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply", style="Primary.TButton", command=self._apply).pack(side="right", padx=(0, 8))

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
                    messagebox.showerror("Metadata", "Rating must be a number 1-5.", parent=self)
                    return
                if not 1 <= rating <= 5:
                    messagebox.showerror("Metadata", "Rating must be 1-5.", parent=self)
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


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class VamosDesktopApp:
    def __init__(self, root: tk.Tk, base_dir: Path):
        self.root = root
        self.base_dir = base_dir
        self.config = load_config(base_dir)
        self.assets: list[dict] = []
        self.queued_shas: set[str] = set()
        self.downloaded_count = 0
        self.done_count = 0
        self.remote_deleted_count = 0
        self.preview_image = None
        self.gallery_images: list[object] = []
        self.sync_running = False
        self.thumbnail_running = False
        self.upload_running = False
        self.last_output_path: Path | None = None
        self.last_zip_path: Path | None = None
        self.active_nav: tuple[str, str | None] = ("all", None)
        self._nav_rows: list[tuple[tuple[str, str | None], tk.Frame, tk.Label, tk.Label]] = []
        self._cards: dict[str, dict] = {}
        self._gallery_columns = 0
        self._thumb_cache: dict[tuple, object] = {}
        self._board_dirty = False
        self._active_tab = "board"
        self._last_sync = 0.0
        self._search_placeholder = "Search clips, projects, tags, scenes, people…"
        self._search_active = False

        self.search_var = StringVar()
        self.project_var = StringVar(value="")
        self.status_var = StringVar(value="")
        self.sort_var = StringVar(value="Newest")
        self.group_var = StringVar(value="None")
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
        if not self.welcome_hidden():
            self.root.after(500, self.show_help)

    # -- UI construction ----------------------------------------------------
    def _build_ui(self) -> None:
        self.root.title("Vamos Vault")
        self.root.geometry("1320x820")
        self.root.minsize(1080, 680)
        self.root.configure(bg=BG)
        apply_theme(self.root)
        icon_path = self.base_dir / "assets" / "vamos-vault.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_topbar()

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 6))
        self._main_pane = main

        self._build_sidebar(main)
        self._build_center(main)
        self._build_inspector(main)
        self.root.after(220, self._set_initial_panes)

        # Status bar
        bottom = tk.Frame(self.root, bg=BG)
        bottom.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
        bottom.columnconfigure(0, weight=1)
        tk.Label(bottom, textvariable=self.status_text, font=FONT_SM, bg=BG, fg=MUTED, anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(bottom, textvariable=self.thumb_status, font=FONT_SM, bg=BG, fg=FAINT, anchor="e").grid(row=0, column=1, sticky="e")

        self._bind_shortcuts()

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg=SURFACE)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(2, weight=1)

        brand = tk.Frame(bar, bg=SURFACE)
        brand.grid(row=0, column=0, sticky="w", padx=(16, 0), pady=12)
        tk.Label(brand, text="◉", font=("Segoe UI", 14), bg=SURFACE, fg=ACCENT).pack(side="left")
        tk.Label(brand, text="Vamos Vault", font=("Segoe UI", 13, "bold"), bg=SURFACE, fg=TEXT).pack(side="left", padx=(8, 0))

        self.conn_chip = tk.Label(bar, text="", font=FONT_SM, bg=SURFACE_3, fg=MUTED, padx=10, pady=4)
        self.conn_chip.grid(row=0, column=1, sticky="w", padx=(16, 0))

        actions = tk.Frame(bar, bg=SURFACE)
        actions.grid(row=0, column=3, sticky="e", padx=(0, 14))
        ttk.Button(actions, text="↑  Upload", style="Primary.TButton", command=self.open_upload_dialog).pack(side="left")
        ttk.Button(actions, text="↻  Sync", command=self.sync_now).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(actions, text="Auto", variable=self.auto_sync_var, style="Card.TCheckbutton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Setup", style="Ghost.TButton", command=self.open_setup_dialog).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="?", style="Ghost.TButton", command=self.show_help).pack(side="left", padx=(8, 0))

    def _build_sidebar(self, parent: ttk.PanedWindow) -> None:
        side = tk.Frame(parent, bg=SURFACE, width=216)
        side.grid_propagate(False)
        parent.add(side, weight=0)
        self._sidebar = side

        tk.Label(side, text="LIBRARY", font=FONT_SM, bg=SURFACE, fg=FAINT).pack(anchor="w", padx=16, pady=(14, 6))
        self.nav_fixed = tk.Frame(side, bg=SURFACE)
        self.nav_fixed.pack(fill="x")
        fixed = [
            (("all", None), "All footage"),
            (("originals", None), "Originals (lossless)"),
            (("compressed", None), "Compressed ⚠"),
            (("remote", None), "Telegram archive"),
            (("downloaded", None), "Downloaded"),
            (("done", None), "Done"),
            (("needs", None), "Needs metadata"),
            (("queue", None), "Download list"),
        ]
        for key, label in fixed:
            self._add_nav_row(self.nav_fixed, key, label)

        tk.Label(side, text="PROJECTS", font=FONT_SM, bg=SURFACE, fg=FAINT).pack(anchor="w", padx=16, pady=(14, 6))
        self.nav_projects = tk.Frame(side, bg=SURFACE)
        self.nav_projects.pack(fill="x")

        ttk.Button(side, text="Open downloads folder", style="Ghost.TButton", command=self.open_downloads_folder).pack(side="bottom", fill="x", padx=12, pady=12)

    def _add_nav_row(self, parent: tk.Widget, key: tuple[str, str | None], label: str) -> None:
        frame = tk.Frame(parent, bg=SURFACE, cursor="hand2")
        frame.pack(fill="x")
        lbl = tk.Label(frame, text=label, bg=SURFACE, fg=MUTED, font=FONT, anchor="w", padx=16, pady=7)
        lbl.pack(side="left", fill="x", expand=True)
        cnt = tk.Label(frame, text="", bg=SURFACE, fg=FAINT, font=FONT_SM, padx=12)
        cnt.pack(side="right")
        for w in (frame, lbl, cnt):
            w.bind("<Button-1>", lambda _e, k=key: self._set_active_nav(k))
            w.bind("<Enter>", lambda _e, k=key, f=frame, l=lbl, c=cnt: self._nav_hover(k, f, l, c, True))
            w.bind("<Leave>", lambda _e, k=key, f=frame, l=lbl, c=cnt: self._nav_hover(k, f, l, c, False))
        self._nav_rows.append((key, frame, lbl, cnt))

    def _nav_hover(self, key, frame, lbl, cnt, entering: bool) -> None:
        if key == self.active_nav:
            return
        bg = SURFACE_2 if entering else SURFACE
        frame.config(bg=bg)
        lbl.config(bg=bg)
        cnt.config(bg=bg)

    def _set_active_nav(self, key: tuple[str, str | None]) -> None:
        self.active_nav = key
        self.project_var.set("")
        for k, frame, lbl, cnt in self._nav_rows:
            active = k == key
            bg = SURFACE_2 if active else SURFACE
            frame.config(bg=bg)
            lbl.config(bg=bg, fg=ACCENT if active else MUTED, font=FONT_BD if active else FONT)
            cnt.config(bg=bg, fg=ACCENT if active else FAINT)
        self.populate()

    def _build_center(self, parent: ttk.PanedWindow) -> None:
        center = tk.Frame(parent, bg=BG)
        center.rowconfigure(3, weight=1)
        center.columnconfigure(0, weight=1)
        parent.add(center, weight=4)

        # Onboarding banner (shown when not connected)
        self.banner = tk.Frame(center, bg=SURFACE, highlightthickness=1, highlightbackground=ACCENT_DK)
        self.banner.columnconfigure(0, weight=1)
        tk.Label(self.banner, text="Welcome — let's connect your Telegram vault", font=FONT_H2, bg=SURFACE, fg=TEXT).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        tk.Label(
            self.banner,
            text="Connect once, then send clips from your phone to Saved Messages as FILES (zero compression).",
            font=FONT_SM,
            bg=SURFACE,
            fg=MUTED,
        ).grid(row=1, column=0, sticky="w", padx=14)
        banner_btns = tk.Frame(self.banner, bg=SURFACE)
        banner_btns.grid(row=0, column=1, rowspan=2, sticky="e", padx=14)
        ttk.Button(banner_btns, text="Connect Telegram", style="Primary.TButton", command=self.open_setup_dialog).pack(side="left")
        ttk.Button(banner_btns, text="How to send lossless", style="Ghost.TButton", command=self.show_help).pack(side="left", padx=(8, 0))

        # Stat chips
        chips = tk.Frame(center, bg=BG)
        chips.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        for i in range(4):
            chips.columnconfigure(i, weight=1)
        self.card_total = StringVar(value="0")
        self.card_remote = StringVar(value="0")
        self.card_queue = StringVar(value="0")
        self.card_storage = StringVar(value="0 B")
        chipdefs = [("Assets", self.card_total), ("In Telegram", self.card_remote), ("Download list", self.card_queue), ("Storage", self.card_storage)]
        for i, (label, var) in enumerate(chipdefs):
            chip = tk.Frame(chips, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
            chip.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            tk.Label(chip, text=label.upper(), font=FONT_SM, bg=SURFACE, fg=FAINT).pack(anchor="w", padx=12, pady=(8, 0))
            tk.Label(chip, textvariable=var, font=("Segoe UI", 15, "bold"), bg=SURFACE, fg=TEXT).pack(anchor="w", padx=12, pady=(0, 8))

        # Filter toolbar
        toolbar = tk.Frame(center, bg=BG)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        search_wrap = tk.Frame(toolbar, bg=SURFACE_3)
        search_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        tk.Label(search_wrap, text="⌕", font=("Segoe UI", 12), bg=SURFACE_3, fg=MUTED).pack(side="left", padx=(8, 0))
        self.search_entry = tk.Entry(search_wrap, textvariable=self.search_var, bg=SURFACE_3, fg=FAINT, insertbackground=TEXT, relief="flat", font=FONT)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(6, 8))
        self.search_var.set(self._search_placeholder)
        self.search_entry.bind("<FocusIn>", self._search_focus_in)
        self.search_entry.bind("<FocusOut>", self._search_focus_out)
        self.search_var.trace_add("write", lambda *_: self.populate())

        self.project_combo = ttk.Combobox(toolbar, textvariable=self.project_var, state="readonly", width=18)
        self.project_combo.grid(row=0, column=1, padx=(0, 8))
        self.status_combo = ttk.Combobox(toolbar, textvariable=self.status_var, state="readonly", width=12)
        self.status_combo.grid(row=0, column=2, padx=(0, 8))
        self.sort_combo = ttk.Combobox(
            toolbar, textvariable=self.sort_var, state="readonly", width=12,
            values=["Newest", "Oldest", "Name A–Z", "Largest", "Top rated"],
        )
        self.sort_combo.grid(row=0, column=3, padx=(0, 8))
        self.group_combo = ttk.Combobox(
            toolbar, textvariable=self.group_var, state="readonly", width=12,
            values=["None", "Project", "Shoot date"],
        )
        self.group_combo.grid(row=0, column=4, padx=(0, 8))
        ttk.Button(toolbar, text="Select view", style="Ghost.TButton", command=self.select_visible).grid(row=0, column=5)
        self.project_combo.bind("<<ComboboxSelected>>", lambda _e: self.populate())
        self.status_combo.bind("<<ComboboxSelected>>", lambda _e: self.populate())
        self.sort_combo.bind("<<ComboboxSelected>>", lambda _e: self.populate())
        self.group_combo.bind("<<ComboboxSelected>>", lambda _e: self.populate())

        # Notebook: Shot Board + Catalog
        tabs = ttk.Notebook(center)
        tabs.grid(row=3, column=0, sticky="nsew")
        self.tabs = tabs
        tabs.bind("<<NotebookTabChanged>>", lambda _e: self.on_tab_changed())

        board = tk.Frame(tabs, bg=BG)
        board.rowconfigure(0, weight=1)
        board.columnconfigure(0, weight=1)
        tabs.add(board, text="  Shot Board  ")
        self.gallery_canvas = tk.Canvas(board, highlightthickness=0, background=BG)
        self.gallery_canvas.grid(row=0, column=0, sticky="nsew")
        gsb = ttk.Scrollbar(board, orient="vertical", command=self.gallery_canvas.yview)
        gsb.grid(row=0, column=1, sticky="ns")
        self.gallery_canvas.configure(yscrollcommand=gsb.set)
        self.gallery_frame = tk.Frame(self.gallery_canvas, bg=BG)
        self.gallery_window = self.gallery_canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")
        self.gallery_frame.bind("<Configure>", lambda _e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.bind("<Configure>", self.on_gallery_resize)
        self.gallery_canvas.bind("<Enter>", lambda _e: self.gallery_canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.gallery_canvas.bind("<Leave>", lambda _e: self.gallery_canvas.unbind_all("<MouseWheel>"))

        catalog = tk.Frame(tabs, bg=BG)
        catalog.rowconfigure(0, weight=1)
        catalog.columnconfigure(0, weight=1)
        tabs.add(catalog, text="  Catalog  ")
        columns = ("file", "project", "date", "quality", "size", "duration", "status")
        self.tree = ttk.Treeview(catalog, columns=columns, show="headings", selectmode="extended")
        headings = {"file": "File", "project": "Project", "date": "Shoot", "quality": "Quality", "size": "Size", "duration": "Dur", "status": "Status"}
        widths = {"file": 320, "project": 170, "date": 92, "quality": 110, "size": 92, "duration": 70, "status": 110}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=56)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tsb = ttk.Scrollbar(catalog, orient="vertical", command=self.tree.yview)
        tsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.tag_configure("compressed", foreground=WARN)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_selection())
        self.tree.bind("<Double-1>", lambda _e: self.primary_action())

    def _build_inspector(self, parent: ttk.PanedWindow) -> None:
        insp = tk.Frame(parent, bg=SURFACE, width=350)
        insp.grid_propagate(False)
        insp.columnconfigure(0, weight=1)
        insp.rowconfigure(3, weight=1)
        parent.add(insp, weight=0)

        preview = tk.Frame(insp, bg=SURFACE_2, height=210)
        preview.pack(fill="x", padx=12, pady=12)
        preview.pack_propagate(False)
        self.preview_label = tk.Label(preview, text="Select footage", bg=SURFACE_2, fg=MUTED, font=FONT)
        self.preview_label.pack(fill="both", expand=True)

        head = tk.Frame(insp, bg=SURFACE)
        head.pack(fill="x", padx=12)
        self.insp_title = tk.Label(head, text="No selection", font=FONT_BD, bg=SURFACE, fg=TEXT, anchor="w", wraplength=320, justify="left")
        self.insp_title.pack(anchor="w")
        self.insp_badges = tk.Frame(head, bg=SURFACE)
        self.insp_badges.pack(anchor="w", pady=(6, 0))

        self.detail = tk.Text(insp, height=12, wrap="word", relief="flat", bg=SURFACE, fg=MUTED, font=FONT_SM, padx=12, pady=8, highlightthickness=0)
        self.detail.pack(fill="both", expand=True, padx=4, pady=(8, 0))
        self.detail.configure(state="disabled")

        actions = tk.Frame(insp, bg=SURFACE)
        actions.pack(fill="x", padx=12, pady=(8, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.primary_btn = ttk.Button(actions, text="Download for editing", style="Primary.TButton", command=self.primary_action)
        self.primary_btn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.btn_zip = ttk.Button(actions, text="Export ZIP", command=self.export_zip_selected)
        self.btn_zip.grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=3)
        self.btn_add = ttk.Button(actions, text="Add to list", command=self.add_selected_to_queue)
        self.btn_add.grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=3)
        self.btn_meta = ttk.Button(actions, text="Metadata", command=self.edit_metadata)
        self.btn_meta.grid(row=2, column=0, sticky="ew", padx=(0, 3), pady=3)
        self.btn_preview = ttk.Button(actions, text="Fetch preview", command=self.fetch_selected_previews)
        self.btn_preview.grid(row=2, column=1, sticky="ew", padx=(3, 0), pady=3)
        self.btn_finish = ttk.Button(actions, text="Finish", command=self.finish_selected)
        self.btn_finish.grid(row=3, column=0, sticky="ew", padx=(0, 3), pady=3)
        self.btn_remove = ttk.Button(actions, text="Remove from list", style="Ghost.TButton", command=self.remove_selected_from_queue)
        self.btn_remove.grid(row=3, column=1, sticky="ew", padx=(3, 0), pady=3)

        jobs = tk.Frame(insp, bg=SURFACE)
        jobs.pack(fill="x", side="bottom", padx=12, pady=12)
        self.job_status = StringVar(value="No job running.")
        self.job_progress = tk.DoubleVar(value=0)
        tk.Label(jobs, textvariable=self.job_status, font=FONT_SM, bg=SURFACE, fg=MUTED, wraplength=320, justify="left", anchor="w").pack(fill="x")
        ttk.Progressbar(jobs, variable=self.job_progress, maximum=100, style="Accent.Horizontal.TProgressbar").pack(fill="x", pady=(6, 8))
        last_row = tk.Frame(jobs, bg=SURFACE)
        last_row.pack(fill="x")
        ttk.Button(last_row, text="Open last download", style="Ghost.TButton", command=self.open_last_output).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(last_row, text="Open last ZIP", style="Ghost.TButton", command=self.open_last_zip).pack(side="left", fill="x", expand=True, padx=(3, 0))
        dl_row = tk.Frame(jobs, bg=SURFACE)
        dl_row.pack(fill="x", pady=(6, 0))
        ttk.Button(dl_row, text="Download list", command=self.download_queue).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(dl_row, text="HTML report", style="Ghost.TButton", command=self.open_studio_report).pack(side="left", fill="x", expand=True, padx=(3, 0))

    def _set_initial_panes(self) -> None:
        try:
            self._main_pane.sashpos(0, 216)
            self._main_pane.sashpos(1, max(760, self.root.winfo_width() - 364))
        except tk.TclError:
            pass

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-f>", lambda _e: (self.search_entry.focus_set(), "break"))
        self.root.bind("<F5>", lambda _e: self.sync_now())
        self.root.bind("<Control-u>", lambda _e: self.open_upload_dialog())
        self.root.bind("<F1>", lambda _e: self.show_help())
        # Sync when the window regains focus (e.g. after you sent a clip on your phone).
        self.root.bind("<FocusIn>", self._on_focus_in)

    def _on_focus_in(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        if not (self.auto_sync_var.get() and self._has_credentials()):
            return
        if time.time() - self._last_sync < FOCUS_SYNC_COOLDOWN:
            return
        self.sync_now()

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.gallery_canvas.yview_scroll(int(-event.delta / 120), "units")

    # -- Search placeholder -------------------------------------------------
    def _search_focus_in(self, _e: tk.Event) -> None:
        if not self._search_active:
            self._search_active = True
            self.search_var.set("")
            self.search_entry.config(fg=TEXT)

    def _search_focus_out(self, _e: tk.Event) -> None:
        if not self.search_var.get().strip():
            self._search_active = False
            self.search_entry.config(fg=FAINT)
            self.search_var.set(self._search_placeholder)

    def _query(self) -> str:
        if not self._search_active:
            return ""
        return self.search_var.get().strip().lower()

    # -- Data ---------------------------------------------------------------
    def db(self) -> VaultDB:
        self.config = load_config(self.base_dir)
        return db_from_config(self.config, self.base_dir)

    def _has_credentials(self) -> bool:
        api_id, api_hash = telegram_credentials()
        return bool(api_id and api_hash)

    def needs_metadata(self, row: dict) -> bool:
        return not (row.get("project") and row.get("tags") and row.get("rights"))

    def refresh_assets(self) -> None:
        db = self.db()
        try:
            self.assets = [dict(row) for row in db.all_assets()]
            self.queued_shas = {row["sha256"] for row in db.queued_assets()}
        finally:
            db.close()
        self.downloaded_count = sum(1 for r in self.assets if r.get("status") == "downloaded")
        self.done_count = sum(1 for r in self.assets if r.get("status") == "done")
        self.remote_deleted_count = sum(1 for r in self.assets if r.get("status") == "remote-deleted")

        projects = sorted({r.get("project") or "" for r in self.assets if r.get("project")})
        self.project_combo["values"] = [""] + projects
        self.status_combo["values"] = [""] + sorted({r.get("status") or "" for r in self.assets if r.get("status")})
        self._rebuild_project_nav(projects)
        self._refresh_nav_counts()

        total_bytes = sum(int(r.get("size_bytes") or 0) for r in self.assets)
        remote = sum(1 for r in self.assets if r.get("telegram_message_id") and r.get("status") != "remote-deleted")
        self.card_total.set(str(len(self.assets)))
        self.card_remote.set(str(remote))
        self.card_queue.set(str(len(self.queued_shas)))
        self.card_storage.set(format_bytes(total_bytes))
        self.update_connection_chip()
        self.populate()

    def _rebuild_project_nav(self, projects: list[str]) -> None:
        self._nav_rows = [row for row in self._nav_rows if row[0][0] != "project"]
        for child in self.nav_projects.winfo_children():
            child.destroy()
        for project in projects[:40]:
            self._add_nav_row(self.nav_projects, ("project", project), project)
        # Re-apply active styling now that rows were rebuilt.
        self._set_active_nav(self.active_nav if any(self.active_nav == r[0] for r in self._nav_rows) else ("all", None))

    def _refresh_nav_counts(self) -> None:
        counts = {
            ("all", None): len(self.assets),
            ("originals", None): sum(1 for r in self.assets if r.get("lossless") == 1),
            ("compressed", None): sum(1 for r in self.assets if r.get("lossless") == 0),
            ("remote", None): sum(1 for r in self.assets if r.get("status") == "remote"),
            ("downloaded", None): self.downloaded_count,
            ("done", None): self.done_count,
            ("needs", None): sum(1 for r in self.assets if self.needs_metadata(r)),
            ("queue", None): len(self.queued_shas),
        }
        for key, _frame, _lbl, cnt in self._nav_rows:
            if key in counts:
                cnt.config(text=str(counts[key]))
            elif key[0] == "project":
                cnt.config(text=str(sum(1 for r in self.assets if r.get("project") == key[1])))

    def filtered_assets(self) -> list[dict]:
        query = self._query()
        project = self.project_var.get()
        status = self.status_var.get()
        kind, value = self.active_nav
        rows = []
        for row in self.assets:
            if kind == "project" and row.get("project") != value:
                continue
            if kind == "originals" and row.get("lossless") != 1:
                continue
            if kind == "compressed" and row.get("lossless") != 0:
                continue
            if kind == "remote" and row.get("status") != "remote":
                continue
            if kind == "downloaded" and row.get("status") != "downloaded":
                continue
            if kind == "done" and row.get("status") != "done":
                continue
            if kind == "needs" and not self.needs_metadata(row):
                continue
            if kind == "queue" and row.get("sha256") not in self.queued_shas:
                continue
            if project and row.get("project") != project:
                continue
            if status and row.get("status") != status:
                continue
            if query:
                hay = " ".join(
                    _row_text(row, k)
                    for k in ["filename", "project", "tags", "notes", "scene", "location", "people", "camera", "lens", "youtube_status"]
                ).lower()
                if query not in hay:
                    continue
            rows.append(row)
        return self._sort_rows(rows)

    def _sort_rows(self, rows: list[dict]) -> list[dict]:
        mode = self.sort_var.get()
        if mode == "Oldest":
            return sorted(rows, key=lambda r: (r.get("uploaded_at") or r.get("created_at") or ""))
        if mode == "Name A–Z":
            return sorted(rows, key=lambda r: str(r.get("filename") or "").lower())
        if mode == "Largest":
            return sorted(rows, key=lambda r: int(r.get("size_bytes") or 0), reverse=True)
        if mode == "Top rated":
            return sorted(rows, key=lambda r: int(r.get("rating") or 0), reverse=True)
        # Newest (default): most recent Telegram upload / catalog time first.
        return sorted(rows, key=lambda r: (r.get("uploaded_at") or r.get("created_at") or ""), reverse=True)

    def populate(self) -> None:
        visible = self.filtered_assets()
        self.tree.delete(*self.tree.get_children())
        for row in visible:
            lossless = row.get("lossless")
            quality = "ORIGINAL" if lossless == 1 else ("COMPRESSED" if lossless == 0 else "")
            tags = ("compressed",) if lossless == 0 else ()
            self.tree.insert(
                "",
                "end",
                iid=row["sha256"],
                tags=tags,
                values=(
                    row.get("filename") or "",
                    row.get("project") or "",
                    row.get("shoot_date") or "",
                    quality,
                    format_bytes(int(row.get("size_bytes") or 0)),
                    format_duration(row.get("duration_seconds")),
                    row.get("status") or "",
                ),
            )
        if self._active_tab == "board":
            self.render_board(visible)
            self._board_dirty = False
        else:
            self._board_dirty = True
        self.status_text.set(f"Showing {len(visible)} of {len(self.assets)} assets")
        self.ensure_local_thumbnails()

    def on_tab_changed(self) -> None:
        try:
            idx = self.tabs.index(self.tabs.select())
        except tk.TclError:
            return
        self._active_tab = "board" if idx == 0 else "catalog"
        if self._active_tab == "board" and self._board_dirty:
            self.render_board(self.filtered_assets())
            self._board_dirty = False

    # -- Shot board ---------------------------------------------------------
    def on_gallery_resize(self, event: tk.Event) -> None:
        self.gallery_canvas.itemconfigure(self.gallery_window, width=event.width)
        columns = self.gallery_columns_for_width(event.width)
        if columns != self._gallery_columns:
            self._gallery_columns = columns
            if self._active_tab == "board":
                self.render_board(self.filtered_assets())
            else:
                self._board_dirty = True

    def gallery_columns_for_width(self, width: int) -> int:
        return max(1, min(5, max(1, width) // 250))

    def render_board(self, rows: list[dict]) -> None:
        for child in self.gallery_frame.winfo_children():
            child.destroy()
        self.gallery_images = []
        self._cards = {}
        if not rows:
            tk.Label(
                self.gallery_frame,
                text="No footage in this view.\nClick Sync to pull clips from Telegram, or Upload to add originals.",
                bg=BG,
                fg=MUTED,
                font=FONT,
                justify="center",
            ).grid(row=0, column=0, sticky="w", padx=16, pady=16)
            return
        width = self.gallery_canvas.winfo_width() or 980
        columns = self._gallery_columns or self.gallery_columns_for_width(width)
        self._gallery_columns = columns
        for i in range(columns):
            self.gallery_frame.columnconfigure(i, weight=1, uniform="cards")
        selected = set(self.tree.selection())
        rows = rows[:160]
        group_by = self.group_var.get()
        grid_row = 0
        if group_by in ("Project", "Shoot date"):
            field = "project" if group_by == "Project" else "shoot_date"
            groups: dict[str, list[dict]] = {}
            for row in rows:
                key = row.get(field) or ("No project" if field == "project" else "No date")
                groups.setdefault(str(key), []).append(row)
            for gkey, items in groups.items():
                header = tk.Frame(self.gallery_frame, bg=BG)
                header.grid(row=grid_row, column=0, columnspan=columns, sticky="ew", padx=6, pady=(12, 2))
                tk.Label(header, text=f"{gkey}   ·   {len(items)}", bg=BG, fg=ACCENT, font=FONT_BD).pack(anchor="w")
                grid_row += 1
                col = 0
                for row in items:
                    self._make_card(row, grid_row, col, selected)
                    col += 1
                    if col >= columns:
                        col = 0
                        grid_row += 1
                if col != 0:
                    grid_row += 1
        else:
            col = 0
            for row in rows:
                self._make_card(row, grid_row, col, selected)
                col += 1
                if col >= columns:
                    col = 0
                    grid_row += 1

    def _make_card(self, row: dict, grid_row: int, col: int, selected: set) -> None:
        sha = row["sha256"]
        border = ACCENT if sha in selected else BORDER
        card = tk.Frame(self.gallery_frame, bg=SURFACE, highlightthickness=2, highlightbackground=border, highlightcolor=border)
        card.grid(row=grid_row, column=col, sticky="nsew", padx=6, pady=6)

        thumb = self._thumb_widget(card, row)
        thumb.pack(fill="x")

        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="x", padx=10, pady=8)
        name = row.get("filename") or "untitled"
        tk.Label(body, text=name[:32], bg=SURFACE, fg=TEXT, font=FONT_BD, anchor="w").pack(anchor="w")
        meta_parts = [
            row.get("project") or "No project",
            row.get("shoot_date") or "",
            format_duration(row.get("duration_seconds")),
            format_bytes(int(row.get("size_bytes") or 0)),
        ]
        meta = "  ·  ".join(str(p) for p in meta_parts if p)
        tk.Label(body, text=meta[:42], bg=SURFACE, fg=MUTED, font=FONT_SM, anchor="w").pack(anchor="w", pady=(2, 0))

        badges = tk.Frame(body, bg=SURFACE)
        badges.pack(anchor="w", pady=(6, 0))
        qa = quality_badge_args(row.get("lossless"))
        if qa:
            make_badge(badges, qa[0], qa[1], qa[2]).pack(side="left", padx=(0, 4))
        st = row.get("status") or "cataloged"
        fg, bg = STATUS_BADGES.get(st, (MUTED, SURFACE_3))
        make_badge(badges, st.upper(), fg, bg).pack(side="left", padx=(0, 4))
        if sha in self.queued_shas:
            make_badge(badges, "IN LIST", ACCENT_INK, ACCENT).pack(side="left")

        self._cards[sha] = {"frame": card}
        self._bind_card(card, sha)

    def _thumb_widget(self, parent: tk.Widget, row: dict) -> tk.Widget:
        thumb = row.get("thumbnail_path")
        if thumb and Path(str(thumb)).exists() and Image is not None and ImageTk is not None:
            key = (str(thumb), 230, 130)
            photo = self._thumb_cache.get(key)
            if photo is None:
                try:
                    with Image.open(str(thumb)) as image:
                        image.thumbnail((230, 130))
                        photo = ImageTk.PhotoImage(image)
                    if len(self._thumb_cache) > 800:
                        self._thumb_cache.clear()
                    self._thumb_cache[key] = photo
                except Exception:
                    photo = None
            if photo is not None:
                self.gallery_images.append(photo)
                return tk.Label(parent, image=photo, bg=SURFACE_2)
        holder = tk.Frame(parent, bg=SURFACE_2, height=120)
        holder.pack_propagate(False)
        is_video = (row.get("codec") or "").startswith("video/") or str(row.get("filename") or "").lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".mts", ".mxf"))
        if is_video and not row.get("downloaded_path"):
            text = "▶  download for preview"
        elif is_video:
            text = "▶  video"
        else:
            text = "file"
        tk.Label(holder, text=text, bg=SURFACE_2, fg=FAINT, font=FONT_SM).pack(expand=True)
        return holder

    def _bind_card(self, widget: tk.Widget, sha: str) -> None:
        widget.bind("<Button-1>", lambda _e, s=sha: self._card_click(s))
        widget.bind("<Control-Button-1>", lambda _e, s=sha: self._card_toggle(s))
        widget.bind("<Double-Button-1>", lambda _e, s=sha: self._card_double(s))
        for child in widget.winfo_children():
            self._bind_card(child, sha)

    def _card_click(self, sha: str) -> None:
        if self.tree.exists(sha):
            self.tree.selection_set(sha)
            self.tree.see(sha)

    def _card_toggle(self, sha: str) -> None:
        if not self.tree.exists(sha):
            return
        if sha in self.tree.selection():
            self.tree.selection_remove(sha)
        else:
            self.tree.selection_add(sha)

    def _card_double(self, sha: str) -> None:
        self._card_click(sha)
        self.primary_action()

    def _refresh_card_selection(self) -> None:
        selected = set(self.tree.selection())
        for sha, info in self._cards.items():
            border = ACCENT if sha in selected else BORDER
            try:
                info["frame"].config(highlightbackground=border, highlightcolor=border)
            except tk.TclError:
                pass

    # -- Selection / inspector ---------------------------------------------
    def selected_rows(self) -> list[dict]:
        selected = set(self.tree.selection())
        by_sha = {r["sha256"]: r for r in self.assets}
        return [by_sha[s] for s in selected if s in by_sha]

    def select_asset(self, sha: str) -> None:
        if self.tree.exists(sha):
            self.tree.selection_set(sha)
            self.tree.see(sha)

    def select_visible(self) -> None:
        items = self.tree.get_children()
        self.tree.selection_set(items)
        self.status_text.set(f"Selected {len(items)} visible assets.")

    def show_selection(self) -> None:
        self._refresh_card_selection()
        rows = self.selected_rows()
        for widget in self.insp_badges.winfo_children():
            widget.destroy()
        if not rows:
            self.preview_label.config(text="Select footage", image="")
            self.insp_title.config(text="No selection")
            self._set_detail("")
            self._update_actions([])
            return
        row = rows[0]
        self.show_preview(row)
        title = row.get("filename") or "(unnamed)"
        if len(rows) > 1:
            title = f"{len(rows)} clips selected"
        self.insp_title.config(text=title)

        qa = quality_badge_args(row.get("lossless"))
        if qa:
            make_badge(self.insp_badges, qa[0], qa[1], qa[2]).pack(side="left", padx=(0, 4))
        st = row.get("status") or "cataloged"
        fg, bg = STATUS_BADGES.get(st, (MUTED, SURFACE_3))
        make_badge(self.insp_badges, st.upper(), fg, bg).pack(side="left", padx=(0, 4))

        total_bytes = sum(int(r.get("size_bytes") or 0) for r in rows)
        lines = [
            f"Selected: {len(rows)} asset(s), {format_bytes(total_bytes)}",
            "",
            f"Project: {row.get('project') or '-'}",
            f"Shoot date: {row.get('shoot_date') or '-'}",
            f"Scene: {row.get('scene') or '-'}",
            f"Location: {row.get('location') or '-'}",
            f"Camera: {row.get('camera') or '-'}",
            f"Lens: {row.get('lens') or '-'}",
            f"Tags: {row.get('tags') or '-'}",
            f"Rating: {(str(row.get('rating')) + '/5') if row.get('rating') else '-'}",
            f"Duration: {format_duration(row.get('duration_seconds')) or '-'}",
            f"Size: {format_bytes(int(row.get('size_bytes') or 0))}",
        ]
        if row.get("lossless") == 0:
            lines += ["", "⚠ This clip was compressed by Telegram (sent as a video, not a file).", "Re-send it from your phone as a FILE to keep full quality."]
        if row.get("downloaded_path"):
            lines += ["", f"Local copy: {row.get('downloaded_path')}"]
        if row.get("notes"):
            lines += ["", str(row.get("notes"))]
        self._set_detail("\n".join(lines))
        self._update_actions(rows)

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _update_actions(self, rows: list[dict]) -> None:
        has = bool(rows)
        first = rows[0] if rows else None
        downloaded = bool(first and first.get("downloaded_path") and Path(str(first["downloaded_path"])).exists())
        any_remote = any(r.get("telegram_message_id") for r in rows)
        any_no_thumb = any(r.get("telegram_message_id") and not r.get("thumbnail_path") for r in rows)
        in_list = bool(first and first.get("sha256") in self.queued_shas)

        if downloaded:
            self.primary_btn.config(text="Open file", state="normal")
        elif any_remote:
            self.primary_btn.config(text="Download for editing", state="normal")
        else:
            self.primary_btn.config(text="Download for editing", state="disabled")
        self.btn_zip.config(state="normal" if any_remote else "disabled")
        self.btn_add.config(state="normal" if (any_remote and not in_list) else "disabled")
        self.btn_remove.config(state="normal" if in_list else "disabled")
        self.btn_meta.config(state="normal" if has else "disabled")
        self.btn_preview.config(state="normal" if any_no_thumb else "disabled")
        self.btn_finish.config(state="normal" if has else "disabled")

    def show_preview(self, row: dict) -> None:
        thumb = row.get("thumbnail_path")
        if not thumb or not Path(str(thumb)).exists() or Image is None or ImageTk is None:
            self.preview_label.config(text=row.get("filename") or "No preview", image="")
            return
        try:
            with Image.open(str(thumb)) as image:
                image.thumbnail((330, 200))
                self.preview_image = ImageTk.PhotoImage(image)
            self.preview_label.config(image=self.preview_image, text="")
        except Exception:
            self.preview_label.config(text=row.get("filename") or "No preview", image="")

    def primary_action(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        row = rows[0]
        path = row.get("downloaded_path")
        if path and Path(str(path)).exists():
            self.open_path(Path(str(path)))
            return
        if row.get("telegram_message_id"):
            self.download_selected()
            return
        messagebox.showinfo("Open", "This asset is not in Telegram yet.")

    # -- Thumbnails ---------------------------------------------------------
    def ensure_local_thumbnails(self) -> None:
        if self.thumbnail_running:
            return
        rows = [
            r
            for r in self.assets
            if not r.get("thumbnail_path") and r.get("downloaded_path") and Path(str(r.get("downloaded_path"))).exists()
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

    # -- Connection / setup -------------------------------------------------
    def update_connection_chip(self) -> None:
        target = self.config["telegram"]["target"]
        if self._has_credentials():
            self.conn_chip.config(text=f"●  Connected · {target}", fg=GOOD, bg=GOOD_BG)
            self.banner.grid_remove()
        else:
            self.conn_chip.config(text="●  Setup needed", fg=WARN, bg=WARN_BG)
            self.banner.grid(row=0, column=0, sticky="ew", pady=(8, 0))

    def update_connection_header(self) -> None:  # backwards-compatible alias
        self.update_connection_chip()

    def open_setup_dialog(self) -> None:
        TelegramSetupDialog(self)

    def show_help(self) -> None:
        HelpDialog(self)

    def _ui_state_path(self) -> Path:
        return resolve_data_path(self.base_dir, ".vamos-vault/ui-state.json")

    def _load_ui_state(self) -> dict:
        try:
            return json.loads(self._ui_state_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def welcome_hidden(self) -> bool:
        return bool(self._load_ui_state().get("hide_welcome"))

    def set_welcome_hidden(self, value: bool) -> None:
        state = self._load_ui_state()
        state["hide_welcome"] = bool(value)
        try:
            path = self._ui_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state), encoding="utf-8")
        except Exception:
            pass

    def open_api_page(self) -> None:
        webbrowser.open(API_URL)
        self.status_text.set("Opened Telegram API page. Create an app, then paste api_id and api_hash.")

    def save_settings(self) -> bool:
        api_id = self.api_id_var.get().strip()
        api_hash = self.api_hash_var.get().strip()
        target = self.target_var.get().strip() or "me"
        if not api_id or not api_hash:
            messagebox.showwarning("Telegram setup", "Paste both API ID and API Hash first.")
            return False
        _update_env_file(
            self.base_dir / ".env",
            {"TELEGRAM_API_ID": api_id, "TELEGRAM_API_HASH": api_hash, "TELEGRAM_TARGET": target},
        )
        write_config(self.base_dir, target=target, premium=self.premium_var.get(), database=self.config["vault"]["database"])
        self.config = load_config(self.base_dir)
        self.update_connection_chip()
        self.status_text.set("Settings saved. Now click Save + Connect.")
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
        self.status_text.set("Telegram account connected.")
        self.update_connection_chip()
        messagebox.showinfo("Telegram login", "Connected! Syncing your vault now.")
        self.sync_now()

    # -- Sync / upload ------------------------------------------------------
    def sync_now(self) -> None:
        if self.sync_running:
            return
        if not self._has_credentials():
            self.open_setup_dialog()
            return
        self.sync_running = True
        self._last_sync = time.time()
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
        if self.auto_sync_var.get() and self._has_credentials():
            self.sync_now()
        try:
            self.root.after(AUTOSYNC_MS, self.maybe_auto_sync)
        except tk.TclError:
            pass

    def open_upload_dialog(self) -> None:
        if self.upload_running:
            messagebox.showinfo("Upload", "An upload is already running.")
            return
        if not self._has_credentials():
            self.open_setup_dialog()
            return
        dialog = UploadDialog(self)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self._run_upload(dialog.result)

    def _run_upload(self, opts: dict) -> None:
        self.upload_running = True
        paths = [Path(p) for p in opts["paths"]]
        self.job_progress.set(0)
        self.job_status.set("Preparing upload...")
        self.status_text.set("Uploading originals to Telegram...")

        def progress(filename: str, sent: int, total: int) -> None:
            pct = (sent / total * 100) if total else 0
            label = f"Uploading {filename}: {format_bytes(sent)} / {format_bytes(total)}"
            self.root.after(0, lambda: self.job_status.set(label))
            self.root.after(0, lambda v=pct: self.job_progress.set(max(0, min(100, v))))

        def status(message: str) -> None:
            self.root.after(0, lambda: self.status_text.set(message))

        def worker() -> None:
            try:
                config = load_config(self.base_dir)
                rows = upload_paths(
                    config,
                    self.base_dir,
                    paths,
                    project=opts["project"],
                    shoot_date=opts["shoot_date"],
                    camera=opts["camera"],
                    lens=opts["lens"],
                    scene=opts["scene"],
                    location=opts["location"],
                    tags=opts["tags"],
                    rating=opts["rating"],
                    notes=opts["notes"],
                    favorite=opts["favorite"],
                    dry_run=opts["dry_run"],
                    progress_callback=progress,
                    status_callback=status,
                )
                uploaded = sum(1 for r in rows if r.get("status") == "uploaded")
                self.root.after(0, lambda: self.job_progress.set(100))
                self.root.after(0, self.refresh_assets)
                self.root.after(0, lambda: self.job_status.set(f"Upload complete: {uploaded} file(s)."))
                self.root.after(0, lambda: messagebox.showinfo("Upload", f"Done. {uploaded} file(s) archived, {len(rows)} processed."))
            except Exception as exc:
                self.root.after(0, lambda: self.job_progress.set(0))
                self.root.after(0, lambda error=exc: self.job_status.set(f"Upload failed: {error}"))
                self.root.after(0, lambda error=exc: messagebox.showerror("Upload failed", str(error)))
            finally:
                self.upload_running = False
                self.root.after(0, lambda: self.status_text.set("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    # -- Metadata / queue ---------------------------------------------------
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
        if not self.queued_shas:
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
        if not rows:
            messagebox.showinfo("Download list", "The download list is empty. Add clips with 'Add to list'.")
            return
        self._pack_rows(rows, "download-list", make_zip=False, title="Download list")

    # -- Open helpers -------------------------------------------------------
    def open_selected_download(self) -> None:
        rows = self.selected_rows()
        if not rows:
            messagebox.showinfo("Open", "Select an asset first.")
            return
        path = Path(str(rows[0].get("downloaded_path") or ""))
        if not path.exists():
            messagebox.showinfo("Open", "This asset has not been downloaded on this PC yet.")
            return
        self.open_path(path)

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

    # -- Finish / preview ---------------------------------------------------
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
            done_count = local_deleted = remote_deleted = 0
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
            summary = f"Done: {done_count}. Local deleted: {local_deleted}. Telegram deleted: {remote_deleted}."
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
        rows = [r for r in self.selected_rows() if not r.get("thumbnail_path") and r.get("telegram_message_id")]
        if not rows:
            messagebox.showinfo("Fetch preview", "Select remote clips that do not already have a preview.")
            return
        total_bytes = sum(int(r.get("size_bytes") or 0) for r in rows)
        if not messagebox.askyesno(
            "Fetch preview",
            f"Create previews for {len(rows)} item(s)?\n\nVamos will temporarily download {format_bytes(total_bytes)} to make preview frames, then delete the temporary originals.",
        ):
            return
        self.status_text.set("Fetching preview thumbnails...")

        def progress(filename: str, received: int, total: int) -> None:
            self.root.after(0, lambda: self.status_text.set(f"Preview {filename}: {format_bytes(received)} / {format_bytes(total)}"))

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
                self.root.after(0, lambda: messagebox.showinfo("Fetch preview", f"Created {made} preview(s)."))
            except Exception as exc:
                self.root.after(0, lambda error=exc: messagebox.showerror("Fetch preview failed", str(error)))
            finally:
                self.root.after(0, lambda: self.status_text.set("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    # -- Packaging ----------------------------------------------------------
    def _pack_rows(self, rows: list[dict], default_name: str, *, make_zip: bool, title: str) -> None:
        rows = [r for r in rows if r.get("telegram_message_id")]
        if not rows:
            messagebox.showinfo(title, "Nothing downloadable selected (these clips are not in Telegram).")
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
        self.job_status.set(f"{title}: preparing {len(rows)} file(s).")
        self.job_progress.set(0)
        job_total_bytes = max(1, sum(int(r.get("size_bytes") or 0) for r in rows))
        progress_by_file: dict[str, int] = {}

        def progress(filename: str, received: int, total: int) -> None:
            progress_by_file[filename or "current"] = int(received or 0)
            total_received = min(job_total_bytes, sum(progress_by_file.values()))
            pct = (total_received / job_total_bytes) * 100
            label = f"{filename}: {format_bytes(received)} / {format_bytes(total)}"
            self.root.after(0, lambda: self.status_text.set(label))
            self.root.after(0, lambda: self.job_status.set("Downloading: " + label))
            self.root.after(0, lambda v=pct: self.job_progress.set(max(0, min(100, v))))

        def job_status(message: str) -> None:
            self.root.after(0, lambda: self.status_text.set(message))
            self.root.after(0, lambda: self.job_status.set(message))

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
                self.root.after(0, lambda: self.job_progress.set(100))
                self.root.after(0, self.refresh_assets)
                message = f"Folder:\n{result.folder}" + (f"\n\nZIP:\n{result.zip_path}" if result.zip_path else "")
                self.root.after(0, lambda: self.job_status.set(f"{title} complete: {len(result.rows)} file(s)."))
                self.root.after(0, lambda: messagebox.showinfo(f"{title} complete", message))
                if open_after:
                    self.root.after(0, lambda: self.open_path(result.folder))
            except Exception as exc:
                self.root.after(0, lambda: self.job_progress.set(0))
                self.root.after(0, lambda error=exc: self.job_status.set(f"{title} failed: {error}"))
                self.root.after(0, lambda error=exc: messagebox.showerror(f"{title} failed", str(error)))
            finally:
                self.root.after(0, lambda: self.status_text.set("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    def download_selected(self) -> None:
        rows = self.selected_rows()
        default = (rows[0].get("project") if rows else None) or "selected-footage"
        self._pack_rows(rows, default, make_zip=False, title="Download for editing")

    def download_filtered(self) -> None:
        rows = self.filtered_assets()
        default = (rows[0].get("project") if rows else None) or "visible-footage"
        self._pack_rows(rows, default, make_zip=False, title="Download visible")

    def export_zip_selected(self) -> None:
        rows = self.selected_rows()
        default = (rows[0].get("project") if rows else None) or "selected-footage"
        self._pack_rows(rows, default, make_zip=True, title="Export ZIP")

    def export_zip_filtered(self) -> None:
        rows = self.filtered_assets()
        default = (rows[0].get("project") if rows else None) or "visible-footage"
        self._pack_rows(rows, default, make_zip=True, title="Export visible ZIP")

    def pack_queue(self) -> None:
        db = self.db()
        try:
            rows = [dict(row) for row in db.queued_assets()]
        finally:
            db.close()
        self._pack_rows(rows, "download-list", make_zip=True, title="Export download list ZIP")

    # -- System -------------------------------------------------------------
    def open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # noqa: S606 - intended desktop open
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
