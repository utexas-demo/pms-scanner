# Contract: Backend Upload Endpoint

**Branch**: `001-folder-monitor-upload` | **Phase**: 1 | **Date**: 2026-04-08  
**Direction**: pms-scanner → backend (client-side contract)

## Overview

pms-scanner acts as an HTTP client. This document specifies the interface contract the service expects the backend to honour when receiving file uploads.

## Request

```
POST {BACKEND_UPLOAD_URL}
```

### Headers

| Header | Value | Required |
|--------|-------|----------|
| `Authorization` | `Bearer {api_token}` | Yes |
| `Content-Type` | `multipart/form-data; boundary=...` | Set by requests library |

### Body (multipart/form-data)

| Part name | Type | Description |
|-----------|------|-------------|
| `file` | binary | The image file. Filename and MIME type are included in the part headers. |
| `folder` | string | Relative path of the source folder within the watch directory (e.g., `patient-123`). Empty string `""` if the file is directly in the watch root. |

### Example (curl)

```bash
curl -X POST https://api.example.com/v1/images/upload \
  -H "Authorization: Bearer eyJ..." \
  -F "file=@scan-001.jpg;type=image/jpeg" \
  -F "folder=patient-123"
```

---

## Expected Response

### Success

| Code | Meaning | pms-scanner action |
|------|---------|--------------------|
| `200 OK` | Upload accepted | Log success; mark file as UPLOADED |
| `201 Created` | Upload accepted and resource created | Log success; mark file as UPLOADED |

The response body is not parsed by the scanner — any 2xx response is treated as success.

### Retriable Errors

| Code | Meaning | pms-scanner action |
|------|---------|--------------------|
| `500 Internal Server Error` | Backend fault | Retry with exponential back-off (up to 3 attempts) |
| `502 Bad Gateway` | Upstream unavailable | Retry |
| `503 Service Unavailable` | Backend overloaded | Retry |
| `504 Gateway Timeout` | Upstream timeout | Retry |
| Network error / timeout | No response received | Retry |

### Non-Retriable Errors

| Code | Meaning | pms-scanner action |
|------|---------|--------------------|
| `400 Bad Request` | Malformed request | Log error; mark FAILED; do not retry |
| `401 Unauthorized` | Invalid or missing token | Log error; mark FAILED; do not retry |
| `403 Forbidden` | Token lacks permission | Log error; mark FAILED; do not retry |
| `404 Not Found` | Endpoint URL wrong | Log error; mark FAILED; do not retry |
| `413 Payload Too Large` | File exceeds backend limit | Log error; mark FAILED; do not retry |

---

## Retry Policy

- **Max attempts**: 3
- **Back-off**: Exponential — 1s, 2s, 4s (max 10s per interval)
- **Jitter**: ±1s random (prevents thundering herd on burst uploads)
- **Retry on**: Network errors, timeouts, 5xx responses
- **No retry on**: 4xx responses (operator action required)

---

## Security

- `api_token` is transmitted only in the `Authorization` header — never in the URL, query string, body, or log output.
- TLS (HTTPS) is assumed for the backend URL in production. The service does not enforce this — operators are responsible for using an HTTPS endpoint.
