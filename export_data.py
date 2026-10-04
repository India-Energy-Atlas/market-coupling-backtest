#!/usr/bin/env python3
"""Write the back-test's input snapshot from the India Energy Atlas database (read only).

Not needed to reproduce the back-test: the snapshot it writes is committed in
data/. Kept so the snapshot's provenance is code, not a claim.

  python export_data.py --dsn "$DATABASE_URL" --from 2026-01-01 --to 2026-03-31

Sources (all public market data, as stored by the Atlas):
  * IEX DAM, All India, per 15-minute block: purchase bid, sell bid, cleared
    volume (MW) and clearing price (atlas_intelligence.iex_market_data).
  * IEX DAM area clearing prices for the 13 bid areas (iex_area_prices).
  * IEX, PXIL and HPX daily volume and volume-weighted price, DAM and RTM, from
    CERC's Market Monitoring Cell monthly reports (exchange_daily_stats).
"""

from __future__ import annotations

import argparse
import csv
import gzip
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--from", dest="first", type=date.fromisoformat, required=True)
    ap.add_argument("--to", dest="last", type=date.fromisoformat, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    args = ap.parse_args()
    import psycopg

    start = datetime.combine(args.first, time(0), tzinfo=IST)
    end = datetime.combine(args.last + timedelta(days=1), time(0), tzinfo=IST)
    args.out.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(args.dsn) as conn:
        conn.execute("SET default_transaction_read_only = on")
        blocks = conn.execute("""
            SELECT timestamp, avg(purchase_bid_mw), avg(sell_bid_mw), avg(mcv_mw), avg(mcp_rs_mwh)
              FROM atlas_intelligence.iex_market_data
             WHERE market_type = 'DAM' AND region IN ('All India', 'ALL_INDIA')
               AND timestamp >= %s AND timestamp < %s
             GROUP BY timestamp ORDER BY timestamp""", (start, end)).fetchall()
        areas = conn.execute("""
            SELECT timestamp, area, avg(mcp_rs_mwh) FROM atlas_intelligence.iex_area_prices
             WHERE timestamp >= %s AND timestamp < %s GROUP BY 1, 2 ORDER BY 1, 2""", (start, end)).fetchall()
        daily = conn.execute("""
            SELECT trade_date, exchange, market, volume_mu, wavg_price_rs_mwh, source_url
              FROM atlas_intelligence.exchange_daily_stats
             WHERE trade_date BETWEEN %s AND %s ORDER BY 1, 2, 3""", (args.first, args.last)).fetchall()

    def ist(ts: datetime) -> tuple[str, int]:
        local = ts.astimezone(IST)
        return local.date().isoformat(), local.hour * 4 + local.minute // 15 + 1

    with gzip.open(args.out / "iex_dam_blocks.csv.gz", "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "block", "purchase_bid_mw", "sell_bid_mw", "mcv_mw", "mcp_rs_mwh"])
        for ts, pb, sb, v, p in blocks:
            w.writerow([*ist(ts), round(pb, 2), round(sb, 2), round(v, 2), round(p, 2)])
    with gzip.open(args.out / "iex_dam_area_prices.csv.gz", "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "block", "area", "mcp_rs_mwh"])
        for ts, area, p in areas:
            w.writerow([*ist(ts), area, round(p, 2)])
    with open(args.out / "exchange_daily.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "exchange", "market", "volume_mu", "wavg_price_rs_mwh", "source_url"])
        for d, x, m, v, p, url in daily:
            w.writerow([d.isoformat(), x, m, v, p, url])
    print(f"{len(blocks)} IEX blocks, {len(areas)} area prices, {len(daily)} exchange-days -> {args.out}")


if __name__ == "__main__":
    main()
