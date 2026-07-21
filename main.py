import os
import re
import asyncio
from datetime import datetime
import nodriver as uc
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
# 统一存放在 public 文件夹供现代 GitHub Pages 部署
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
        print("邮件已发送（包含 HTML 格式）")
    except Exception as e:
        print("发送邮件失败:", e)

def extract_date_from_text(text):
    """从任意文本中提取日期"""
    if not text:
        return None
    date_pattern = r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}"
    dates = re.findall(date_pattern, text)
    if dates:
        date_str = dates[0]
        date_str = date_str.replace('/', '-').replace('年', '-').replace('月', '-').replace('日', '')
        parts = date_str.split('-')
        if len(parts) == 3:
            year = parts[0]
            month = parts[1].zfill(2)
            day = parts[2].zfill(2)
            return f"{year}-{month}-{day}"
        return date_str
    return None

async def fetch_once():
    updated_text = None
    browser = None
    
    try:
        print(f"正在初始化 nodriver 并访问: {URL}")
        # 启动无头浏览器
        browser = await uc.start(
            headless=True,
            browser_args=["--no-sandbox", "--disable-gpu", "--window-size=1920,1080"]
        )
        
        page = await browser.get(URL)
        await asyncio.sleep(4)  # 等待初始页面渲染
        
        # 截图用于调试
        await page.save_screenshot("page_load.png")
        print("初始页面已截图: page_load.png")

        # --- 步骤 1: 找到并点击 "电脑版" 标签 ---
        print("正在寻找 '电脑版' 标签...")
        try:
            # 使用 nodriver 直接在页面查找文本元素
            tabs = await page.find_all("电脑版")
            clicked = False
            for tab in tabs:
                try:
                    await tab.click()
                    clicked = True
                    print("已通过 nodriver click() 点击电脑版标签")
                    break
                except:
                    pass
            
            if not clicked:
                # 备用方案：通过执行 JS 强制点击
                print("常规点击失败，尝试使用 JS 点击...")
                js_code = """
                let els = document.querySelectorAll('*');
                for (let el of els) {
                    if (el.textContent.includes('电脑版') && el.children.length === 0) {
                        el.click();
                        return true;
                    }
                }
                return false;
                """
                await page.evaluate(js_code)
                
        except Exception as e:
            print(f"点击标签时发生警告: {e}")
            
        await asyncio.sleep(3)  # 等待点击后的内容加载
        await page.save_screenshot("after_tab_click.png")
        print("点击后页面已截图: after_tab_click.png")

        # --- 步骤 2: 查找目标软件并获取日期 ---
        print(f"正在查找目标软件: {TARGET}")
        
        # 获取所有包含目标软件名称的元素
        elements = await page.find_all(TARGET)
        if elements:
            for el in elements:
                # 使用 JS 获取其所在的表格行（tr）或父级容器的文本
                row_text = await page.evaluate("arguments[0].closest('tr')?.innerText || arguments[0].parentElement?.innerText", el)
                if row_text:
                    date_match = extract_date_from_text(row_text)
                    if date_match:
                        updated_text = date_match
                        print(f"从目标行文本中找到日期: {updated_text}")
                        break

        # --- 步骤 3: 如果上述方法失败，尝试在整个页面文本中搜索 ---
        if not updated_text:
            print("尝试在整个页面中搜索日期...")
            body_text = await page.evaluate("document.body.innerText")
            for line in body_text.split('\n'):
                if TARGET in line or "通达信" in line:
                    date_match = extract_date_from_text(line)
                    if date_match:
                        updated_text = date_match
                        print(f"从页面文本匹配行找到日期: {updated_text}")
                        break

        if not updated_text:
            updated_text = "未找到日期 (Parsed None)"
            print("警告: 未找到日期")
            
        # 保存完整源代码供调试
        html_content = await page.get_content()
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("已保存完整页面源代码到 debug_page.html")

    except Exception as e:
        print("抓取过程发生异常:", e)
        import traceback
        traceback.print_exc()
        updated_text = f"Error: {str(e)}"
    finally:
        if browser:
            browser.stop()

    return updated_text

def read_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip()]
    return lines

def append_history(entry):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")

def build_html(value, history):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
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
    <div style="background-color: #f4f7f9; padding: 30px 15px; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        <div style="max-width: 550px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #e1e8ed;">
            <div style="background: linear-gradient(90deg, #3b82f6, #2563eb); padding: 20px; text-align: center;">
                <h2 style="margin: 0; color: #ffffff; font-size: 20px; letter-spacing: 1px;">🚀 国新证券软件更新监测通知</h2>
            </div>
            <div style="padding: 30px;">
                <p style="color: #4b5563; font-size: 15px; line-height: 1.6;">Hello, Mr.Jian~~</p>
                <div style="margin: 25px 0; padding: 20px; background-color: #f8fafc; border-left: 5px solid #3b82f6; border-radius: 4px;">
                    <div style="margin-bottom: 12px;">
                        <span style="display: block; color: #64748b; font-size: 12px; text-transform: uppercase; font-weight: bold;">最新变动</span>
                        <span style="color: #1e293b; font-size: 18px; font-weight: 600;">{value}</span>
                    </div>
                    <div>
                        <span style="display: block; color: #64748b; font-size: 12px; text-transform: uppercase; font-weight: bold;">检测时间</span>
                        <span style="color: #1e293b; font-size: 14px;">{now}</span>
                    </div>
                </div>
                <div style="text-align: center; margin-top: 30px;">
                    <a href="{url}" style="display: inline-block; padding: 12px 35px; background-color: #3b82f6; color: #ffffff; text-decoration: none; font-weight: 600; border-radius: 8px; font-size: 15px; box-shadow: 0 4px 6px rgba(59, 130, 246, 0.2);">查看更新</a>
                </div>
            </div>
            <div style="background-color: #f1f5f9; padding: 15px; text-align: center; border-top: 1px solid #e2e8f0;">
                <p style="margin: 0; font-size: 12px; color: #94a3b8;">
                    数据来源: <span style="color: #64748b;">{domain}</span>
                </p>
            </div>
        </div>
    </div>
    """

async def main():
    value = await fetch_once()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
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
    
    # 构建 HTML 页面
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    history = read_history()
    html = build_html(value, history)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("完成，输出写入", OUTPUT_FILE)

if __name__ == "__main__":
    # 使用 asyncio 运行异步的主函数
    asyncio.run(main())
