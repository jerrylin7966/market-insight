import axios from 'axios';
import { toUsd } from '../fx';
import type { FetchResult } from '../types';

const BASE_URL = 'https://live.trading212.com/api/v0';

export async function fetchTrading212(): Promise<FetchResult> {
  const apiKey    = process.env.T212_API_KEY;
  const apiSecret = process.env.T212_API_SECRET;
  if (!apiKey || !apiSecret) return errorResult('T212_API_KEY or T212_API_SECRET not set');

  try {
    const credentials = Buffer.from(`${apiKey}:${apiSecret}`).toString('base64');
    const res = await axios.get(`${BASE_URL}/equity/account/cash`, {
      headers: { Authorization: `Basic ${credentials}` },
      timeout: 10000,
    });
    const cash: number     = res.data.free     ?? 0;
    const invested: number = res.data.invested ?? 0;
    const result: number   = res.data.result   ?? 0;
    const total = cash + invested + result;
    const { usd, fxRate } = await toUsd(total, 'GBP');
    console.log(`[Trading 212] GBP ${total.toFixed(2)} → $${usd.toFixed(2)}`);
    return { platform: 'trading212', balanceNative: total, currency: 'GBP', balanceUsd: usd, fxRate, fetchedAt: new Date().toISOString() };
  } catch (err: any) {
    const msg = err?.response?.data?.code ?? err?.message ?? 'Unknown error';
    console.error(`[Trading 212] Error: ${msg}`);
    return errorResult(msg);
  }
}

function errorResult(error: string): FetchResult {
  return { platform: 'trading212', balanceNative: 0, currency: 'GBP', balanceUsd: 0, fxRate: 1, fetchedAt: new Date().toISOString(), error };
}
