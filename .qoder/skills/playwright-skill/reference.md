# Playwright API 参考(按需查阅)

本文件是 [SKILL.md](SKILL.md) 的补充,仅在需要细节时阅读。

## 定位器速查

| 方法 | 适用场景 |
|------|---------|
| `get_by_role(role, name=)` | 按钮、链接、标题等语义元素 |
| `get_by_text("文本", exact=True)` | 精确文本匹配 |
| `get_by_label("标签")` | 带 label 的表单控件 |
| `get_by_placeholder("占位符")` | 输入框 |
| `get_by_test_id("id")` | `data-testid` 属性 |
| `locator("css=div.card >> nth=0")` | CSS 链式过滤 |
| `locator("xpath=//div[@id='x']")` | 兜底,慎用 |

## 常用过滤器

```python
cards = page.locator(".card").filter(has_text="待办")
first = cards.first
count = cards.count()
```

## 等待策略

| 场景 | 写法 |
|------|------|
| 元素可见 | `expect(loc).to_be_visible(timeout=10_000)` |
| 元素消失 | `expect(loc).not_to_be_visible()` |
| 网络空闲 | `page.wait_for_load_state("networkidle")` |
| 指定请求完成 | `page.wait_for_response("**/api/data")` |
| 新标签页 | `with page.expect_popup() as info: ...` |

## 表单与文件

```python
page.get_by_label("邮箱").fill("a@b.com")
page.get_by_role("combobox").select_option("bj")
page.get_by_label("头像").set_input_files("avatar.png")
page.get_by_role("checkbox").check()
```

## 上下文与登录态复用

```python
context = browser.new_context(storage_state="auth.json")  # 复用登录态
# ... 登录后保存:
context.storage_state(path="auth.json")
```

## 断言全集(常用)

`to_be_visible` / `to_be_enabled` / `to_have_text` /
`to_contain_text` / `to_have_value` / `to_have_count` /
`to_have_url` / `to_have_title`

## 执行自定义脚本模式

`browser_run.py run --script my_flow.py` 会导入脚本中的
`run(page)` 函数并传入已打开的 page 对象:

```python
# my_flow.py
def run(page):
    page.goto("https://example.com")
    page.screenshot(path="shots/custom.png")
    return "完成:已截图"
```

## 故障排查

- **超时失败**:把 `timeout` 调大,或先用截图确认页面真实状态;
- **iframe 内元素**:`frame = page.frame_locator("#frame"); frame.locator(...)`;
- **Shadow DOM**:Playwright 的 CSS 定位器默认穿透开放 shadow root;
- **中文输入**:优先 `fill()`,避免 `type()` 触发输入法问题。
