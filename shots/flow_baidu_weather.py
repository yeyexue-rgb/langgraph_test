"""临时自动化流程:百度搜索武汉天气。

由 playwright-skill 的 browser_run.py run 模式调用,
需要定义 run(page) 函数。

直接访问搜索结果 URL（首页表单交互容易触发百度安全验证）。
"""

from __future__ import annotations

from urllib.parse import quote


QUERY = "今天武汉的天气如何"


def run(page) -> str:
    # 1. 直接打开搜索结果页，等待加载完成。
    search_url = f"https://www.baidu.com/s?wd={quote(QUERY)}"
    page.goto(search_url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")

    # 2. 检测是否命中安全验证。
    body_text = page.locator("body").inner_text()

    if "百度安全验证" in body_text:
        page.screenshot(path="shots/baidu_captcha.png", full_page=True)
        return "BLOCKED: 触发百度安全验证，截图见 shots/baidu_captcha.png"

    page.screenshot(path="shots/baidu_2_results.png", full_page=True)

    # 3. 提取首屏文本（天气卡片通常在最前）。
    results = page.locator("#content_left")
    container = results if results.count() else page.locator("body")
    text = container.first.inner_text()
    snippet = "\n".join(text.splitlines()[:60])

    return f"搜索结果首屏文本:\n{snippet}"
