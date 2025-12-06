# monitor_edge.py
# 说明：在 GitHub Actions 上使用 Selenium + Edge 抓取目标页面并生成 index.html 与 history.txt
# 要求：Actions 的运行器需安装 Edge 或脚本中安装 Edge（你的 workflow 已包含安装步骤）
# 注意：不要在日志中打印 secrets

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

# 邮件配置（在 Actions 中通过 Secrets 注入环境变量）
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

        # 465 -> SSL, 其他常用 587 -> STARTTLS
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
                    # 如果 STARTTLS 不支持，继续尝试登录（某些服务器在非加密端口上允许明文）
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
    接受一个元素（理想为 <tr> 或包含单元格的容器），尝试定位“更新时间”列或匹配日期字符串并返回文本。
    返回 None 表示未能提取。
    """
    try:
        # 确保我们有一个容器（tr 或可回溯到 tr）
        tag = el.tag_name.lower()
        if tag != "tr":
            try:
                tr = el.find_element(By.XPATH, "./ancestor::tr")
            except Exception:
                tr = el  # 退回到传入元素作为容器
        else:
            tr = el

        # 尝试找到包含表头的 table
        table = None
        try:
            table = tr.find_element(By.XPATH, "./ancestor::table")
        except Exception:
            table = None

        # 如果有表头，尝试根据表头索引定位更新时间列
        if table:
            headers = table.find_elements(By.XPATH, ".//th")
            header_texts = [safe_text(h) for h in headers]
            idx = None
            for i, t in enumerate(header_texts):
                if "更新时间" in t or "更新" in t or "时间" == t:
                    idx = i
                    break
            tds = tr.find_elements(By.TAG_NAME, "td")
            if idx is not None and idx < len(tds):
                return safe_text(tds[idx])

        # 兜底：在当前容器的 td 中查找包含“更新时间”或日期格式的文本
        tds = tr.find_elements(By.TAG_NAME, "td")
        for td in tds:
            txt = safe_text(td)
            if "更新时间" in txt:
                return txt
            if re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", txt):
                return txt

        # 再兜底：在容器内全文本中找日期
        all_text = safe_text(tr)
        m = re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}", all_text)
        if m:
            return m.group(0)

        # 最后返回整行拼接文本作为可读输出
        if tds:
            return " | ".join([safe_text(td) for td in tds if safe_text(td)])
        return all_text or None
    except Exception as e:
        print("extract_update_from_row 异常:", e)
        return None

def try_switch_to_frame_containing_text(driver, text, timeout=2):
    """
    遍历页面 iframe，尝试切换到包含指定文本的 frame。
    成功返回 True 并保持在该 frame；失败返回 False 并保持原 frame。
    """
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, fr in enumerate(iframes):
            try:
                driver.switch_to.frame(fr)
                time.sleep(0.3)
                if text in driver.page_source:
                    return True
                driver.switch_to.default_content()
            except Exception:
                # 切换失败则继续
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
        return False
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False

def fetch_once():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    # 可根据需要添加 user-agent 或其他参数
    driver = webdriver.Edge(options=opts)
    try:
        driver.set_page_load_timeout(60)
        driver.get(URL)

        wait = WebDriverWait(driver, 20)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            print("页面主体未在超时内加载，继续尝试抓取")

        # 尝试点击“电脑版”（若存在）
        try:
            el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.LINK_TEXT, "电脑版")))
            el.click()
            time.sleep(1.0)
        except Exception:
            try:
                el = driver.find_element(By.XPATH, "//*[contains(text(),'电脑版')]")
                el.click()
                time.sleep(1.0)
            except Exception:
                # 忽略，继续
                pass

        # 保存调试产物（Actions 会保留工作区文件，可作为工件上传）
        try:
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            driver.save_screenshot("page_screenshot.png")
            print("已保存 page_source.html 与 page_screenshot.png")
        except Exception as e:
            print("保存调试文件失败:", e)

        # 如果目标文本在 iframe 中，切换到包含该文本的 frame
        try:
            if TARGET not in driver.page_source:
                switched = try_switch_to_frame_containing_text(driver, TARGET)
                if switched:
                    print("已切换到包含目标文本的 iframe")
        except Exception:
            pass

        updated_text = None
        try:
            # 优先：直接定位包含目标文本的 tr
            xpath_tr = f"//tr[.//text()[contains(., '{TARGET}')]]"
            rows = driver.find_elements(By.XPATH, xpath_tr)
            if rows:
                updated_text = extract_update_from_row(rows[0])
            else:
                # 其次：查找 td 包含目标文本
                td_xpath = f"//td[contains(normalize-space(.), '{TARGET}')]"
                tds = driver.find_elements(By.XPATH, td_xpath)
                if tds:
                    # 上溯到 tr
                    try:
                        tr = tds[0].find_element(By.XPATH, "./ancestor::tr")
                        updated_text = extract_update_from_row(tr)
                    except Exception:
                        updated_text = extract_update_from_row(tds[0])
                else:
                    # 最后：全局查找任意包含目标文本的元素并尝试多种 ancestor
                    elems = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{TARGET}')]")
                    if elems:
                        e = elems[0]
                        for anc in ("ancestor::tr", "ancestor::td", "ancestor::li", "ancestor::div"):
                            try:
                                parent = e.find_element(By.XPATH, f"./{anc}")
                                updated_text = extract_update_from_row(parent)
                                if updated_text:
                                    break
                            except Exception:
                                continue
                    else:
                        raise Exception("页面中未找到包含目标文本的元素")
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
        subject = "国新证券软件下载 更新时间变更"
        body = f"检测到变更\n时间: {now}\n新值: {value}\n来源: {URL}"
        send_email(subject, body)
    history = read_history()
    html = build_html(value, history)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("完成，输出写入", OUTPUT_FILE)

if __name__ == "__main__":
    main()
    
