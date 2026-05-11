import { toMap, rolling200Array, rollingArray, withCache, yf, yfetch } from './_shared.js';

export const onRequestGet = async (ctx) => {
  return withCache(ctx, 'breadth-v3', 21600, async () => {
    const [spyData, rspData] = await Promise.all([
      yfetch(yf('SPY', '1d', '2y')),
      yfetch(yf('RSP', '1d', '2y')),
    ]);
    const spyResult = spyData?.chart?.result?.[0];
    const rspResult = rspData?.chart?.result?.[0];
    if (!spyResult || !rspResult) return { error: 'Yahoo Finance data unavailable', prices: [], adLine: [] };

    const spyMap = toMap(spyResult);
    const rspMap = toMap(rspResult);
    const dates  = [...spyMap.keys()].filter(d => rspMap.has(d)).sort();

    const priceValues = dates.map(d => spyMap.get(d));
    const priceSma    = rolling200Array(priceValues);
    const priceSma50  = rollingArray(priceValues, 50);
    const currentPrice    = priceValues[priceValues.length - 1];
    const currentPriceSma = priceSma[priceSma.length - 1];
    const priceHealth = currentPriceSma != null && currentPrice > currentPriceSma ? 'Bullish' : 'Bearish';

    const ratioValues = dates.map(d => rspMap.get(d) / spyMap.get(d));
    const ratioSma    = rolling200Array(ratioValues);
    const ratioSma50  = rollingArray(ratioValues, 50);
    const currentAdValue = ratioValues[ratioValues.length - 1];
    const currentAdSma   = ratioSma[ratioSma.length - 1];
    const internalHealth = currentAdSma != null && currentAdValue > currentAdSma ? 'Strong' : 'Weak';

    let interpretation, interpretationColor;
    if      (priceHealth === 'Bullish' && internalHealth === 'Strong') { interpretation = 'Confirmatory — broad participation. Safest time to be long.';    interpretationColor = 'green'; }
    else if (priceHealth === 'Bullish' && internalHealth === 'Weak')   { interpretation = 'Divergent — generals leading, soldiers retreating. High risk.';   interpretationColor = 'red';   }
    else if (priceHealth === 'Bearish' && internalHealth === 'Strong') { interpretation = 'Accumulation — price lagging but stocks rising under the hood.'; interpretationColor = 'amber'; }
    else                                                                { interpretation = 'Capitulation — maximum systemic weakness.';                      interpretationColor = 'red';   }

    return {
      priceHealth, internalHealth, isDivergent: priceHealth === 'Bullish' && internalHealth === 'Weak',
      interpretation, interpretationColor,
      adLine:       dates.map((d, i) => ({ date: d, value: Math.round(ratioValues[i] * 100000) / 100000 })),
      prices:       dates.map((d, i) => ({ date: d, value: priceValues[i] })),
      adLineSma200: dates.map((d, i) => ({ date: d, value: ratioSma[i] })),
      adLineSma50:  dates.map((d, i) => ({ date: d, value: ratioSma50[i] })),
      priceSma200:  dates.map((d, i) => ({ date: d, value: priceSma[i] })),
      priceSma50:   dates.map((d, i) => ({ date: d, value: priceSma50[i] })),
      currentPrice, currentAdValue,
      metrics: { lastPrice: currentPrice, lastAD: currentAdValue },
    };
  });
};
