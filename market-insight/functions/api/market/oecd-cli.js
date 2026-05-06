import { withCache, jsonResponse } from './_shared.js';

const FRED_CLI_SERIES = [
  ['USA', 'USALOLITONOSTSAM'],
  ['GBR', 'GBRLOLITONOSTSAM'],
  ['DEU', 'DEULOLITONOSTSAM'],
  ['JPN', 'JPNLOLITONOSTSAM'],
  ['G-7', 'G7LOLITONOSTSAM'],
];

function analyseCliSeries(series) {
  if (!series?.length) return null;
  const last = series[series.length - 1];
  const mo3  = series.slice(-4, -1);
  const trend    = mo3.length >= 3 ? (last.value > mo3[0].value ? 'rising' : 'falling') : 'unknown';
  const expanding = last.value > 100;
  const isBullish = expanding && trend === 'rising';
  const signal    = expanding && trend === 'rising' ? 'Expanding ↑'
                  : expanding                       ? 'Decelerating ↓'
                  : trend === 'rising'              ? 'Recovery ↑'
                  :                                   'Contraction ↓';
  const color     = isBullish ? 'green' : (!expanding && trend !== 'rising') ? 'red' : 'amber';
  return { series, latestDate: last.date, latest: last.value, trend, expanding, isBullish, signal, color };
}

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'oecd-cli', 3600, async () => {

    // ── 1. Static file committed daily by GitHub Actions ──────────────────
    // This is the primary source — always current, zero API latency.
    try {
      const origin = new URL(ctx.request.url).origin;
      const r = await fetch(`${origin}/data/oecd-cli.json`, { signal: AbortSignal.timeout(5000) });
      if (r.ok) {
        const data = await r.json();
        if (data?.countries && Object.keys(data.countries).length > 0) {
          return { ...data, _via: 'static-file' };
        }
      }
    } catch { /* static file not deployed yet — fall through */ }

    // ── 2. OECD SDMX direct (browser headers, two endpoints) ─────────────
    const OECD_URLS = [
      'https://data-api.oecd.org/v1/data/OECD.SDD.STES,DSD_STES@CLI,4.0/M.USA+GBR+DEU+JPN+G-7.LI.AA?startPeriod=2004-01&format=jsondata',
      'https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@CLI,4.0/M.USA+GBR+DEU+JPN+G-7.LI.AA?startPeriod=2004-01',
    ];
    const OECD_HEADERS = {
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      'Accept': 'application/vnd.sdmx.data+json;version=2.0, application/json',
      'Accept-Language': 'en-US,en;q=0.9',
      'Referer': 'https://data-explorer.oecd.org/',
      'Origin': 'https://data-explorer.oecd.org',
    };
    for (const url of OECD_URLS) {
      try {
        const r = await fetch(url, { headers: OECD_HEADERS, signal: AbortSignal.timeout(5000) });
        if (r.ok) {
          const raw = await r.json();
          const structure  = raw.data?.structure  ?? raw.structure;
          const datasetArr = raw.data?.dataSets   ?? raw.dataSets;
          if (structure && datasetArr?.length) {
            const seriesDims = structure.dimensions.series;
            const obsDims    = structure.dimensions.observation;
            const timePeriods = obsDims.find(d => d.id === 'TIME_PERIOD').values.map(v => v.id);
            const locDimIdx   = seriesDims.findIndex(d => d.id === 'REF_AREA' || d.id === 'LOCATION');
            const locValues   = seriesDims[locDimIdx].values;
            const countries   = {};
            for (const [key, s] of Object.entries(datasetArr[0].series)) {
              const locId = locValues[key.split(':').map(Number)[locDimIdx]]?.id ?? 'UNK';
              const pts   = Object.entries(s.observations ?? {})
                .map(([ti, arr]) => ({ date: timePeriods[Number(ti)], value: arr[0] }))
                .filter(p => p.value != null && !isNaN(p.value));
              pts.sort((a, b) => a.date.localeCompare(b.date));
              if (!countries[locId]) countries[locId] = [];
              countries[locId].push(...pts);
            }
            if (Object.keys(countries).length > 0) {
              if (countries['G7M'] && !countries['G-7']) { countries['G-7'] = countries['G7M']; delete countries['G7M']; }
              const analysed = {};
              for (const [loc, pts] of Object.entries(countries)) analysed[loc] = analyseCliSeries(pts);
              const scored = (analysed['USA']?.isBullish ?? false) || (analysed['G-7']?.isBullish ?? false);
              return { countries: analysed, scored, source: 'OECD-SDMX' };
            }
          }
        }
      } catch { /* try next */ }
    }

    // ── 3. FRED mirror (lagged ~early 2024) ───────────────────────────────
    const fredKey = ctx.env.FRED_API_KEY;
    if (!fredKey) return { countries: null, scored: false, error: 'No CLI data available' };

    const fetches = FRED_CLI_SERIES.map(([country, seriesId]) =>
      fetch(`https://api.stlouisfed.org/fred/series/observations?series_id=${seriesId}&api_key=${fredKey}&file_type=json&sort_order=asc&observation_start=2004-01-01`,
        { signal: AbortSignal.timeout(10000) })
        .then(r => r.ok ? r.json() : null)
        .then(body => ({ country, obs: body?.observations ?? null }))
        .catch(() => ({ country, obs: null }))
    );
    const results  = await Promise.all(fetches);
    const countries = {};
    for (const { country, obs } of results) {
      if (!obs?.length) continue;
      const pts = obs
        .map(o => ({ date: o.date.slice(0, 7), value: parseFloat(o.value) }))
        .filter(p => !isNaN(p.value));
      if (pts.length) countries[country] = pts;
    }

    if (!Object.keys(countries).length) return { countries: null, scored: false, error: 'No CLI data available' };

    const analysed = {};
    for (const [loc, pts] of Object.entries(countries)) analysed[loc] = analyseCliSeries(pts);
    const scored = (analysed['USA']?.isBullish ?? false) || (analysed['G-7']?.isBullish ?? false);
    const usaLatest = analysed['USA']?.latestDate ?? '?';
    return { countries: analysed, scored, source: `FRED (data to ~${usaLatest} — OECD API restricted)` };
  });
};
