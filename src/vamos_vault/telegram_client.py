from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import resolve_data_path, telegram_credentials


class TelegramConfigError(RuntimeError):
    pass


@dataclass
class RemoteMedia:
    message_id: int
    filename: str
    size_bytes: int
    caption: str | None
    link: str | None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    date: str | None = None
    thumbnail_path: str | None = None
    lossless: bool | None = None


def _message_link(message: object) -> str | None:
    chat = getattr(message, "chat", None)
    message_id = getattr(message, "id", None)
    if not message_id:
        return None

    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"

    chat_id = str(getattr(message, "chat_id", "") or "")
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    return None


def _message_filename(message: object) -> str:
    file_obj = getattr(message, "file", None)
    name = getattr(file_obj, "name", None)
    if name:
        return str(name)
    message_id = getattr(message, "id", "unknown")
    mime_type = str(getattr(file_obj, "mime_type", "") or "")
    if mime_type.startswith("video/"):
        suffix = mime_type.split("/", 1)[1].split(";", 1)[0] or "mp4"
        return f"telegram-video-{message_id}.{suffix}"
    if mime_type.startswith("image/"):
        suffix = mime_type.split("/", 1)[1].split(";", 1)[0] or "jpg"
        return f"telegram-photo-{message_id}.{suffix}"
    if mime_type.startswith("audio/"):
        suffix = mime_type.split("/", 1)[1].split(";", 1)[0] or "audio"
        return f"telegram-audio-{message_id}.{suffix}"
    return f"telegram-file-{message_id}"


def _is_lossless_upload(message: object, file_obj: object) -> bool:
    """True when Telegram is storing the original bytes (sent as a file/document).

    Telegram only preserves a ``DocumentAttributeFilename`` when the media was
    attached as a *file/document*. Gallery photos and "as video" sends are
    re-encoded by the sending client before upload and arrive without an original
    filename, so the original bytes are already gone. A plain ``photo`` message is
    always a compressed thumbnail-style image.
    """

    if getattr(message, "photo", None) is not None:
        return False
    return bool(getattr(file_obj, "name", None))


def _remote_media_from_message(message: object) -> RemoteMedia | None:
    file_obj = getattr(message, "file", None)
    if file_obj is None:
        return None
    size = int(getattr(file_obj, "size", 0) or 0)
    if size <= 0:
        return None
    date = getattr(message, "date", None)
    return RemoteMedia(
        message_id=int(getattr(message, "id")),
        filename=_message_filename(message),
        size_bytes=size,
        caption=getattr(message, "message", None),
        link=_message_link(message),
        duration_seconds=getattr(file_obj, "duration", None),
        width=getattr(file_obj, "width", None),
        height=getattr(file_obj, "height", None),
        mime_type=getattr(file_obj, "mime_type", None),
        date=date.isoformat(timespec="seconds") if date else None,
        lossless=_is_lossless_upload(message, file_obj),
    )


async def authenticate(config: dict, base_dir: Path) -> None:
    from telethon import TelegramClient

    api_id, api_hash = telegram_credentials()
    if not api_id or not api_hash:
        raise TelegramConfigError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    session_path = resolve_data_path(base_dir, f".vamos-vault/{config['telegram']['session_name']}")
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start()
    await client.disconnect()


def _safe_thumb_dir_name(value: object) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value)).strip("_") or "telegram"


async def _download_thumbnail(client: object, message: object, thumb_dir: Path) -> str | None:
    message_id = int(getattr(message, "id"))
    thumb_dir.mkdir(parents=True, exist_ok=True)
    destination = thumb_dir / f"{message_id}.jpg"
    if destination.exists() and destination.stat().st_size > 0:
        return str(destination)
    media = getattr(message, "media", None)
    thumbs = list(getattr(getattr(message, "document", None), "thumbs", None) or [])
    thumbs.extend(list(getattr(media, "thumbs", None) or []))
    candidates: list[object] = [-1, 0]
    candidates.extend(reversed(thumbs))
    sources = [message]
    if media is not None:
        sources.append(media)
    seen: set[str] = set()
    for source in sources:
        for thumb in candidates:
            key = f"{id(source)}:{repr(thumb)}"
            if key in seen:
                continue
            seen.add(key)
            if destination.exists():
                destination.unlink(missing_ok=True)
            try:
                downloaded = await client.download_media(source, file=str(destination), thumb=thumb)
            except Exception:
                continue
            if downloaded is not None:
                candidate = Path(downloaded)
                if candidate.exists() and candidate.stat().st_size > 0:
                    return str(candidate)
    if destination.exists() and destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
    return None


