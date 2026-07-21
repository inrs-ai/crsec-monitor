import os
import re
import asyncio
from datetime import datetime, UTC
import nodriver as uc
from bs4 import BeautifulSoup
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

URL = "https://www.crsec.com.cn/link/download.html"
TARGET = "国新证券通达信行情交易软件"

# 邮件配置
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 0)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")

HISTORY_FILE = "history.txt"
OUTPUT_DIR = "public"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "index.html")

def send_email(subject: str, body_text: str, body_html: str = None):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and EMAIL_FROM and EMAIL_TO):
        print("邮件配置不完整，跳过发送邮件")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("Notification", EMAIL_FROM))
        msg["To"] = EMAIL_TO
        
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype='html')

        if SMTP_PORT == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except Exception:
                    pass
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        print("邮件已发送成功")
    except Exception as e:
        print("发送邮件失败:", e)

def extract_date_from_text(text):
    """从任意文本中提取并格式化日期"""
    if not text:
        return None
    date_pattern = r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}"
    dates = re.findall(date_pattern, text)
    if dates:
        date_str = dates[0].replace('/', '-').replace('年', '-').replace('月', '-').replace('日', '')
        parts = date_str.split('-')
        if len(parts) == 3:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        return date_str
    return None

async def fetch_once():
    updated_text = None
    browser = None
    try:
        print(f"正在访问: {URL}")
        # 启动无头浏览器 (Ubuntu-latest 自带 Chrome，nodriver 会自动寻址)
        browser = await uc.start(
            browser_executable_path="/usr/bin/google-chrome",
            headless=True,
            no_sandbox=True,  # <--- 必须显式传递这个参数
            browser_args=["--disable-gpu", "--window-size=1920,1080"]
        )
        
        page = await browser.get(URL)
        await asyncio.sleep(4)  # 等待 Vue 页面初始渲染
        await page.save_screenshot("page_load.png")

        # 找到并点击 "电脑版" 标签
        tabs = await page.find_all("电脑版")
        for tab in tabs:
            try:
                await tab.click()
                print("已点击电脑版标签")
                break
            except:
                pass
                
        await asyncio.sleep(2)  # 等待列表数据刷新
        await page.save_screenshot("after_tab_click.png")

        # 获取渲染后的完整 HTML 交给 BeautifulSoup 分析（更稳定、不涉及复杂的 DOM evaluate）
        html_content = await page.get_content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"正在解析 HTML 查找: {TARGET}")
        
        # 策略 1: 遍历所有的表格行 <tr>，由于结构通常在表格中
        for tr in soup.find_all("tr"):
            text = tr.get_text(" ", strip=True)
            if TARGET in text or ("国新证券" in text and "通达信" in text):
                date_match = extract_date_from_text(text)
                if date_match:
                    updated_text = date_match
                    print(f"在表格行中找到日期: {updated_text}")
                    break
        
        # 策略 2: Fallback 如果没在 tr 中找到，暴力搜索全文每一行
        if not updated_text:
            body_text = soup.body.get_text("\n", strip=True) if soup.body else ""
            for line in body_text.split('\n'):
                if TARGET in line or "通达信" in line:
                    date_match = extract_date_from_text(line)
                    if date_match:
                        updated_text = date_match
                        print(f"在文本行中找到日期: {updated_text}")
                        break

        if not updated_text:
            updated_text = "未找到日期 (Parsed None)"
            print("警告: 页面中未能解析出日期")

    except Exception as e:
        print(f"抓取过程发生异常: {e}")
        updated_text = f"Error: {str(e)}"
    finally:
        if browser:
            browser.stop()

    return updated_text

def read_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip()]

def append_history(entry):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

def build_html(value, history):
    # 使用 Python 3.13 推荐的时间格式
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    html = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>国新证券 更新时间监控</title>
    <style>
        body {{ font-family: sans-serif; max-width: 800px; margin: 20px auto; padding: 0 20px; }}
        pre {{ background: #f4f4f4; padding: 10px; border-radius: 5px; }}
        .latest {{ color: #2e7d32; font-weight: bold; }}
    </style>
</head>
<body>
  <h2>国新证券 通达信行情交易软件 更新时间监控</h2>
  <p><strong>抓取时间（UTC）</strong>: {now}</p>
  <p><strong>当前抓取结果</strong>:</p>
  <pre class="latest">{value}</pre>
  <h3>历史（最近 10 条）</h3>
  <ul>
"""
    for line in reversed(history[-10:]):
        html += f"    <li>{line}</li>\n"
    html += """
  </ul>
  <p style="font-size:0.8em; color:#666;">由 GitHub Actions 每周自动更新并发布。</p>
</body>
</html>
"""
    return html

def build_email_html(value, now, url):
    domain = url.split('/')[2] if '://' in url else "查看详情"
    return f"""
    <div style="background-color: #f4f7f9; padding: 30px 15px; font-family: sans-serif;">
        <div style="max-width: 550px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e1e8ed;">
            <div style="background: linear-gradient(90deg, #3b82f6, #2563eb); padding: 20px; text-align: center;">
                <h2 style="margin: 0; color: #ffffff; font-size: 20px;">🚀 国新证券软件更新监测通知</h2>
            </div>
            <div style="padding: 30px;">
                <p style="color: #4b5563; font-size: 15px;">Hello, Mr.Jian~~</p>
                <div style="margin: 25px 0; padding: 20px; background-color: #f8fafc; border-left: 5px solid #3b82f6; border-radius: 4px;">
                    <div style="margin-bottom: 12px;">
                        <span style="display: block; color: #64748b; font-size: 12px; font-weight: bold;">最新变动</span>
                        <span style="color: #1e293b; font-size: 18px; font-weight: bold;">{value}</span>
                    </div>
                    <div>
                        <span style="display: block; color: #64748b; font-size: 12px; font-weight: bold;">检测时间</span>
                        <span style="color: #1e293b; font-size: 14px;">{now}</span>
                    </div>
                </div>
                <div style="text-align: center; margin-top: 30px;">
                    <a href="{url}" style="display: inline-block; padding: 12px 35px; background-color: #3b82f6; color: #ffffff; text-decoration: none; font-weight: bold; border-radius: 8px;">查看更新</a>
                </div>
            </div>
            <div style="background-color: #f1f5f9; padding: 15px; text-align: center; border-top: 1px solid #e2e8f0;">
                <p style="margin: 0; font-size: 12px; color: #94a3b8;">数据来源: {domain}</p>
            </div>
        </div>
    </div>
    """

async def main():
    value = await fetch_once()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    if value and "Error" not in value and "Parsed None" not in value:
        entry = f"{now} — {value}"
    else:
        entry = f"{now} — [抓取异常] {value}"

    history = read_history()
    last = history[-1] if history else None
    
    if last != entry:
        append_history(entry)
        if "抓取异常" not in entry:
            subject = "🔭软件更新监测通知"
            body_text = f"时间:{now}\n新值:{value}\n来源:\n{URL}"
            body_html = build_email_html(value, now, URL)
            send_email(subject, body_text, body_html)
    
    # 构建 HTML 页面用于 GitHub Pages 发布
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    history = read_history()
    html = build_html(value, history)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("完成，输出写入", OUTPUT_FILE)

if __name__ == "__main__":
    asyncio.run(main())
