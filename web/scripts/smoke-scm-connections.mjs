import process from 'node:process';

const parseOptions = () => {
  const args = process.argv.slice(2);
  const optionMap = new Map();
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--' || !arg.startsWith('--')) continue;
    const nextValue = args[index + 1];
    if (!nextValue || nextValue.startsWith('--')) {
      optionMap.set(arg, 'true');
      continue;
    }
    optionMap.set(arg, nextValue);
    index += 1;
  }

  const apiBaseUrl = (optionMap.get('--api-base-url') ?? process.env.OPENWEBPX_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');
  const token = optionMap.get('--token') ?? process.env.OPENWEBPX_AUTH_TOKEN ?? '';
  if (!token.trim()) {
    throw new Error('缺少 token。请通过 --token 或 OPENWEBPX_AUTH_TOKEN 传入。');
  }

  return {
    apiBaseUrl,
    token: token.trim(),
    provider: optionMap.get('--provider'),
    gitlabBaseUrl: optionMap.get('--gitlab-base-url'),
    revoke: optionMap.get('--revoke') === 'true'
  };
};

const buildQuery = ({ provider, gitlabBaseUrl }) => {
  const query = new URLSearchParams();
  if (provider) query.set('provider', provider);
  if (gitlabBaseUrl) query.set('gitlab_base_url', gitlabBaseUrl);
  const queryText = query.toString();
  return queryText ? `?${queryText}` : '';
};

const request = async (options, path, init) => {
  return fetch(`${options.apiBaseUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${options.token}`,
      Accept: 'application/json',
      ...(init.headers ?? {})
    }
  });
};

const readPayload = async (response) => {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

const ensureOk = async (response, actionName) => {
  if (response.ok) return;
  const payload = await readPayload(response);
  throw new Error(`${actionName} 失败（HTTP ${response.status}）: ${JSON.stringify(payload)}`);
};

const main = async () => {
  const options = parseOptions();
  const query = buildQuery(options);

  const listResponse = await request(options, `/api/integrations/scm/connections${query}`, {
    method: 'GET'
  });
  await ensureOk(listResponse, '查询 connections');
  const listPayload = await readPayload(listResponse);
  console.log('✅ connections:', JSON.stringify(listPayload, null, 2));

  if (!options.provider) {
    console.log('ℹ️ 未传 --provider，跳过 validate/revoke 检查。');
    return;
  }

  const validateResponse = await request(
    options,
    `/api/integrations/scm/connections/validate${query}`,
    { method: 'GET' }
  );
  await ensureOk(validateResponse, '校验 connection');
  const validatePayload = await readPayload(validateResponse);
  console.log('✅ validate:', JSON.stringify(validatePayload, null, 2));

  if (!options.revoke) {
    console.log('ℹ️ 已跳过 revoke（可传 --revoke true 启用真实断开）。');
    return;
  }

  const revokeResponse = await request(options, `/api/integrations/scm/connections${query}`, {
    method: 'DELETE'
  });
  await ensureOk(revokeResponse, '断开 connection');
  const revokePayload = await readPayload(revokeResponse);
  console.log('✅ revoke:', JSON.stringify(revokePayload, null, 2));
};

void main().catch((error) => {
  console.error('❌ SCM 连接中心 smoke 失败:', error);
  process.exitCode = 1;
});
