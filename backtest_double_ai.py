#!/usr/bin/env python3
"""
Double AI Super Trend Backtest
原Pine Script: PresentTrading - Double AI Super Trend Trading Strategy
回测 2 年 BTC 5分钟 K 线
"""

import ccxt
import numpy as np
import time
import os
import sys

# ===================== Config =====================
EXCHANGE = "okx"      # okx / gate / binance
SYMBOL = "BTC/USDT"
TIMEFRAME = "5m"
YEARS = 2
INITIAL_CAPITAL = 10000
POSITION_SIZE = 0.10   # 10% per trade
COMMISSION = 0.001     # 0.1%
SLIPPAGE = 0.001       # 0.1%

# SuperTrend params
ST_LEN, ST_FACTOR = 10, 4.0
ST_LEN2, ST_FACTOR2 = 5, 3.0

# KNN params
K, N_DATA = 3, 12
K2, N_DATA2 = 5, 20
KNN_PRICE_LEN, KNN_ST_LEN = 20, 80
KNN_PRICE_LEN2, KNN_ST_LEN2 = 40, 80


# ===================== Helpers =====================
def wma(series, length):
    w = np.arange(1, length + 1)
    result = np.full(len(series), np.nan)
    for i in range(length - 1, len(series)):
        result[i] = np.sum(series[i - length + 1:i + 1] * w) / np.sum(w)
    return result


def rma(series, length):
    alpha = 1 / length
    result = np.full(len(series), np.nan)
    st = 0
    while st < len(series) and np.isnan(series[st]):
        st += 1
    if st + length > len(series):
        return result
    result[st + length - 1] = np.nanmean(series[st:st + length])
    for i in range(st + length, len(series)):
        v = series[i] if not np.isnan(series[i]) else result[i - 1]
        result[i] = alpha * v + (1 - alpha) * result[i - 1]
    return result


def calc_atr(highs, lows, closes, length):
    tr = np.zeros(len(closes))
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return rma(tr, length)


# ===================== Fetch Data =====================
def fetch_ohlcv(exchange_id, symbol, timeframe, years=2):
    print(f"Connecting to {exchange_id}...")
    
    ex_class = getattr(ccxt, exchange_id)
    ex = ex_class({
        'enableRateLimit': True,
        'timeout': 15000,
    })
    
    # Check for cached data first
    cache_file = f"backtest_cache_{exchange_id}_{symbol.replace('/', '_')}_{timeframe}.npz"
    if os.path.exists(cache_file):
        print(f"  Loading cached data: {cache_file}")
        data = np.load(cache_file)
        return data['dt'], data['o'], data['h'], data['l'], data['cl'], data['v'], None
    
    # Calculate start time
    now = int(time.time() * 1000)
    since = now - years * 365 * 24 * 60 * 60 * 1000
    
    all_candles = []
    limit = 300  # smaller batches to avoid rate limits
    consecutive_errors = 0
    while since < now:
        try:
            ohlcv = ex.fetch_ohlcv(symbol, timeframe, since, limit)
            consecutive_errors = 0
            if not ohlcv:
                break
            all_candles.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            print(f"  Fetched {len(ohlcv)} candles, total: {len(all_candles)}", end='\r')
            time.sleep(0.3)
        except Exception as e:
            consecutive_errors += 1
            print(f"\n  Error ({consecutive_errors}): {str(e)[:80]}")
            if consecutive_errors >= 5:
                print("  Too many errors, stopping fetch")
                break
            time.sleep(3)
    
    print(f"\nTotal candles: {len(all_candles)}")
    
    # Deduplicate and sort
    seen = set()
    unique = []
    for c in all_candles:
        if c[0] not in seen:
            seen.add(c[0])
            unique.append(c)
    unique.sort(key=lambda x: x[0])
    
    dt = np.array([c[0] for c in unique])
    o = np.array([c[1] for c in unique], dtype=float)
    h = np.array([c[2] for c in unique], dtype=float)
    l = np.array([c[3] for c in unique], dtype=float)
    cl = np.array([c[4] for c in unique], dtype=float)
    v = np.array([c[5] for c in unique], dtype=float)
    
    # Save cache
    np.savez_compressed(cache_file, dt=dt, o=o, h=h, l=l, cl=cl, v=v)
    print(f"  Saved cache: {cache_file}")
    
    return dt, o, h, l, cl, v, ex


