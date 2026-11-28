# V2 Workspace Upload Queue

## Overview

The V2 workspace document explorer can now take a selection of hundreds of files in one go. Before, every selected file travelled in a single multipart request, so a selection of more than about ten files could exceed what a gateway will carry or the time a request may take, and the whole upload failed.

The explorer now sends the selection as a queue of small requests from the browser, one after another. Nothing changes on the server.

- **Version**: 0.261.492
- **Implemented in**: 0.261.492
- **Dependencies**: the existing upload routes (`/api/documents/upload`, `/api/groups/<id>/documents/upload`, `/api/public-workspaces/<id>/documents/upload`)

## Technical Specifications

### Architecture

- `application/v2_ui/src/lib/documentUploadQueue.ts`
  - `planUploadBatches(files, limits)` splits a selection, in order, into requests of at most `UPLOAD_BATCH_MAX_FILES` (5) files and `UPLOAD_BATCH_MAX_BYTES` (50 MB). A single file larger than the byte limit goes alone, as it always did.
  - `uploadInBatches(files, upload, options)` sends the requests sequentially, merges each answer into one outcome, and reports progress after each request. Its outcome carries `remaining` (files never sent) and `unconfirmed` (files in a request that had no confirmed outcome).
- `application/v2_ui/src/components/documents/DocumentExplorer.tsx` calls the queue from `onUploadFiles`, after the file type check, the size check and the user agreement. The progress bar advances as each request is answered.
- `application/v2_ui/src/components/documents/ExplorerCommandBar.tsx`: `ExplorerProgress` shows a **Stop** button while an upload queue is running.

### Behavior

- Requests never overlap, so the server does the same work in the same order as before, in smaller pieces.
- A request that the server refuses with per-file reasons is an answer; the queue continues with the next request.
- A request with no confirmed outcome (a dropped connection, a gateway error) does not stop the queue either. Its files are listed as possibly stored, so the list should be checked before they are uploaded again, and the queue continues with the next request. One bad file costs at most its own request of up to five files.
- The queue stops early in three cases only: **Stop** is pressed (it ends after the request in flight), the session ends, or `UPLOAD_MAX_CONSECUTIVE_FAILURES` (2) requests fail in a row, which means the fault is in the connection or the server and not in the files.
- A request refused because the session ended read no files, so its files count as never sent.
- Whenever the queue stops early, the files that were never sent are kept in the page for that workspace. **Send remaining files** sends them through the same checks and the same user agreement; **Discard** drops them. Nothing was sent for those files, so continuing cannot create duplicates.
- While an upload is running, the browser asks before the tab is closed or reloaded.
- Leaving the explorer stops the queue before its next request.

### Configuration

None. The two limits are constants in `documentUploadQueue.ts`.

## Usage Instructions

Select or drop any number of files on the Documents page of a personal, group or public workspace. There is no limit on the number of files; each must be within the maximum file size. The progress bar shows `Uploading files` with a running count and a **Stop** button. When the queue ends, the summary reads `Accepted N of M files. Processing is queued, not complete.` If files were left unsent, a notice offers **Send remaining files**.

## Testing and Validation

- `functional_tests/test_v2_document_upload_queue_logic.mjs` runs the real queue and the real upload adapter against controlled HTTP: batch planning for 250 files, the byte limit, sequential sending, merged answers, refusals, carrying on past a failed request, stopping after failures in a row, stopping on an ended session, an interrupted queue, and continuing with what remained so every file is sent exactly once.
- `functional_tests/test_v2_user_agreement_gate.py` still proves the agreement is asked before anything is sent.

### Limitations

- The queue lives in the page. Closing or reloading the tab ends it and loses the unsent files; files already accepted keep processing.
- A stopped queue is continued by the person, not automatically.
- Files in a request with no confirmed outcome are not offered for resending, because they may already be stored. A failed request cannot say which of its files was at fault, so all of them are reported.
- Files are accepted faster than they are processed. A very large selection waits on the server's background workers after the upload itself has finished.
- Chat attachments are not affected; they were already sent one file per request.
