import { getManualBalance } from '../db';
import { toUsd } from '../fx';
import type { FetchResult, PlatformId } from '../types';

async function fetchManual(platform: PlatformId, currency: string): Promise<FetchResult> {
  const stored = getManualBalance(platform);
  if (!stored) {
    return { platform, balanceNative: 0, currency, balanceUsd: 0, fxRate: 1, fetchedAt: new Date().toISOString() };
  }
  const { usd, fxRate } = await toUsd(stored.balanceNative, currency);
  console.log(`[${platform}] ${currency} ${stored.balanceNative.toFixed(2)} → $${usd.toFixed(2)}`);
  return { platform, balanceNative: stored.balanceNative, currency, balanceUsd: usd, fxRate, fetchedAt: new Date().toISOString() };
}

export async function fetchBinance():        Promise<FetchResult> { return fetchManual('binance',         'USD'); }
export async function fetchCoinbase():       Promise<FetchResult> { return fetchManual('coinbase',        'USD'); }
export async function fetchPhantom():        Promise<FetchResult> { return fetchManual('phantom',         'USD'); }
export async function fetchRevolutBalance(): Promise<FetchResult> { return fetchManual('revolut_balance', 'GBP'); }
export async function fetchRevolutStocks():  Promise<FetchResult> { return fetchManual('revolut_stocks',  'GBP'); }
export async function fetchRevolutCrypto():  Promise<FetchResult> { return fetchManual('revolut_crypto',  'GBP'); }
export async function fetchTiger():          Promise<FetchResult> { return fetchManual('tiger',           'USD'); }
export async function fetchChinaBank():      Promise<FetchResult> { return fetchManual('china_bank',      'CNY'); }
export async function fetchCtbcBalance():    Promise<FetchResult> { return fetchManual('ctbc_balance',    'TWD'); }
export async function fetchCtbcStocks():     Promise<FetchResult> { return fetchManual('ctbc_stocks',     'TWD'); }
export async function fetchDbs():            Promise<FetchResult> { return fetchManual('dbs',             'SGD'); }
export async function fetchTiktokRsu():      Promise<FetchResult> { return fetchManual('tiktok_rsu',      'USD'); }
export async function fetchMetaRsu():        Promise<FetchResult> { return fetchManual('meta_rsu',        'USD'); }
