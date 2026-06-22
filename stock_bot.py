import os
import datetime
import multiprocessing
from flask import Flask
import discord
import yfinance as yf
import pandas as pd
from finmind.data import DataLoader

# ================= 網頁伺服器設定 =================
app = Flask('')

@app.route('/')
def home():
    return "🤖 全功能股市查價機器人正在雲端線上安全運作中！"

def run_flask_process(port):
    """在完全獨立的進程中執行 Flask，避開 Python 3.14 的異步相容性問題"""
    from werkzeug.serving import make_server
    print(f"🤖 網頁偽裝伺服器正在獨立進程中啟動 (Port: {port})...")
    server = make_server('0.0.0.0', port, app)
    server.serve_forever()
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

# 2. 建立機器人實例
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✨ 機器人已經登入成功，目前身分是: {client.user} ✨')
    print("👉 已經可以在 Discord 頻道輸入 '!查價 股票名稱' 來呼叫機器人！")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('!查價 '):
        query = message.content.replace('!查價 ', '').strip()
        
        await message.channel.send(f"🔍 正在為您全面分析 `{query}` 的技術面、基本面、籌碼面與新聞，請稍候...")
        
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
        try:
            info = stock.info
            pe_ratio = round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else "無"
            eps = round(info.get('trailingEps', 0), 2) if info.get('trailingEps') else "無"
            yield_raw = info.get('dividendYield', 0)
            div_yield = f"{round(yield_raw * 100, 2)}%" if yield_raw else "無"
        except Exception:
            pe_ratio, eps, div_yield = "暫無資料", "暫無資料", "暫無資料"

        # ---------------- 👥 籌碼面抓取 (三大法人) ----------------
        chip_text = "非台股標的，暫不提供三大法人籌碼。"
        if ".TW" in ticker or ".TWO" in ticker:
            try:
                stock_id = ticker.split('.')[0]
                fm_api = DataLoader()
                end_date = datetime.date.today().strftime('%Y-%m-%d')
                start_date = (datetime.date.today() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
                
                chip_df = fm_api.taiwan_stock_institutional_investors(
                    stock_id=stock_id, start_date=start_date, end_date=end_date
                )
                
                if not chip_df.empty:
                    latest_chip_date = chip_df['date'].max()
                    day_chip = chip_df[chip_df['date'] == latest_chip_date]
                    
                    foreign = day_chip[day_chip['name'].str.contains('外資|陸資', na=False)]
                    trust = day_chip[day_chip['name'].str.contains('投信', na=False)]
                    dealer = day_chip[day_chip['name'].str.contains('自營商', na=False)]
                    
                    f_net = int(foreign['buy'].sum() - foreign['sell'].sum()) // 1000 if not foreign.empty else 0
                    t_net = int(trust['buy'].sum() - trust['sell'].sum()) // 1000 if not trust.empty else 0
                    d_net = int(dealer['buy'].sum() - dealer['sell'].sum()) // 1000 if not dealer.empty else 0
                    
                    def fmt_chip(val):
                        if val > 0: return f"🟢 買超 +{val} 張"
                        elif val < 0: return f"🔴 賣超 {val} 張"
                        return "⚪ ❌無買賣超"

                    chip_text = f"📅 數據日期：`{latest_chip_date}`\n" \
                                f"👤 外資法人：{fmt_chip(f_net)}\n" \
                                f"👤 投信法人：{fmt_chip(t_net)}\n" \
                                f"👤 自營法人：{fmt_chip(d_net)}"
                else:
                    chip_text = "⏳ 今日法人籌碼尚未更新或暫無資料。"
            except Exception as e:
                chip_text = "❌ 籌碼面資料讀取失敗。"

        # ---------------- 📰 相關重大新聞 ----------------
        news_text = "暫無相關新聞資訊。"
        try:
            news_list = stock.news
            if news_list:
                news_lines = []
                for item in news_list[:3]:
                    title = item.get('title', '未知標題')
                    link = item.get('link', '#')
                    if len(title) > 28:
                        title = title[:28] + "..."
                    news_lines.append(f"• [{title}]({link})")
                news_text = "\n".join(news_lines)
        except Exception:
            news_text = "⚠️ 無法取得即時新聞。"

        # ---------------- 🎨 製作 Discord Embed 字卡 ----------------
        embed = discord.Embed(
            title=f"📊 {ticker} 綜合分析報告",
            description=f"**🔥 當前狀態：** `{status_text}`",
            color=embed_color,
            timestamp=datetime.datetime.utcnow()
        )
        
        tech_field = f"**💵 最新收盤：** `{latest_price}`\n" \
                     f"**🔹 5MA 均線：** `{ma5}`\n" \
                     f"**🔸 20MA 均線：** `{ma20}`\n" \
                     f"**⚡ 14日 RSI：** `{rsi14}`\n" \
                     f"**📊 成交量能：** `{vol_ratio} 倍` (相較5日均量)"
        embed.add_field(name="📈 技術面指標", value=tech_field, inline=False)
        
        fund_field = f"**🎯 本益比 (PE)：** `{pe_ratio} 倍`\n" \
                     f"**💰 每股盈餘 (EPS)：** `${eps}`\n" \
                     f"**💎 現金殖利率：** `{div_yield}`"
        embed.add_field(name="💎 基本面數據", value=fund_field, inline=False)
        
        embed.add_field(name="👥 法人籌碼面 (張數以千計捨入)", value=chip_text, inline=False)
        embed.add_field(name="📰 最新重大消息", value=news_text, inline=False)
        embed.set_footer(text="數據僅供參考，投資請謹慎評估")
        
        await message.channel.send(embed=embed)

# 4. 啟動機器人
if __name__ == "__main__":
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    port_num = int(os.getenv("PORT", 8080))
    
    if DISCORD_BOT_TOKEN:
        # 💡 使用 multiprocessing (獨立多進程) 啟動 Flask，完美防禦環境相容性衝突
        flask_process = multiprocessing.Process(target=run_flask_process, args=(port_num,))
        flask_process.daemon = True
        flask_process.start()
        
        print("🤖 正在連線至 Discord 伺服器...")
        client.run(DISCORD_BOT_TOKEN)
    else:
        print("❌ 錯誤：找不到 DISCORD_BOT_TOKEN 環境變數，請檢查 Render 後台設定！")
