// test_v2_document_upload_queue_logic.mjs
// Version: 0.261.492
// Implemented in: 0.261.492
// Executes the real V2 workspace upload queue (lib/documentUploadQueue.ts) and the real upload
// adapter (lib/documentOperations.ts) against controlled HTTP. A large selection is sent as a
// series of small requests, in order, each within the file and byte limits; what the server says
// about each request is merged. Neither a request refused with per-file reasons nor a request
// with no confirmed outcome stops the queue: one bad file costs its own request, not the
// selection. The queue stops only when requests fail in a row or the session has ended, and then
// hands back the files it never sent, in order, so they can be sent later without sending
// anything twice.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const { PERSONAL_DOCUMENT_OPERATIONS } = await import('../application/v2_ui/src/lib/documentOperations.ts');
const {
    UPLOAD_BATCH_MAX_BYTES, UPLOAD_BATCH_MAX_FILES, UPLOAD_MAX_CONSECUTIVE_FAILURES, planUploadBatches, uploadInBatches,
} = await import('../application/v2_ui/src/lib/documentUploadQueue.ts');

const originalFetch = globalThis.fetch;
let checks = 0;

async function check(name, run) {
    await run();
    checks += 1;
    console.log(`ok ${name}`);
}

function sized(count, size = 1024) {
    return Array.from({ length: count }, (_, index) => ({ name: `file-${index + 1}.txt`, size }));
}

function receipt(batch) {
    return {
        document_ids: batch.map((file) => `id-${file.name}`),
        processed_filenames: batch.map((file) => file.name),
        errors: [],
    };
}

