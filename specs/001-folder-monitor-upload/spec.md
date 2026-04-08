# Feature Specification: Folder Monitor and File Upload

**Feature Branch**: `001-folder-monitor-upload`  
**Created**: 2026-04-08  
**Status**: Draft  
**Input**: User description: "we want to monitor a local folder and whenever a file is ready for processing, wait an extra .5 seconds and then upload it to the backend using hard coded authentication for the time being until we implement API login into the system."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - File Automatically Uploaded After Detection (Priority: P1)

A file appears in the watched local folder. The system detects it, waits 0.5 seconds to ensure the file is fully written, then uploads it to the backend without any manual intervention.

**Why this priority**: This is the core value — files must flow from the local folder to the backend reliably and automatically. Everything else depends on this pipeline working.

**Independent Test**: Can be fully tested by placing a file in the watched folder and confirming it is received by the backend within a few seconds, delivering a complete end-to-end upload flow.

**Acceptance Scenarios**:

1. **Given** the monitoring service is running and the watched folder is empty, **When** a new file is placed in the folder and fully written, **Then** the system detects the file, waits 0.5 seconds, and submits it to the backend
2. **Given** the monitoring service is running, **When** a file arrives in the folder, **Then** the upload occurs with no user interaction required
3. **Given** the service is using hard-coded credentials, **When** the file is uploaded, **Then** the backend accepts the request as authenticated

---

### User Story 2 - Upload Failure Is Captured and Surfaced (Priority: P2)

When a file cannot be uploaded (e.g., backend unavailable, auth rejected), the failure is recorded so the operator is aware and the file is not silently lost.

**Why this priority**: Silent failures in an unattended system can cause data loss. Operators must be able to detect and recover from upload failures without relying on manual checks.

**Independent Test**: Can be fully tested by simulating a backend unavailability and confirming the system logs the failure clearly and does not crash.

**Acceptance Scenarios**:

1. **Given** the backend is unreachable, **When** the system attempts to upload a file, **Then** the failure is recorded with enough detail to identify the file and the error
2. **Given** an upload fails, **When** the failure is recorded, **Then** the system continues monitoring for new files without stopping

---

### User Story 3 - Multiple Files Are Processed Without Loss (Priority: P3)

Multiple files arriving in the watched folder in quick succession are each independently detected and uploaded, with none being skipped.

**Why this priority**: In realistic scanning workflows, bursts of files can arrive together. Each file must reach the backend.

**Independent Test**: Can be fully tested by dropping several files into the watched folder simultaneously and confirming all are eventually uploaded to the backend.

**Acceptance Scenarios**:

1. **Given** five files are placed in the watched folder within one second, **When** the system processes them, **Then** all five are uploaded to the backend
2. **Given** a file is being uploaded, **When** a new file arrives in the folder, **Then** the new file is queued and uploaded after the current one completes

---

### Edge Cases

- What happens when a file is still being written when first detected (partial file)?
- What happens when the backend returns an error response (4xx, 5xx)?
- If the watched folder does not exist at startup, the service creates it automatically (including parent directories).
- What happens when the same filename is written twice (overwrite scenario)?
- What happens when disk space is insufficient to buffer the file before upload?
- The `processed/` subfolder MUST be created automatically if it does not exist; files in `processed/` MUST NOT be re-watched or re-uploaded.
- On service restart, files already in `processed/` are ignored; files remaining in the root watch dir (whether never attempted or previously failed) will be re-detected and re-uploaded.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST continuously monitor a designated local folder for newly created or completed files; if the folder does not exist at startup, the system MUST create it automatically (including any missing parent directories) and then begin monitoring
- **FR-002**: System MUST wait exactly 0.5 seconds after a file is detected as ready before initiating the upload
- **FR-003**: System MUST upload each detected file to the configured backend endpoint
- **FR-004**: System MUST authenticate every upload request using pre-configured, hard-coded credentials
- **FR-005**: System MUST record a failure entry when an upload does not succeed, including the file name and reason; the file MUST remain in the watched folder so it is automatically re-attempted on next service restart
- **FR-006**: System MUST continue monitoring and processing other files even when an individual upload fails
- **FR-007**: System MUST process files that arrive concurrently without dropping any
- **FR-008**: System MUST move each successfully uploaded file into a `processed/` subfolder within the watched folder immediately after confirmed upload

### Key Entities

- **Watched Folder**: The local directory the system monitors; files placed here trigger the upload workflow
- **Detected File**: A file found in the watched folder that is ready for processing (fully written to disk)
- **Upload Request**: The act of sending a detected file to the backend, including authentication headers derived from hard-coded credentials
- **Upload Credentials**: Pre-configured authentication values embedded in the service configuration; used until API-based login is introduced
- **Upload Result**: The outcome of an upload attempt — success or failure with error detail

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every file placed in the watched folder is uploaded to the backend within 5 seconds of becoming ready under normal conditions
- **SC-002**: 100% of files placed in the watched folder are accounted for — either uploaded successfully or recorded as a named failure
- **SC-003**: The system processes bursts of 10 simultaneous files without skipping any
- **SC-004**: A failed upload does not halt the system; subsequent files continue to be processed within 1 second of the failure being recorded

## Clarifications

### Session 2026-04-08

- Q: After a file is successfully uploaded, what should happen to it in the watched folder? → A: Move to a `processed/` subfolder inside the watch dir
- Q: After a file exhausts all retries and upload still fails, what should happen to it? → A: Leave it in the watched folder (will be re-detected and re-attempted on next service restart)
- Q: If the watched folder does not exist when the service starts, what should happen? → A: Create the folder automatically and continue startup

## Assumptions

- The service runs on Windows in an unattended, background process (consistent with the pms-scanner project context)
- "File ready for processing" is determined by a file-system close or stabilization event — the 0.5-second delay supplements this to guard against partial writes
- Hard-coded credentials are a deliberate temporary measure; the credential format matches what the backend will eventually require from the API login system
- The backend accepts file uploads via a standard HTTP multipart/form-data request
- Files are expected to be images (consistent with the PMS scanner workflow)
- The watched folder path and backend endpoint URL will be configurable via a settings file, not hard-coded
- Only one instance of the monitoring service runs at a time on a given machine
- Network connectivity to the backend is generally available; the service is not designed for offline-first operation
