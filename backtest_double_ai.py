#!/usr/bin/env python3
"""
Double AI Super Trend Backtest
原Pine Script: PresentTrading - Double AI Super Trend Trading Strategy
回测 2 年 BTC 5分钟 K 线
"""

import numpy as np
import time
import os
import requests

# ===================== Config =====================
EXCHANGE = "okx"
SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"
YEARS = 2

ST_LEN, ST_FACTOR = 10, 4.0
ST_LEN2, ST_FACTOR2 = 5, 3.0
K, N_DATA = 3, 12
K2, N_DATA2 = 5, 20
KNN_PRICE_LEN, KNN_ST_LEN = 20, 80
KNN_PRICE_LEN2, KNN_ST_LEN2 = 40, 80
POSITION_SIZE = 0.10
COMMISSION = 0.001
SLIPPAGE = 0.001


def wma(s, l):
    w = np.arange(1, l + 1); r = np.full(len(s), np.nan)
    for i in range(l - 1, len(s)): r[i] = np.sum(s[i - l + 1:i + 1] * w) / np.sum(w)
    return r


def rma(s, l):
    a = 1 / l; r = np.full(len(s), np.nan); st = 0
    while st < len(s) and np.isnan(s[st]): st += 1
    if st + l > len(s): return r
    r[st + l - 1] = np.nanmean(s[st:st + l])
    for i in range(st + l, len(s)): v = s[i] if not np.isnan(s[i]) else r[i - 1]; r[i] = a * v + (1 - a) * r[i - 1]
    return r


def calc_atr(h, lo, c, l):
    tr = np.zeros(len(c)); tr[0] = h[0] - lo[0]
    for i in range(1, len(c)): tr[i] = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
    return rma(tr, l)


