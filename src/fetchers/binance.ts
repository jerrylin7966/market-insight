import axios from 'axios';
import crypto from 'crypto';
import type { FetchResult } from '../types';

const BASE_URL = 'https://api.binance.com';

function sign(query: string, secret: string): string {
  return crypto.createHmac('sha256', secret).update(query).digest('hex');
}

export async function fetchBinance(): Promise<FetchResult> {
  const apiKey    = process.env.BINANCE_API_KEY;
  const apiSecret = process.env.BINANCE_API_SECRET;
  if (!apiKey || !apiSecret) return errorResult('BINANCE_API_KEY or BINANCE_API_SECRET not set');

  try {
    const timestamp = Date.now();
    const query = `timestamp=${timestamp}`;
    const signature = sign(query, apiSecret);
    const res = await axios.get(`${BASE_URL}/api/v3/account?${query}&signature=${signature}`, {
      headers: { 'X-MBX-APIKEY': apiKey },
      timeout: 10000,
    });

    const balances: Array<{ asset: string; free: string; locked: string }> = res.data.balances ?? [];
    const nonZero = balances.filter(b => parseFloat(b.free) + parseFloat(b.locked) > 0.00001);

    const pricesRes = await axios.get(`${BASE_URL}/api/v3/ticker/price`, { timeout: 8000 });
    const prices: Record<string, number> = {};
    for (const p of pricesRes.data as Array<{ symbol: string; price: string }>) {
      prices[p.symbol] = parseFloat(p.price);
    }

    let total = 0;
    for (const b of nonZero) {
      const amount = parseFloat(b.free) + parseFloat(b.locked);
      if (['USDT','BUSD','USDC'].includes(b.asset)) {
        total += amount;
      } else if (prices[`${b.asset}USDT`]) {
        total += amount * prices[`${b.asset}USDT`];
      } else if (prices[`${b.asset}BTC`] && prices['BTCUSDT']) {
        total += amount * prices[`${b.asset}BTC`] * prices['BTCUSDT'];
      }
    }

    console.log(`[Binance] Total: $${total.toFixed(2)}`);
    return { platform: 'binance', balanceNative: total, currency: 'USD', balanceUsd: total, fxRate: 1, fetchedAt: new Date().toISOString() };
  } catch (err: any) {
    const msg = err?.response?.data?.msg ?? err?.message ?? 'Unknown error';
    console.error(`[Binance] Error: ${msg}`);
    return errorResult(msg);
  }
}

function errorResult(error: string): FetchResult {
  return { platform: 'binance', balanceNative: 0, currency: 'USD', balanceUsd: 0, fxRate: 1, fetchedAt: new Date().toISOString(), error };
}
