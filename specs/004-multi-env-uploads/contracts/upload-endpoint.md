# Contract: Upload Endpoint (reference)

**Branch**: `004-multi-env-uploads` | **Date**: 2026-05-15

**This feature adds no new server-side contract.** The existing endpoint from
feature 003 — `POST /api/scanned-images/upload` — is reused unchanged. See
[003's contract](../../003-we-watch-all/contracts/upload-endpoint.md) for the
schema.

What changes is purely client-side: which **base URL** and which **API token**
the uploader uses for any given file is determined by the file's source
environment (FR-002 / FR-003 / FR-005):

| Source environment | Base URL | Auth header |
|---|---|---|
| `production` | `https://adg.mpsinc.io` | `X-API-Key: ${ENV_PRODUCTION__API_TOKEN}` |
| `staging` | `https://dev.adg.mpsinc.io` | `X-API-Key: ${ENV_STAGING__API_TOKEN}` |

> **Auth-header correction (2026-05-15).** Earlier revisions of this table and
> the 004 uploader used `Authorization: Bearer <token>`. That is wrong: the
> backend authenticates opaque `pms_…` API keys **only** via the `X-API-Key`
> header (`pms-backend` `src/pms/middleware/auth.py` — `X-API-Key` →
> DB key lookup; `Authorization: Bearer` → JWT decode, which 401s
> `{"detail":"Invalid token"}` for an API key). 003's working code used
> `X-API-Key`; the T020 env-aware rewrite regressed it to `Bearer`. Verified
> live: same token returns HTTP 422 (auth OK, missing file) via `X-API-Key`
> vs HTTP 401 via `Bearer`.

The `Environment` object (see `data-model.md`) carries both fields; the
uploader signature changes from 003's implicit `Settings` dependency to an
explicit `env: Environment` parameter so the routing decision is impossible to
miswire.

---

## Contract-test stance

The existing `tests/contract/test_upload_contract.py` from 003 continues to
exercise the endpoint shape. It is extended to run twice — once with a
production-shaped `Environment`, once with a staging-shaped one — proving that
no aspect of the request changes between environments other than base URL and
token.
