from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from datetime import datetime, timedelta

app = Flask(__name__)

RATIO_MULTIPLIER = 1000

SYMBOL_MASTER = [
    {"name":"NIFTY 50","yahoo":"^NSEI","industry":"NIFTY"},
    {"name":"NIFTY NEXT 50","yahoo":"^NSMIDCP","industry":"NIFTY JR"},
    {"name":"NIFTY 100","yahoo":"^CNX100","industry":"LARGE CAP 100"},
    {"name":"NIFTY 200","yahoo":"^CNX200","industry":"LARGE MIDCAP 200"},
    {"name":"NIFTY LARGE MIDCAP 250","yahoo":"NIFTY_LARGEMID250.NS","industry":"LARGE MIDCAP 250"},
    {"name":"NIFTY MIDCAP 50","yahoo":"^NSEMDCP50","industry":"MIDCAP 50"},
    {"name":"NIFTY MIDCAP 100","yahoo":"NIFTY_MIDCAP_100.NS","industry":"MIDCAP 100"},
    {"name":"NIFTY MIDCAP 150","yahoo":"NIFTYMIDCAP150.NS","industry":"MIDCAP 150"},
    {"name":"NIFTY MID SMALLCAP 400","yahoo":"NIFTYMIDSML400.NS","industry":"MID SMALL CAP"},
    {"name":"NIFTY SMALLCAP 100","yahoo":"^CNXSC","industry":"SMALL CAP"},
    {"name":"NIFTY SMALLCAP 250","yahoo":"NIFTYSMLCAP250.NS","industry":"SMALL CAP"},
    {"name":"NIFTY MICROCAP 250","yahoo":"NIFTY_MICROCAP250.NS","industry":"MICRO CAP"},
    {"name":"NIFTY 500","yahoo":"^CRSLDX","industry":"BROAD MARKET"},
    {"name":"NIFTY AUTO","yahoo":"^CNXAUTO","industry":"AUTO"},
    {"name":"NIFTY COMMODITIES","yahoo":"^CNXCMDT","industry":"COMMODITIES"},
    {"name":"NIFTY CONSUMPTION","yahoo":"^CNXCONSUM","industry":"CONSUMPTION"},
    {"name":"NIFTY ENERGY","yahoo":"^CNXENERGY","industry":"ENERGY"},
    {"name":"NIFTY FMCG","yahoo":"^CNXFMCG","industry":"FMCG"},
    {"name":"NIFTY INFRA","yahoo":"^CNXINFRA","industry":"INFRA"},
    {"name":"NIFTY IT","yahoo":"^CNXIT","industry":"IT"},
    {"name":"NIFTY MEDIA","yahoo":"^CNXMEDIA","industry":"MEDIA"},
    {"name":"NIFTY METAL","yahoo":"^CNXMETAL","industry":"METAL"},
    {"name":"NIFTY MNC","yahoo":"^CNXMNC","industry":"MNC"},
    {"name":"NIFTY PHARMA","yahoo":"^CNXPHARMA","industry":"PHARMA"},
    {"name":"NIFTY PSE","yahoo":"^CNXPSE","industry":"PSE"},
    {"name":"NIFTY PSU BANK","yahoo":"^CNXPSUBANK","industry":"PSUBANK"},
    {"name":"NIFTY REALTY","yahoo":"^CNXREALTY","industry":"REALTY"},
    {"name":"NIFTY SERVICE","yahoo":"^CNXSERVICE","industry":"SERVICE"},
    {"name":"NIFTY BANK","yahoo":"^NSEBANK","industry":"BANKNIFTY"},
    {"name":"NIFTY CHEMICAL","yahoo":"NIFTY_CHEMICALS.NS","industry":"CHEMICAL"},
    {"name":"NIFTY CONSUMER DURABLES","yahoo":"NIFTY_CONSR_DURBL.NS","industry":"CONSUMER DURABLES"},
    {"name":"NIFTY CPSE","yahoo":"NIFTY_CPSE.NS","industry":"CPSE"},
    {"name":"NIFTY FINANCIAL SERVICE","yahoo":"NIFTY_FIN_SERVICE.NS","industry":"FINANCIAL SERVICE"},
    {"name":"NIFTY HEALTHCARE","yahoo":"NIFTY_HEALTHCARE.NS","industry":"HEALTHCARE"},
    {"name":"NIFTY INDIA DEFENCE","yahoo":"NIFTY_IND_DEFENCE.NS","industry":"DEFENCE"},
    {"name":"NIFTY DIGITAL","yahoo":"NIFTY_IND_DIGITAL.NS","industry":"DIGITAL"},
    {"name":"NIFTY OIL AND GAS","yahoo":"NIFTY_OIL_AND_GAS.NS","industry":"OIL AND GAS"},
    {"name":"NIFTY PRIVATE BANK","yahoo":"NIFTYPVTBANK.NS","industry":"PRIVATE BANK"},
]