async def list_remote_media(
    config: dict,
    base_dir: Path,
    *,
    limit: int = 100,
    download_thumbnails: bool = True,
) -> list[RemoteMedia]:
    from telethon import TelegramClient

    api_id, api_hash = telegram_credentials()
    if not api_id or not api_hash:
        raise TelegramConfigError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    session_path = resolve_data_path(base_dir, f".vamos-vault/{config['telegram']['session_name']}")
    target = config["telegram"]["target"]
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start()
    entity = await client.get_entity(target)
    thumb_dir = resolve_data_path(base_dir, ".vamos-vault/thumbs") / _safe_thumb_dir_name(target)
    found: list[RemoteMedia] = []
    async for message in client.iter_messages(entity, limit=limit):
        media = _remote_media_from_message(message)
        if media is not None:
            if download_thumbnails:
                media.thumbnail_path = await _download_thumbnail(client, message, thumb_dir)
            found.append(media)
    await client.disconnect()
    return found


async def send_file(
    config: dict,
    base_dir: Path,
    file_path: Path,
    *,
    caption: str,
    thumb_path: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[int, str | None]:
    from telethon import TelegramClient

    api_id, api_hash = telegram_credentials()
    if not api_id or not api_hash:
        raise TelegramConfigError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    session_path = resolve_data_path(base_dir, f".vamos-vault/{config['telegram']['session_name']}")
    target = config["telegram"]["target"]
    # Archive uploads must preserve original bytes. Telegram document mode is
    # the safe path for camera originals; video mode can create preview-focused
    # behavior that is wrong for a master archive.
    send_as_document = True

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start()
    entity = await client.get_entity(target)
    send_kwargs = {
        "caption": caption,
        "force_document": send_as_document,
        "supports_streaming": False,
        "progress_callback": progress_callback,
    }
    if thumb_path is not None and Path(thumb_path).exists():
        send_kwargs["thumb"] = str(thumb_path)
    try:
        message = await client.send_file(entity, str(file_path), **send_kwargs)
    except Exception:
        if "thumb" not in send_kwargs:
            raise
        send_kwargs.pop("thumb", None)
        message = await client.send_file(entity, str(file_path), **send_kwargs)
    link = _message_link(message)
    message_id = int(getattr(message, "id"))
    await client.disconnect()
    return message_id, link


async def download_file(
    config: dict,
    base_dir: Path,
    *,
    message_id: int,
    out_dir: Path,
    filename: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    from telethon import TelegramClient

    api_id, api_hash = telegram_credentials()
    if not api_id or not api_hash:
        raise TelegramConfigError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    session_path = resolve_data_path(base_dir, f".vamos-vault/{config['telegram']['session_name']}")
    target = config["telegram"]["target"]
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / filename

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start()
    entity = await client.get_entity(target)
    message = await client.get_messages(entity, ids=message_id)
    if message is None:
        await client.disconnect()
        raise TelegramConfigError(f"Telegram message not found: {message_id}")
    downloaded = await client.download_media(
        message,
        file=str(destination),
        progress_callback=progress_callback,
    )
    await client.disconnect()
    if downloaded is None:
        raise TelegramConfigError(f"Telegram message has no downloadable media: {message_id}")
    return Path(downloaded)


async def delete_message(config: dict, base_dir: Path, *, message_id: int) -> None:
    from telethon import TelegramClient

    api_id, api_hash = telegram_credentials()
    if not api_id or not api_hash:
        raise TelegramConfigError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")

    session_path = resolve_data_path(base_dir, f".vamos-vault/{config['telegram']['session_name']}")
    target = config["telegram"]["target"]
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.start()
    entity = await client.get_entity(target)
    await client.delete_messages(entity, [message_id])
    await client.disconnect()
