import os
import datetime
import multiprocessing
from flask import Flask

import discord
import yfinance as yf
import pandas as pd

# ================= 網頁伺服器設定 =================
app = Flask('')

@app.route('/')
def home():
    return "🤖 股市技術與基本面分析機器人正在雲端安全運作中！"

def run_flask_process(port_num):
    from werkzeug.serving import make_server
    print(f"🤖 網頁偽裝伺服器正在獨立進程中啟動 (Port: {port_num})...")
    server = make_server('0.0.0.0', port_num, app)
    server.serve_forever()
# ====================================================================================

intents = discord.Intents.default()
intents.message_content = True

STOCK_MAPPING = {
    "台積電": "2330.TW", "聯發科": "2454.TW", "鴻海": "2317.TW",
    "世芯": "3661.TW", "世芯-KY": "3661.TW", "信驊": "5274.TWO",
    "臻鼎": "4958.TW", "費半": "SOXX", "SOXX": "SOXX"
}

def get_stock_ticker(user_input):
    if user_input in STOCK_MAPPING:
        return STOCK_MAPPING[user_input]
    if user_input.isdigit():
        return f"{user_input}.TW"
    return user_input

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✨ 機器人已經登入成功，目前身分是: {client.user} ✨')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('!查價 '):
        query = message.content.replace('!查價 ', '').strip()
        
        await message.channel.send(f"🔍 正在為您全面分析 `{query}` 的技術面、基本面與最新新聞，請稍候...")
        
        try:
            ticker = get_stock_ticker(query)
            stock = yf.Ticker(ticker)
            
            try:
                data = stock.history(period="3mo")
            except Exception:
                data = pd.DataFrame()
            
            if data.empty:
                await message.channel.send(f"❌ 找不到 `{query}` 的資料，請確認名稱或代號是否正確。")
                return
                
            # ---------------- 📊 技術面計算 ----------------
            data['5MA'] = data['Close'].rolling(window=5).mean()
            data['20MA'] = data['Close'].rolling(window=20).mean()
            
            delta = data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            data['RSI'] = 100 - (100 / (1 + rs))
            
            if len(data) < 20:
                await message.channel.send("⚠️ 歷史數據不足，無法計算完整的技術指標。")
                return

            latest_price = round(data['Close'].iloc[-1], 2)
            ma5 = round(data['5MA'].iloc[-1], 2)
            ma20 = round(data['20MA'].iloc[-1], 2)
            rsi14 = round(data['RSI'].iloc[-1], 1) if not pd.isna(data['RSI'].iloc[-1]) else "計算中"
            
            avg_volume = data['Volume'].rolling(window=5).mean().iloc[-2]
            current_volume = data['Volume'].iloc[-1]
            vol_ratio = round(current_volume / avg_volume, 2) if avg_volume > 0 else 1.0
            
            yesterday_5ma = data['5MA'].iloc[-2]
            yesterday_20ma = data['20MA'].iloc[-2]
            today_5ma = data['5MA'].iloc[-1]
            today_20ma = data['20MA'].iloc[-1]
            
            is_golden_cross = (yesterday_5ma <= yesterday_20ma) and (today_5ma > today_20ma)
            
            if is_golden_cross:
                status_text = "🔥 發生黃金交叉！短均線突破長均線！"
                embed_color = discord.Color.red()
            elif ma5 > ma20:
                status_text = "📈 短期趨勢偏多 (5MA > 20MA)"
                embed_color = discord.Color.orange()
            else:
                status_text = "📉 短期趨勢偏空 (5MA < 20MA)"
                embed_color = discord.Color.green()

            # ---------------- 💎 基本面抓取 ----------------
            pe_ratio, eps, div_yield = "暫無資料", "暫無資料", "暫無資料"
            try:
                info = stock.info
                if info:
                    pe_ratio = round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else "無"
                    eps = round(info.get('trailingEps', 0), 2) if info.get('trailingEps') else "無"
                    yield_raw = info.get('dividendYield', 0)
                    div_yield = f"{round(yield_raw * 100, 2)}%" if yield_raw else "無"
            except Exception:
                pass

            # ---------------- 📰 相關重大新聞 ----------------
            news_text = "暫無相關新聞資訊。"
            try:
                news_list = stock.news
                if news_