try {
    await check('250 files become ordered requests within the file limit', async () => {
        const files = sized(250);
        const batches = planUploadBatches(files);
        assert.equal(batches.length, Math.ceil(250 / UPLOAD_BATCH_MAX_FILES));
        assert.ok(batches.every((batch) => batch.length >= 1 && batch.length <= UPLOAD_BATCH_MAX_FILES));
        assert.deepEqual(batches.flat(), files);
    });

    await check('a request never exceeds the byte limit unless one file does alone', async () => {
        const megabyte = 1024 * 1024;
        const files = [
            { name: 'a', size: 30 * megabyte }, { name: 'b', size: 30 * megabyte },
            { name: 'huge', size: UPLOAD_BATCH_MAX_BYTES + 1 }, { name: 'c', size: megabyte }, { name: 'd', size: megabyte },
        ];
        const batches = planUploadBatches(files);
        assert.deepEqual(batches.map((batch) => batch.map((file) => file.name)), [['a'], ['b'], ['huge'], ['c', 'd']]);
        assert.deepEqual(planUploadBatches([]), []);
        assert.deepEqual(planUploadBatches(sized(3), { maxFiles: 0, maxBytes: 1 }).map((batch) => batch.length), [1, 1, 1]);
    });

    await check('every request is sent one after another and the answers are merged', async () => {
        const files = sized(23);
        let inFlight = 0;
        const sizes = [];
        const progress = [];
        const outcome = await uploadInBatches(files, async (batch) => {
            inFlight += 1;
            assert.equal(inFlight, 1, 'requests must not overlap');
            await new Promise((resolve) => setTimeout(resolve, 1));
            inFlight -= 1;
            sizes.push(batch.length);
            return receipt(batch);
        }, { onProgress: (state) => progress.push(state.completed) });
        assert.deepEqual(sizes, [5, 5, 5, 5, 3]);
        assert.deepEqual(progress, [5, 10, 15, 20, 23]);
        assert.deepEqual(outcome.processed_filenames, files.map((file) => file.name));
        assert.equal(outcome.document_ids.length, 23);
        assert.deepEqual([outcome.errors, outcome.unsent, outcome.stopped], [[], 0, null]);
        assert.deepEqual([outcome.remaining, outcome.unconfirmed], [[], []]);
    });

    await check('a request refused with per-file reasons does not stop the queue', async () => {
        let request = 0;
        const outcome = await uploadInBatches(sized(12), async (batch) => {
            request += 1;
            if (request === 2) return { document_ids: [], processed_filenames: [], errors: batch.map((file) => `${file.name}: refused`) };
            return receipt(batch);
        });
        assert.equal(request, 3);
        assert.equal(outcome.document_ids.length, 7);
        assert.equal(outcome.errors.length, 5);
        assert.deepEqual([outcome.unsent, outcome.stopped], [0, null]);
    });

    await check('a request with no confirmed outcome costs its own files and the queue carries on', async () => {
        let request = 0;
        const progress = [];
        const outcome = await uploadInBatches(sized(22), async (batch) => {
            request += 1;
            if (request === 2 || request === 4) throw new Error('Connection lost.');
            return receipt(batch);
        }, { onProgress: (state) => progress.push(state.completed) });
        assert.equal(request, 5);
        assert.equal(outcome.document_ids.length, 12);
        assert.deepEqual([outcome.unsent, outcome.remaining, outcome.stopped], [0, [], null]);
        assert.equal(outcome.errors.length, 2);
        assert.match(outcome.errors[0], /^file-6\.txt, .*file-10\.txt: Connection lost\.$/);
        assert.deepEqual(outcome.unconfirmed.map((file) => file.name), [
            'file-6.txt', 'file-7.txt', 'file-8.txt', 'file-9.txt', 'file-10.txt',
            'file-16.txt', 'file-17.txt', 'file-18.txt', 'file-19.txt', 'file-20.txt',
        ]);
        assert.deepEqual(progress, [5, 10, 15, 20, 22]);
    });

    await check('requests failing in a row stop the queue and hand back what was never sent', async () => {
        assert.equal(UPLOAD_MAX_CONSECUTIVE_FAILURES, 2);
        let request = 0;
        const outcome = await uploadInBatches(sized(32), async (batch) => {
            request += 1;
            if (request >= 2) throw new Error('SimpleChat could not be reached.');
            return receipt(batch);
        });
        assert.equal(request, 3);
        assert.equal(outcome.document_ids.length, 5);
        assert.equal(outcome.unconfirmed.length, 10);
        assert.equal(outcome.stopped, 'SimpleChat could not be reached.');
        assert.deepEqual(outcome.remaining.map((file) => file.name), sized(32).slice(15).map((file) => file.name));
        assert.equal(outcome.unsent, 17);
    });

    await check('a failure that refuses every request stops at once and its files count as never sent', async () => {
        let request = 0;
        const ended = new Error('Sign in again.');
        const outcome = await uploadInBatches(sized(14), async (batch) => {
            request += 1;
            if (request === 2) throw ended;
            return receipt(batch);
        }, { refusesEveryRequest: (cause) => cause === ended });
        assert.equal(request, 2);
        assert.deepEqual([outcome.document_ids.length, outcome.errors, outcome.unconfirmed], [5, [], []]);
        assert.equal(outcome.stopped, 'Sign in again.');
        assert.deepEqual(outcome.remaining.map((file) => file.name), sized(14).slice(5).map((file) => file.name));
    });

    await check('the queue stops before a request when asked not to continue', async () => {
        let request = 0;
        const outcome = await uploadInBatches(sized(15), async (batch) => {
            request += 1;
            return receipt(batch);
        }, { shouldContinue: () => request < 1 });
        assert.equal(request, 1);
        assert.deepEqual([outcome.document_ids.length, outcome.unsent], [5, 10]);
        assert.ok(outcome.stopped);
        assert.deepEqual(outcome.unconfirmed, []);
    });

    await check('sending what remained after a stop sends every file exactly once', async () => {
        const files = sized(17);
        const sent = [];
        let stop = false;
        const upload = async (batch) => {
            sent.push(...batch.map((file) => file.name));
            stop = true;
            return receipt(batch);
        };
        const first = await uploadInBatches(files, upload, { shouldContinue: () => !stop });
        assert.equal(first.remaining.length, 12);
        const second = await uploadInBatches(first.remaining, upload);
        assert.deepEqual([second.unsent, second.stopped], [0, null]);
        assert.deepEqual(sent, files.map((file) => file.name));
    });

    await check('the real personal adapter carries 120 files as 24 requests of 5', async () => {
        const posts = [];
        globalThis.fetch = async (path, options = {}) => {
            const url = new URL(String(path), 'http://fixture.test');
            const names = options.body.getAll('file').map((file) => file.name);
            posts.push({ path: url.pathname, method: options.method, names });
            return new Response(JSON.stringify({
                message: 'ok', document_ids: names.map((name) => `id-${name}`), processed_filenames: names, errors: [],
            }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        };
        const files = Array.from({ length: 120 }, (_, index) => new File(['x'], `doc-${index + 1}.txt`, { type: 'text/plain' }));
        const outcome = await uploadInBatches(files, (batch) => PERSONAL_DOCUMENT_OPERATIONS.upload(batch));
        assert.equal(posts.length, 24);
        assert.ok(posts.every((post) => post.path === '/api/documents/upload' && post.method === 'POST' && post.names.length === 5));
        assert.deepEqual(posts.flatMap((post) => post.names), files.map((file) => file.name));
        assert.deepEqual([outcome.document_ids.length, outcome.errors.length, outcome.unsent], [120, 0, 0]);
    });

    console.log(`${checks} document upload queue checks passed.`);
} finally {
    globalThis.fetch = originalFetch;
}
