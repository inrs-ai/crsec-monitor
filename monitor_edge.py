# monitor_edge.py
# 说明：使用 Selenium Manager（Selenium >=4.10）驱动 Edge，抓取目标页面并把结果写入 index.html
# 在 GitHub Actions 中运行时，Actions 会把生成的 index.html 提交到 gh-pages 分支以供 GitHub Pages 发布

import os, time, re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
import smtplib
from email.mime.text import MIMEText

URL = "https://www.crsec.com.cn/link/download.html"
TARGET = "国新证券通达信行情交易软件"

# 邮件配置（在 Actions 中通过 Secrets 注入环境变量）
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 0)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")

# 本地/Actions 中用于保存历史的文件名（Actions 会在工作区提交）
HISTORY_FILE = "history.txt"
OUTPUT_FILE = "index.html"

def send_email(subject: str, body: str):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and EMAIL_FROM and EMAIL_TO):
        print("邮件配置不完整，跳过发送邮件")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print("邮件已发送")
    except Exception as e:
        print("发送邮件失败:", e)

def extract_update_from_row(tr):
    """根据表头定位更新时间列并返回对应单元格文本；兜底返回整行拼接文本"""
    try:
        table = tr.find_element(By.XPATH, "./ancestor::table")
        headers = table.find_elements(By.XPATH, ".//th")
        header_texts = [h.text.strip() for h in headers]
        idx = None
        for i, t in enumerate(header_texts):
            if "更新时间" in t or "更新" in t:
                idx = i
                break
        tds = tr.find_elements(By.TAG_NAME, "td")
        if idx is not None and idx < len(tds):
            return tds[idx].text.strip()
        # 兜底：在 td 中找日期或包含“更新时间”的文本
        for td in tds:
            txt = td.text.strip()
            if "更新时间" in txt:
                return txt
            if re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", txt):
                return txt
        return " | ".join([td.text.strip() for td in tds])
    except Exception as e:
        print("extract_update_from_row 异常:", e)
        return None

def fetch_once():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    # Selenium Manager（selenium >=4.10）会自动处理驱动
    driver = webdriver.Edge(options=opts)
    try:
        driver.set_page_load_timeout(30)
        driver.get(URL)
        time.sleep(1.5)
        # 尝试点击“电脑版”
        try:
            el = driver.find_element(By.LINK_TEXT, "电脑版")
            el.click()
            time.sleep(1.0)
        except Exception:
            try:
                el = driver.find_element(By.XPATH, "//*[contains(text(),'电脑版')]")
                el.click()
                time.sleep(1.0)
            except Exception:
                print("未找到或无法点击“电脑版”，继续抓取当前页面")

        # 定位包含目标名称的元素并上溯到 tr
        updated_text = None
        try:
            elem = driver.find_element(By.XPATH, f"//*[contains(text(), '{TARGET}')]")
            tr = elem.find_element(By.XPATH, "./ancestor::tr")
            updated_text = extract_update_from_row(tr)
        except Exception as e:
            print("未能定位到目标软件行:", e)
            updated_text = f"抓取失败: {e}"

        return updated_text
    finally:
        try:
            driver.quit()
        except Exception:
            pass

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
<head><meta charset="utf-8"><title>国新证券 更新时间监控</title></head>
<body>
  <h2>国新证券 通达信行情交易软件 更新时间监控</h2>
  <p><strong>抓取时间（UTC）</strong>: {now}</p>
  <p><strong>当前抓取结果</strong>:</p>
  <pre>{value}</pre>
  <h3>历史（最近 50 条）</h3>
  <ul>
"""
    for line in history[-50:]:
        html += f"    <li>{line}</li>\n"
    html += """
  </ul>
  <p>由 GitHub Actions 每日自动更新并发布到 GitHub Pages。</p>
</body>
</html>
"""
    return html

def main():
    value = fetch_once()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"{now} — {value}"
    history = read_history()
    last = history[-1] if history else None
    if last != entry:
        append_history(entry)
        # 发送邮件通知（仅在变更时）
        subject = "国新证券软件下载 更新时间变更"
        body = f"检测到变更\n时间: {now}\n新值: {value}\n来源: {URL}"
        send_email(subject, body)
    # 重新读取历史并生成页面
    history = read_history()
    html = build_html(value, history)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("完成，输出写入", OUTPUT_FILE)

if __name__ == "__main__":
    main()
