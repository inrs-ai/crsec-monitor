# monitor_edge.py
# 说明：在 GitHub Actions 上使用 Selenium + Edge 抓取目标页面并生成 index.html 与 history.txt
# 修正版：增加了窗口大小设置、User-Agent伪装及更强的元素定位逻辑

import os
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import smtplib
import ssl
from email.message import EmailMessage

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
OUTPUT_FILE = "index.html"

def send_email(subject: str, body: str):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and EMAIL_FROM and EMAIL_TO):
        print("邮件配置不完整，跳过发送邮件")
        return
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

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
        print("邮件已发送（已调用 SMTP）")
    except Exception as e:
        print("发送邮件失败:", e)

def safe_text(el):
    try:
        return el.text.strip()
    except Exception:
        return ""

def extract_update_from_row(el):
    """
    尝试从元素（行或容器）中提取日期
    """
    try:
        # 1. 尝试直接在文本中正则匹配日期
        all_text = safe_text(el)
        # 匹配 YYYY-MM-DD 或 YYYY/MM/DD 或 YYYY年MM月DD日
        date_pattern = r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}"
        dates = re.findall(date_pattern, all_text)
        if dates:
            # 返回找到的第一个日期
            return dates[0]

        # 2. 如果没找到，尝试按列遍历 (针对标准表格)
        tag = el.tag_name.lower()
        tr = el if tag == "tr" else el.find_element(By.XPATH, "./ancestor::tr")
        tds = tr.find_elements(By.TAG_NAME, "td")
        for td in tds:
            txt = safe_text(td)
            if re.search(date_pattern, txt):
                return txt
        
        return None
    except Exception as e:
        print(f"extract_update_from_row 异常: {e}")
        return None

def fetch_once():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    # --- 关键修正 1: 设置大分辨率，确保加载桌面版页面布局 ---
    opts.add_argument("--window-size=1920,1080")
    # --- 关键修正 2: 添加 User-Agent 防止被识别为爬虫拒绝服务 ---
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")
    
    driver = webdriver.Edge(options=opts)
    updated_text = None
    
    try:
        print(f"正在访问: {URL}")
        driver.set_page_load_timeout(60)
        driver.get(URL)

        wait = WebDriverWait(driver, 20)
        
        # --- 关键修正 3: 等待特定目标文本出现，而不仅仅是 body ---
        # 尝试查找包含 "通达信" 的元素，确保内容已动态加载
        try:
            print("等待页面内容加载...")
            wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '通达信')]")))
            print("检测到关键文本，页面已渲染。")
        except Exception:
            print("未直接检测到关键词，尝试继续解析...")

        # 截图调试
        driver.save_screenshot("debug_screenshot.png")
        with open("debug_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        # 定位逻辑优化
        # 使用 normalize-space 忽略 HTML 源码中的换行和多余空格
        # 策略 A: 查找包含 TARGET 的 tr
        target_rows = driver.find_elements(By.XPATH, f"//tr[contains(normalize-space(.), '{TARGET}')]")
        
        if target_rows:
            print(f"找到 {len(target_rows)} 个包含目标的表格行")
            for row in target_rows:
                res = extract_update_from_row(row)
                if res:
                    updated_text = res
                    break
        
        # 策略 B: 如果表格定位失败，全局查找包含 TARGET 的元素，然后找其附近的日期
        if not updated_text:
            print("策略 A 未找到日期，尝试策略 B (相邻查找)...")
            # 找到包含名字的元素
            elements = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{TARGET}')]")
            for el in elements:
                # 尝试找父级 tr
                try:
                    parent_tr = el.find_element(By.XPATH, "./ancestor::tr")
                    res = extract_update_from_row(parent_tr)
                    if res: 
                        updated_text = res
                        break
                except:
                    continue

        if not updated_text:
            updated_text = "未找到日期 (Parsed None)"
            print("警告: 页面已加载但未能提取到日期格式")

    except Exception as e:
        print("抓取过程发生异常:", e)
        updated_text = f"Error: {str(e)}"
    finally:
        driver.quit()

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
  <h3>历史（最近 50 条）</h3>
  <ul>
"""
    # 倒序显示，最新的在上面
    for line in reversed(history[-50:]):
        html += f"    <li>{line}</li>\n"
    html += """
  </ul>
  <p style="font-size:0.8em; color:#666;">由 GitHub Actions 每日自动更新并发布到 GitHub Pages。</p>
</body>
</html>
"""
    return html

def main():
    value = fetch_once()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # 简单的去重逻辑：如果抓取失败(Error或None)，尽量不要覆盖历史，或者单独记录
    # 这里假设 value 只要不是 None 就记录
    if value and "Error" not in value and "Parsed None" not in value:
        entry = f"{now} — {value}"
    else:
        entry = f"{now} — [抓取异常] {value}"

    history = read_history()
    
    # 只有当最新的有效记录不同时才发邮件 (避免重复报错刷屏)
    # 这里简化为：只要内容变了就记录
    last = history[-1] if history else None
    
    # 如果本次是异常，且上次也是异常，可能就不需要重复写了？
    # 简单起见，这里总是写入文件，但可以控制发邮件逻辑
    if last != entry:
        append_history(entry)
        # 只有抓取成功且变化时才发邮件，或者你可以选择异常也发
        if "抓取异常" not in entry:
            subject = "国新证券软件下载 更新时间变更"
            body = f"检测到变更\n时间: {now}\n新值: {value}\n来源: {URL}"
            send_email(subject, body)
    
    # 重新读取用于生成 HTML
    history = read_history()
    html = build_html(value, history)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("完成，输出写入", OUTPUT_FILE)

if __name__ == "__main__":
    main()