# ===================== Strategy =====================
def run_backtest(opens, highs, lows, closes, volume):
    n = len(closes)
    print(f"\nCalculating indicators ({n} candles)...")
    
    # Volume WMA
    vw = wma(closes * volume, ST_LEN) / wma(volume, ST_LEN)
    vw2 = wma(closes * volume, ST_LEN2) / wma(volume, ST_LEN2)
    
    # ATR
    atr1 = calc_atr(highs, lows, closes, ST_LEN)
    atr2 = calc_atr(highs, lows, closes, ST_LEN2)
    
    # SuperTrend
    ub1 = np.full(n, np.nan); lb1 = np.full(n, np.nan)
    dr1 = np.full(n, 0); sp1 = np.full(n, np.nan)
    ub2 = np.full(n, np.nan); lb2 = np.full(n, np.nan)
    dr2 = np.full(n, 0); sp2 = np.full(n, np.nan)
    
    for i in range(max(ST_LEN, ST_LEN2), n):
        u1 = vw[i] + ST_FACTOR * atr1[i]
        l1 = vw[i] - ST_FACTOR * atr1[i]
        u2 = vw2[i] + ST_FACTOR2 * atr2[i]
        l2 = vw2[i] - ST_FACTOR2 * atr2[i]
        
        for uu, ll, ubb, lbb, drr, spp, pu, pl, ps in [
            (u1, l1, ub1, lb1, dr1, sp1, ub1[i - 1], lb1[i - 1], sp1[i - 1]),
            (u2, l2, ub2, lb2, dr2, sp2, ub2[i - 1], lb2[i - 1], sp2[i - 1])
        ]:
            if np.isnan(pu):
                ubb[i] = uu
                lbb[i] = ll
            else:
                ubb[i] = min(uu, pu) if closes[i - 1] <= pu else uu
                lbb[i] = max(ll, pl) if closes[i - 1] >= pl else ll
            
            if np.isnan(pu):
                drr[i] = 1
            elif ps == pu:
                drr[i] = -1 if closes[i] > ubb[i] else 1
            else:
                drr[i] = 1 if closes[i] < lbb[i] else -1
            spp[i] = lbb[i] if drr[i] == -1 else ubb[i]
    
    print("  SuperTrend done")
    
    # KNN
    pw = wma(closes, KNN_PRICE_LEN)
    sw = wma(sp1, KNN_ST_LEN)
    pw2 = wma(closes, KNN_PRICE_LEN2)
    sw2 = wma(sp2, KNN_ST_LEN2)
    
    lp = np.full(n, 0.5)
    lp2 = np.full(n, 0.5)
    bs = max(KNN_PRICE_LEN, KNN_ST_LEN, N_DATA) * 3
    
    for i in range(bs, n):
        if np.isnan(sp1[i]) or np.isnan(sp2[i]):
            continue
        
        # KNN 1
        if not np.isnan(pw[i]) and not np.isnan(sw[i]):
            te = i - 1
            ts = min(N_DATA, te - bs + 1)
            if ts >= K:
                t0 = te - ts + 1
                d = sp1[t0:te + 1]
                labs = (pw[t0:te + 1] > sw[t0:te + 1]).astype(float)
                vld = ~np.isnan(d) & ~np.isnan(labs)
                if np.sum(vld) >= K:
                    dists = np.abs(d[vld] - sp1[i])
                    idx = np.argsort(dists)[:K]
                    ws = 0; tw = 0
                    for j in idx:
                        w_ = 1.0 / (dists[j] + 1e-6)
                        ws += w_ * labs[vld][j]
                        tw += w_
                    lp[i] = ws / tw if tw > 0 else 0.5
        
        # KNN 2
        if not np.isnan(pw2[i]) and not np.isnan(sw2[i]):
            te = i - 1
            ts = min(N_DATA2, te - bs + 1)
            if ts >= K2:
                t0 = te - ts + 1
                d = sp2[t0:te + 1]
                labs = (pw2[t0:te + 1] > sw2[t0:te + 1]).astype(float)
                vld = ~np.isnan(d) & ~np.isnan(labs)
                if np.sum(vld) >= K2:
                    dists = np.abs(d[vld] - sp2[i])
                    idx = np.argsort(dists)[:K2]
                    ws = 0; tw = 0
                    for j in idx:
                        w_ = 1.0 / (dists[j] + 1e-6)
                        ws += w_ * labs[vld][j]
                        tw += w_
                    lp2[i] = ws / tw if tw > 0 else 0.5
        
        if i % 50000 == 0:
            print(f"  KNN progress: {i}/{n}", end='\r')
    
    print("\n  KNN done")
    
    # ===================== Backtest =====================
    pos = 0
    ep = 0
    ts_price = 0
    trade_pnls = []
    trade_hold = []
    hold_bars = 0
    total_signal_bars = 0
    
    for i in range(bs, n):
        px = closes[i]
        
        if np.isnan(dr1[i]) or np.isnan(lp[i]) or np.isnan(dr2[i]) or np.isnan(lp2[i]):
            continue
        
        st1_l = dr1[i] == -1
        st1_s = dr1[i] == 1
        st2_l = dr2[i] == -1
        st2_s = dr2[i] == 1
        a1_b = lp[i] >= 0.7
        a1_be = lp[i] <= 0.3
        a2_b = lp2[i] >= 0.7
        a2_be = lp2[i] <= 0.3
        
        long_cond = st1_l and st2_l and a1_b and a2_b
        short_cond = st1_s and st2_s and a1_be and a2_be
        
        if long_cond or short_cond:
            total_signal_bars += 1
        
        # Trailing stop
        if pos == 1 and not np.isnan(sp1[i]):
            nts = sp1[i] - ST_FACTOR * atr1[i]
            ts_price = max(ts_price, nts) if ts_price > 0 else nts
        if pos == -1 and not np.isnan(sp1[i]):
            nts = sp1[i] + ST_FACTOR * atr1[i]
            ts_price = min(ts_price, nts) if ts_price < 1e8 else nts
        
        # Exit conditions
        long_exit = st1_l and a1_b and st2_l and a2_b
        short_exit = st1_s and a1_be and st2_s and a2_be
        
        should_close = False
        if pos == 1 and ts_price > 0 and px <= ts_price:
            should_close = True
        elif pos == 1 and not long_exit:
            should_close = True
        elif pos == -1 and ts_price > 0 and px >= ts_price:
            should_close = True
        elif pos == -1 and not short_exit:
            should_close = True
        
        if should_close and pos != 0:
            slip_dir = -1 if pos == 1 else 1
            exit_px = px * (1 + slip_dir * SLIPPAGE)
            pnl_pct = pos * (exit_px - ep) / ep if ep > 0 else 0
            trade_pnls.append(pnl_pct * 100)
            trade_hold.append(hold_bars)
            pos = 0
            ep = 0
            ts_price = 0
            hold_bars = 0
        
        if pos == 0 and (long_cond or short_cond):
            pos = 1 if long_cond else -1
            ep = px * (1 + SLIPPAGE if long_cond else 1 - SLIPPAGE)
            if not np.isnan(sp1[i]):
                ts_price = sp1[i] - ST_FACTOR * atr1[i] if pos == 1 else sp1[i] + ST_FACTOR * atr1[i]
            hold_bars = 0
        
        if pos != 0:
            hold_bars += 1
    
    # Close final
    if pos != 0:
        pnl_pct = pos * (closes[-1] - ep) / ep if ep > 0 else 0
        trade_pnls.append(pnl_pct * 100)
        trade_hold.append(hold_bars)
    
    return trade_pnls, trade_hold, total_signal_bars


