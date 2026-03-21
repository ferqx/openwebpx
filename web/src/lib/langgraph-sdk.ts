import { Client } from '@langchain/langgraph-sdk';
import { withAuthHeaders } from '@/lib/auth';

export const base_path = `${window.location.origin}/api`;

export const client = new Client({
  apiUrl: base_path,
  apiKey: null,
  onRequest: (_: URL, init: RequestInit) => withAuthHeaders(init)
});
