import 'dotenv/config';

export type PlatformId =
  | 'trading212'
  | 'kraken'
  | 'binance'
  | 'revolut_balance'
  | 'revolut_stocks'
  | 'revolut_crypto'
  | 'tiger'
  | 'china_bank'
  | 'ctbc_balance'
  | 'ctbc_stocks'
  | 'dbs';

export type PlatformCategory = 'bank' | 'broker' | 'crypto' | 'manual';

export interface PlatformMeta {
  id: PlatformId;
  name: string;
  category: PlatformCategory;
  currency: string;
  flag: string;
}

export const PLATFORMS: Record<PlatformId, PlatformMeta> = {
  trading212:      { id: 'trading212',      name: 'Trading 212',     category: 'broker', currency: 'GBP', flag: '🇬🇧' },
  kraken:          { id: 'kraken',          name: 'Kraken',          category: 'crypto', currency: 'USD', flag: '🌐' },
  binance:         { id: 'binance',         name: 'Binance',         category: 'crypto', currency: 'USD', flag: '🌐' },
  revolut_balance: { id: 'revolut_balance', name: 'Revolut Balance', category: 'manual', currency: 'GBP', flag: '🇬🇧' },
  revolut_stocks:  { id: 'revolut_stocks',  name: 'Revolut Stocks',  category: 'manual', currency: 'GBP', flag: '🇬🇧' },
  revolut_crypto:  { id: 'revolut_crypto',  name: 'Revolut Crypto',  category: 'manual', currency: 'GBP', flag: '🇬🇧' },
  tiger:           { id: 'tiger',           name: 'Tiger Trade',     category: 'manual', currency: 'USD', flag: '🌐' },
  china_bank:      { id: 'china_bank',      name: 'China Bank',      category: 'manual', currency: 'CNY', flag: '🇨🇳' },
  ctbc_balance:    { id: 'ctbc_balance',    name: 'CTBC Balance',    category: 'manual', currency: 'TWD', flag: '🇹🇼' },
  ctbc_stocks:     { id: 'ctbc_stocks',     name: 'CTBC Stocks',     category: 'manual', currency: 'TWD', flag: '🇹🇼' },
  dbs:             { id: 'dbs',             name: 'DBS',             category: 'manual', currency: 'SGD', flag: '🇸🇬' },
};

export interface FetchResult {
  platform: PlatformId;
  balanceNative: number;
  currency: string;
  balanceUsd: number;
  fxRate: number;
  fetchedAt: string;
  error?: string;
}

export interface DailySnapshot {
  id?: number;
  date: string;
  platform: PlatformId;
  balanceNative: number;
  currency: string;
  balanceUsd: number;
  fxRate: number;
  createdAt: string;
}

export interface ManualUpdatePayload {
  platform: PlatformId;
  balanceNative: number;
}
