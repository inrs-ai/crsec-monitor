# monitor_edge.py
# 说明：在 GitHub Actions 上使用 Selenium + Edge 抓取目标页面并生成 index.html 与 history.txt

import os
import time
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
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

def extract_date_from_text(text):
    """从任意文本中提取日期"""
    if not text:
        return None
    # 匹配 YYYY-MM-DD 或 YYYY/MM/DD 或 YYYY年MM月DD日
    date_pattern = r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}"
    dates = re.findall(date_pattern, text)
    if dates:
        return dates[0]
    return None

def fetch_once():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0")
    
    driver = webdriver.Edge(options=opts)
    updated_text = None
    
    try:
        print(f"正在访问: {URL}")
        driver.set_page_load_timeout(60)
        driver.get(URL)
        wait = WebDriverWait(driver, 15)

        # --- 步骤 1: 尝试点击 "电脑版" 标签 ---
        try:
            print("正在寻找并点击 '电脑版' 标签...")
            # 寻找包含 "电脑版" 字样的可点击元素 (li, div, span, a)
            tab_xpath = "//*[contains(text(), '电脑版') and (self::li or self::div or self::span or self::a)]"
            tab_element = wait.until(EC.element_to_be_clickable((By.XPATH, tab_xpath)))
            
            # 点击标签
            driver.execute_script("arguments[0].click();", tab_element)
            time.sleep(2) # 等待内容切换动画完成
            print("已点击 '电脑版' 标签")
        except Exception as e:
            print(f"警告: 未能找到或点击 '电脑版' 标签，尝试直接解析 (可能已是默认页): {e}")

        # --- 步骤 2: 等待目标软件名称出现 ---
        print(f"正在定位目标软件: {TARGET}")
        # 这里使用 presence 即可，稍后我们用 JS 获取内容以防 display 问题
        target_el = wait.until(EC.presence_of_element_located((By.XPATH, f"//*[contains(text(), '{TARGET}')]")))
        
        # --- 步骤 3: 智能提取日期 ---
        # 策略 A: 找到目标元素的父级容器（可能是 tr 也可能是 div），获取整行文本
        print("找到目标元素，正在解析日期...")
        
        # 获取包含目标文本的元素
        target_elements = driver.find_elements(By.XPATH, f"//*[contains(text(), '{TARGET}')]")
        
        found_date = None
        
        for el in target_elements:
            # 向上找两层，通常能涵盖整个行信息 (tr 或者 div-row)
            # 尝试 1: 直接找最近的 tr
            try:
                row = el.find_element(By.XPATH, "./ancestor::tr")
                # 优先使用 textContent，因为它能获取到即使是隐藏样式的文本（有些网页懒加载会导致 .text 为空）
                row_text = row.get_attribute("textContent") 
                found_date = extract_date_from_text(row_text)
                if found_date:
                    print(f"策略 A (Table) 成功: {found_date}")
                    break
            except:
                pass

            # 尝试 2: 如果不是表格，找父级 div/ul
            if not found_date:
                try:
                    # 获取父级文本
                    parent = el.find_element(By.XPATH, "./..")
                    parent_text = parent.get_attribute("textContent")
                    found_date = extract_date_from_text(parent_text)
                    
                    # 如果父级没找到，再找父级的父级 (爷爷级)
                    if not found_date:
                        grandparent = el.find_element(By.XPATH, "./../..")
                        grandparent_text = grandparent.get_attribute("textContent")
                        found_date = extract_date_from_text(grandparent_text)
                    
                    if found_date:
                        print(f"策略 B (Div/List) 成功: {found_date}")
                        break
                except:
                    pass
        
        updated_text = found_date

        # --- 步骤 4: 终极兜底 (如果精确定位失败) ---
        if not updated_text:
            print("精确定位失败，尝试全页搜索...")
            # 获取整个 body 的文本
            body_text = driver.find_element(By.TAG_NAME, "body").get_attribute("innerText")
            # 截取目标文字附近的内容 (前后 200 字符)
            idx = body_text.find(TARGET)
            if idx != -1:
                snippet = body_text[idx:idx+300] # 往后找 300 字符
                updated_text = extract_date_from_text(snippet)
                if updated_text:
                    print(f"策略 C (全页片段匹配) 成功: {updated_text}")

        if not updated_text:
            updated_text = "未找到日期 (Parsed None)"
            # 保存截图以供调试
            driver.save_screenshot("debug_failed.png")
            print("警告: 即使在全页搜索后也未找到日期。")

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
    
    if value and "Error" not in value and "Parsed None" not in value:
        entry = f"{now} — {value}"
    else:
        entry = f"{now} — [抓取异常] {value}"

    history = read_history()
    last = history[-1] if history else None
    
    # 简单的去重与通知逻辑
    if last != entry:
        append_history(entry)
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
