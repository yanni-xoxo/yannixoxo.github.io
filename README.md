# yannixoxo.github.io — Pokémon collection

Public catalogue at **https://yannixoxo.github.io/pkmncollection/**  
Add form redirect at **https://yannixoxo.github.io/pkmncollection/add/**

Pipeline: **Google Form → Google Sheet → GitHub Action sync → GitHub Pages**

- Filters by **Pokémon species** (not item kind)
- **No Approved column** — every form response is published
- **Daily scheduled full resync** (UTC 16:00) plus manual append/full runs

---

## Setup checklist

### 1. Create the Google Form

Suggested fields (titles matter for column mapping):

| Form question | Type | Notes |
|---------------|------|-------|
| Item Name | Short answer | Required |
| Image | File upload | Prefer square photo |
| Species | Dropdown | Mimikyu, Jigglypuff, Wooper, Clodsire, Furret, Drifloon, Mudkip, Cubone, Others |
| Source | Short answer | Gift, store, etc. |
| Notes | Paragraph | Optional |

Link the Form to a **Google Sheet** (Responses → Link to Sheets).

Restrict the Form to her Google account if you want (Settings → Responses → Restrict to users in … / collect email). That replaces the old approval gate.

### 2. Add the Synced column

In row 1 of the linked Sheet, add **Synced** if missing. Leave cells blank; the sync script writes `TRUE` after a successful sync.

Typical header row:

`Timestamp | Image | Species | Source | Notes | Item Name | Synced`

(Order can vary — the script matches by header name.)

### 3. Point `/pkmncollection/add` at the Form

1. Form → **Send** → copy the link.
2. Edit `pkmncollection/add/index.html` and replace every `REPLACE_WITH_YOUR_FORM_ID` URL with that link (meta refresh, script, and anchor).

### 4. Google Cloud service account

1. [Google Cloud Console](https://console.cloud.google.com/) → create/reuse a project.
2. Enable **Google Sheets API** and **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create service account**.
4. **Keys → Add key → JSON** — download the key. Keep it secret.
5. Copy the service account email (`…@….iam.gserviceaccount.com`).

### 5. Share Sheet + photo folder

- **Sheet** → Share → service account email as **Editor** (needed to write Synced).
- Form file uploads go to a **Drive folder** → Share that folder with the same email as **Viewer** (or Editor).

### 6. GitHub secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|--------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Entire contents of the JSON key file |
| `PKMNCOLLECTION_SHEET_ID` | From Sheet URL: `https://docs.google.com/spreadsheets/d/SHEET_ID/edit` |

Optional: if the tab is not named `Form Responses 1`, add secret/variable `PKMNCOLLECTION_WORKSHEET` and set it in the workflow env (or rename the tab).

### 7. Enable GitHub Pages

**Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)`.**

Live URLs after deploy:

- https://yannixoxo.github.io/pkmncollection/
- https://yannixoxo.github.io/pkmncollection/add/

### 8. First test

1. Submit one test item on the Form (with photo).
2. Actions → **Sync Pokémon catalogue** → Run workflow → mode **append**.
3. Confirm `pkmncollection/collection.json` and `images/` updated, then check the live page.

Scheduled runs use **full** sync every day at **16:00 UTC** (midnight HKT). Change the cron in `.github/workflows/sync-pkmncollection.yml` if needed.

---

## Day-to-day

1. Submit items on the Form (or via `/pkmncollection/add`).
2. Wait for the daily sync, or run **Sync Pokémon catalogue** manually:
   - **append** — only new rows not yet Synced
   - **full** — re-read every row; drop items whose sheet rows were deleted
3. To remove an item: delete the row in the Sheet, then run **full** (or wait for the daily full sync).

---

## Species filters

`mimikyu` · `jigglypuff` · `wooper` · `clodsire` · `furret` · `drifloon` · `mudkip` · `cubone` · `other`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Missing `GOOGLE_SERVICE_ACCOUNT_JSON` / `PKMNCOLLECTION_SHEET_ID` | Add the secrets under Actions |
| Invalid JSON secret | Paste the **entire** key file, not a path |
| 403 / permission | Share Sheet (Editor) + upload folder (Viewer) with the service account |
| Missing Species / Item Name columns | Fix header row names |
| Photos missing | Drive folder shared? Photo cell has a Drive URL? |
| Empty page after sync | Hard refresh; confirm Pages is on `main` |

Local dry run:

```bash
pip install -r scripts/requirements-pkmncollection-sync.txt
# Windows PowerShell:
$env:GOOGLE_SERVICE_ACCOUNT_JSON="C:\path\to\key.json"
$env:PKMNCOLLECTION_SHEET_ID="your_sheet_id"
$env:PKMNCOLLECTION_DRY_RUN="1"
python scripts/sync_pkmncollection.py
```
