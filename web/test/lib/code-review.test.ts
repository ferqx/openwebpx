import test from 'node:test';
import assert from 'node:assert/strict';

// Mock import.meta.env before importing code-review.ts
// @ts-expect-error test-only import.meta shim
import.meta.env = {};

import {
  approveCodeReviewFixRequest,
  CodeReviewRequestError,
  getCodeReviewRepositoryConfig,
  listCodeReviewRepositories,
  listCodeReviewRuns,
  publishCodeReviewRun,
  rejectCodeReviewFixRequest,
  syncCodeReviewRepositories,
  updateCodeReviewRepositoryConfig
} from '../../src/lib/code-review.ts';

const createMockResponse = <TData>(
  data: TData,
  options: { ok?: boolean; status?: number; statusText?: string } = {}
) => {
  const body = JSON.stringify(data);
  const text = async () => body;
  const json = async () => data;
  return {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    statusText: options.statusText ?? 'OK',
    json,
    text
  } as Response;
};

test.beforeEach(() => {
  global.fetch = async () => {
    throw new Error('Fetch not mocked for this test');
  };
});

test('CodeReviewRequestError stores status code', () => {
  const error = new CodeReviewRequestError('Not Found', { status: 404 });
  assert.equal(error.message, 'Not Found');
  assert.equal(error.status, 404);
  assert.equal(error.name, 'CodeReviewRequestError');
});

test('listCodeReviewRepositories returns repository list on success', async () => {
  const repositories = [{ id: 1, provider: 'github', external_repo_id: '42' }];
  global.fetch = async () => createMockResponse({ repositories });

  const result = await listCodeReviewRepositories();
  assert.deepEqual(result, repositories);
});

test('syncCodeReviewRepositories posts payload and returns repositories', async () => {
  let initBody = '';
  global.fetch = async (_input, init) => {
    initBody = String(init?.body ?? '');
    return createMockResponse({
      repositories: [
        { id: 1, provider: 'gitlab', external_repo_id: 'abc' }
      ]
    });
  };

  const result = await syncCodeReviewRepositories({
    provider: 'gitlab',
    gitlab_base_url: 'https://gitlab.example.com'
  });

  assert.equal(initBody.includes('"provider":"gitlab"'), true);
  assert.deepEqual(result, [
    { id: 1, provider: 'gitlab', external_repo_id: 'abc' }
  ]);
});

test('getCodeReviewRepositoryConfig and updateCodeReviewRepositoryConfig call expected endpoints', async () => {
  const urls: string[] = [];
  global.fetch = async (input, init) => {
    urls.push(String(input));
    if (init?.method === 'PUT') {
      return createMockResponse({
        id: 7,
        repository_integration_id: 3,
        review_enabled: true,
        review_triggers: null,
        auto_fix_enabled: false,
        auto_fix_severities: null,
        auto_fix_requires_approval: true,
        auto_publish_enabled: false
      });
    }
    return createMockResponse({
      id: 7,
      repository_integration_id: 3,
      review_enabled: true,
      review_triggers: null,
      auto_fix_enabled: false,
      auto_fix_severities: null,
      auto_fix_requires_approval: true,
      auto_publish_enabled: false
    });
  };

  await getCodeReviewRepositoryConfig(3);
  await updateCodeReviewRepositoryConfig(3, { review_enabled: false });

  assert.equal(urls[0], '/api/code-review/repositories/3/config');
  assert.equal(urls[1], '/api/code-review/repositories/3/config');
});

test('listCodeReviewRuns and publishCodeReviewRun return typed payloads', async () => {
  const urls: string[] = [];
  global.fetch = async (input, init) => {
    urls.push(`${init?.method ?? 'GET'} ${String(input)}`);
    if (String(input).endsWith('/publish')) {
      return createMockResponse({
        published: true,
        run_id: 99,
        status: 'completed',
        published_at: '2026-03-22T00:00:00.000Z',
        stubbed: true
      });
    }
    return createMockResponse({
      runs: [
        {
          id: 99,
          repository_integration_id: 3,
          provider: 'github',
          event_type: 'pull_request',
          status: 'queued',
          idempotency_key: 'k'
        }
      ]
    });
  };

  const runs = await listCodeReviewRuns();
  const publishResult = await publishCodeReviewRun(99);

  assert.deepEqual(runs, [
    {
      id: 99,
      repository_integration_id: 3,
      provider: 'github',
      event_type: 'pull_request',
      status: 'queued',
      idempotency_key: 'k'
    }
  ]);
  assert.equal(publishResult.published, true);
  assert.equal(urls[0], 'GET /api/code-review/runs');
  assert.equal(urls[1], 'POST /api/code-review/runs/99/publish');
});

test('approveCodeReviewFixRequest and rejectCodeReviewFixRequest call expected endpoints', async () => {
  const requests: Array<{ url: string; method: string; body: string }> = [];
  global.fetch = async (input, init) => {
    requests.push({
      url: String(input),
      method: init?.method ?? 'GET',
      body: String(init?.body ?? '')
    });
    return createMockResponse({
      id: 12,
      review_run_id: 99,
      review_finding_id: 4,
      source: 'auto_policy',
      status: String(input).endsWith('/approve') ? 'running' : 'rejected',
      approval_required: true
    });
  };

  const approved = await approveCodeReviewFixRequest(12);
  const rejected = await rejectCodeReviewFixRequest(12, 'not needed');

  assert.equal(approved.status, 'running');
  assert.equal(rejected.status, 'rejected');
  assert.deepEqual(requests, [
    {
      url: '/api/code-review/fix-requests/12/approve',
      method: 'POST',
      body: ''
    },
    {
      url: '/api/code-review/fix-requests/12/reject',
      method: 'POST',
      body: JSON.stringify({ reason: 'not needed' })
    }
  ]);
});

test('listCodeReviewRuns filters malformed run summaries missing repository integration id', async () => {
  global.fetch = async () =>
    createMockResponse({
      runs: [
        {
          id: 99,
          provider: 'github',
          event_type: 'pull_request',
          status: 'queued',
          idempotency_key: 'k'
        }
      ]
    });

  const runs = await listCodeReviewRuns();

  assert.deepEqual(runs, []);
});

test('request errors preserve plain text response messages', async () => {
  global.fetch = async () =>
    ({
      ok: false,
      status: 502,
      clone: () => ({
        json: async () => {
          throw new Error('Invalid JSON');
        }
      }),
      json: async () => {
        throw new Error('Invalid JSON');
      },
      text: async () => 'upstream gateway failed'
    }) as Response;

  await assert.rejects(
    () => listCodeReviewRepositories(),
    (error: unknown) => {
      assert.ok(error instanceof CodeReviewRequestError);
      assert.equal(error.status, 502);
      assert.equal(error.message, 'upstream gateway failed');
      return true;
    }
  );
});
