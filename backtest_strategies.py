#!/usr/bin/env python3
"""各策略独立回测对比 - BTC 5m 真实数据"""
import numpy as np, time, os

cache = "sf_stochst_cache.npz"
if not os.path.exists(cache):
    print("Cache not found! Run backtest_sf_stochst.py first"); exit(1)
d = np.load(cache); c5=d['c']; h5=d['h']; l5=d['l']; v5=d['v']; n5=len(c5)

# Resample 5m → 15m
step = 3; n = n5 // step
o15 = np.array([c5[i*step] for i in range(n)])
h15 = np.array([np.max(h5[i*step:(i+1)*step]) for i in range(n)])
l15 = np.array([np.min(l5[i*step:(i+1)*step]) for i in range(n)])
c15 = np.array([c5[(i+1)*step-1] for i in range(n)])
v15 = np.array([np.sum(v5[i*step:(i+1)*step]) for i in range(n)])
c=c15; h=h15; l=l15; v=v15

print(f"5m: {n5} → 15m: {n} candles")
print(f"${c[0]:.0f}~${c[-1]:.0f}")

def wma(s,ln):
    w=np.arange(1,ln+1); r=np.full(len(s),np.nan)
    for i in range(ln-1,len(s)): r[i]=np.sum(s[i-ln+1:i+1]*w)/np.sum(w)
    return r
def rma(s,ln):
    a=1/ln; r=np.full(len(s),np.nan); st=0
    while st<len(s) and np.isnan(s[st]): st+=1
    if st+ln>len(s): return r
    r[st+ln-1]=np.nanmean(s[st:st+ln])
    for i in range(st+ln,len(s)): vv=s[i] if not np.isnan(s[i]) else r[i-1]; r[i]=a*vv+(1-a)*r[i-1]
    return r

def bt(label, long_sig, short_sig, delay=3):
    pos=0;ep=0;tp=[];last_c=-99
    for i in range(max(60,delay),n):
        px=c[i]; can=(i-last_c)>=delay
        ls=long_sig[i] and can; ss=short_sig[i] and can
        if pos==0:
            if ls: pos=1; ep=px*1.001
            elif ss: pos=-1; ep=px*0.999
        else:
            ex=(pos==1 and ss) or (pos==-1 and ls)
            if ex:
                slp=-1 if pos==1 else 1; e=px*(1+slp*0.001)
                pp=pos*(e-ep)/ep*100 if ep>0 else 0
                tp.append(pp); pos=0; ep=0; last_c=i
    if pos!=0: pp=pos*(c[-1]-ep)/ep*100 if ep>0 else 0; tp.append(pp)
    pa=np.array(tp); w=pa[pa>0]; ls_=pa[pa<0]
    eq=1.0; rv=[]
    for p in pa: r=(p/100)*0.1-0.0002; eq*=(1+r); rv.append(r)
    ra=np.array(rv); md=0; pk=1.0; ec=[1.0]
    for r in rv: ec.append(ec[-1]*(1+r))
    for e in ec: pk=max(e,pk); md=max(md,(pk-e)/pk*100)
    sh=np.mean(ra)/np.std(ra)*np.sqrt(365*288) if np.std(ra)>0 else 0
    print(f"  {label:35s}  Tr:{len(pa):5d}  W/L:{len(w):4d}/{len(ls_):4d} ({len(w)/max(len(pa),1)*100:5.1f}%)  "
          f"Ret:{(eq-1)*100:+8.2f}%  DD:{md:5.1f}%  Sh:{sh:6.2f}")

print(f"\n{'='*100}")
print(f"  STRATEGY BACKTEST - BTC 5m (1 year)")
print(f"{'='*100}")

# 1. SuperFilter
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

print(f"\n--- SuperFilter ---")
bt("SF (dual ST)", (dr1==-1)&(dr2==-1), (dr1==1)&(dr2==1))
bt("SF ST1 only", (dr1==-1), (dr1==1))

# 2. Stoch SuperTrend
up=rma(np.maximum(np.diff(c,prepend=c[0]),0),14)
dn=rma(-np.minimum(np.diff(c,prepend=c[0]),0),14)
rsi=np.where((up+dn)>0,100-100/(1+up/dn),50); rsi[0]=50
k=np.full(n,50.0)
for i in range(14-1+3,n):
    hh=np.max(rsi[i-14+1:i+1]); ll=np.min(rsi[i-14+1:i+1])
    k[i]=100*(rsi[i]-ll)/(hh-ll) if hh>ll else 50
