import os
import sys
import datetime
import threading
import requests
import pandas as pd
import yfinance as yf
import discord
from flask import Flask

# ==================== 1. Flask 背景輕量伺服器 (Render 活體檢查用) ====================
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    # Render 會自動注入 PORT 環境變數，若無則預設 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 啟動 Flask 執行緒
threading.Thread(target=run_flask, daemon=True).start()
print("🚀 Flask 網頁監聽服務已在背景啟動")


# ==================== 2. 籌碼面：FinMind API 抓取函式 ====================
def get_taiwan_chips(stock_id):
    """
    透過 FinMind 免費 API 取得最新交易日的三大法人買賣超資料 (單位：張)
    """
    try:
        # 移除 yfinance 可能帶有的 .TW 或 .TWO 尾綴，FinMind 只需要純數字 (如 4958)
        clean_id = stock_id.split('.')[0]
        url = "https://api.finmindtrade.com/api/v4/data"
        
        # 抓取最近 10 天的資料，確保能涵蓋到最新的一個交易日（避開週休二日或連假）
        start_date = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        
        parameter = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": clean_id,
            "start_date": start_date
        }
        
        response = requests.get(url, params=parameter, timeout=8)
        res_key = response.json()
        
        if res_key.get("status") == 200 and res_key.get("data"):
            df_chips = pd.DataFrame(res_key["data"])
            # 依日期排序
            df_chips = df_chips.sort_values(by="date")
            
            # 取得最新的那一天交易日
            latest_date = df_chips["date"].iloc[-1]
            latest_data = df_chips[df_chips["date"] == latest_date]
            
            chips_summary = {"date": latest_date, "外資": 0, "投信": 0, "自營商": 0}
            
            # 名稱映射字典
            name_map = {
                "Foreign_Investor": "外資",
                "Investment_Trust": "投信",
                "Dealer": "自營商",
                "Dealer_Self": "自營商",
                "Dealer_Hedging": "自營商"
            }
            
            # 統計各大法人買賣超 (買進股數 - 賣出股數)
            for _, row in latest_data.iterrows():
                eng_name = row.get("name")
                chi_name = name_map.get(eng_name, None)
                
                if chi_name:
                    net_shares = int(row.get("buy", 0)) - int(row.get("sell", 0))
                    # FinMind 回傳為「股數」，除以 1000 換算為「張數」，取小數點後1位
                    net_lots = round(net_shares / 1000, 1)
                    chips_summary[chi_name] += net_lots
            
            return chips_summary
    except Exception as e:
        print(f"⚠️ 籌碼面資料抓取失敗: {e}")
    return None


# ==================== 3. Discord 機器人主程式 ====================
# 讀取環境變數
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN.strip() == "":
    print("❌ 【錯誤】找不到環境變數 DISCORD_BOT_TOKEN，程式終止！")
    sys.exit(1)

# 設定 Discord 意圖 (Intents)
intents = discord.Intents.default()
intents.message_content = True  # 允許機器人讀取對話訊息
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✨ 機器人已經登入成功，目前身分是: {client.user} ✨")

@client.event
async def on_message(message):
    # 排除機器人自身的訊息，避免無限循環
    if message.author == client.user:
        return

    # 觸發指令設定為： !stock 股票代號 (例如: !stock 4958)
    if message.content.startswith("!stock "):
        try:
            # 解析使用者輸入的代號
            parts = message.content.split(" ")
            if len(parts) < 2:
                await message.channel.send("⚠️ 請輸入正確格式，例如：`!stock 4958`")
                return
                
            query = parts[1].strip()
            
            # 自動補上台股尾綴 (預設先查上市 .TW)
            if not query.endswith((".TW", ".TWO")):
                stock_code = f"{query}.TW"
            else:
                stock_code = query

            await message.channel.send(f"🔍 正在努力分析 `{stock_code}` 中，請稍候...")

            # 抓取技術面、基本面資料
            stock = yf.Ticker(stock_code)
            data = stock.history(period="3mo")

            # 如果上市查無資料，嘗試改成上櫃 (.TWO) 再查一次
            if data.empty and not query.endswith(".TWO"):
                stock_code = f"{query}.TWO"
                stock = yf.Ticker(stock_code)
                data = stock.history(period="3mo")

            if data.empty:
                await message.channel.send(f"❌ 找不到 `{query}` 的股市資料，請確認代號是否正確。")
                return

            # 🔥 【核心修復】剔除尚未開盤、Close為 NaN 的空白列，防止夜間/週末查價時均線變 nan
            data = data.dropna(subset=['Close'])
            if data.empty:
                await message.channel.send("❌ 該股票近期無有效交易數據。")
                return

            # ---------------- 📊 技術面計算 ----------------
            data['5MA'] = data['Close'].rolling(window=5).mean()
            data['20MA'] = data['Close'].rolling(window=20).mean()

            # 計算 14日 RSI
            delta = data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            data['RSI'] = 100 - (100 / (1 + rs))

            # 取出最新一筆有效交易日的數據
            latest = data.iloc[-1]
            close_val = round(latest['Close'], 2)
            ma5_val = round(latest['5MA'], 2)
            ma20_val = round(latest['20MA'], 2)
            rsi_val = round(latest['RSI'], 1) if not pd.isna(latest['RSI']) else "計算中"

            # 趨勢判斷
            trend = "📈 短期趨勢偏多 (5MA > 20MA)" if ma5_val > ma20_val else "📉 短期趨勢偏空 (5MA < 20MA)"

            # ---------------- 🏢 基本面數據 ----------------
            info = stock.info
            pe_ratio = info.get('trailingPE', '無')
            if pe_ratio != '無': pe_ratio = f"{round(pe_ratio, 2)} 倍"
            
            eps = info.get('trailingEps', '無')
            if eps != '無': eps = f"${round(eps, 2)}"
            
            yield_rate = info.get('dividendYield', '無')
            if yield_rate != '無' and yield_rate is not None:
                yield_rate = f"{round(yield_rate * 100, 2)}%"
            else:
                yield_rate = "無"

            # ---------------- 👥 籌碼面數據 ----------------
            chips = get_taiwan_chips(query)
            if chips:
                def format_chip(val):
                    if val > 0: return f"🟢 買超 +{val} 張"
                    elif val < 0: return f"🔴 賣超 {val} 張"
                    return "⚪ 估平 0 張"
                
                chips_text = (
                    f"最新交易日 ({chips['date']})：\n"
                    f" • 外資：`{format_chip(chips['外資'])}`\n"
                    f" • 投信：`{format_chip(chips['投信'])}`\n"
                    f" • 自營商：`{format_chip(chips['自營商'])}`"
                )
            else:
                chips_text = "⚠️ 暫時無法取得該股籌碼面數據"

            # ---------------- ✉️ 組裝並發送綜合報告 ----------------
            report = f"""
📋 **{stock_code} 綜合分析報告**
當前狀態：{trend}

**【技術面指標】**
• 最新收盤價：`${close_val}`
• 5MA 均線：`${ma5_val}`
• 20MA 均線：`${ma20_val}`
• 14日 RSI：`{rsi_val}`

**【基本面數據】**
• 本益比 (PE)：`{pe_ratio}`
• 每股盈餘 (EPS)：`{eps}`
• 現金殖利率：`{yield_rate}`

**【籌碼面數據 (三大法人)】**
{chips_text}

*數據僅供參考，投資請謹慎評估。*
            """
            await message.channel.send(report)

        except Exception as e:
            await message.channel.send(f"❌ 查詢時發生未預期的錯誤: {e}")

# 啟動 Discord 機器人
client.run(DISCORD_BOT_TOKEN)
