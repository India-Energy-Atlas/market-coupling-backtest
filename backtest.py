#!/usr/bin/env python3
"""ILLUSTRATIVE shadow uniform-price back-test for Indian power-exchange market coupling.

Question: if IEX, PXIL and HPX day-ahead (DAM) bids had been pooled and cleared
together at one uniform price per 15-minute block, what would that price have
been, and how far is it from what each exchange actually cleared?

This is an illustration under stated assumptions, not a reconstruction. None
of the exchanges publishes its aggregate buy and sell curves in a form the
Atlas holds, so every curve here is built from a few published points. See
ASSUMPTIONS below; the same list heads every report this writes.

Run:  python backtest.py --data data --out out
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Iterable

CAP = 10_000.0           # CERC price ceiling for DAM since 3 Apr 2023, Rs/MWh
FLOOR = 0.0
BLOCK_H = 0.25           # hours per block
VERSION = "v1"

ASSUMPTIONS = [
    "ILLUSTRATIVE ONLY. Not a forecast, not a reconstruction of any exchange's order book.",
    "Window: IEX, PXIL and HPX DAM, 1 Jan to 31 Mar 2026, the months for which the Atlas holds all three "
    "exchanges' daily figures (CERC Market Monitoring Cell monthly reports).",
    "Aggregate bid curves are not published in a form the Atlas holds, for any exchange. Each exchange's "
    "demand curve is a straight line from its total purchase bid at Rs 0 to its cleared volume at its clearing "
    "price, then to zero at the Rs 10,000/MWh ceiling; its supply curve runs from zero at Rs 0 to its cleared "
    "volume at its clearing price, then to its total sell bid at the ceiling. In a block that cleared at the "
    "ceiling, demand at the ceiling is the cleared volume. These curves reproduce each exchange's own clearing "
    "exactly; their shape away from the clearing point is assumed.",
    "IEX: per-block purchase bid, sell bid, cleared volume and clearing price (All India), as published.",
    "PXIL and HPX: only daily cleared volume and volume-weighted price are held. Each day's volume is spread over "
    "the 96 blocks in proportion to IEX's cleared volume; each block's price is IEX's block price scaled so the "
    "day's volume-weighted average equals the exchange's published daily price; bids are set at IEX's block "
    "bid-to-cleared ratios.",
    "Market splitting: no transmission congestion data is used. IEX's own area prices for its 13 bid areas carry "
    "the transmission constraints IEX saw; each area's coupled price is the coupled uniform price plus that "
    "area's IEX premium over the IEX All India price in the block, kept within Rs 0 to Rs 10,000.",
    "No cross-exchange arbitrage, bid re-optimisation or change in participation is modelled: the same bids clear "
    "together. Real coupling would change behaviour.",
]

DATA_GAPS = [
    "No PXIL or HPX block-level bids, volumes or prices: daily figures only (see the shaping rule above).",
    "No aggregate demand or supply curves for any exchange: the curve shape is assumed.",
    "No CERC Market Monitoring Cell daily data after 31 Mar 2026 in the Atlas, so the window stops there.",
    "No corridor-level transmission congestion data: IEX's 13 area prices stand in for it.",
]


# ── Curves ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Book:
    """One exchange in one block: what it published (or what was shaped for it)."""
    exchange: str
    purchase_bid_mw: float
    sell_bid_mw: float
    cleared_mw: float
    price: float

    def demand(self, p: float) -> float:
        """MW bought at price p: (0, PB) -> (P, V) -> (CAP, V if capped else 0)."""
        pb, v, pc = max(self.purchase_bid_mw, self.cleared_mw), self.cleared_mw, self.price
        at_cap = v if pc >= CAP else 0.0
        if p <= pc:
            return pb if pc <= 0 else pb + (v - pb) * p / pc
        return v if pc >= CAP else v + (at_cap - v) * (p - pc) / (CAP - pc)

    def supply(self, p: float) -> float:
        """MW sold at price p: (0, 0 or V) -> (P, V) -> (CAP, SB)."""
        sb, v, pc = max(self.sell_bid_mw, self.cleared_mw), self.cleared_mw, self.price
        if p <= pc:
            return v if pc <= 0 else v * p / pc
        return v if pc >= CAP else v + (sb - v) * (p - pc) / (CAP - pc)


def clear(books: Iterable[Book], tol: float = 0.01) -> tuple[float, float]:
    """Uniform price and volume where pooled demand meets pooled supply."""
    books = list(books)
    excess = lambda p: sum(b.demand(p) for b in books) - sum(b.supply(p) for b in books)  # noqa: E731
    if excess(CAP) >= 0:
        return CAP, sum(b.supply(CAP) for b in books)
    if excess(FLOOR) <= 0:
        return FLOOR, sum(b.demand(FLOOR) for b in books)
    lo, hi = FLOOR, CAP
    while hi - lo > tol:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if excess(mid) > 0 else (lo, mid)
    p = (lo + hi) / 2
    return p, sum(b.supply(p) for b in books)


# ── Data ────────────────────────────────────────────────────────────────────


def _open(path: Path):
    return gzip.open(path, "rt", newline="") if path.suffix == ".gz" else open(path, newline="")


def load(data: Path):
    iex: dict[tuple[str, int], Book] = {}
    with _open(data / "iex_dam_blocks.csv.gz") as f:
        for r in csv.DictReader(f):
            iex[(r["date"], int(r["block"]))] = Book("IEX", float(r["purchase_bid_mw"]), float(r["sell_bid_mw"]),
                                                     float(r["mcv_mw"]), float(r["mcp_rs_mwh"]))
    areas: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    with _open(data / "iex_dam_area_prices.csv.gz") as f:
        for r in csv.DictReader(f):
            areas[(r["date"], int(r["block"]))][r["area"]] = float(r["mcp_rs_mwh"])
    daily: dict[tuple[str, str], tuple[float, float]] = {}
    with _open(data / "exchange_daily.csv") as f:
        for r in csv.DictReader(f):
            # A day an exchange cleared nothing has no price: it simply does not take part.
            if r["market"] == "DAM" and r["volume_mu"] and r["wavg_price_rs_mwh"] and float(r["volume_mu"]) > 0:
                daily[(r["date"], r["exchange"])] = (float(r["volume_mu"]), float(r["wavg_price_rs_mwh"]))
    return iex, areas, daily


def shaped(exchange: str, day: str, iex_day: dict[int, Book], volume_mu: float, wavg: float) -> dict[int, Book]:
    """Spread a daily volume and price over the day's blocks on IEX's shape (ASSUMPTIONS 5)."""
    total_v = sum(b.cleared_mw for b in iex_day.values())
    iex_wavg = sum(b.cleared_mw * b.price for b in iex_day.values()) / total_v if total_v else 0.0
    scale = wavg / iex_wavg if iex_wavg else 1.0
    energy_mwh = volume_mu * 1000.0
    out = {}
    for blk, b in iex_day.items():
        v = energy_mwh * (b.cleared_mw / total_v) / BLOCK_H if total_v else 0.0
        ratio = v / b.cleared_mw if b.cleared_mw else 0.0
        out[blk] = Book(exchange, b.purchase_bid_mw * ratio, b.sell_bid_mw * ratio, v, min(CAP, b.price * scale))
    return out


# ── Back-test ───────────────────────────────────────────────────────────────


def run(data: Path) -> dict:
    iex, areas, daily = load(data)
    days = sorted({d for d, _ in iex})
    blocks_out, days_out = [], []
    for day in days:
        iex_day = {blk: b for (d, blk), b in iex.items() if d == day}
        books = {"IEX": iex_day}
        for x in ("PXIL", "HPX"):
            if (day, x) in daily and daily[(day, x)][0] > 0:
                books[x] = shaped(x, day, iex_day, *daily[(day, x)])
        day_rows = []
        for blk in sorted(iex_day):
            members = [books[x][blk] for x in books if blk in books[x]]
            p, v = clear(members)
            iex_b = iex_day[blk]
            premiums = {a: ap - iex_b.price for a, ap in areas.get((day, blk), {}).items()}
            split = {a: round(min(CAP, max(FLOOR, p + d)), 2) for a, d in premiums.items()}
            row = {"date": day, "block": blk, "coupled_price": round(p, 2), "coupled_mw": round(v, 1),
                   "iex_price": iex_b.price, "iex_mw": iex_b.cleared_mw,
                   "pooled_mw_own": round(sum(m.cleared_mw for m in members), 1),
                   "split": any(abs(d) > 0.5 for d in premiums.values()),
                   "area_min": min(split.values()) if split else None,
                   "area_max": max(split.values()) if split else None}
            for x in ("PXIL", "HPX"):
                row[f"{x.lower()}_price"] = round(books[x][blk].price, 2) if x in books else None
            day_rows.append(row)
        blocks_out += day_rows
        vol = sum(r["coupled_mw"] for r in day_rows)
        coupled_wavg = sum(r["coupled_price"] * r["coupled_mw"] for r in day_rows) / vol if vol else None
        drow = {"date": day, "coupled_wavg": round(coupled_wavg, 2) if coupled_wavg else None}
        iex_v = sum(b.cleared_mw for b in iex_day.values())
        drow["iex_wavg"] = round(sum(b.cleared_mw * b.price for b in iex_day.values()) / iex_v, 2) if iex_v else None
        for x in ("PXIL", "HPX"):
            drow[f"{x.lower()}_wavg"] = daily.get((day, x), (None, None))[1]
        days_out.append(drow)
    return {"blocks": blocks_out, "days": days_out, "summary": summarise(blocks_out, days_out)}


def summarise(blocks: list[dict], days: list[dict]) -> dict:
    d_iex = [r["coupled_price"] - r["iex_price"] for r in blocks]
    traded = {x: sum(1 for r in days if r[f"{x}_wavg"]) for x in ("pxil", "hpx")}
    out = {
        "version": VERSION,
        "days_traded": {"IEX": len(days), "PXIL": traded["pxil"], "HPX": traded["hpx"]},
        "window": {"from": days[0]["date"], "to": days[-1]["date"], "days": len(days), "blocks": len(blocks)},
        "blocks_coupled_at_cap": sum(1 for r in blocks if r["coupled_price"] >= CAP),
        "blocks_iex_at_cap": sum(1 for r in blocks if r["iex_price"] >= CAP),
        "blocks_split_on_iex": sum(1 for r in blocks if r["split"]),
        "coupled_minus_iex_block": {"mean": round(fmean(d_iex), 1), "mean_abs": round(fmean(abs(x) for x in d_iex), 1),
                                    "max_abs": round(max(abs(x) for x in d_iex), 1)},
    }
    for x in ("iex", "pxil", "hpx"):
        pairs = [(r["coupled_wavg"], r[f"{x}_wavg"]) for r in days if r["coupled_wavg"] and r[f"{x}_wavg"]]
        if pairs:
            diffs = [c - a for c, a in pairs]
            out[f"coupled_minus_{x}_daily_wavg"] = {"days": len(pairs), "mean": round(fmean(diffs), 1),
                                                     "mean_abs": round(fmean(abs(v) for v in diffs), 1)}
    return out


def write(result: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("blocks.csv", result["blocks"]), ("days.csv", result["days"])):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    s = result["summary"]
    gaps = DATA_GAPS + [f"In the window PXIL cleared DAM volume on {s['days_traded']['PXIL']} of {s['window']['days']} "
                        f"days and HPX on {s['days_traded']['HPX']}; on the other days only IEX takes part."]
    body = {"label": "ILLUSTRATIVE", "assumptions": ASSUMPTIONS, "data_gaps": gaps, **result["summary"],
            "days": result["days"]}
    (out / "summary.json").write_text(json.dumps(body, indent=1))
    lines = ["# Shadow uniform-price back-test (ILLUSTRATIVE)", "", "## Assumptions", ""]
    lines += [f"{i}. {a}" for i, a in enumerate(ASSUMPTIONS, 1)]
    lines += ["", "## Data gaps", ""] + [f"- {g}" for g in gaps]
    lines += ["", "## Results", "",
              f"Window {s['window']['from']} to {s['window']['to']}: {s['window']['days']} days, "
              f"{s['window']['blocks']} blocks.", "",
              f"- Coupled price minus IEX price, per block: mean {s['coupled_minus_iex_block']['mean']} Rs/MWh, "
              f"mean absolute {s['coupled_minus_iex_block']['mean_abs']} Rs/MWh.",
              f"- Blocks at the Rs 10,000 ceiling: IEX {s['blocks_iex_at_cap']}, coupled {s['blocks_coupled_at_cap']}.",
              f"- Blocks in which IEX split into areas: {s['blocks_split_on_iex']}."]
    for x in ("iex", "pxil", "hpx"):
        k = f"coupled_minus_{x}_daily_wavg"
        if k in s:
            lines.append(f"- Coupled daily average minus {x.upper()} daily average: mean {s[k]['mean']} Rs/MWh "
                         f"over {s[k]['days']} days (mean absolute {s[k]['mean_abs']}).")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=Path(__file__).resolve().parent / "data")
    ap.add_argument("--out", type=Path, default=Path("out"))
    args = ap.parse_args()
    result = run(args.data)
    write(result, args.out)
    print(json.dumps(result["summary"], indent=1))


if __name__ == "__main__":
    main()
