import { API_BASE } from './api';

const DEFAULT_KEY = "12a12b12c";

export function getAuthState(): string | null {
  return localStorage.getItem('qwen2api_key');
}

export function setAuthKey(key: string) {
  localStorage.setItem('qwen2api_key', key);
}

export function clearAuthKey() {
  localStorage.removeItem('qwen2api_key');
}

export function getAuthHeader(providedKey?: string) {
  const key = providedKey || getAuthState() || DEFAULT_KEY;
  return { Authorization: `Bearer ${key}` };
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Validates the current or a provided key against the backend.
 * Hardened: Retries on server errors (500/503) to survive backend restarts.
 */
export async function checkSession(key?: string): Promise<boolean> {
  const targetKey = key || getAuthState() || DEFAULT_KEY;
  let retries = 3;
  
  while (retries > 0) {
    try {
      const res = await fetch(`${API_BASE}/api/admin/status`, {
        headers: { Authorization: `Bearer ${targetKey}` }
      });
      
      if (res.ok) {
        if (!getAuthState()) setAuthKey(targetKey);
        return true;
      }
      
      // If it's a structural auth error (401/403), don't retry, just fail.
      if (res.status === 401 || res.status === 403) {
        return false;
      }
      
      // For other errors (500, 503, etc), we retry.
      console.warn(`Auth check received ${res.status}, retrying... (${retries} left)`);
    } catch (error) {
      console.error('Auth check network error, retrying...', error);
    }
    
    retries--;
    if (retries > 0) await sleep(1500); // Wait 1.5s between retries
  }
  
  return false;
}

/**
 * Standard fetch wrapper that automatically injects the Admin API Key.
 */
export async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}/api${endpoint}`;
  const headers = {
    ...getAuthHeader(),
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...options.headers,
  };

  return fetch(url, {
    ...options,
    headers,
  });
}
