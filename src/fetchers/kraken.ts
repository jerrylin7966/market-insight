import axios from 'axios';
import crypto from 'crypto';
import type { FetchResult } from '../types';

const BASE_URL = 'https://api.kraken.com';

function getSignature(urlPath: string, data: Record<string, string>, secret: string): string {
  const nonce = data.nonce;
  const postData = new URLSearchParams(data).toString();
  const encoded = Buffer.from(nonce + postData);
  const sha256 = crypto.createHash('sha256').update(encoded).digest();
  const message = Buffer.concat([Buffer.from(urlPath), sha256]);
  return crypto.createHmac('sha512', Buffer.from(secret, 'base64')).update(message).digest('base64');
}

async function krakenPost(endpoint: string, apiKey: string, apiSecret: string): Promise<any> {
  const nonce = Date.now().toString();
  const data = { nonce };
  const sig = getSignature(endpoint, data, apiSecret);
  const res = await axios.post(`${BASE_URL}${endpoint}`, new URLSearchParams(data).toString(), {
    headers: { 'API-Key': apiKey, 'API-Sign': sig, 'Content-Type': 'application/x-www-form-urlencoded' },
    timeout: 10000,
  });
  if (res.data.error?.length > 0) throw new Error(res.data.error.join(', '));
  return res.data.result;
}

export async function fetchKraken(): Promise<FetchResult> {
  const apiKey    = process.env.KRAKEN_API_KEY;
  const apiSecret = process.env.KRAKEN_API_SECRET;
  if (!apiKey || !apiSecret) return errorResult('KRAKEN_API_KEY or KRAKEN_API_SECRET not set');

  try {
    const tb = await krakenPost('/0/private/TradeBalance', apiKey, apiSecret);
    const totalUsd = parseFloat(tb.eb ?? '0');
    console.log(`[Kraken] Total: $${totalUsd.toFixed(2)}`);
    return { platform: 'kraken', balanceNative: totalUsd, currency: 'USD', balanceUsd: totalUsd, fxRate: 1, fetchedAt: new Date().toISOString() };
  } catch (err: any) {
    console.error(`[Kraken] Error: ${err?.message}`);
    return errorResult(err?.message ?? 'Unknown error');
  }
}

function errorResult(error: string): FetchResult {
  return { platform: 'kraken', balanceNative: 0, currency: 'USD', balanceUsd: 0, fxRate: 1, fetchedAt: new Date().toISOString(), error };
}
