#!/usr/bin/env python3
"""
SuperFilter + StochSuperTrend 否决权回测
回测 1 年 BTC 5m 真实数据
"""
import numpy as np, time, os, requests

EXCHANGE = "okx"; SYMBOL = "BTC/USDT"; TIMEFRAME = "5m"; YEARS = 1

def fetch_data():
    cache = f"sf_stochst_cache.npz"
    if os.path.exists(cache):
        d = np.load(cache)
        if len(d['c']) > 0: return d['c'], d['h'], d['l'], d['v']
    
    px = None
    for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY']:
        v = os.environ.get(k)
        if v: px = {'http':v,'https':v}; break
    
    now = int(time.time()*1000); since = now - YEARS*365*24*60*60*1000
    all_c, errs = [], 0
    while since < now and errs < 5:
        try:
            if EXCHANGE == 'okx':
                sym = SYMBOL.replace('/','-')
                p = {'instId':sym+'-SWAP','bar':TIMEFRAME,'after':str(since),'limit':'300'}
                r = requests.get("https://www.okx.com/api/v5/market/history-candles",params=p,proxies=px,timeout=15)
                if r.status_code != 200:
                    p['instId'] = sym
                    r = requests.get("https://www.okx.com/api/v5/market/history-candles",params=p,proxies=px,timeout=15)
                data = r.json().get('data',[]) if r.status_code==200 else []
                batch = [[int(c[0]),float(c[2]),float(c[3]),float(c[4]),float(c[1]),float(c[5])] for c in data]
            elif EXCHANGE == 'binance':
                p = {'symbol':SYMBOL.replace('/',''),'interval':TIMEFRAME,'startTime':since,'limit':1000}
                r = requests.get("https://api.binance.com/api/v3/klines",params=p,proxies=px,timeout=15)
                data = r.json()
                batch = [[int(c[0]),float(c[2]),float(c[3]),float(c[4]),float(c[1]),float(c[5])] for c in data] if isinstance(data,list) else []
            errs = 0
            if not batch: break
            all_c.extend(batch)
            since = max(c[0] for c in batch)+1
            print(f"  {len(all_c)}", end='\r')
            time.sleep(0.3)
        except Exception as e:
            errs += 1; print(f"\n  [{errs}] {str(e)[:80]}"); time.sleep(3)
    
    print(f"\nTotal: {len(all_c)}")
    if not all_c: return None,None,None,None
    all_c.sort(key=lambda x:x[0])
    seen=set(); u=[c for c in all_c if not (c[0] in seen or seen.add(c[0]))]
    c=np.array([x[4] for x in u],dtype=float); h=np.array([x[1] for x in u],dtype=float)
    l=np.array([x[2] for x in u],dtype=float); v=np.array([x[5] for x in u],dtype=float)
    np.savez_compressed(cache,c=c,h=h,l=l,v=v)
    return c,h,l,v

def wma(s,l):
    w=np.arange(1,l+1); r=np.full(len(s),np.nan)
    for i in range(l-1,len(s)): r[i]=np.sum(s[i-l+1:i+1]*w)/np.sum(w)
    return r

def rma(s,l):
    a=1/l; r=np.full(len(s),np.nan); st=0
    while st<len(s) and np.isnan(s[st]): st+=1
    if st+l>len(s): return r
    r[st+l-1]=np.nanmean(s[st:st+l])
    for i in range(st+l,len(s)): vv=s[i] if not np.isnan(s[i]) else r[i-1]; r[i]=a*vv+(1-a)*r[i-1]
    return r