us=np.full(n,np.nan); ls=np.full(n,np.nan); d=np.full(n,0); ts=np.full(n,np.nan)
for i in range(60,n):
    u=k[i]+3; lv=k[i]-3
    if np.isnan(us[i-1]): us[i]=u; ls[i]=lv
    else: us[i]=min(u,us[i-1]) if k[i-1]>us[i-1] else u; ls[i]=max(lv,ls[i-1]) if k[i-1]<ls[i-1] else lv
    if np.isnan(us[i-1]): d[i]=1
    elif np.isnan(ts[i-1]): d[i]=1
    elif ts[i-1]==us[i-1]: d[i]=-1 if k[i]>us[i] else 1
    else: d[i]=1 if k[i]<ls[i] else -1
    ts[i]=ls[i] if d[i]==-1 else us[i]

print(f"\n--- Stoch SuperTrend ---")
bt("SST (raw ST)", (d==-1), (d==1))
bt("SST (ST + k<50/50)", (d==-1)&(k<50), (d==1)&(k>50))

# 3. Two-Pole Oscillator
sma1=np.convolve(c,np.ones(25)/25,mode='same')
diff=(c-sma1)-np.convolve(c-sma1,np.ones(25)/25,mode='same')
diff[diff==0]=np.nan
st25=np.array([np.nanstd(c[max(0,i-24):i+1]-sma1[max(0,i-24):i+1]) for i in range(n)])
sn=diff/np.where(st25>0,st25,1)
tp=np.full(n,np.nan)
alpha=2.0/16; s1,s2=np.nan,np.nan
for i in range(n):
    if np.isnan(sn[i]): continue
    s1=sn[i] if np.isnan(s1) else (1-alpha)*s1+alpha*sn[i]
    s2=s1 if np.isnan(s2) else (1-alpha)*s2+alpha*s1
    tp[i]=s2
tp4=np.roll(tp,4)
print(f"\n--- Two-Pole ---")
bt("TwoPole (cross)", (tp>tp4)&(tp<0)&(~np.isnan(tp)), (tp<tp4)&(tp>0)&(~np.isnan(tp)))
bt("TwoPole (dir)", (tp>0)&(~np.isnan(tp)), (tp<0)&(~np.isnan(tp)))

# 4. Double AI SuperTrend (KNN + ST1)
PL,STL,NK,K=20,80,12,3
pw=wma(c,PL); sw=wma(st1,STL)
lp=np.full(n,0.5); bs=max(PL,STL,NK)*3
for i in range(bs,n):
    if np.isnan(st1[i]) or np.isnan(pw[i]) or np.isnan(sw[i]): continue
    te=i-1; ts=min(NK,te-bs+1)
    if ts<K: continue
    t0=te-ts+1; dd=st1[t0:te+1]; labs=(pw[t0:te+1]>sw[t0:te+1]).astype(float)
    vld=~np.isnan(dd)&~np.isnan(labs)
    if np.sum(vld)<K: continue
    dists=np.abs(dd[vld]-st1[i]); idx=np.argsort(dists)[:K]; ws=0;tw=0
    for j in idx: w_=1.0/(dists[j]+1e-6); ws+=w_*labs[vld][j]; tw+=w_
    lp[i]=ws/tw if tw>0 else 0.5
print(f"\n--- Double AI SuperTrend ---")
bt("DAIST (ST+KNN>0.5)", (dr1==-1)&(lp>=0.5), (dr1==1)&(lp<=0.5))
bt("DAIST (ST+KNN>0.7)", (dr1==-1)&(lp>=0.7), (dr1==1)&(lp<=0.3))
# KNN alone
bt("KNN alone >0.7", (lp>=0.7)&(~np.isnan(lp)), (lp<=0.3)&(~np.isnan(lp)))
bt("KNN alone >0.5", (lp>=0.5)&(~np.isnan(lp)), (lp<=0.5)&(~np.isnan(lp)))

# 5. VIDYA
m=n; cmo_n=np.full(m,np.nan); vidya=np.full(m,np.nan)
for i in range(20,m):
    ch=c[1:i+1]-c[:i]
    spos=np.sum(ch[ch>=0]); sneg=-np.sum(ch[ch<0])
    cmo=100*(spos-sneg)/(spos+sneg+1e-10)
    a=2/(10+1); abc=a*abs(cmo)/100
    vidya[i]=abc*c[i]+(1-abc)*vidya[i-1] if not np.isnan(vidya[i-1]) else c[i]
vidya_sm=np.convolve(vidya,np.ones(15)/15,mode='same')
atr200=rma(np.maximum(h-l,np.maximum(abs(h-np.roll(c,1)),abs(l-np.roll(c,1)))),200)
atr200[0]=h[0]-l[0]
ub_v=vidya_sm+atr200*2; lb_v=vidya_sm-atr200*2
print(f"\n--- VIDYA ---")
bt("VIDYA (break band)", (c>ub_v)&(~np.isnan(ub_v)), (c<lb_v)&(~np.isnan(lb_v)))
bt("VIDYA trend (p>MA)", (c>vidya_sm)&(~np.isnan(vidya_sm)), (c<vidya_sm)&(~np.isnan(vidya_sm)))

print(f"\n{'='*100}")