# ===================== Results =====================
def print_results(pnls, holds, total_signal_bars):
    print(f"\n{'='*55}")
    print(f"  Double AI Super Trend - BTC {TIMEFRAME} ({YEARS} Years)")
    print(f"{'='*55}")
    
    if not pnls:
        print("  No trades executed!")
        return
    
    pnls = np.array(pnls)
    holds = np.array(holds)
    
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    
    # Calculate cumulative return with proper compounding
    pos_size = POSITION_SIZE
    comm = COMMISSION
    
    eq = 1.0
    returns = []
    for p in pnls:
        trade_ret = (p / 100) * pos_size - comm * 2 * pos_size
        eq *= (1 + trade_ret)
        returns.append(trade_ret)
    
    total_ret = (eq - 1) * 100
    returns_arr = np.array(returns)
    
    # Max drawdown
    eq_curve = [1.0]
    for r in returns:
        eq_curve.append(eq_curve[-1] * (1 + r))
    
    mdd = 0
    peak = 1.0
    for e in eq_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > mdd:
            mdd = dd
    
    # Sharpe (annualized, assuming 5m bars, ~288 per day)
    if len(returns_arr) > 1 and np.std(returns_arr) > 0:
        sharpe = np.mean(returns_arr) / np.std(returns_arr) * np.sqrt(365 * 288) if np.std(returns_arr) > 0 else 0
    else:
        sharpe = 0
    
    avg_hold_mins = np.mean(holds) * 5 if holds.any() else 0
    
    print(f"  Total Return:    {total_ret:+.2f}%")
    print(f"  Max Drawdown:    {mdd:.1f}%")
    print(f"  Sharpe Ratio:    {sharpe:.2f}")
    print(f"  Total Trades:    {len(pnls)}")
    print(f"  Wins/Losses:     {len(wins)}/{len(losses)}")
    print(f"  Win Rate:        {len(wins)/len(pnls)*100:.1f}%")
    print(f"  Avg Win:         {np.mean(wins):+.2f}%")
    print(f"  Avg Loss:        {np.mean(losses):+.2f}%")
    print(f"  Best/Worst:       {np.max(wins):+.2f}% / {np.min(losses):.2f}%")
    print(f"  Avg Hold:        {avg_hold_mins:.0f} min ({avg_hold_mins/60:.1f}h)")
    print(f"  Total Signal Bars: {total_signal_bars}")
    print(f"{'='*55}")


# ===================== Main =====================
if __name__ == "__main__":
    start_time = time.time()
    
    print("=" * 55)
    print(f"  Double AI Super Trend Backtest")
    print(f"  {EXCHANGE} | {SYMBOL} | {TIMEFRAME} | {YEARS}年")
    print("=" * 55)
    
    timestamps, opens, highs, lows, closes, volume, ex = fetch_ohlcv(
        EXCHANGE, SYMBOL, TIMEFRAME, YEARS
    )
    
    print(f"  Data range: {time.strftime('%Y-%m-%d', time.gmtime(timestamps[0]/1000))} "
          f"~ {time.strftime('%Y-%m-%d', time.gmtime(timestamps[-1]/1000))}")
    print(f"  Price: ${closes[0]:.1f} ~ ${closes[-1]:.1f}")
    
    pnls, holds, signal_bars = run_backtest(opens, highs, lows, closes, volume)
    print_results(pnls, holds, signal_bars)
    
    elapsed = time.time() - start_time
    print(f"\nDone in {int(elapsed//60)}m {int(elapsed%60)}s")