def run(c,h,l,v):
    n=len(c)
    print(f"Indicators ({n})...")
    
    SL,SF,S2,F2=10,4.0,5,3.0
    vw=wma(c*v,SL)/wma(v,SL); vw2=wma(c*v,S2)/wma(v,S2)
    a1=rma(np.maximum(h-l,np.maximum(abs(h-np.roll(c,1)),abs(l-np.roll(c,1)))),SL)
    a2=rma(np.maximum(h-l,np.maximum(abs(h-np.roll(c,1)),abs(l-np.roll(c,1)))),S2)
    a1[0]=h[0]-l[0]; a2[0]=h[0]-l[0]
    ub1=np.full(n,np.nan);lb1=np.full(n,np.nan);dr1=np.full(n,0);st1=np.full(n,np.nan)
    ub2=np.full(n,np.nan);lb2=np.full(n,np.nan);dr2=np.full(n,0);st2=np.full(n,np.nan)
    for i in range(max(SL,S2),n):
        for uu,ll,ubb,lbb,drr,spp,pu,pl,ps in [
            (vw[i]+SF*a1[i],vw[i]-SF*a1[i],ub1,lb1,dr1,st1,ub1[i-1],lb1[i-1],st1[i-1]),
            (vw2[i]+F2*a2[i],vw2[i]-F2*a2[i],ub2,lb2,dr2,st2,ub2[i-1],lb2[i-1],st2[i-1])]:
            if np.isnan(pu): ubb[i]=uu; lbb[i]=ll
            else: ubb[i]=min(uu,pu) if c[i-1]<=pu else uu; lbb[i]=max(ll,pl) if c[i-1]>=pl else ll
            if np.isnan(pu): drr[i]=1
            elif ps==pu: drr[i]=-1 if c[i]>ubb[i] else 1
            else: drr[i]=1 if c[i]<lbb[i] else -1
            spp[i]=lbb[i] if drr[i]==-1 else ubb[i]
    
    sf_l=(dr1==-1)&(dr2==-1); sf_s=(dr1==1)&(dr2==1)
    
    up=rma(np.maximum(np.diff(c,prepend=c[0]),0),14)
    dn=rma(-np.minimum(np.diff(c,prepend=c[0]),0),14)
    rsi=np.where((up+dn)>0,100-100/(1+up/dn),50); rsi[0]=50
    k=np.full(n,50.0)
    for i in range(14-1+3,n):
        hh=np.max(rsi[i-14+1:i+1]); ll=np.min(rsi[i-14+1:i+1])
        k[i]=100*(rsi[i]-ll)/(hh-ll) if hh>ll else 50
    
    us=np.full(n,np.nan); ls=np.full(n,np.nan); d=np.full(n,0); ts=np.full(n,np.nan)
    for i in range(60,n):
        u=k[i]+10; lv=k[i]-10
        if np.isnan(us[i-1]): us[i]=u; ls[i]=lv
        else: us[i]=min(u,us[i-1]) if k[i-1]>us[i-1] else u; ls[i]=max(lv,ls[i-1]) if k[i-1]<ls[i-1] else lv
        if np.isnan(us[i-1]): d[i]=1
        elif np.isnan(ts[i-1]): d[i]=1
        elif ts[i-1]==us[i-1]: d[i]=-1 if k[i]>us[i] else 1
        else: d[i]=1 if k[i]<ls[i] else -1
        ts[i]=ls[i] if d[i]==-1 else us[i]
    
    print("Indicators done")
    
    def bt(label, vlong=None, vshort=None):
        pos=0;ep=0;tp=[];last_close=-99
        for i in range(60,n):
            px=c[i]
            can=(i-last_close)>=3
            ls=sf_l[i] and can; ss=sf_s[i] and can
            if vlong is not None and vlong[i]: ls=False
            if vshort is not None and vshort[i]: ss=False
            if pos==0:
                if ls: pos=1; ep=px*1.001
                elif ss: pos=-1; ep=px*0.999
            else:
                ex=(pos==1 and sf_s[i]) or (pos==-1 and sf_l[i])
                if ex:
                    slp=-1 if pos==1 else 1
                    e=px*(1+slp*0.001); pp=pos*(e-ep)/ep*100 if ep>0 else 0
                    tp.append(pp); pos=0; ep=0; last_close=i
        if pos!=0:
            pp=pos*(c[-1]-ep)/ep*100 if ep>0 else 0
            tp.append(pp)
        pa=np.array(tp); w=pa[pa>0]; ls_=pa[pa<0]
        eq=1.0; rv=[]
        for p in pa: r=(p/100)*0.1-0.0002; eq*=(1+r); rv.append(r)
        ra=np.array(rv); md=0; pk=1.0
        ec=[1.0]
        for r in rv: ec.append(ec[-1]*(1+r))
        for e in ec: pk=max(e,pk); md=max(md,(pk-e)/pk*100)
        sh=np.mean(ra)/np.std(ra)*np.sqrt(365*288) if np.std(ra)>0 else 0
        print(f"  {label:30s}  Tr:{len(pa):5d}  W/L:{len(w):4d}/{len(ls_):4d} ({len(w)/max(len(pa),1)*100:.1f}%)  "
              f"Ret:{(eq-1)*100:+7.2f}%  DD:{md:5.1f}%  Sh:{sh:.2f}")
        return pa
    
    print(f"\n{'='*65}")
    b1=bt("SF baseline")
    v3l=(k>=60)&(~np.isnan(k)); v3s=(k<=40)&(~np.isnan(k))
    b2=bt("SF + StochRSI 40/60", v3l, v3s)
    v4l=(sf_l)&~(d==-1); v4s=(sf_s)&~(d==1)
    b3=bt("SF + StochST disagree", v4l, v4s)
    v5l=v3l|v4l; v5s=v3s|v4s
    b4=bt("SF + Combined veto", v5l, v5s)
    print(f"\n  Blocks: 40/60={np.sum(v3l|v3s)}  StochST={np.sum(v4l|v4s)}  Combined={np.sum(v5l|v5s)}")

if __name__=="__main__":
    ts=time.time()
    print("="*65)
    print(f"  SF + StochSuperTrend Backtest")
    print(f"  {EXCHANGE} | {SYMBOL} | {TIMEFRAME} | {YEARS}yr")
    print("="*65)
    c,h,l,v=fetch_data()
    if c is None or len(c)==0: print("No data!"); exit(1)
    print(f"  ${c[0]:.0f} ~ ${c[-1]:.0f}  ({len(c)} candles)")
    run(c,h,l,v)
    print(f"\nDone in {int((time.time()-ts)//60)}m {int((time.time()-ts)%60)}s")
