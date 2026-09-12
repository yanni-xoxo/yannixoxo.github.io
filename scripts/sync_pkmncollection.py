#!/usr/bin/env python3
"""
Sync Pokémon merchandise from a Google Sheet (linked to Google Form) into
pkmncollection/collection.json and pkmncollection/images/.

Environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON  Path to service-account JSON, or the JSON string itself
  PKMNCOLLECTION_SHEET_ID      Google Sheet ID (from the URL)
  PKMNCOLLECTION_WORKSHEET     Worksheet name (default: "Form Responses 1")
  PKMNCOLLECTION_DRY_RUN       Set to "1" to preview without writing files or the sheet
  PKMNCOLLECTION_FULL_SYNC     Set to "1" to re-read every row (ignores Synced column)

All non-empty rows are synced (no Approved column). Incremental runs mark Synced = TRUE.
Full sync rebuilds the catalogue from all sheet rows and drops deleted ones.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE_JSON = REPO_ROOT / "pkmncollection" / "collection.json"
IMAGES_DIR = REPO_ROOT / "pkmncollection" / "images"
THUMBS_DIR = IMAGES_DIR / "thumbs"
THUMB_MAX_PX = 320
THUMB_JPEG_QUALITY = 82
API_RETRY_ATTEMPTS = 6
API_RETRY_BASE_SECONDS = 2.0

T = TypeVar("T")

DEFAULT_SPECIES = [
    {"id": "mimikyu", "label": "Mimikyu"},
    {"id": "jigglypuff", "label": "Jigglypuff"},
    {"id": "wooper", "label": "Wooper"},
    {"id": "clodsire", "label": "Clodsire"},
    {"id": "furret", "label": "Furret"},
    {"id": "drifloon", "label": "Drifloon"},
    {"id": "mudkip", "label": "Mudkip"},
    {"id": "cubone", "label": "Cubone"},
    {"id": "other", "label": "Others"},
]

SPECIES_ALIASES = {
    "mimikyu": "mimikyu",
    "jigglypuff": "jigglypuff",
    "jiggly puff": "jigglypuff",
    "puff": "jigglypuff",
    "wooper": "wooper",
    "clodsire": "clodsire",
    "furret": "furret",
    "drifloon": "drifloon",
    "mudkip": "mudkip",
    "cubone": "cubone",
    "other": "other",
    "others": "other",
}


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "item"


def species_lookup() -> dict[str, str]:
    lookup = dict(SPECIES_ALIASES)
    for entry in DEFAULT_SPECIES:
        lookup[entry["id"]] = entry["id"]
        lookup[entry["label"].lower()] = entry["id"]
        lookup[slugify(entry["label"])] = entry["id"]
    return lookup


def normalize_species_token(raw: str) -> str | None:
    key = raw.strip().lower()
    if not key:
        return None

    lookup = species_lookup()
    if key in lookup:
        return lookup[key]

    compact = slugify(key).replace("-", "")
    for alias, species_id in lookup.items():
        alias_compact = slugify(alias).replace("-", "")
        if alias_compact and alias_compact == compact:
            return species_id

    return None


def parse_species_list(raw: str) -> list[str]:
    """Parse Form checkbox (or dropdown) values into unique species ids.

    Google Forms checkboxes usually join selections with commas, e.g.
    "Mimikyu, Wooper, Furret". Also accept newlines, semicolons, pipes, ampersands.
    """
    if not raw or not str(raw).strip():
        return ["other"]

    parts = re.split(r"[\n,;|/&]+", str(raw))
    ordered: list[str] = []
    seen: set[str] = set()
    for part in parts:
        species_id = normalize_species_token(part)
        if not species_id or species_id in seen:
            continue
        seen.add(species_id)
        ordered.append(species_id)

    return ordered or ["other"]


HEADER_ALIASES = {
    "timestamp": "timestamp",
    "item name": "name",
    "name": "name",
    "title": "name",
    "species": "species",
    "pokemon": "species",
    "pokémon": "species",
    "category": "species",
    "notes": "notes",
    "description": "notes",
    "source": "source",
    "where from": "source",
    "origin": "source",
    "image": "photo",
    "file upload": "photo",
    "upload": "photo",
    "acquired": "acquired",
    "date acquired": "acquired",
    "synced": "synced",
}

HEADER_CONTAINS = [
    ("name", "name"),
    ("photo", "photo"),
    ("upload", "photo"),
    ("image", "photo"),
    ("species", "species"),
    ("pokemon", "species"),
    ("pokémon", "species"),
    ("source", "source"),
    ("synced", "synced"),
]

TRUTHY = {"1", "true", "yes", "y", "x", "approved", "publish"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_tags(raw: str) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    parts = re.split(r"[,;|]", str(raw))
    return [part.strip() for part in parts if part.strip()]


def is_truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def load_credentials():
    import google.oauth2.service_account as service_account

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set.")

    if raw.startswith("{"):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly",
            ],
        )

    path = Path(raw)
    if not path.is_file():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must be JSON text or a valid file path.")
    return service_account.Credentials.from_service_account_file(
        str(path),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )


def load_catalogue() -> dict[str, Any]:
    if CATALOGUE_JSON.is_file():
        with CATALOGUE_JSON.open(encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        data = {}

    data.setdefault("species", DEFAULT_SPECIES)
    data.setdefault("items", [])
    return data


def save_catalogue(data: dict[str, Any]) -> None:
    CATALOGUE_JSON.parent.mkdir(parents=True, exist_ok=True)
    with CATALOGUE_JSON.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def map_headers(header_row: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(header_row):
        normalized = str(cell).strip().lower()
        key = HEADER_ALIASES.get(normalized)
        if key and key not in mapping:
            mapping[key] = index

    for index, cell in enumerate(header_row):
        normalized = str(cell).strip().lower()
        if not normalized:
            continue
        for needle, key in HEADER_CONTAINS:
            if key in mapping:
                continue
            if needle in normalized:
                mapping[key] = index
                break

    return mapping


def format_header_help(header_row: list[str]) -> str:
    headers = [str(cell).strip() for cell in header_row if str(cell).strip()]
    if not headers:
        return "The worksheet header row is empty."
    return "Found columns: " + ", ".join(headers)


def open_worksheet(spreadsheet, worksheet_name: str):
    import gspread

    try:
        return spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        titles = [sheet.title for sheet in spreadsheet.worksheets()]
        if len(titles) == 1:
            print(
                f'Worksheet "{worksheet_name}" not found; using only tab "{titles[0]}".'
            )
            return spreadsheet.get_worksheet(0)
        raise RuntimeError(
            f'Worksheet "{worksheet_name}" not found. Available tabs: {", ".join(titles)}. '
            "Set PKMNCOLLECTION_WORKSHEET to one of these names."
        ) from None


def credential_help(error: Exception) -> str:
    message = str(error)
    if "PKMNCOLLECTION_SHEET_ID is not set" in message:
        return "Add the PKMNCOLLECTION_SHEET_ID repository secret (Sheet ID from the URL)."
    if "GOOGLE_SERVICE_ACCOUNT_JSON is not set" in message:
        return "Add the GOOGLE_SERVICE_ACCOUNT_JSON repository secret (full JSON key contents)."
    if isinstance(error, json.JSONDecodeError):
        return (
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON. "
            "Paste the entire key file contents into the GitHub secret."
        )
    if "Missing required column" in message:
        return message + " Add Item Name and Species columns to row 1 of the sheet."
    if "403" in message or "permission" in message.lower():
        return (
            str(error)
            + " Share the Google Sheet (Editor) and Form upload Drive folder (Viewer) "
            "with your service account email."
        )
    if "503" in message or "currently unavailable" in message.lower():
        return (
            str(error)
            + " Google Sheets/Drive had a temporary outage (503). Re-run the workflow in a minute."
        )
    return message


def is_transient_google_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "503",
        "502",
        "500",
        "504",
        "429",
        "currently unavailable",
        "backend error",
        "internal error",
        "rate limit",
        "quota exceeded",
        "timed out",
        "timeout",
        "connection reset",
        "temporarily unavailable",
    )
    return any(marker in message for marker in markers)


def with_retries(label: str, operation: Callable[[], T]) -> T:
    last_error: Exception | None = None
    for attempt in range(1, API_RETRY_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as error:  # noqa: BLE001 - retry policy decides
            last_error = error
            if not is_transient_google_error(error) or attempt >= API_RETRY_ATTEMPTS:
                raise
            delay = API_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            print(
                f"{label} failed ({error}); retry {attempt}/{API_RETRY_ATTEMPTS} in {delay:.0f}s…"
            )
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def cell(row: list[str], mapping: dict[str, int], key: str) -> str:
    index = mapping.get(key)
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def extract_drive_file_id(url: str) -> str | None:
    if not url:
        return None
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", url.strip()):
        return url.strip()
    return None


def unique_item_id(name: str, sheet_row: int, existing_ids: set[str]) -> str:
    base = slugify(name)[:48] or f"item-{sheet_row}"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def guess_extension(mime_type: str, fallback: str = ".jpg") -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    return mapping.get((mime_type or "").lower(), fallback)


def download_drive_file(credentials, file_id: str, destination: Path) -> None:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    def _download():
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        metadata = service.files().get(fileId=file_id, fields="mimeType,name").execute()
        mime_type = metadata.get("mimeType", "")

        target = destination
        if target.suffix == "":
            target = target.with_suffix(guess_extension(mime_type))

        target.parent.mkdir(parents=True, exist_ok=True)
        request = service.files().get_media(fileId=file_id)
        with target.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return target

    return with_retries(f"Drive download {file_id}", _download)


def thumb_relative_path(filename: str) -> str:
    return f"thumbs/{filename}"


def create_thumbnail(source_path: Path, force: bool = False) -> Path | None:
    from PIL import Image

    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    dest = THUMBS_DIR / f"{source_path.stem}.jpg"
    if dest.is_file() and not force:
        return dest

    try:
        with Image.open(source_path) as img:
            if getattr(img, "is_animated", False):
                img.seek(0)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.Resampling.LANCZOS)
            img.save(dest, "JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
        return dest
    except Exception as error:  # noqa: BLE001
        print(f"Thumbnail failed for {source_path.name}: {error}")
        return None


def ensure_item_thumbnail(image_name: str | None, force: bool = False) -> str | None:
    if not image_name:
        return None
    source = IMAGES_DIR / image_name
    if not source.is_file():
        return None
    thumb = create_thumbnail(source, force=force)
    if not thumb:
        return None
    return thumb_relative_path(thumb.name)


def generate_all_thumbnails(force: bool = False) -> int:
    catalogue = load_catalogue()
    updated = 0
    for item in catalogue["items"]:
        image_name = item.get("image")
        thumb = ensure_item_thumbnail(image_name, force=force)
        if thumb:
            item["imageThumb"] = thumb
            updated += 1
        elif item.get("imageThumb"):
            del item["imageThumb"]
    catalogue["updatedAt"] = utc_now_iso()
    save_catalogue(catalogue)
    print(f"Generated thumbnails for {updated} item(s).")
    return updated


def items_by_sheet_row(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for item in items:
        row = item.get("sheetRow")
        if isinstance(row, int):
            indexed[row] = item
    return indexed


def sync(full_sync: bool = False) -> int:
    sheet_id = os.environ.get("PKMNCOLLECTION_SHEET_ID", "").strip()
    if not sheet_id:
        raise RuntimeError("PKMNCOLLECTION_SHEET_ID is not set.")

    worksheet_name = os.environ.get("PKMNCOLLECTION_WORKSHEET", "Form Responses 1").strip()
    dry_run = os.environ.get("PKMNCOLLECTION_DRY_RUN", "").strip() == "1"

    if full_sync:
        print("Full sync: re-reading all rows (ignoring Synced column).")

    import gspread

    credentials = load_credentials()
    client = gspread.authorize(credentials)
    spreadsheet = with_retries(
        "Open spreadsheet",
        lambda: client.open_by_key(sheet_id),
    )
    worksheet = with_retries(
        "Open worksheet",
        lambda: open_worksheet(spreadsheet, worksheet_name),
    )
    values = with_retries(
        "Read sheet values",
        worksheet.get_all_values,
    )
    if not values:
        print("Sheet is empty; nothing to sync.")
        return 0

    header_row = values[0]
    mapping = map_headers(header_row)
    print(format_header_help(header_row))
    print(
        "Mapped fields: "
        + ", ".join(f"{key}={header_row[index]!r}" for key, index in sorted(mapping.items()))
    )
    required = ["name", "species"]
    missing = [key for key in required if key not in mapping]
    if missing:
        raise RuntimeError(
            "Missing required column(s) in sheet header: "
            + ", ".join(missing)
            + ". Expected at least: Item Name, Species. "
            + format_header_help(header_row)
        )

    catalogue = load_catalogue()
    catalogue["species"] = DEFAULT_SPECIES
    old_by_row = items_by_sheet_row(catalogue["items"])
    if full_sync:
        existing_by_row: dict[int, dict[str, Any]] = {}
    else:
        existing_by_row = dict(old_by_row)
    used_ids = {item["id"] for item in catalogue["items"] if item.get("id")}

    processed_rows: list[int] = []
    changed = False

    for row_number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue

        existing = old_by_row.get(row_number) if full_sync else existing_by_row.get(row_number)
        if not full_sync:
            already_synced = is_truthy(cell(row, mapping, "synced")) if "synced" in mapping else False
            if already_synced and existing:
                continue

        name = cell(row, mapping, "name")
        species_raw = cell(row, mapping, "species")
        if not name:
            print(f"Row {row_number}: skipped (missing name).")
            continue

        item_id = (
            existing["id"]
            if existing and existing.get("id")
            else unique_item_id(name, row_number, used_ids)
        )
        used_ids.add(item_id)

        photo_url = cell(row, mapping, "photo")
        image_name = existing.get("image") if existing else None

        file_id = extract_drive_file_id(photo_url)
        should_download_photo = bool(file_id) and (full_sync or not image_name)
        if should_download_photo:
            target = IMAGES_DIR / f"{item_id}.jpg"
            if dry_run:
                action = "re-download" if full_sync and image_name else "download"
                print(f"Row {row_number}: would {action} photo -> {target.name}")
            else:
                try:
                    saved = download_drive_file(credentials, file_id, target)
                    image_name = saved.name
                    verb = (
                        "re-downloaded"
                        if full_sync and existing and existing.get("image")
                        else "downloaded"
                    )
                    print(f"Row {row_number}: {verb} photo -> {image_name}")
                except Exception as error:  # noqa: BLE001 - surface row-level failures
                    print(f"Row {row_number}: photo download failed ({error}).")
        elif not image_name:
            image_name = None

        should_refresh_thumb = bool(image_name) and (should_download_photo or full_sync)
        image_thumb = ensure_item_thumbnail(image_name, force=should_refresh_thumb)
        if not image_thumb and image_name:
            image_thumb = ensure_item_thumbnail(image_name, force=False)

        item = {
            "id": item_id,
            "name": name,
            "species": parse_species_list(species_raw),
            "source": cell(row, mapping, "source") or None,
            "notes": cell(row, mapping, "notes") or None,
            "tags": parse_tags(cell(row, mapping, "tags")),
            "image": image_name,
            "imageThumb": image_thumb,
            "acquired": cell(row, mapping, "acquired") or None,
            "sheetRow": row_number,
            "addedAt": existing.get("addedAt") if existing else utc_now_iso(),
        }
        if not item["source"]:
            del item["source"]
        if not item["notes"]:
            del item["notes"]
        if not item["tags"]:
            del item["tags"]
        if not item["acquired"]:
            del item["acquired"]
        if not item["imageThumb"]:
            del item["imageThumb"]

        existing_by_row[row_number] = item
        processed_rows.append(row_number)
        changed = True
        verb = "updated" if full_sync and existing else "synced"
        print(f"Row {row_number}: {verb} '{name}' as {item_id}")

    if full_sync:
        removed_rows = set(old_by_row) - set(existing_by_row)
        for row_number in sorted(removed_rows):
            removed_item = old_by_row[row_number]
            print(
                f"Row {row_number}: removed '{removed_item.get('name', 'item')}' "
                "(row deleted from sheet)."
            )
        if removed_rows:
            changed = True

    if not changed:
        if full_sync:
            print("Full sync: no rows to publish.")
        else:
            print("No new rows to sync.")
        return 0

    catalogue["items"] = sorted(
        existing_by_row.values(),
        key=lambda entry: (entry.get("name") or "").lower(),
    )
    catalogue["updatedAt"] = utc_now_iso()

    if dry_run:
        print("Dry run complete; files were not written.")
        return len(processed_rows)

    save_catalogue(catalogue)

    if "synced" in mapping and processed_rows:
        synced_col = mapping["synced"] + 1  # gspread is 1-indexed
        for row_number in processed_rows:
            with_retries(
                f"Mark Synced row {row_number}",
                lambda row_number=row_number: worksheet.update_cell(
                    row_number, synced_col, "TRUE"
                ),
            )

    label = "Full sync" if full_sync else "Sync"
    print(f"{label}: {len(processed_rows)} row(s) published. Catalogue -> {CATALOGUE_JSON}")
    return len(processed_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Pokémon catalogue from Google Sheets.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Re-read every row, update existing entries, and drop deleted rows.",
    )
    parser.add_argument(
        "--thumbs-only",
        action="store_true",
        help="Generate thumbnails for all catalogue images (no Google Sheet access needed).",
    )
    parser.add_argument(
        "--force-thumbs",
        action="store_true",
        help="With --thumbs-only, regenerate thumbnails even if they already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.thumbs_only:
        try:
            generate_all_thumbnails(force=args.force_thumbs)
        except Exception as error:  # noqa: BLE001
            print("Thumbnail generation failed:", error, file=sys.stderr)
            return 1
        return 0

    full_sync = args.full or os.environ.get("PKMNCOLLECTION_FULL_SYNC", "").strip() == "1"
    try:
        count = sync(full_sync=full_sync)
    except Exception as error:  # noqa: BLE001
        print("Sync failed:", credential_help(error), file=sys.stderr)
        return 1
    return 0 if count >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
