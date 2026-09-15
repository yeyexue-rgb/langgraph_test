---
name: playwright-skill
description: Automates browsers with Python Playwright to open pages, click, fill forms, assert elements, take screenshots and export test reports. Use when the user asks to automate a web page, run browser tests, take page screenshots, verify UI elements, or scrape rendered page content.
---

# Playwright 浏览器自动化

使用本项目虚拟环境中的 Python Playwright(已安装,Chromium 内核就绪)
完成网页操作、断言验证、截图取证与报告输出。

## 环境约定(本项目)

- Python 解释器:`.venv/Scripts/python.exe`
- 运行脚本:`.venv/Scripts/python.exe .qoder/skills/playwright-skill/scripts/browser_run.py ...`
- 内核缺失时执行一次:`.venv/Scripts/python.exe -m playwright install chromium`
- 工作目录始终使用项目根目录,脚本内路径用相对路径。

## 快速开始

优先使用内置脚本,而不是每次现写代码:

```bash
# 打开页面并截图（默认 headless）
.venv/Scripts/python.exe .qoder/skills/playwright-skill/scripts/browser_run.py screenshot --url https://example.com --out shots/home.png

# 打开页面检查元素是否存在并可见
.venv/Scripts/python.exe .qoder/skills/playwright-skill/scripts/browser_run.py check --url https://example.com --selector "h1"

# 执行自定义自动化脚本（复杂场景，脚本需定义 run(page) 函数）
.venv/Scripts/python.exe .qoder/skills/playwright-skill/scripts/browser_run.py run --script my_flow.py
```

## 核心操作模式

### 1. 同步脚本骨架

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(url, wait_until="domcontentloaded")
    # ... 操作与断言 ...
    browser.close()
```

### 2. 定位元素(优先级从高到低)

1. `page.get_by_role("button", name="提交")` — 语义化,首选;
2. `page.get_by_label("用户名")` / `page.get_by_placeholder(...)` — 表单场景;
3. `page.get_by_test_id("submit-btn")` — 有 data-testid 时;
4. `page.locator("css=...")` — 兜底,避免脆弱的层级选择器。

### 3. 交互与等待

- 点击/填写:`locator.click()`、`locator.fill("文本")`;
- 等待用显式断言,禁止 `time.sleep`:
  `expect(locator).to_be_visible(timeout=10_000)`;
- 页面跳转后 `page.wait_for_load_state("networkidle")`。

### 4. 断言(使用 expect)

```python
from playwright.sync_api import expect

expect(page.get_by_role("heading")).to_have_text("欢迎")
expect(page.get_by_test_id("result")).to_contain_text("成功")
```

### 5. 截图取证

```python
page.screenshot(path="shots/step1.png", full_page=True)
locator.screenshot(path="shots/component.png")  # 局部截图
```

## 工作流清单

执行自动化任务时复制此清单跟踪进度:

```
- [ ] 1. 明确目标页面与验证点
- [ ] 2. 先用 screenshot 命令确认页面可访问、结构符合预期
- [ ] 3. 编写/执行操作脚本,每关键步骤截图
- [ ] 4. 断言失败时保存失败截图与 page.content() 片段
- [ ] 5. 汇总结果到报告(见下方报告模板)
```

## 报告模板

任务结束后按此结构输出:

```markdown
## 自动化执行报告
- 目标: [一句话描述]
- 环境: Chromium headless / 1280x900
- 步骤结果:
  1. [步骤] ✅/❌ [证据截图路径]
- 结论: 通过 / 失败(附失败原因与截图)
```

## 常见问题

| 现象 | 处理 |
|------|------|
| `Executable doesn't exist` | 运行 `-m playwright install chromium` |
| 元素找不到 | 先 `screenshot` + `page.content()` 确认真实 DOM |
| 页面未渲染完 | `wait_until="networkidle"` 或等待具体元素 |
| 动态内容闪断 | 用 `expect(...).to_be_visible()` 轮询,不用 sleep |

## 附加资源

- 更多定位器与 API 细节见 [reference.md](reference.md)
