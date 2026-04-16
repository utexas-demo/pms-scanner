# Feature Specification: PDF Scan Batch Processing with Cron Scheduling and Progress Dashboard

**Feature Branch**: `003-pdf-scan-cron-upload`  
**Created**: 2026-04-14  
**Status**: Draft  
**Input**: User description: "we want to watch all the files in this folder and loop through them, for every pdf file in the folder check how many pages, take every page make sure it is upright and if it is not then rotate 90 degrees until the page is majority up right.  then treat every page as single upload to the server same as what we currently have in this app.  This app will also be running on MAC now, when it was originally built, it was supposed to be on Windows.  We want it to be a cron job and the server should be accessible so we can watch the progress of upload.  We should report the file name, the number of pages in that file and as we are uploading, we should report say page 1/33, 2/33..etc. as the progress is going on."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scheduled PDF Batch Upload (Priority: P1)

An operator places scanned PDF files into the ARIAscans network folder. On the next scheduled run, the system automatically finds all PDF files, corrects the orientation of every page, and uploads each page individually to the backend — without any manual intervention.

**Why this priority**: This is the entire core value of the application. Every other story depends on this working first. Without batch processing and upload, nothing else matters.

**Independent Test**: Place 2–3 multi-page PDFs (including one with rotated pages) into the watch folder, trigger a run, and verify all pages appear correctly oriented in the backend system.

**Acceptance Scenarios**:

1. **Given** the watch folder contains 3 PDF files, **When** the scheduled run executes, **Then** the system processes all 3 files and uploads every page of every file to the backend
2. **Given** a PDF page is rotated 90° clockwise, **When** the system processes that page, **Then** the page is corrected to upright orientation before upload
3. **Given** a PDF page is already upright, **When** the system processes that page, **Then** the page is uploaded as-is without unnecessary rotation
4. **Given** a PDF has 33 pages, **When** the system uploads page 5, **Then** the progress log/dashboard shows "page 5/33" for that file
5. **Given** the watch folder contains no PDF files, **When** the scheduled run executes, **Then** the system completes without error and logs that no files were found

---

### User Story 2 - Live Progress Dashboard (Priority: P2)

An operator opens a browser to a local web address while a batch run is in progress. They can see which file is currently being processed, how many pages it has, and which page is currently uploading — updating in real time without refreshing the page.

**Why this priority**: Without visibility into progress, operators cannot tell if the system is working, stuck, or done. This is critical for day-to-day confidence in the system.

**Independent Test**: Start a batch run against a large PDF (20+ pages), open the dashboard in a browser mid-run, and verify the progress indicator advances page-by-page in real time.

**Acceptance Scenarios**:

1. **Given** a batch run is in progress, **When** an operator navigates to the dashboard URL, **Then** they see the current filename, total page count, and current page number (e.g., "scanning_batch.pdf — page 7/33")
2. **Given** the dashboard is open in a browser, **When** the next page finishes uploading, **Then** the displayed page counter updates without requiring a manual page refresh
3. **Given** a batch run just completed, **When** an operator opens the dashboard, **Then** they see a summary of the last run: files processed, total pages uploaded, any errors
4. **Given** multiple files are queued, **When** the system moves from one file to the next, **Then** the dashboard updates to show the new filename and resets the page counter

---

### User Story 3 - macOS-Native Operation (Priority: P3)

A staff member sets up the application on a Mac connected to the MedPath Wi-Fi, configures it once, and the cron job runs automatically every day without needing to log into a Windows machine.

**Why this priority**: The existing system was built for Windows. Running on macOS is now the target deployment environment. Without this, the system cannot be used at all in the current office setup.

**Independent Test**: Install and configure the application on a fresh macOS machine, verify the cron job fires on schedule, and confirm at least one file is processed and uploaded successfully end-to-end.

**Acceptance Scenarios**:

1. **Given** the application is installed on macOS, **When** the cron job fires, **Then** it successfully connects to the ARIAscans share and processes files
2. **Given** the macOS system restarts, **When** the machine comes back up, **Then** the cron job is automatically re-registered and continues running on schedule
3. **Given** the application is configured on macOS, **When** a new operator sets it up following the documentation, **Then** the full setup takes under 30 minutes

---

### Edge Cases

