import time
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
from providers.binance import fetch_klines, BinanceLive
from providers.twelvedata import fetch_candles, TwelveDataLive, INTERVALS
from core.timeframes import TIMEFRAMES, SCALPING, INTRADAY, SWING
from core.analysis import analyze, validate
from core.indicators import ema, rsi
from core.data_quality import validate_candles
from core.backtest import run_backtest

st.set_page_config(page_title="KILMAS PRO", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root{--bg:#080d17;--panel:#101827;--panel2:#151f31;--line:#243249;--cyan:#45d9f5;--blue:#638cff;--muted:#91a0b8}
.stApp{background:radial-gradient(ellipse at 15% 0%,#13253a 0%,#080d17 42%);font-family:'DM Sans',sans-serif}
h1,h2,h3{font-family:'Space Grotesk',sans-serif!important;letter-spacing:-.025em}
.block-container{padding-top:1.4rem;max-width:1500px}
[data-testid="stSidebar"]{background:#0b1220;border-right:1px solid #243249}
[data-testid="stMetric"]{background:linear-gradient(145deg,#121e30,#0e1624);border:1px solid #26354b;padding:15px 17px;border-radius:16px}
[data-testid="stMetricLabel"]{color:#91a0b8!important;font-size:.78rem}
[data-testid="stMetricValue"]{font-family:'Space Grotesk',sans-serif}
.stButton>button{border:1px solid #2a3a52;border-radius:12px;background:linear-gradient(135deg,#17283c,#111b2b);color:#e9f4ff;min-height:43px;font-weight:600}
.stButton>button:hover{border-color:#45d9f5;color:#45d9f5}
div[data-baseweb="input"]>div,div[data-baseweb="select"]>div{background:#111b2b;border-color:#2a3a52;border-radius:10px}
.kilmas-hero{padding:23px 25px;border:1px solid #26354b;border-radius:22px;background:linear-gradient(120deg,rgba(25,47,72,.94),rgba(12,20,34,.96));margin-bottom:18px}
.kilmas-eyebrow{font-size:.75rem;color:#45d9f5;font-weight:700;letter-spacing:.16em;text-transform:uppercase}
.kilmas-title{font-family:'Space Grotesk',sans-serif;font-size:2.2rem;font-weight:700;line-height:1.2;margin:.35rem 0}
.kilmas-sub{color:#a9b8cc;font-size:.93rem}
.section-label{color:#45d9f5;text-transform:uppercase;font-size:.75rem;letter-spacing:.12em;font-weight:700;margin:1rem 0 .5rem}
.pill{display:inline-block;border:1px solid #2a3a52;border-radius:99px;padding:5px 10px;color:#a9b8cc;font-size:.76rem;margin-right:6px}
.note{color:#91a0b8;font-size:.82rem}
</style>
""", unsafe_allow_html=True)

for key, default in {"live":None,"candles":[],"last_symbol":"BTCUSDT","last_tf":"1m","mtf_result":None,
                     "loaded_symbol":None,"loaded_tf":None,"loaded_market":None,"live_identity":None,"backtest_result":None}.items():
    if key not in st.session_state: st.session_state[key]=default

def stop_live():
    live=st.session_state.get("live")
    if live:
        live.stop()
    st.session_state.live=None
    st.session_state.live_identity=None

def provider_fetch(market, symbol, tf, api_key, limit=500):
    if market == "Crypto": return fetch_klines(symbol,tf,limit)
    return fetch_candles(symbol,tf,api_key,limit)

def provider_live(market,symbol,tf,api_key):
    if market == "Crypto": return BinanceLive(symbol,tf)
    return TwelveDataLive(symbol,tf,api_key)

with st.sidebar:
    st.markdown("## 📈 KILMAS **PRO**")
    st.caption("MARKET ANALYTICS WORKSPACE")
    st.markdown("---")
    market=st.selectbox("Market provider",["Crypto · Binance","Forex · Twelve Data","Gold spot · Twelve Data"],index=0)
    market_class="Crypto" if market.startswith("Crypto") else "Forex" if market.startswith("Forex") else "Gold"
    if market_class == "Crypto":
        default_symbol="BTCUSDT"; options=TIMEFRAMES
        st.caption("Public Binance market data; no API key required.")
    elif market_class == "Forex":
        default_symbol="EUR/USD"; options=list(INTERVALS.keys())
        st.caption("Twelve Data API key required. Use format EUR/USD, GBP/USD, USD/JPY.")
    else:
        default_symbol="XAU/USD"; options=list(INTERVALS.keys())
        st.caption("Twelve Data API key required. Gold spot symbol: XAU/USD. Live access depends on your plan.")
    symbol=st.text_input("Market symbol",value=default_symbol,help="Crypto: BTCUSDT · Forex: EUR/USD · Gold: XAU/USD").upper().strip()
    tf=st.selectbox("Primary timeframe",options,index=options.index("1m") if "1m" in options else 0)
    mode=st.selectbox("Analysis profile",["Scalping","Intraday","Swing"])
    api_key=""
    if market_class != "Crypto":
        api_key=st.text_input("Twelve Data API key",type="password",help="Key digunakan hanya di aplikasi lokal ini dan tidak ditulis ke kode atau file konfigurasi.").strip()
        st.markdown("[Dokumentasi Twelve Data](https://twelvedata.com/docs)")
    st.markdown("---")
    st.markdown("**Connection controls**")
    load=st.button("↻  Load market snapshot",use_container_width=True)
    test=st.button("⌁  Test live stream",use_container_width=True)
    start=st.button("▶  Start live stream",use_container_width=True,type="primary")
    stop=st.button("■  Stop live stream",use_container_width=True)
    st.markdown("---")
    st.caption("Live analysis and simulated setup only; no real-money order execution.")

TIMEFRAME_MS={"1m":60_000,"3m":180_000,"5m":300_000,"15m":900_000,"30m":1_800_000,
              "1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"6h":21_600_000,
              "8h":28_800_000,"12h":43_200_000,"1d":86_400_000}
provider_name="Binance" if market_class=="Crypto" else "Twelve Data"
st.markdown(f"""<div class="kilmas-hero"><div class="kilmas-eyebrow">Market intelligence · {provider_name}</div><div class="kilmas-title">KILMAS PRO</div><div class="kilmas-sub">Multi-timeframe analysis · Market structure · Momentum · Data-health monitoring · Simulated setup</div><div style="margin-top:14px"><span class="pill">LIVE MARKET DATA</span><span class="pill">MTF VALIDATION</span><span class="pill">RISK SIMULATION</span></div></div>""",unsafe_allow_html=True)

if load:
    try:
        stop_live()
        if market_class != "Crypto" and not api_key: raise ValueError("Masukkan API key Twelve Data terlebih dahulu.")
        if not symbol: raise ValueError("Simbol pasar tidak boleh kosong.")
        st.session_state.candles=provider_fetch(market_class,symbol,tf,api_key,500)
        st.session_state.last_symbol,st.session_state.last_tf=symbol,tf
        st.session_state.loaded_symbol,st.session_state.loaded_tf,st.session_state.loaded_market=symbol,tf,market_class
        st.session_state.mtf_result=None
        st.session_state.backtest_result=None
        st.success(f"Snapshot berhasil dimuat: {len(st.session_state.candles)} candle · {symbol} · {tf} · {provider_name}.")
    except Exception as exc:
        st.session_state.candles=[]
        st.session_state.loaded_symbol=st.session_state.loaded_tf=st.session_state.loaded_market=None
        st.error(f"Gagal mengambil snapshot: {exc}")

if test:
    probe=None
    try:
        if market_class != "Crypto" and not api_key: raise ValueError("Masukkan API key Twelve Data terlebih dahulu.")
        probe=provider_live(market_class,symbol,tf,api_key); probe.start(); time.sleep(4)
        health=probe.health()
        if health["state"]=="LIVE": st.success("Live stream berhasil: tick harga baru diterima.")
        else: st.error(f"Stream belum terverifikasi. Status {health['state']}. {health.get('error','')}")
    except Exception as exc: st.error(f"Tes stream gagal: {exc}")
    finally:
        if probe: probe.stop()

if start:
    stop_live()
    try:
        if not symbol: raise ValueError("Simbol pasar tidak boleh kosong.")
        if market_class != "Crypto" and not api_key: raise ValueError("Masukkan API key Twelve Data terlebih dahulu.")
        # Load historical candles before starting live quote updates.
        if (not st.session_state.candles or symbol != st.session_state.loaded_symbol or tf != st.session_state.loaded_tf or market_class != st.session_state.loaded_market):
            st.session_state.candles=provider_fetch(market_class,symbol,tf,api_key,500)
        st.session_state.live=provider_live(market_class,symbol,tf,api_key)
        st.session_state.live_identity=(market_class,symbol,tf)
        st.session_state.live.start()
        st.session_state.last_symbol,st.session_state.last_tf=symbol,tf
        st.session_state.loaded_symbol,st.session_state.loaded_tf,st.session_state.loaded_market=symbol,tf,market_class
        st.session_state.mtf_result=None
        st.session_state.backtest_result=None
    except Exception as exc:
        stop_live(); st.error(f"Tidak dapat memulai streaming: {exc}")
if stop:
    stop_live(); st.info("Live stream dihentikan. Snapshot candle terakhir tetap tersedia.")

current_identity=(market_class,symbol,tf)
live=st.session_state.live
# Never display a previous symbol/timeframe under the newly selected market.
if live and st.session_state.get("live_identity") != current_identity:
    stop_live()
    live=None
if live:
    st_autorefresh(interval=2000,key="kilmas_refresh")
    h=live.health()
    if h.get("latest") and st.session_state.candles:
        candle=h["latest"]; current_candles=st.session_state.candles
        if candle["ts"]==current_candles[-1]["ts"]:
            if market_class == "Crypto":
                # Binance kline updates contain the exchange's current OHLCV candle.
                current_candles[-1]=candle
            else:
                # Twelve Data sends quote ticks, not full OHLCV candles. Preserve
                # the REST candle's opening price/range and update from the quote.
                base=current_candles[-1]
                current_candles[-1]={"ts":base["ts"],"open":base["open"],
                    "high":max(float(base["high"]),float(candle["high"])),
                    "low":min(float(base["low"]),float(candle["low"])),
                    "close":float(candle["close"]),"volume":base.get("volume",0),"closed":False}
        elif candle["ts"]>current_candles[-1]["ts"]:
            current_candles.append(candle); st.session_state.candles=current_candles[-500:]
else:
    h={"state":"SNAPSHOT" if st.session_state.candles else "DISCONNECTED","age":None,"reconnects":0,"attempts":0,"error":""}

loaded_identity=(st.session_state.get("loaded_market"),st.session_state.get("loaded_symbol"),st.session_state.get("loaded_tf"))
if loaded_identity != (market_class,symbol,tf):
    candles=[]
    st.info("Pilihan pasar/simbol/timeframe berubah. Muat snapshot baru agar analisis tidak memakai data dari pilihan sebelumnya.")
else:
    candles=st.session_state.candles
if candles:
    quality=validate_candles(candles,timeframe_ms=TIMEFRAME_MS.get(tf))
    analysis_candles=[x for x in candles if x.get("closed",True)]
    analysis=analyze(candles)
    last=candles[-1]
    stamp=datetime.fromtimestamp(last["ts"]/1000).astimezone().strftime("%d %b %Y · %H:%M:%S")
    analysis_stamp=(datetime.fromtimestamp(analysis_candles[-1]["ts"]/1000).astimezone().strftime("%d %b %Y · %H:%M:%S")
                    if analysis_candles else "belum tersedia")
    if quality["errors"]:
        st.error("Kualitas data bermasalah: " + " | ".join(quality["errors"][:3]))
        st.stop()
    for warning in quality["warnings"]:
        st.warning(warning)
    st.caption(f'Data check: {quality["count"]} candle diterima · {quality["closed_count"]} candle tertutup · {len(candles)-quality["closed_count"]} candle berjalan.')
    state_color="#42e3a5" if h["state"]=="LIVE" else "#f3bf5f" if h["state"] in ("SNAPSHOT","CONNECTING","DELAYED") else "#ff6f7d"
    st.markdown(f'<div class="section-label">Market overview <span style="color:{state_color};letter-spacing:0">● {h["state"]}</span> · {provider_name}</div>',unsafe_allow_html=True)
    c1,c2,c3,c4,c5=st.columns(5)
    c1.metric("LAST PRICE",f'{analysis["price"]:,.5f}' if market_class!="Crypto" else f'{analysis["price"]:,.2f}')
    c2.metric("ANALYSIS SCORE",f'{analysis.get("score",0)}/100')
    c3.metric("PRIMARY BIAS",analysis.get("bias","NEUTRAL"))
    c4.metric("SETUP",analysis.get("state","WAIT"))
    c5.metric("RSI · 14",f'{analysis["rsi"]:.1f}' if analysis.get("rsi") is not None else "—")
    if h["age"] is not None:
        st.caption(f'Pesan live terakhir {h["age"]:.1f} detik lalu · reconnect {h["reconnects"]} · attempts {h["attempts"]} · candle terakhir {stamp}')
        if h["state"] != "LIVE":
            st.warning("Feed belum terverifikasi aktif saat ini. Jangan gunakan snapshot lama seolah-olah harga live; periksa koneksi, kuota, simbol, dan akses provider.")
    else: st.caption(f'Snapshot REST · candle terakhir {stamp}. Snapshot bukan streaming kontinu; jalankan Start live stream untuk update tick.')
    st.caption(f'Waktu candle tertutup terakhir yang dipakai mesin analisis: {analysis_stamp}. Candle berjalan dikecualikan dari perhitungan sinyal.')
    if market_class!="Crypto" and live and h.get("latest"):
        st.caption("Catatan: candle yang sedang berjalan dibentuk dari tick quote live; volume tidak tersedia pada feed quote ini dan ditampilkan 0.")
    if h.get("error") and h["state"]!="LIVE": st.warning("Status koneksi: "+str(h["error"])[:400])

    st.markdown('<div class="section-label">Price action</div>',unsafe_allow_html=True)
    show=candles[-220:]; dates=[datetime.fromtimestamp(x["ts"]/1000).astimezone() for x in show]; closes=[x["close"] for x in show]
    e9,e21,e50=ema(closes,9),ema(closes,21),ema(closes,50)
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.035,row_heights=[.78,.22],specs=[[{"secondary_y":False}],[{"secondary_y":False}]])
    fig.add_trace(go.Candlestick(x=dates,open=[x["open"] for x in show],high=[x["high"] for x in show],low=[x["low"] for x in show],close=closes,name=symbol,increasing_line_color="#42e3a5",decreasing_line_color="#ff6f7d",increasing_fillcolor="#42e3a5",decreasing_fillcolor="#ff6f7d"),row=1,col=1)
    fig.add_trace(go.Scatter(x=dates,y=e9,name="EMA 9",line=dict(color="#45d9f5",width=1.3)),row=1,col=1)
    fig.add_trace(go.Scatter(x=dates,y=e21,name="EMA 21",line=dict(color="#638cff",width=1.3)),row=1,col=1)
    fig.add_trace(go.Scatter(x=dates,y=e50,name="EMA 50",line=dict(color="#c59cff",width=1.3)),row=1,col=1)
    fig.add_trace(go.Bar(x=dates,y=[x.get("volume",0) for x in show],name="Volume (if provided)",marker_color=["#42e3a5" if x["close"]>=x["open"] else "#ff6f7d" for x in show],opacity=.65),row=2,col=1)
    fig.update_layout(height=610,template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(8,13,23,.6)",margin=dict(l=8,r=8,t=24,b=8),xaxis_rangeslider_visible=False,legend=dict(orientation="h",y=1.02,x=0),font=dict(family="DM Sans",color="#c9d6e8"),hovermode="x unified")
    fig.update_xaxes(showgrid=True,gridcolor="#1e2a3d",rangeslider_visible=False); fig.update_yaxes(showgrid=True,gridcolor="#1e2a3d",row=1,col=1); fig.update_yaxes(showgrid=False,row=2,col=1)
    st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False,"scrollZoom":True})
    left,right=st.columns([1.1,.9],gap="large")
    with left:
        st.markdown('<div class="section-label">Analysis engine</div>',unsafe_allow_html=True); st.subheader("Signal reasoning")
        for reason in analysis.get("reasons",["Data belum cukup untuk analisis."]): st.markdown("- "+reason)
        structure=analysis.get("structure",{}); m1,m2,m3=st.columns(3)
        m1.metric("Structure",structure.get("label","UNKNOWN")); m2.metric("BOS",structure.get("bos","NONE")); m3.metric("CHoCH",structure.get("choch","NONE"))
        st.caption(f'Support area: {structure.get("support",0):,.5f} · Resistance area: {structure.get("resistance",0):,.5f}')
    with right:
        st.markdown('<div class="section-label">Simulated setup</div>',unsafe_allow_html=True)
        if analysis.get("rr",0)>0:
            st.metric("Risk / Reward",f'1 : {analysis["rr"]:.2f}')
            st.dataframe([{"Level":"Reference price","Price":analysis["price"]},{"Level":"Entry idea","Price":analysis["entry"]},{"Level":"Stop loss (simulated)","Price":analysis["sl"]},{"Level":"Take profit 1","Price":analysis["tp1"]},{"Level":"Take profit 2","Price":analysis["tp2"]}],hide_index=True,use_container_width=True)
        else: st.info("Bias belum cukup jelas. KILMAS memilih WAIT dan tidak memaksakan level entry.")
    st.markdown('<div class="section-label">Multi-timeframe validation</div>',unsafe_allow_html=True)
    if market_class=="Crypto": tfset=SCALPING if mode=="Scalping" else INTRADAY if mode=="Intraday" else SWING
    else: tfset={"Scalping":["1h","15m","5m","1m"],"Intraday":["4h","1h","15m","5m"],"Swing":["1d","4h","1h"]}[mode]
    st.caption("Mode: "+mode+" · "+" → ".join(tfset))
    if st.button("🧠 Analyze Multi-Timeframe",use_container_width=True,type="primary"):
        results=[]; progress=st.progress(0)
        for i,timeframe in enumerate(tfset):
            try:
                mtf_candles=candles if timeframe==tf else provider_fetch(market_class,symbol,timeframe,api_key,300)
                result=analyze(mtf_candles); result["tf"]=timeframe; result["error"]=""
            except Exception as exc: result={"tf":timeframe,"state":"WAIT","bias":"UNKNOWN","score":0,"error":str(exc)}
            results.append(result); progress.progress((i+1)/len(tfset))
        st.session_state.mtf_result={"results":results,"primary":analysis,"at":datetime.now().strftime("%H:%M:%S")}; progress.empty()
    mtf_result=st.session_state.get("mtf_result")
    if mtf_result:
        results=mtf_result["results"]; validation=validate(mtf_result["primary"],results)
        v1,v2,v3,v4,v5=st.columns(5); v1.metric("FINAL",validation["final"]); v2.metric("ALIGNMENT",f'{validation["alignment"]*100:.0f}%'); v3.metric("MTF","PASS" if validation["mtf"] else "WAIT"); v4.metric("STRUCTURE","PASS" if validation["structure"] else "WAIT"); v5.metric("MOMENTUM / R:R","PASS" if validation["momentum"] and validation["rr"] else "WAIT")
        st.dataframe([{"Timeframe":r["tf"],"State":r.get("state","WAIT"),"Bias":r.get("bias","UNKNOWN"),"Score":r.get("score",0),"RSI":round(r["rsi"],1) if r.get("rsi") is not None else "—","Structure":r.get("structure",{}).get("label","—"),"Provider note":r.get("error","")} for r in results],hide_index=True,use_container_width=True)
        if validation["final"]=="WAIT": st.warning("WAIT: validasi belum lengkap. Skor adalah ukuran aturan analisis, bukan probabilitas keuntungan.")
        else: st.success(f'{validation["final"]} lolos aturan validasi internal. Hasil eksperimental; bukan jaminan hasil.')
    with st.expander("🧪 Backtest Lab · Historical simulation",expanded=False):
        st.caption("Sinyal dihitung dari candle tertutup dan entry simulasi dilakukan pada open candle berikutnya. Jika SL dan TP tersentuh dalam candle yang sama, hasil dihitung sebagai SL terlebih dahulu.")
        b1,b2=st.columns(2)
        fee_bps=b1.number_input("Estimated fee (bps per side)",min_value=0.0,max_value=100.0,value=5.0,step=0.5,help="Isi sesuai perkiraan biaya transaksi instrumen/provider. 1 bps = 0,01%.")
        slippage_bps=b2.number_input("Estimated slippage (bps per side)",min_value=0.0,max_value=100.0,value=5.0,step=0.5)
        if st.button("Run historical backtest",use_container_width=True):
            st.session_state.backtest_result={"identity":(market_class,symbol,tf),
                "result":run_backtest(candles,fee_bps=fee_bps,slippage_bps=slippage_bps)}
        bt=st.session_state.get("backtest_result")
        if bt and bt.get("identity")== (market_class,symbol,tf):
            result=bt["result"]
            if not result.get("ready"):
                st.info(result.get("message","Backtest belum siap."))
            else:
                st.caption(result.get("message",""))
                if result.get("trade_count",0):
                    p1,p2,p3,p4,p5=st.columns(5)
                    p1.metric("TRADES",result["trade_count"])
                    p2.metric("WIN RATE",f'{result["win_rate"]:.1f}%')
                    p3.metric("NET RESULT",f'{result["net_r"]:.2f} R')
                    p4.metric("AVG / TRADE",f'{result["avg_net_r"]:.2f} R')
                    p5.metric("MAX DRAWDOWN",f'{result["max_drawdown_r"]:.2f} R')
                    pf=result["profit_factor"]
                    st.metric("PROFIT FACTOR", "∞" if pf==float("inf") else f"{pf:.2f}")
                    st.dataframe([{"Side":t["direction"],"Entry":t["entry"],"Exit":t["exit"],"Exit reason":t["exit_reason"],"Gross R":round(t["gross_R"],2),"Estimated cost R":round(t["estimated_cost_R"],3),"Net R":round(t["net_R"],2)} for t in result["trades"][-50:]],hide_index=True,use_container_width=True)
                else:
                    st.info(result.get("message","Tidak ada trade simulasi."))
        st.caption("Hasil historis bukan prediksi. Asumsi biaya, slippage, likuiditas, dan eksekusi aktual dapat berbeda. Backtest ini belum menguji semua kondisi pasar atau seluruh kemungkinan bias strategi.")

    st.download_button("⬇ Download candles as CSV",data="timestamp,open,high,low,close,volume,closed\n"+"\n".join(f'{x["ts"]},{x["open"]},{x["high"]},{x["low"]},{x["close"]},{x.get("volume",0)},{x.get("closed",False)}' for x in candles),file_name=f"KILMAS_{symbol.replace('/','')}_{tf}.csv",mime="text/csv")
    report_lines=[
        "KILMAS PRO - ANALYSIS REPORT",
        f"Market: {market} | Symbol: {symbol} | Timeframe: {tf}",
        f"Generated local time: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Data state: {h.get('state','UNKNOWN')} | Candle count: {len(candles)} | Closed candles used: {analysis.get('candles_used',0)} | Latest chart candle: {stamp} | Latest closed analysis candle: {analysis_stamp}",
        f"Last price: {analysis.get('price',0)} | Bias: {analysis.get('bias','UNKNOWN')} | Setup: {analysis.get('state','WAIT')} | Rule score: {analysis.get('score',0)}/100",
        f"RSI(14): {analysis.get('rsi','N/A')} | ATR(14): {analysis.get('atr','N/A')}",
        f"Entry idea: {analysis.get('entry','N/A')} | Simulated SL: {analysis.get('sl','N/A')} | TP1: {analysis.get('tp1','N/A')} | TP2: {analysis.get('tp2','N/A')} | R:R: {analysis.get('rr','N/A')}",
        "Reasons:", *[f"- {r}" for r in analysis.get('reasons',[])],
        "DISCLAIMER: Educational simulation only. Score is not win probability. Levels are simulated, not financial advice or order execution. Backtest assumptions are simplified."
    ]
    st.download_button("⬇ Download analysis report (.txt)",data="\n".join(map(str,report_lines)),file_name=f"KILMAS_REPORT_{symbol.replace('/','')}_{tf}.txt",mime="text/plain")
else:
    st.markdown('<div style="padding:28px;border:1px dashed #2b3b52;border-radius:18px;background:rgba(16,24,39,.65)"><div style="font-size:1.15rem;font-weight:700">Mulai dengan data pasar</div><p style="color:#91a0b8">Pilih provider dan simbol di sidebar, lalu klik <b>Load market snapshot</b>. Untuk pembaruan kontinu, klik <b>Start live stream</b>.</p><p style="color:#91a0b8">Crypto memakai Binance. Forex dan emas spot memakai Twelve Data dan memerlukan API key serta hak akses data yang sesuai.</p></div>',unsafe_allow_html=True)

st.markdown("---")
st.markdown('<div class="note">KILMAS PRO · Data live bergantung pada provider, paket, kuota, dan koneksi. Untuk Twelve Data, candle berjalan dirakit dari quote ticks; volume pada candle tick tidak tersedia. Analisis hanya menggunakan candle tertutup; candle berjalan dikeluarkan untuk mengurangi sinyal yang berubah sebelum penutupan. Skor 0–100 adalah skor aturan internal, bukan probabilitas menang. Analisis hanya untuk pembelajaran/simulasi; tidak ada eksekusi order uang nyata.</div>',unsafe_allow_html=True)
