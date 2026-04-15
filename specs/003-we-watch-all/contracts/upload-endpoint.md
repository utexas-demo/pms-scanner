# Contract: Backend Upload Endpoint

**Endpoint**: `POST {BACKEND_BASE_URL}/api/scanned-images/upload`  
**Status**: Existing — no changes required  
**Consumer**: `scanner/uploader.py`

## Request

**Headers**:
```
Authorization: Bearer {API_TOKEN}
Content-Type: multipart/form-data
```

**Multipart fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | file | Yes | Single rasterised page image (JPEG or PNG); filename is `{source_pdf_basename}_p{page_num:03d}.jpg` |
| `requisition_id` | string (UUID) | No | Optional; links image to an existing requisition |

**Filename convention** (new — per-page uploads):
```
{source_filename_without_ext}_p{page_num:03d}.jpg
# e.g., 20260414192055_p001.jpg, 20260414192055_p002.jpg
```

## Response

**Success** (`HTTP 200`):
```json
{
  "batch_id": "uuid-string",
  "images": [
    { "filename": "...", "id": "uuid-string" }
  ],
  "rejected": []
}
```

**Partial rejection** (`HTTP 200` with non-empty `rejected`):
- The page was received but rejected by the backend (e.g., duplicate, unsupported format)
- `uploader.py` logs this as a WARNING; the page is counted as failed in `PageResult`

**Auth failure** (`HTTP 401` / `HTTP 403`):
- Logged as ERROR; upload attempt counted as failed
- Batch run continues with remaining pages

**Server error** (`HTTP 5xx`):
- Logged as ERROR with status code
- Batch run continues with remaining pages (FR-009)

## Behaviour Contract

- One HTTP request per page (not per file)
- No retry logic in scope for this feature — failed pages are logged and the file is still moved to `processed/` after all pages are attempted
- Timeout governed by `UPLOAD_TIMEOUT_SECONDS` (default: 30 s)
