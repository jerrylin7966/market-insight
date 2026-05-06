#!/usr/bin/env python3
"""
fetch-oecd-cli.py
Tries OECD SDMX direct, falls back to FRED mirror.
Usage: python3 scripts/fetch-oecd-cli.py <output_path> [fred_api_key]
"""

import json, sys, os, urllib.request, urllib.error
from datetime import datetime

OUTPUT   = sys.argv[1] if len(sys.argv) > 1 else 'public/data/oecd-cli.json'
FRED_KEY = sys.argv[2] if len(sys.argv) > 2 else ''

BROWSER_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept':          'application/vnd.sdmx.data+json;version=2.0, application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer':         'https://data-explorer.oecd.org/',
    'Origin':          'https://data-explorer.oecd.org',
}

OECD_URLS = [
    'https://data-api.oecd.org/v1/data/OECD.SDD.STES,DSD_STES@CLI,4.0/M.USA+GBR+DEU+JPN+G-7.LI.AA?startPeriod=2004-01&format=jsondata',
    'https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@CLI,4.0/M.USA+GBR+DEU+JPN+G-7.LI.AA?startPeriod=2004-01',
]

FRED_SERIES = [
    ('USA', 'USALOLITONOSTSAM'),
    ('GBR', 'GBRLOLITONOSTSAM'),
    ('DEU', 'DEULOLITONOSTSAM'),
    ('JPN', 'JPNLOLITONOSTSAM'),
    ('G-7', 'G7LOLITONOSTSAM'),
]


def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def analyse(series):
    if not series:
        return None
    last  = series[-1]
    mo3   = series[-4:-1]
    trend = ('rising' if last['value'] > mo3[0]['value'] else 'falling') if len(mo3) >= 3 else 'unknown'
    expanding  = last['value'] > 100
    is_bullish = expanding and trend == 'rising'
    if   expanding and trend == 'rising': signal = 'Expanding ↑'
    elif expanding:                        signal = 'Decelerating ↓'
    elif trend == 'rising':                signal = 'Recovery ↑'
    else:                                  signal = 'Contraction ↓'
    color = 'green' if is_bullish else ('red' if not expanding and trend != 'rising' else 'amber')
    return {
        'series': series, 'latestDate': last['date'], 'latest': last['value'],
        'trend': trend, 'expanding': expanding, 'isBullish': is_bullish,
        'signal': signal, 'color': color,
    }


def parse_sdmx(raw):
    structure   = raw.get('data', {}).get('structure') or raw.get('structure')
    datasets    = raw.get('data', {}).get('dataSets')  or raw.get('dataSets')
    if not structure or not datasets:
        raise ValueError('Unexpected SDMX-JSON shape')

    series_dims  = structure['dimensions']['series']
    obs_dims     = structure['dimensions']['observation']
    time_periods = [v['id'] for v in next(d for d in obs_dims if d['id'] == 'TIME_PERIOD')['values']]
    loc_idx      = next(i for i, d in enumerate(series_dims) if d['id'] in ('REF_AREA', 'LOCATION'))
    loc_values   = series_dims[loc_idx]['values']

    countries = {}
    for key, s in datasets[0]['series'].items():
        loc_id = loc_values[int(key.split(':')[loc_idx])]['id']
        pts = [
            {'date': time_periods[int(ti)], 'value': arr[0]}
            for ti, arr in s.get('observations', {}).items()
            if arr[0] is not None
        ]
        pts.sort(key=lambda p: p['date'])
        countries.setdefault(loc_id, []).extend(pts)

    if 'G7M' in countries and 'G-7' not in countries:
        countries['G-7'] = countries.pop('G7M')

    if not countries:
        raise ValueError('No country series parsed from SDMX')
    return countries


def try_oecd():
    for url in OECD_URLS:
        print(f'  Trying {url[:60]}...')
        try:
            raw      = fetch_json(url, BROWSER_HEADERS)
            countries = parse_sdmx(raw)
            analysed  = {loc: analyse(pts) for loc, pts in countries.items()}
            scored    = bool((analysed.get('USA') or {}).get('isBullish')) or \
                        bool((analysed.get('G-7') or {}).get('isBullish'))
            usa_date  = (analysed.get('USA') or {}).get('latestDate', '?')
            print(f'  OECD success — USA latest: {usa_date}')
            return {'countries': analysed, 'scored': scored, 'source': 'OECD-SDMX'}
        except Exception as e:
            print(f'  Failed: {e}')
    return None


def try_fred(api_key):
    countries = {}
    for country, series_id in FRED_SERIES:
        url = (f'https://api.stlouisfed.org/fred/series/observations'
               f'?series_id={series_id}&api_key={api_key}&file_type=json'
               f'&sort_order=asc&observation_start=2004-01-01')
        try:
            data = fetch_json(url)
            pts  = [
                {'date': o['date'][:7], 'value': float(o['value'])}
                for o in data.get('observations', [])
                if o.get('value', '.') != '.'
            ]
            if pts:
                countries[country] = pts
                print(f'  FRED {country}: {len(pts)} points, latest {pts[-1]["date"]}')
        except Exception as e:
            print(f'  FRED {country} error: {e}')

    if not countries:
        raise ValueError('No FRED data returned')

    analysed = {loc: analyse(pts) for loc, pts in countries.items()}
    scored   = bool((analysed.get('USA') or {}).get('isBullish')) or \
               bool((analysed.get('G-7') or {}).get('isBullish'))
    usa_date = (analysed.get('USA') or {}).get('latestDate', '?')
    return {
        'countries': analysed, 'scored': scored,
        'source': f'FRED (data to ~{usa_date} — OECD API restricted)',
    }


# ── main ─────────────────────────────────────────────────────────────────────
result = None

print('Trying OECD SDMX...')
result = try_oecd()

if result is None and FRED_KEY:
    print('Falling back to FRED mirror...')
    try:
        result = try_fred(FRED_KEY)
    except Exception as e:
        print(f'FRED also failed: {e}')

if result is None:
    print('ERROR: all sources failed', file=sys.stderr)
    sys.exit(1)

result['fetchedAt'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, 'w') as f:
    json.dump(result, f, separators=(',', ':'))

print(f'Done — written to {OUTPUT}')
