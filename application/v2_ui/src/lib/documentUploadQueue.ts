// documentUploadQueue.ts

/**
 * Client-side queue for workspace document uploads.
 *
 * The upload routes take any number of files in one multipart request, but they save, register
 * and screen each one before answering. A large selection sent as a single request therefore
 * grows past what a proxy will carry or a request may take, and fails as a whole. The queue
 * sends the same selection as a series of small requests, one after another, so the size of a
 * selection is no longer bounded by the size of a request.
 */

import type { DocumentUploadOutcome } from './documentOperations';

/** Files in one request. Small enough that a request answers well inside a gateway timeout. */
export const UPLOAD_BATCH_MAX_FILES = 5;

/** Bytes in one request. A single file larger than this still goes, alone, as it always did. */
export const UPLOAD_BATCH_MAX_BYTES = 50 * 1024 * 1024;

/**
 * Requests in a row that may fail before the queue stops. One failed request is taken to be about
 * its own files and the queue moves on; a second straight after it means the fault is not in the
 * files (the connection or the server is down), and sending the rest would only fail them too.
 */
export const UPLOAD_MAX_CONSECUTIVE_FAILURES = 2;

export interface UploadBatchLimits {
    maxFiles: number;
    maxBytes: number;
}

export interface UploadQueueProgress {
    /** Files whose request has been answered, or has failed. */
    completed: number;
    total: number;
}

export interface UploadQueueOutcome<T = unknown> extends DocumentUploadOutcome {
    /** How many files were never sent, because the queue stopped before reaching them. */
    unsent: number;
    /** Those files, in order. Nothing was sent for them, so sending them later cannot duplicate. */
    remaining: T[];
    /** Files in requests that had no confirmed outcome. They may or may not have been stored. */
    unconfirmed: T[];
    /** Why the queue stopped early, or null when it reached the end of the selection. */
    stopped: string | null;
}

export interface UploadQueueOptions {
    limits?: UploadBatchLimits;
    onProgress?: (progress: UploadQueueProgress) => void;
    /** Asked before each request; false leaves the remaining files unsent. */
    shouldContinue?: () => boolean;
    /**
     * True for a failure that refused the request before any file was read and will refuse every
     * later one, such as a session that has ended. The queue stops at once and the refused files
     * count as never sent.
     */
    refusesEveryRequest?: (cause: unknown) => boolean;
}

/** Split a selection into requests, keeping its order, each within both limits. */
export function planUploadBatches<T extends { size: number }>(
    files: readonly T[],
    limits: UploadBatchLimits = { maxFiles: UPLOAD_BATCH_MAX_FILES, maxBytes: UPLOAD_BATCH_MAX_BYTES },
): T[][] {
    const maxFiles = Math.max(1, Math.floor(limits.maxFiles));
    const batches: T[][] = [];
    let current: T[] = [];
    let currentBytes = 0;
    for (const file of files) {
        if (current.length > 0 && (current.length >= maxFiles || currentBytes + file.size > limits.maxBytes)) {
            batches.push(current);
            current = [];
            currentBytes = 0;
        }
        current.push(file);
        currentBytes += file.size;
    }
    if (current.length > 0) batches.push(current);
    return batches;
}

/**
 * Send a selection as sequential requests and merge what the server said about each.
 *
 * A request that is refused with per-file reasons is an answer, and `upload` returns it as one.
 * A request that throws has no confirmed outcome: its files may or may not have been stored, so
 * they are reported as unconfirmed and are never resent. Either way the queue carries on with
 * the next request, so one bad file costs at most its own request and not the selection.
 *
 * The queue stops early in two cases only, and in both it hands back the files it never sent:
 * the caller says the failure refuses every request, or `UPLOAD_MAX_CONSECUTIVE_FAILURES`
 * requests fail in a row.
 */
export async function uploadInBatches<T extends { size: number; name: string }>(
    files: readonly T[],
    upload: (batch: T[]) => Promise<DocumentUploadOutcome>,
    options: UploadQueueOptions = {},
): Promise<UploadQueueOutcome<T>> {
    const outcome: UploadQueueOutcome<T> = {
        document_ids: [], processed_filenames: [], errors: [], unsent: 0, remaining: [], unconfirmed: [], stopped: null,
    };
    const total = files.length;
    let completed = 0;
    let consecutiveFailures = 0;
    for (const batch of planUploadBatches(files, options.limits)) {
        if (options.shouldContinue && !options.shouldContinue()) {
            outcome.stopped = 'The upload was interrupted.';
            break;
        }
        try {
            const response = await upload(batch);
            outcome.document_ids.push(...response.document_ids);
            outcome.processed_filenames.push(...response.processed_filenames);
            outcome.errors.push(...response.errors);
            consecutiveFailures = 0;
        } catch (cause) {
            const reason = cause instanceof Error && cause.message ? cause.message : 'The upload was not confirmed.';
            if (options.refusesEveryRequest?.(cause)) {
                outcome.stopped = reason;
                break;
            }
            outcome.errors.push(`${batch.map((file) => file.name).join(', ')}: ${reason}`);
            outcome.unconfirmed.push(...batch);
            consecutiveFailures += 1;
            if (consecutiveFailures >= UPLOAD_MAX_CONSECUTIVE_FAILURES) {
                outcome.stopped = reason;
                completed += batch.length;
                options.onProgress?.({ completed, total });
                break;
            }
        }
        completed += batch.length;
        options.onProgress?.({ completed, total });
    }
    outcome.remaining = files.slice(completed);
    outcome.unsent = outcome.remaining.length;
    return outcome;
}
