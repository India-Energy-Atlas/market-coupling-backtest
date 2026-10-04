# Shadow uniform-price back-test for market coupling (ILLUSTRATIVE)

What would one uniform day-ahead price per 15-minute block have been if the bids on IEX, PXIL and HPX had been pooled and cleared together, and how far is it from what each exchange cleared? This code answers that for 1 January to 31 March 2026, under the assumptions below. **Every output is illustrative**: no exchange publishes its aggregate bid curves in a form held here, so the curves are built from a few published points.

Results page: https://www.energymap.in/market-coupling/backtest · Code: https://github.com/India-Energy-Atlas/market-coupling-backtest

## Run it

```
docker compose run --rm backtest
```

Writes `out/REPORT.md`, `out/summary.json`, `out/blocks.csv` (one row per block) and `out/days.csv`. Without Docker: `python3 backtest.py --data data --out out` (standard library only).

## Assumptions

1. Illustrative only. Not a forecast and not a reconstruction of any exchange's order book.
2. Window: DAM, 1 Jan to 31 Mar 2026, the months for which all three exchanges' daily figures are held (CERC Market Monitoring Cell monthly reports).
3. Curves. Each exchange's demand curve is a straight line from its total purchase bid at Rs 0 to its cleared volume at its clearing price, then to zero at the Rs 10,000/MWh ceiling (in a block that cleared at the ceiling, demand there is the cleared volume). Its supply curve runs from zero at Rs 0 to its cleared volume at its clearing price, then to its total sell bid at the ceiling. These reproduce each exchange's own clearing exactly; the shape away from the clearing point is assumed.
4. IEX: per-block purchase bid, sell bid, cleared volume and clearing price, All India, as published.
5. PXIL and HPX: only daily cleared volume and volume-weighted price are held. Each day's volume is spread over the 96 blocks in proportion to IEX's cleared volume; each block's price is IEX's block price scaled so the day's average equals the exchange's published daily price (capped at Rs 10,000); bids follow IEX's block bid-to-cleared ratios.
6. Market splitting: no transmission congestion data is used. IEX's 13 bid-area prices carry the constraints IEX saw; each area's coupled price is the coupled uniform price plus that area's IEX premium in the block, kept within Rs 0 to Rs 10,000.
7. Behaviour does not change: the same bids clear together, with no arbitrage or re-optimisation. Real coupling would change both.

## Data gaps

- No PXIL or HPX block-level bids, volumes or prices: daily figures only.
- No aggregate demand or supply curves for any exchange.
- No Market Monitoring Cell data after 31 March 2026 in the source, so the window stops there.
- PXIL cleared DAM volume on 46 of the 90 days and HPX on 4; on other days only IEX takes part.
- No corridor-level transmission congestion data: IEX's 13 area prices stand in for it.

## Data

`data/` is a snapshot written by `export_data.py` from the India Energy Atlas store (read only):

| File | Source |
|---|---|
| `iex_dam_blocks.csv.gz` | IEX DAM market snapshot, All India, per block (purchase bid, sell bid, MCV, MCP) |
| `iex_dam_area_prices.csv.gz` | IEX DAM area clearing prices, 13 bid areas, per block |
| `exchange_daily.csv` | CERC Market Monitoring Cell monthly reports: IEX, PXIL, HPX daily volume and price (each row carries its report URL) |

## Method in one paragraph

For each block, every exchange present is a pair of piecewise-linear curves through its own clearing point. The pooled demand and supply are the sums; the coupled price is where they meet (bisection to Rs 0.01/MWh between Rs 0 and the Rs 10,000 ceiling; if pooled demand still exceeds supply at the ceiling, the block clears at the ceiling). Area prices add IEX's observed area premiums. Results compare the coupled price with each exchange's actual price, block by block for IEX and as daily averages for PXIL and HPX.

## Licence

- Code: Apache License 2.0, see [LICENSE](LICENSE).
- Data in `data/`: public market data from IEX and CERC's Market Monitoring Cell, reproduced with attribution; their publishers' terms apply. See [NOTICE](NOTICE).
- Copyright 2026 India Energy Atlas (energymap.in).