- PDFs still being written when the cron fires are skipped via settle-time check (last-modified within configurable window, default 10s); they will be claimed on the next 1-minute run — no partial-write corruption risk
- How does the system handle a password-protected or corrupted PDF?
- What happens when the ARIAscans network share is not mounted or unreachable at run time?
- What if the backend server is down and an upload fails mid-batch — does the run abort or continue with remaining pages/files?
- Successfully processed files are moved to `ARIAscans/processed/`; files being claimed are moved to `ARIAscans/in-progress/` — both moves prevent other runs from seeing or re-processing those files
- Files left in `ARIAscans/in-progress/` after a crash are recovered on the next run start — all `in-progress/` files are unconditionally moved back to the watch folder before scanning (FR-016); they will be re-processed as normal on that run
- What if a page cannot be conclusively determined as upright after four rotation attempts (0°, 90°, 180°, 270°)?
- What happens when the watch folder contains non-PDF files alongside PDFs?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST scan the configured watch folder for all PDF files at the start of each scheduled run, excluding any file whose last-modified timestamp is within a configurable settle window (default: 10 seconds) — such files are skipped and will be picked up on the next run
- **FR-002**: System MUST determine the exact page count of each PDF file and record it before processing begins
- **FR-016**: At the start of each scheduled run, before scanning for new files, system MUST move all files found in `ARIAscans/in-progress/` back to the watch folder — recovering any files stranded by a prior crash or unexpected shutdown
- **FR-003**: System MUST analyze each page's orientation and rotate it in 90-degree increments until the majority of the page content is upright
- **FR-004**: System MUST upload each corrected page as a separate image to the backend using the existing upload contract (POST /api/scanned-images/upload)
- **FR-005**: System MUST run automatically on a cron schedule defaulting to every 1 minute; the interval is configurable via the `.env` file
- **FR-006**: System MUST expose a web-based progress dashboard accessible from any device on MedPath Wi-Fi — no authentication required; served at a configurable port on the Mac's local IP address
- **FR-007**: The progress dashboard MUST display, in real time: the name of the file currently being processed, total page count for that file, and the current page number in "X/Y" format
- **FR-008**: System MUST track which files have already been successfully processed to avoid re-uploading on subsequent runs
- **FR-009**: System MUST log failures for individual page uploads without aborting the entire batch run — remaining pages and files continue processing
- **FR-013**: System MUST atomically claim a PDF file by moving it to an `ARIAscans/in-progress/` subfolder before beginning processing — ensuring that no two concurrent runs can claim the same file
- **FR-014**: System MUST move a successfully processed PDF file from `ARIAscans/in-progress/` to `ARIAscans/processed/` immediately after all its pages have been uploaded; files that fail mid-processing are returned to the watch folder for retry on the next run
- **FR-015**: Multiple scheduled runs MAY execute simultaneously; because file claiming is atomic (FR-013), each file is guaranteed to be processed by exactly one run at a time
- **FR-010**: System MUST run natively on macOS without requiring Windows-specific tooling or emulation
- **FR-011**: System MUST skip non-PDF files found in the watch folder without error
- **FR-012**: System MUST handle a disconnected or unavailable watch folder gracefully, logging the error and exiting the run cleanly

### Key Entities

- **PDF File**: A scanned multi-page document; lifecycle: appears in watch folder → claimed by atomic move to `in-progress/` → pages uploaded → moved to `processed/` (or returned to watch folder on failure)
- **Page**: An individual page extracted from a PDF file; has an orientation that may require correction; treated as a single upload unit to the backend
- **Batch Run**: A single scheduled execution; processes all unprocessed PDF files in the watch folder; has a start time, end time, file count, page count, and outcome
- **Upload Record**: A record of a single page upload attempt; includes file name, page number, upload timestamp, and success/failure status

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All PDF files present in the watch folder at run time are processed within a single scheduled batch run
- **SC-002**: Zero pages arrive at the backend in a sideways or upside-down orientation (orientation correction succeeds for 100% of rotated pages)
- **SC-003**: The progress dashboard reflects the current page counter within 3 seconds of a page upload completing
- **SC-004**: Operators can determine the outcome of the most recent batch run (files processed, pages uploaded, errors) from the dashboard without accessing log files
- **SC-005**: A file successfully uploaded in a previous run is not re-uploaded in subsequent runs — it is absent from the watch folder, having been moved to `ARIAscans/processed/`
- **SC-006**: The full application installs and runs correctly on macOS with a setup process completable in under 30 minutes by a non-developer
- **SC-007**: Upload processing begins within 1 minute of a PDF file appearing in the watch folder (guaranteed by the 1-minute cron interval)

## Clarifications

### Session 2026-04-14

- Q: What happens when the cron fires a new run while a previous run is still executing? → A: Runs execute in parallel; file-level exclusivity is enforced by atomically moving each file to `in-progress/` before processing — a file claimed by one run is invisible to all others
- Q: How should files stuck in `ARIAscans/in-progress/` be recovered after a crash? → A: Startup recovery — at the start of every run, all files found in `in-progress/` are unconditionally moved back to the watch folder before scanning begins
- Q: How should the system handle a PDF still being written when the cron fires? → A: Settle time — skip any PDF whose last-modified timestamp is within a configurable number of seconds; it will be claimed on the next run
- Q: How frequently should the cron run? → A: Every 1 minute; upload must begin within 1 minute of a file appearing in the folder
- Q: What happens to a PDF file after all its pages are successfully uploaded? → A: Move to a `processed` subfolder (`ARIAscans/processed/`) — file is relocated after successful completion
- Q: Who can access the progress dashboard? → A: Open to anyone on MedPath Wi-Fi — no authentication required; accessible at `http://<mac-ip>:<port>` from any device on the local network

## Assumptions

- The watch folder is the ARIAscans subfolder on the ARIA network share (`smb://adgligo2/aria`), mounted at `/Volumes/aria/ARIAscans` on macOS
- The Mac running this application must be on MedPath Wi-Fi for the network share to be accessible
- Files that fail orientation detection after all four rotations (0°, 90°, 180°, 270°) are uploaded in their best-guess orientation and flagged in the dashboard as needing manual review
- The cron schedule defaults to every 1 minute; this is configurable via the `.env` file
- The file settle window defaults to 10 seconds (reuses the existing `FILE_SETTLE_SECONDS` setting); PDFs modified more recently than this are skipped until the next run
- The progress dashboard requires no authentication and is accessible from any device on MedPath Wi-Fi via `http://<mac-ip>:<port>`; the port is configurable via the `.env` file
- The existing upload contract (POST /api/scanned-images/upload) is used without modification; each page is rasterized to an image before upload, consistent with current behavior
- Files are considered processed when physically moved to `ARIAscans/processed/`; no separate state-tracking database is needed
- The cron job is registered using macOS-native scheduling (launchd) so it survives reboots without manual intervention
- The current Docker-based architecture may be replaced or supplemented with a macOS-native service; this is a planning decision
