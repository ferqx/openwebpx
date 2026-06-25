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

  const apiBaseUrl = (optionMap.get('--api-base-url') ?? process.env.SANDBOX_AGENT_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');
  const token = optionMap.get('--token') ?? process.env.SANDBOX_AGENT_AUTH_TOKEN ?? '';
  const threadId = optionMap.get('--thread-id') ?? '';
  const action = optionMap.get('--action') ?? 'interrupt';

  if (!token.trim()) throw new Error('缺少 token。请通过 --token 或 SANDBOX_AGENT_AUTH_TOKEN 传入。');
  if (!threadId.trim()) throw new Error('缺少 thread id。请通过 --thread-id 传入。');
  if (action !== 'cancel' && action !== 'interrupt') {
    throw new Error('action 仅支持 cancel 或 interrupt。');
  }

  return {
    apiBaseUrl,
    token: token.trim(),
    threadId: threadId.trim(),
    action
  };
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

const main = async () => {
  const options = parseOptions();
  const endpoint = `${options.apiBaseUrl}/api/sandbox/threads/${encodeURIComponent(options.threadId)}/cancel?action=${encodeURIComponent(options.action)}`;

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${options.token}`,
      Accept: 'application/json'
    }
  });

  const payload = await readPayload(response);

  if (!response.ok) {
    if (response.status === 404 || response.status === 405) {
      console.warn('⚠️ 后端不支持线程级 cancel 接口（404/405），前端会回退 runs.list -> runs.cancel。');
      console.warn('响应:', JSON.stringify(payload, null, 2));
      return;
    }
    throw new Error(`线程级 cancel 调用失败（HTTP ${response.status}）: ${JSON.stringify(payload)}`);
  }

  console.log('✅ 线程级 cancel 返回:', JSON.stringify(payload, null, 2));
};

void main().catch((error) => {
  console.error('❌ 线程级 cancel smoke 失败:', error);
  process.exitCode = 1;
});
