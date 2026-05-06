import axios from 'axios';
import { toUsd } from '../fx';
import { getOAuthToken, setOAuthToken } from '../db';
import type { FetchResult, PlatformId } from '../types';

const AUTH_URL = 'https://auth.truelayer.com';
const API_URL  = 'https://api.truelayer.com';

export async function refreshToken(platform: 'hsbc' | 'revolut'): Promise<string | null> {
  const stored = await getOAuthToken(platform);
  if (!stored?.refreshToken) return null;
  if (stored.expiresAt.getTime() - Date.now() > 5 * 60 * 1000) return stored.accessToken;

  try {
    const res = await axios.post(`${AUTH_URL}/connect/token`,
      new URLSearchParams({
        grant_type:    'refresh_token',
        client_id:     process.env.TRUELAYER_CLIENT_ID!,
        client_secret: process.env.TRUELAYER_CLIENT_SECRET!,
        refresh_token: stored.refreshToken,
      }).toString(),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, timeout: 10000 }
    );
    const { access_token, refresh_token, expires_in } = res.data;
    const expiresAt = new Date(Date.now() + expires_in * 1000);
    await setOAuthToken(platform, { access_token, refresh_token: refresh_token ?? stored.refresh_token, expires_at: expiresAt.toISOString() });
    return access_token;
  } catch (err: any) {
    console.error(`[TrueLayer] Token refresh failed for ${platform}:`, err?.message);
    return null;
  }
}

async function fetchPlatform(platform: 'hsbc' | 'revolut', platformId: PlatformId): Promise<FetchResult> {
  const token = await refreshToken(platform);
  if (!token) return errorResult(platformId, `No token for ${platform} — visit /auth/truelayer/connect?provider=${platform}`);

  try {
    const accountsRes = await axios.get(`${API_URL}/data/v1/accounts`, {
      headers: { Authorization: `Bearer ${token}` }, timeout: 10000,
    });
    const accounts = accountsRes.data.results ?? [];
    let total = 0;
    for (const acc of accounts) {
      const balRes = await axios.get(`${API_URL}/data/v1/accounts/${acc.account_id}/balance`, {
        headers: { Authorization: `Bearer ${token}` }, timeout: 10000,
      });
      total += balRes.data.results?.[0]?.available ?? 0;
    }
    const { usd, fxRate } = await toUsd(total, 'GBP');
    console.log(`[TrueLayer/${platform}] GBP ${total.toFixed(2)} → $${usd.toFixed(2)}`);
    return { platform: platformId, balanceNative: total, currency: 'GBP', balanceUsd: usd, fxRate, fetchedAt: new Date().toISOString() };
  } catch (err: any) {
    const msg = err?.response?.data?.error ?? err?.message ?? 'Unknown error';
    console.error(`[TrueLayer/${platform}] Error: ${msg}`);
    return errorResult(platformId, msg);
  }
}

export async function fetchHsbc(): Promise<FetchResult> { return fetchPlatform('hsbc', 'revolut_balance'); }
export async function fetchRevolut(): Promise<FetchResult> {
  return errorResult('revolut_balance', 'Revolut via TrueLayer restricts /accounts access to within 5 minutes of consent. Re-authenticate at /auth/truelayer/connect?provider=revolut immediately before fetching, or enter your balance manually.');
}

function errorResult(platform: PlatformId, error: string): FetchResult {
  return { platform, balanceNative: 0, currency: 'GBP', balanceUsd: 0, fxRate: 1, fetchedAt: new Date().toISOString(), error };
}

export function buildAuthUrl(provider: 'hsbc' | 'revolut', redirectUri: string): string {
  const providerMap: Record<string, string> = { hsbc: 'uk-ob-hsbc uk-oauth-all', revolut: 'uk-ob-revolut uk-oauth-all' };
  const params = new URLSearchParams({
    response_type: 'code',
    client_id:     process.env.TRUELAYER_CLIENT_ID!,
    scope:         'info accounts balance transactions',
    redirect_uri:  redirectUri,
    providers:     providerMap[provider],
    state:         provider,
  });
  return `${AUTH_URL}/?${params.toString()}`;
}

export async function exchangeCode(code: string, provider: 'hsbc' | 'revolut', redirectUri: string): Promise<void> {
  const res = await axios.post(`${AUTH_URL}/connect/token`,
    new URLSearchParams({
      grant_type:    'authorization_code',
      client_id:     process.env.TRUELAYER_CLIENT_ID!,
      client_secret: process.env.TRUELAYER_CLIENT_SECRET!,
      redirect_uri:  redirectUri,
      code,
    }).toString(),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, timeout: 10000 }
  );
  const { access_token, refresh_token, expires_in } = res.data;
  await setOAuthToken(provider, { access_token, refresh_token, expires_at: new Date(Date.now() + expires_in * 1000).toISOString() });
  console.log(`[TrueLayer] ${provider} tokens saved`);
}