ALL_NAMES = [s["name"] for s in SYMBOL_MASTER]
BENCHMARK_INDEX = "NIFTY 500"

prices_cache = {}
cache_time = None

def fetch_all_prices():
    global prices_cache, cache_time
    
    if cache_time and (datetime.now() - cache_time).seconds < 3600 and prices_cache:
        return prices_cache
    
    tickers = [s["yahoo"] for s in SYMBOL_MASTER]
    end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.today() - pd.DateOffset(years=3)).strftime('%Y-%m-%d')
    
    try:
        df = yf.download(tickers, start=start_date, end=end_date, group_by='ticker', progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        print(f"Critical Download Error: {e}")
        return {}
    
    out = {}
    for s in SYMBOL_MASTER:
        t = s["yahoo"]
        try:
            if t in df.columns.levels[0]:
                series = df[t]["Close"].dropna()
                if not series.empty:
                    out[s["name"]] = series.to_dict()
                else:
                    out[s["name"]] = None
            else:
                out[s["name"]] = None
        except Exception:
            out[s["name"]] = None
    
    prices_cache = out
    cache_time = datetime.now()
    return out

def ema(s, n):
    series = pd.Series(s)
    return series.ewm(span=n, adjust=False).mean()

def safe_ratio(a, b):
    if a is None or b is None:
        return None
    sa = pd.Series(a)
    sb = pd.Series(b)
    df = pd.concat([sa, sb], axis=1).dropna()
    if df.empty:
        return None
    return ((df.iloc[:, 0] / df.iloc[:, 1]) * RATIO_MULTIPLIER).to_dict()

def rs_calc(r, n):
    series = pd.Series(r)
    return ((series / series.shift(n)) - 1) * 100

def rsi(series_dict, period=14):
    series = pd.Series(series_dict)
    if series.nunique() <= 1:
        return pd.Series(50, index=series.index)
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    res = 100 - (100 / (1 + rs))
    return res.fillna(100)

@app.route('/')
def index():
    return render_template('index.html', symbols=ALL_NAMES)

@app.route('/api/plot_ratio', methods=['POST'])
def api_plot_ratio():
    data = request.json
    numerator = data['numerator']
    denominator = data['denominator']
    rs_periods = data.get('rs_periods', [])
    
    prices = fetch_all_prices()
    num_series = prices.get(numerator)
    den_series = prices.get(denominator)
    
    if num_series is None or den_series is None:
        return jsonify({'error': 'Data missing'}), 400
    
    r_dict = safe_ratio(num_series, den_series)
    if r_dict is None:
        return jsonify({'error': 'Unable to calculate ratio'}), 400
    
    r = pd.Series(r_dict)
    
    if not rs_periods:
        rows = 1
        row_heights = [1.0]
        subplot_titles = ["Ratio Trend"]
    else:
        rows = 1 + len(rs_periods)
        row_heights = [0.6] + [0.4/len(rs_periods)] * len(rs_periods)
        subplot_titles = ["Ratio Trend"] + [f"Relative Strength ({p})" for p in rs_periods]
    
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=row_heights, subplot_titles=subplot_titles)
    
    prev_day_cond = (r >= r.shift(1)).fillna(False)
    for i in range(1, len(r)):
        x_segment = [r.index[i-1], r.index[i]]
        y_segment = [r.iloc[i-1], r.iloc[i]]
        color = "#00ff99" if prev_day_cond.iloc[i] else "#ff4d4d"
        fig.add_trace(go.Scatter(x=x_segment, y=y_segment, mode="lines", line=dict(color=color, width=3), showlegend=False, hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Value:</b> %{y:.2f}<extra></extra>'), row=1, col=1)
    
    e200 = ema(r, 200)
    e200_cond = (r > e200).values
    x_arr = r.index.values
    y_arr = e200.values
    
    i = 0
    while i < len(e200_cond):
        current_color = e200_cond[i]
        start_idx = i
        while i < len(e200_cond) and e200_cond[i] == current_color:
            i += 1
        end_idx = i
        if end_idx < len(e200_cond):
            x_segment = x_arr[start_idx:end_idx + 1]
            y_segment = y_arr[start_idx:end_idx + 1]
        else:
            x_segment = x_arr[start_idx:end_idx]
            y_segment = y_arr[start_idx:end_idx]
        color = "#00ff99" if current_color else "#ff4d4d"
        fig.add_trace(go.Scatter(x=x_segment, y=y_segment, mode="lines", line=dict(color=color, width=2), showlegend=False, hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>EMA 200:</b> %{y:.2f}<extra></extra>'), row=1, col=1)
    
    e100 = ema(r, 100)
    e100_cond = (r > e100).values
    y100_arr = e100.values
    
    i = 0
    while i < len(e100_cond):
        current_color = e100_cond[i]
        start_idx = i
        while i < len(e100_cond) and e100_cond[i] == current_color:
            i += 1
        end_idx = i
        if end_idx < len(e100_cond):
            x_segment = x_arr[start_idx:end_idx + 1]
            y_segment = y100_arr[start_idx:end_idx + 1]
        else:
            x_segment = x_arr[start_idx:end_idx]
            y_segment = y100_arr[start_idx:end_idx]
        color = "#ffff00" if current_color else "#ff4d4d"
        fig.add_trace(go.Scatter(x=x_segment, y=y_segment, mode="lines", line=dict(color=color, width=2), showlegend=False, hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>EMA 100:</b> %{y:.2f}<extra></extra>'), row=1, col=1)
    
    rs_annotations = []
    if rs_periods:
        for idx, p in enumerate(rs_periods):
            row_idx = idx + 2
            rs_line = rs_calc(r, p)
            for i in range(1, len(rs_line)):
                x_segment = [rs_line.index[i-1], rs_line.index[i]]
                y_segment = [rs_line.iloc[i-1], rs_line.iloc[i]]
                color = "#00ff99" if rs_line.iloc[i] >= 0 else "#ff4d4d"
                fig.add_trace(go.Scatter(x=x_segment, y=y_segment, mode="lines", line=dict(color=color, width=2), showlegend=False), row=row_idx, col=1)
            fig.add_hline(y=0, row=row_idx, col=1, line=dict(color="gray", dash="dash", width=2))
            if not rs_line.empty:
                rs_min = rs_line.min()
                rs_max = rs_line.max()
                padding = (rs_max - rs_min) * 0.1
                fig.update_yaxes(range=[rs_min - padding, rs_max + padding], row=row_idx, col=1)
                rs_annotations.append(f"RS {p}: {rs_line.iloc[-1]:.2f}")
    
    rs_text_block = "<br>" + "<br>".join(rs_annotations) if rs_annotations else ""
    fig.add_annotation(xref="paper", yref="paper", x=0.01, y=0.98, text=(f"<b>{numerator} / {denominator}</b> : {r.iloc[-1]:.2f}<br><b>EMA 100</b> : {e100.iloc[-1]:.2f}<br><b>EMA 200</b> : {e200.iloc[-1]:.2f}" + rs_text_block), showarrow=False, align="left", font=dict(size=16, color="white", family="Arial Black"), bgcolor="rgba(0,0,0,0.75)", bordercolor="#888", borderwidth=2, xanchor="left", yanchor="top")
    
    chart_height = 600 if not rs_periods else 600 + (150 * len(rs_periods))
    fig.update_layout(height=chart_height, margin=dict(l=15, r=15, t=60, b=15), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(size=15, color="#e0e0e0"))
    fig.update_xaxes(showgrid=False, tickfont=dict(size=13))
    fig.update_yaxes(showgrid=True, gridcolor="#333", tickfont=dict(size=13))
    fig.update_annotations(font=dict(size=18, color="#ffffff", weight="bold"))
    
    return jsonify({'plot': fig.to_json()})

@app.route('/api/analytics', methods=['POST'])
def api_analytics():
    data = request.json
    base_name = data.get('base_name', BENCHMARK_INDEX)
    prices = fetch_all_prices()
    base_series_dict = prices.get(base_name)
    
    if base_series_dict is None:
        return jsonify({'error': 'Base series not found'}), 400
    
    base_series = pd.Series(base_series_dict)
    rows = []
    
    for i, s in enumerate(SYMBOL_MASTER, start=1):
        ps_dict = prices.get(s["name"])
        if ps_dict is None:
            rows.append({"SL No.": i, "Symbol": s["name"], "Industry": s["industry"], "Status": "DATA MISSING", "Ratio": "-", "Above 100": "-", "Above 200": "-", "Trend": "-", "RS 21": "-", "RS 63": "-", "RS 126": "-", "RS 252": "-"})
            continue
        
        ps = pd.Series(ps_dict)
        r_dict = safe_ratio(ps_dict, base_series_dict)
        
        if r_dict is None:
            rows.append({"SL No.": i, "Symbol": s["name"], "Industry": s["industry"], "Status": "NO RATIO DATA", "Ratio": "-", "Above 100": "-", "Above 200": "-", "Trend": "-", "RS 21": "-", "RS 63": "-", "RS 126": "-", "RS 252": "-"})
            continue
        
        r = pd.Series(r_dict)
        try:
            ema100 = ema(r, 100)
            ema200 = ema(r, 200)
            ratio_val = r.iloc[-1]
            if len(r) >= 200 and not ema200.empty:
                above_100 = "Yes" if ratio_val > ema100.iloc[-1] else "No"
                above_200 = "Yes" if ratio_val > ema200.iloc[-1] else "No"
                trend = "Bullish" if ratio_val > ema200.iloc[-1] else "Bearish"
            elif len(r) >= 100 and not ema100.empty:
                above_100 = "Yes" if ratio_val > ema100.iloc[-1] else "No"
                above_200 = "-"
                trend = "-"
            else:
                above_100 = "-"
                above_200 = "-"
                trend = "-"
        except:
            ratio_val = r.iloc[-1]
            above_100 = "-"
            above_200 = "-"
            trend = "-"
        
        try:
            rs21_val = rs_calc(r, 21).iloc[-1] if len(r) > 21 else "-"
            if rs21_val != "-" and pd.isna(rs21_val):
                rs21_val = "-"
        except:
            rs21_val = "-"
        
        try:
            rs63_val = rs_calc(r, 63).iloc[-1] if len(r) > 63 else "-"
            if rs63_val != "-" and pd.isna(rs63_val):
                rs63_val = "-"
        except:
            rs63_val = "-"
        
        try:
            rs126_val = rs_calc(r, 126).iloc[-1] if len(r) > 126 else "-"
            if rs126_val != "-" and pd.isna(rs126_val):
                rs126_val = "-"
        except:
            rs126_val = "-"
        
        try:
            rs252_val = rs_calc(r, 252).iloc[-1] if len(r) > 252 else "-"
            if rs252_val != "-" and pd.isna(rs252_val):
                rs252_val = "-"
        except:
            rs252_val = "-"
        
        rows.append({"SL No.": i, "Symbol": s["name"], "Industry": s["industry"], "Status": "OK", "Ratio": float(ratio_val), "Above 100": above_100, "Above 200": above_200, "Trend": trend, "RS 21": rs21_val, "RS 63": rs63_val, "RS 126": rs126_val, "RS 252": rs252_val})
    
    return jsonify({'data': rows})

@app.route('/api/technical', methods=['GET'])
def api_technical():
    ema_periods = [5, 9, 21, 30, 52, 75, 88, 125, 137, 208, 252]
    rsi_periods = [5, 9, 14, 21, 30, 52, 75, 88, 125, 137, 208, 252]
    prices = fetch_all_prices()
    rows = []
    
    for i, s in enumerate(SYMBOL_MASTER, start=1):
        series_dict = prices.get(s["name"])
        if series_dict is None:
            row = {"SL No.": i, "Name": s["name"], "Industry": s["industry"], "LTP": "-"}
            for p in ema_periods:
                row[f"EMA {p}"] = "-"
            for p in rsi_periods:
                row[f"RSI {p}"] = "-"
            rows.append(row)
            continue
        
        series = pd.Series(series_dict)
        if len(series) < 5:
            row = {"SL No.": i, "Name": s["name"], "Industry": s["industry"], "LTP": "-"}
            for p in ema_periods:
                row[f"EMA {p}"] = "-"
            for p in rsi_periods:
                row[f"RSI {p}"] = "-"
            rows.append(row)
            continue
        
        ltp = float(series.iloc[-1])
        row = {"SL No.": i, "Name": s["name"], "Industry": s["industry"], "LTP": ltp}
        
        for p in ema_periods:
            if len(series) > p:
                try:
                    ema_val = ema(series, p)
                    if not ema_val.empty and not pd.isna(ema_val.iloc[-1]):
                        row[f"EMA {p}"] = float(ema_val.iloc[-1])
                    else:
                        row[f"EMA {p}"] = "-"
                except:
                    row[f"EMA {p}"] = "-"
            else:
                row[f"EMA {p}"] = "-"
        
        for p in rsi_periods:
            if len(series) > p + 1:
                try:
                    rsi_val = rsi(series_dict, p)
                    if not rsi_val.empty and not pd.isna(rsi_val.iloc[-1]):
                        rv = float(rsi_val.iloc[-1])
                        if 0 <= rv <= 100:
                            row[f"RSI {p}"] = rv
                        else:
                            row[f"RSI {p}"] = "-"
                    else:
                        row[f"RSI {p}"] = "-"
                except:
                    row[f"RSI {p}"] = "-"
            else:
                row[f"RSI {p}"] = "-"
        
        rows.append(row)
    
    return jsonify({'data': rows})

@app.route('/api/scanner', methods=['POST'])
def api_scanner():
    data = request.json
    scan_base = data.get('base', BENCHMARK_INDEX)
    prices = fetch_all_prices()
    base_s_dict = prices.get(scan_base)
    
    if base_s_dict is None:
        return jsonify({'error': 'Base not found'}), 400
    
    base_s = pd.Series(base_s_dict)
    scan_results = []
    
    for s in SYMBOL_MASTER:
        p_series_dict = prices.get(s["name"])
        if p_series_dict is None:
            continue
        
        p_series = pd.Series(p_series_dict)
        if p_series.empty or base_s.empty:
            continue
        
        ltp = p_series.iloc[-1]
        e21 = ema(p_series, 21).iloc[-1]
        e50 = ema(p_series, 50).iloc[-1]
        e100 = ema(p_series, 100).iloc[-1]
        e200 = ema(p_series, 200).iloc[-1]
        
        price_cond = (ltp > e200) and (ltp > e100) and (ltp > e50) and (ltp > e21)
        
        if price_cond:
            rat_dict = safe_ratio(p_series_dict, base_s_dict)
            if rat_dict is not None:
                rat = pd.Series(rat_dict)
                if not rat.empty:
                    rs21 = rs_calc(rat, 21).iloc[-1]
                    rs63 = rs_calc(rat, 63).iloc[-1]
                    rs126 = rs_calc(rat, 126).iloc[-1]
                    rs252 = rs_calc(rat, 252).iloc[-1]
                    rs_cond = (rs21 > 0) and (rs63 > 0) and (rs126 > 0) and (rs252 > 0)
                    if rs_cond:
                        scan_results.append({"Symbol": s["name"], "Industry": s["industry"], "LTP": float(ltp), "Status": "STRONG BUY", "RS 21": float(rs21), "RS 63": float(rs63), "RS 126": float(rs126), "RS 252": float(rs252)})
    
    return jsonify({'data': scan_results})

if __name__ == '__main__':
    app.run(debug=True)