def fetch_ohlcv(exchange_id, symbol, timeframe, years=2):
    cache_file = f"backtest_cache_{exchange_id}_{symbol.replace('/', '_')}_{timeframe}.npz"
    if os.path.exists(cache_file):
        print(f"  Load from cache: {cache_file}")
        d = np.load(cache_file)
        if len(d['cl']) > 0: return d['dt'], d['o'], d['h'], d['l'], d['cl'], d['v']
        os.remove(cache_file)

    print(f"Fetching {years}yr {symbol} {timeframe} from {exchange_id}...")
    px = None
    for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
        v = os.environ.get(k)
        if v: px = {'http': v, 'https': v}; break

    now = int(time.time() * 1000); since = now - years * 365 * 24 * 60 * 60 * 1000
    all_c, errs = [], 0

    while since < now and errs < 5:
        try:
            if exchange_id == 'okx':
                sym = symbol.replace('/', '-')
                url = "https://www.okx.com/api/v5/market/history-candles"
                p = {'instId': sym + '-SWAP', 'bar': timeframe, 'after': str(since), 'limit': '300'}
                r = requests.get(url, params=p, proxies=px, timeout=15)
                if r.status_code != 200:
                    p['instId'] = sym
                    r = requests.get(url, params=p, proxies=px, timeout=15)
                data = r.json().get('data', []) if r.status_code == 200 else []
                batch = [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in data]
            elif exchange_id == 'binance':
                p = {'symbol': symbol.replace('/', ''), 'interval': timeframe, 'startTime': since, 'limit': 1000}
                r = requests.get("https://api.binance.com/api/v3/klines", params=p, proxies=px, timeout=15)
                data = r.json()
                batch = [[int(c[0]), float(c[2]), float(c[3]), float(c[4]), float(c[1]), float(c[5])]
                         for c in data] if isinstance(data, list) else []
            elif exchange_id == 'gate':
                url = f"https://api.gateio.ws/api/v4/spot/candlesticks/{symbol.replace('/', '_')}"
                r = requests.get(url, params={'interval': timeframe, 'from': since // 1000, 'limit': 1000}, proxies=px, timeout=15)
                data = r.json()
                batch = [[int(c[0]), float(c[2]), float(c[3]), float(c[4]), float(c[1]), float(c[5])]
                         for c in data] if isinstance(data, list) else []
            else:
                print(f"Unknown exchange: {exchange_id}"); return [],[],[],[],[],[]

            errs = 0
            if not batch: break
            all_c.extend(batch)
            since = max(c[0] for c in batch) + 1
            print(f"  {len(all_c):7d}", end='\r')
            time.sleep(0.3)
        except Exception as e:
            errs += 1; print(f"\n  [{errs}] {str(e)[:80]}"); time.sleep(3)

    print(f"\nTotal: {len(all_c)} candles")
    if not all_c: return np.array([]), np.array([]), np.array([]), np.array([]), np.array([]), np.array([])

    all_c.sort(key=lambda x: x[0])
    seen = set(); u = [c for c in all_c if not (c[0] in seen or seen.add(c[0]))]
    dt = np.array([c[0] for c in u]); o = np.array([c[1] for c in u], dtype=float)
    h = np.array([c[2] for c in u], dtype=float); l = np.array([c[3] for c in u], dtype=float)
    cl = np.array([c[4] for c in u], dtype=float); v = np.array([c[5] for c in u], dtype=float)
    np.savez_compressed(cache_file, dt=dt, o=o, h=h, l=l, cl=cl, v=v)
    print(f"  Cached: {cache_file}")
    return dt, o, h, l, cl, v


def run_backtest(opens, highs, lows, closes, volume):
    n = len(closes)
    print(f"Indicators ({n} candles)...")

    vw = wma(closes * volume, ST_LEN) / wma(volume, ST_LEN)
    vw2 = wma(closes * volume, ST_LEN2) / wma(volume, ST_LEN2)
    atr1 = calc_atr(highs, lows, closes, ST_LEN)
    atr2 = calc_atr(highs, lows, closes, ST_LEN2)

    ub1 = np.full(n, np.nan); lb1 = np.full(n, np.nan); dr1 = np.full(n, 0); sp1 = np.full(n, np.nan)
    ub2 = np.full(n, np.nan); lb2 = np.full(n, np.nan); dr2 = np.full(n, 0); sp2 = np.full(n, np.nan)

    for i in range(max(ST_LEN, ST_LEN2), n):
        for uu, ll, ubb, lbb, drr, spp, pu, pl, ps in [
            (vw[i] + ST_FACTOR * atr1[i], vw[i] - ST_FACTOR * atr1[i], ub1, lb1, dr1, sp1, ub1[i - 1], lb1[i - 1], sp1[i - 1]),
            (vw2[i] + ST_FACTOR2 * atr2[i], vw2[i] - ST_FACTOR2 * atr2[i], ub2, lb2, dr2, sp2, ub2[i - 1], lb2[i - 1], sp2[i - 1])]:
            if np.isnan(pu): ubb[i] = uu; lbb[i] = ll
            else: ubb[i] = min(uu, pu) if closes[i - 1] <= pu else uu; lbb[i] = max(ll, pl) if closes[i - 1] >= pl else ll
            if np.isnan(pu): drr[i] = 1
            elif ps == pu: drr[i] = -1 if closes[i] > ubb[i] else 1
            else: drr[i] = 1 if closes[i] < lbb[i] else -1
            spp[i] = lbb[i] if drr[i] == -1 else ubb[i]

    print("  SuperTrend done")

    pw = wma(closes, KNN_PRICE_LEN); sw = wma(sp1, KNN_ST_LEN)
    pw2 = wma(closes, KNN_PRICE_LEN2); sw2 = wma(sp2, KNN_ST_LEN2)
    lp = np.full(n, 0.5); lp2 = np.full(n, 0.5)
    bs = max(KNN_PRICE_LEN, KNN_ST_LEN, N_DATA) * 3

    for i in range(bs, n):
        if np.isnan(sp1[i]) or np.isnan(sp2[i]): continue
        for pp, ss, sp_arr, kk, n_len, lp_arr in [
            (pw, sw, sp1, K, N_DATA, lp), (pw2, sw2, sp2, K2, N_DATA2, lp2)]:
            if np.isnan(pp[i]) or np.isnan(ss[i]): continue
            te = i - 1; ts = min(n_len, te - bs + 1)
            if ts < kk: continue
            t0 = te - ts + 1
            d = sp_arr[t0:te + 1]; labs = (pp[t0:te + 1] > ss[t0:te + 1]).astype(float)
            vld = ~np.isnan(d) & ~np.isnan(labs)
            if np.sum(vld) < kk: continue
            dists = np.abs(d[vld] - sp_arr[i]); idx = np.argsort(dists)[:kk]
            ws = 0; tw = 0
            for j in idx: w_ = 1.0 / (dists[j] + 1e-6); ws += w_ * labs[vld][j]; tw += w_
            lp_arr[i] = ws / tw if tw > 0 else 0.5
        if i % 50000 == 0: print(f"  KNN: {i}/{n}", end='\r')

    print("\n  KNN done")

    pos = 0; ep = 0; ts_price = 0; hold = 0
    trade_pnls = []; trade_hold = []; signal_bars = 0

    for i in range(bs, n):
        px = closes[i]
        if np.isnan(dr1[i]) or np.isnan(lp[i]) or np.isnan(dr2[i]) or np.isnan(lp2[i]): continue
        st1_l = dr1[i] == -1; st1_s = dr1[i] == 1
        st2_l = dr2[i] == -1; st2_s = dr2[i] == 1
        a1_b = lp[i] >= 0.7; a1_be = lp[i] <= 0.3
        a2_b = lp2[i] >= 0.7; a2_be = lp2[i] <= 0.3
        lc = st1_l and st2_l and a1_b and a2_b
        sc = st1_s and st2_s and a1_be and a2_be
        if lc or sc: signal_bars += 1

        if pos == 1 and not np.isnan(sp1[i]):
            nts = sp1[i] - ST_FACTOR * atr1[i]; ts_price = max(ts_price, nts) if ts_price > 0 else nts
        if pos == -1 and not np.isnan(sp1[i]):
            nts = sp1[i] + ST_FACTOR * atr1[i]; ts_price = min(ts_price, nts) if ts_price < 1e8 else nts

        le = st1_l and a1_b and st2_l and a2_b
        se = st1_s and a1_be and st2_s and a2_be
        close_now = (pos == 1 and ts_price > 0 and px <= ts_price) or \
                    (pos == 1 and not le) or \
                    (pos == -1 and ts_price > 0 and px >= ts_price) or \
                    (pos == -1 and not se)

        if close_now and pos != 0:
            slip = -1 if pos == 1 else 1
            ex_px = px * (1 + slip * SLIPPAGE)
            ppct = pos * (ex_px - ep) / ep if ep > 0 else 0
            trade_pnls.append(ppct * 100); trade_hold.append(hold)
            pos = 0; ep = 0; ts_price = 0; hold = 0

        if pos == 0 and (lc or sc):
            pos = 1 if lc else -1
            ep = px * (1 + SLIPPAGE if lc else 1 - SLIPPAGE)
            if not np.isnan(sp1[i]): ts_price = sp1[i] - ST_FACTOR * atr1[i] if pos == 1 else sp1[i] + ST_FACTOR * atr1[i]
            hold = 0
        if pos != 0: hold += 1

    if pos != 0:
        ppct = pos * (closes[-1] - ep) / ep if ep > 0 else 0
        trade_pnls.append(ppct * 100); trade_hold.append(hold)
    return trade_pnls, trade_hold, signal_bars


def print_results(pnls, holds, signal_bars):
    print(f"\n{'='*55}")
    print(f"  Double AI Super Trend - BTC {TIMEFRAME} ({YEARS} Years)")
    print(f"{'='*55}")
    if not pnls: print("  No trades"); return

    pnls_a = np.array(pnls); wins = pnls_a[pnls_a > 0]; losses = pnls_a[pnls_a < 0]
    eq = 1.0; rets = []
    for p in pnls:
        r = (p / 100) * POSITION_SIZE - COMMISSION * 2 * POSITION_SIZE
        eq *= (1 + r); rets.append(r)
    total_ret = (eq - 1) * 100; ret_a = np.array(rets)

    ec = [1.0]
    for r in rets: ec.append(ec[-1] * (1 + r))
    mdd = 0; pk = 1.0
    for e in ec: pk = max(e, pk); mdd = max(mdd, (pk - e) / pk * 100)

    shap = np.mean(ret_a) / np.std(ret_a) * np.sqrt(365 * 288) if np.std(ret_a) > 0 else 0
    ah = np.mean(holds) * 5 if holds else 0

    print(f"  Total Return: {total_ret:+.2f}%")
    print(f"  Max Drawdown: {mdd:.1f}%")
    print(f"  Sharpe:       {shap:.2f}")
    print(f"  Trades:       {len(pnls)}")
    print(f"  W/L:          {len(wins)}/{len(losses)} ({len(wins)/len(pnls)*100:.1f}%)")
    print(f"  Avg Win:      {np.mean(wins):+.2f}%")
    print(f"  Avg Loss:     {np.mean(losses):+.2f}%")
    print(f"  Best/Worst:   {np.max(wins):+.2f}% / {np.min(losses):.2f}%")
    print(f"  Avg Hold:     {ah:.0f}m ({ah/60:.1f}h)")
    print(f"  Signal Bars:  {signal_bars}")
    print(f"{'='*55}")


if __name__ == "__main__":
    ts = time.time()
    print("=" * 55)
    print(f"  Double AI Super Trend Backtest")
    print(f"  {EXCHANGE} | {SYMBOL} | {TIMEFRAME} | {YEARS}yr")
    print("=" * 55)

    ts, o, h, l, c, v = fetch_ohlcv(EXCHANGE, SYMBOL, TIMEFRAME, YEARS)
    if len(c) == 0: print("No data!"); exit(1)
    print(f"  {time.strftime('%Y-%m-%d', time.gmtime(ts[0]/1000))} ~ {time.strftime('%Y-%m-%d', time.gmtime(ts[-1]/1000))}")
    print(f"  ${c[0]:.0f} ~ ${c[-1]:.0f}")

    pnls, holds, sigs = run_backtest(o, h, l, c, v)
    print_results(pnls, holds, sigs)

    t = time.time() - ts
    print(f"\nDone in {int(t//60)}m {int(t%60)}s")
