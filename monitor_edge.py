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

def send_email(subject: str, body_text: str, body_html: str = None):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and EMAIL_FROM and EMAIL_TO):
        print("邮件配置不完整，跳过发送邮件")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        
        # 设置纯文本内容（作为 HTML 无法显示时的备选）
        msg.set_content(body_text)
        
        # 如果提供了 HTML 内容，则添加它
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
    # 匹配 YYYY-MM-DD 或 YYYY/MM/DD 或 YYYY年MM月DD日
    date_pattern = r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}"
    dates = re.findall(date_pattern, text)
    if dates:
        # 清理日期格式
        date_str = dates[0]
        # 统一替换为 -
        date_str = date_str.replace('/', '-').replace('年', '-').replace('月', '-').replace('日', '')
        # 确保两位数的月份和日期
        parts = date_str.split('-')
        if len(parts) == 3:
            year = parts[0]
            month = parts[1].zfill(2)
            day = parts[2].zfill(2)
            return f"{year}-{month}-{day}"
        return date_str
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
        wait = WebDriverWait(driver, 20)  # 增加等待时间

        # 保存初始页面截图用于调试
        driver.save_screenshot("page_load.png")
        print("初始页面已截图: page_load.png")

        # --- 步骤 1: 找到并点击 "电脑版" 标签 ---
        print("正在寻找 '电脑版' 标签...")
        
        # 方法1: 尝试多种方式找到电脑版标签
        tab_selectors = [
            "//div[@class='tab-item' and contains(text(), '电脑版')]",
            "//li[contains(text(), '电脑版')]",
            "//a[contains(text(), '电脑版')]",
            "//span[contains(text(), '电脑版')]",
            "//*[contains(@class, 'tab') and contains(text(), '电脑版')]",
            "//*[@id='tab-pc']",
            "//*[contains(@onclick, 'pc') or contains(@onclick, 'computer')]"
        ]
        
        tab_found = False
        for selector in tab_selectors:
            try:
                tab_element = driver.find_element(By.XPATH, selector)
                print(f"找到电脑版标签: {selector}")
                
                # 滚动到元素并高亮显示
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", tab_element)
                time.sleep(1)
                
                # 使用JavaScript点击，更可靠
                driver.execute_script("arguments[0].click();", tab_element)
                print("已点击电脑版标签")
                tab_found = True
                time.sleep(3)  # 等待内容加载
                break
            except Exception as e:
                continue
        
        if not tab_found:
            print("警告: 未找到电脑版标签，尝试直接查找内容")
        
        # 保存点击后的页面截图
        driver.save_screenshot("after_tab_click.png")
        print("点击后页面已截图: after_tab_click.png")

        # --- 步骤 2: 查找目标软件 ---
        print(f"正在查找目标软件: {TARGET}")
        
        # 先获取页面源代码查看结构
        page_source = driver.page_source[:5000]  # 获取前5000字符用于调试
        print("页面源代码片段:", page_source)
        
        # 查找所有包含目标软件名称的元素
        try:
            # 使用更宽松的匹配
            target_elements = driver.find_elements(By.XPATH, f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{TARGET.lower()}')]")
            
            if not target_elements:
                # 尝试部分匹配
                target_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '国新证券') or contains(text(), '通达信')]")
            
            print(f"找到 {len(target_elements)} 个匹配元素")
            
            for i, element in enumerate(target_elements):
                try:
                    element_html = element.get_attribute('outerHTML')
                    element_text = element.text
                    print(f"元素{i+1}: {element_text[:100]}")
                    print(f"HTML片段: {element_html[:200]}")
                    
                    # 获取父元素和祖先元素的文本
                    parent = element.find_element(By.XPATH, "./..")
                    parent_text = parent.text if parent else ""
                    
                    # 获取整个行的文本（如果是表格行）
                    try:
                        row = element.find_element(By.XPATH, "./ancestor::tr")
                        row_text = row.text if row else ""
                        print(f"行文本: {row_text}")
                        
                        # 在行文本中查找更新时间
                        if row_text:
                            # 查找"更新"或"时间"关键字
                            if "更新" in row_text or "时间" in row_text:
                                date_match = extract_date_from_text(row_text)
                                if date_match:
                                    updated_text = date_match
                                    print(f"从行文本中找到日期: {updated_text}")
                                    break
                    except:
                        pass
                    
                    # 如果没有找到，查找兄弟元素中的时间
                    try:
                        siblings = parent.find_elements(By.XPATH, "./*")
                        for sibling in siblings:
                            sibling_text = sibling.text
                            if "更新" in sibling_text or "时间" in sibling_text:
                                date_match = extract_date_from_text(sibling_text)
                                if date_match:
                                    updated_text = date_match
                                    print(f"从兄弟元素中找到日期: {updated_text}")
                                    break
                    except:
                        pass
                    
                except Exception as e:
                    print(f"处理元素{i+1}时出错: {e}")
        
        except Exception as e:
            print(f"查找目标元素时出错: {e}")

        # --- 步骤 3: 如果上述方法失败，尝试在整个页面中搜索日期 ---
        if not updated_text:
            print("尝试在整个页面中搜索日期...")
            
            # 获取整个页面的文本
            full_text = driver.find_element(By.TAG_NAME, "body").text
            print(f"页面文本长度: {len(full_text)}")
            
            # 查找包含"更新时间"的文本
            for line in full_text.split('\n'):
                if "更新" in line or "时间" in line:
                    print(f"找到时间相关行: {line}")
                    date_match = extract_date_from_text(line)
                    if date_match:
                        updated_text = date_match
                        print(f"从页面文本中找到日期: {updated_text}")
                        break

        # --- 步骤 4: 如果仍然没找到，尝试直接查找所有日期格式的文本 ---
        if not updated_text:
            print("尝试查找所有日期格式的文本...")
            all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), '-')]")
            
            for element in all_elements[:50]:  # 检查前50个元素
                text = element.text
                date_match = extract_date_from_text(text)
                if date_match and len(date_match) > 8:  # 确保是完整的日期
                    # 检查这个日期是否在目标软件附近
                    try:
                        # 获取父容器，看看是否包含目标软件
                        parent = element.find_element(By.XPATH, "./ancestor::div[contains(text(), '国新') or contains(text(), '通达信')]")
                        if parent:
                            updated_text = date_match
                            print(f"从附近元素中找到日期: {updated_text}")
                            break
                    except:
                        continue

        if not updated_text:
            updated_text = "未找到日期 (Parsed None)"
            print("警告: 未找到日期")
            
            # 保存完整的页面源代码用于调试
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("已保存完整页面源代码到 debug_page.html")

    except Exception as e:
        print("抓取过程发生异常:", e)
        import traceback
        traceback.print_exc()
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
    # 提取域名称作为显示参考
    domain = url.split('/')[2] if '://' in url else "查看详情"
    
    return f"""
    <div style="background-color: #f4f7f9; padding: 30px 15px; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        <div style="max-width: 550px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #e1e8ed;">
            
            <div style="background: linear-gradient(90deg, #3b82f6, #2563eb); padding: 20px; text-align: center;">
                <h2 style="margin: 0; color: #ffffff; font-size: 20px; letter-spacing: 1px;">🚀 国新证券软件更新监测通知</h2>
            </div>
            
            <div style="padding: 30px;">
                <p style="color: #4b5563; font-size: 15px; line-height: 1.6;">Hello,Mr.Jian~~</p>
                
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

def main():
    value = fetch_once()
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
            # 1. 准备标题
            subject = "🔭软件更新监测通知"
            
            # 2. 准备纯文本内容 (兜底用)
            body_text = f"时间:{now}\n新值:{value}\n来源:\n{URL}"
            
            # 3. 准备漂亮 HTML 内容 (调用封装好的函数)
            body_html = build_email_html(value, now, URL)
            
            # 4. 发送邮件
            send_email(subject, body_text, body_html)
    
    # 重新读取用于生成 HTML
    history = read_history()
    html = build_html(value, history)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("完成，输出写入", OUTPUT_FILE)

if __name__ == "__main__":
    main()






