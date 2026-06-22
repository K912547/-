import os
import threading
from flask import Flask  # 引入輕量網頁套件，供 Render 順利開機用
import discord
import yfinance as yf
import pandas as pd

# ================= 網頁伺服器設定（解決 Render Web Service 部署問題） =================
app = Flask('')

@app.route('/')
def home():
    return "🤖 股市查價機器人正在雲端線上安全運作中！"

def run_web_server():
    # Render 會自動動態分配 PORT，若無則預設為 8080
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
# ====================================================================================

# 1. 設定 intents 權限
intents = discord.Intents.default()
intents.message_content = True  # 開啟讀取訊息內容權限

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

# 3. 建立機器人實例
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✨ 機器人已經登入成功，目前身分是: {client.user} ✨')
    print("👉 已經可以在 Discord 頻道輸入 '!查價 股票名稱' 來呼叫機器人！")

@client.event
async def on_message(message):
    # 避免機器人自己回自己，造成無限迴圈
    if message.author == client.user:
        return

    # 觸發指令：只要在 Discord 輸入 "!查價 XXXXX" 就會觸發
    if message.content.startswith('!查價 '):
        # 取得使用者輸入的名稱/代號（把 '!查價 ' 切掉）
        query = message.content.replace('!查價 ', '').strip()
        
        # 提示處理中
        await message.channel.send(f"🤖 正在為您查詢 `{query}` 的資料，請稍候...")
        
        ticker = get_stock_ticker(query)
        stock = yf.Ticker(ticker)
        data = stock.history(period="2mo")
        
        if data.empty:
            await message.channel.send(f"❌ 找不到 `{query}` 的資料，請確認名稱或代號是否正確。")
            return
            
        data['5MA'] = data['Close'].rolling(window=5).mean()
        data['20MA'] = data['Close'].rolling(window=20).mean()
        
        if len(data) < 20:
            await message.channel.send("⚠️ 歷史數據不足，無法計算均線。")
            return

        latest_price = round(data['Close'].iloc[-1], 2)
        ma5 = round(data['5MA'].iloc[-1], 2)
        ma20 = round(data['20MA'].iloc[-1], 2)
        
        yesterday_5ma = data['5MA'].iloc[-2]
        yesterday_20ma = data['20MA'].iloc[-2]
        today_5ma = data['5MA'].iloc[-1]
        today_20ma = data['20MA'].iloc[-1]
        
        is_golden_cross = (yesterday_5ma <= yesterday_20ma) and (today_5ma > today_20ma)
        
        # 組裝回覆訊息
        reply_msg = f"**【股市分析報告】**\n> **標的:** `{ticker}`\n> **收盤價:** `{latest_price}`\n> **5MA:** `{ma5}` | **20MA:** `{ma20}`\n"
        
        if is_golden_cross:
            reply_msg += "🔥 **狀態:** `發生黃金交叉！短均線突破長均線！` 🔥"
        elif ma5 > ma20:
            reply_msg += "📈 **狀態:** `短期趨勢偏多 (5MA > 20MA)`"
        else:
            reply_msg += "📉 **狀態:** `短期趨勢偏空 (5MA < 20MA)`"
            
        # 直接在頻道回覆
        await message.channel.send(reply_msg)

# 4. 啟動機器人
if __name__ == "__main__":
    # 在背景先將虛擬網頁伺服器吵醒，防止 Render 因偵測不到 Port 而部署失敗
    t = threading.Thread(target=run_web_server)
    t.start()
    
    # 🔐 安全作法：從 Render 環境變數中讀取密碼
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if DISCORD_BOT_TOKEN:
        client.run(DISCORD_BOT_TOKEN)
    else:
        print("❌ 錯誤：找不到 DISCORD_BOT_TOKEN 環境變數，請檢查 Render 後台設定！")
