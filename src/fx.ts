import axios from 'axios';

let _cache: { rates: Record<string, number>; fetchedAt: number } | null = null;

async function fetchRates(): Promise<Record<string, number>> {
  if (_cache && Date.now() - _cache.fetchedAt < 60 * 60 * 1000) {
    return _cache.rates;
  }
  try {
    const res = await axios.get('https://api.frankfurter.app/latest?base=USD', { timeout: 8000 });
    const rates: Record<string, number> = res.data.rates;
    rates['USD'] = 1;
    if (!rates['CNY']) rates['CNY'] = 7.25;
    if (!rates['TWD']) rates['TWD'] = 32.1;
    _cache = { rates, fetchedAt: Date.now() };
    console.log(`[FX] Rates fetched. GBP=${rates.GBP?.toFixed(4)}, SGD=${rates.SGD?.toFixed(4)}, TWD=${rates.TWD?.toFixed(4)}, CNY=${rates.CNY?.toFixed(4)}`);
    return rates;
  } catch (err) {
    console.error('[FX] Failed to fetch rates, using fallback');
    return { USD: 1, GBP: 0.79, SGD: 1.34, TWD: 32.1, CNY: 7.25 };
  }
}

export async function toUsd(amount: number, currency: string): Promise<{ usd: number; fxRate: number }> {
  if (currency === 'USD') return { usd: amount, fxRate: 1 };
  const rates = await fetchRates();
  const rate = rates[currency.toUpperCase()];
  if (!rate) return { usd: amount, fxRate: 1 };
  return { usd: amount / rate, fxRate: 1 / rate };
}

export async function warmRates(): Promise<void> {
  await fetchRates();
}
