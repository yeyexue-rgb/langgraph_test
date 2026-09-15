"""playwright-skill 内置浏览器自动化脚本。

子命令：
- screenshot：打开 URL 并整页截图；
- check：打开 URL 并断言指定选择器的元素存在且可见；
- run：加载用户自定义脚本中的 run(page) 函数执行。

统一使用 headless Chromium，退出码 0 表示成功，1 表示失败，
便于被其他流程串联调用。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    expect,
    sync_playwright,
)


VIEWPORT = {"width": 1280, "height": 900}
DEFAULT_TIMEOUT_MS = 15_000


def _new_page(playwright, headed: bool):
    browser = playwright.chromium.launch(headless=not headed)
    page = browser.new_page(viewport=VIEWPORT)
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
    return browser, page


def _ensure_parent(path: str) -> None:
    parent = Path(path).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def cmd_screenshot(args: argparse.Namespace) -> int:
    with sync_playwright() as playwright:
        browser, page = _new_page(playwright, args.headed)
        try:
            page.goto(args.url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            _ensure_parent(args.out)
            page.screenshot(path=args.out, full_page=True)
            print(f"OK: 截图已保存 -> {args.out}")
            print(f"标题: {page.title()}")
            return 0
        finally:
            browser.close()


def cmd_check(args: argparse.Namespace) -> int:
    with sync_playwright() as playwright:
        browser, page = _new_page(playwright, args.headed)
        try:
            page.goto(args.url, wait_until="domcontentloaded")
            locator = page.locator(args.selector)
            expect(locator.first).to_be_visible(
                timeout=DEFAULT_TIMEOUT_MS
            )
            count = locator.count()
            print(f"OK: 选择器 {args.selector!r} 命中 {count} 个元素")
            print(f"首个元素文本: {locator.first.inner_text()[:200]!r}")
            return 0
        except (AssertionError, PlaywrightTimeoutError) as exc:
            print(f"FAIL: 选择器 {args.selector!r} 未找到可见元素")
            print(f"原因: {exc}")
            return 1
        finally:
            browser.close()


def cmd_run(args: argparse.Namespace) -> int:
    script_path = Path(args.script).resolve()

    if not script_path.is_file():
        print(f"FAIL: 自定义脚本不存在: {script_path}")
        return 1

    spec = importlib.util.spec_from_file_location(
        "custom_flow", script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "run"):
        print("FAIL: 自定义脚本必须定义 run(page) 函数")
        return 1

    with sync_playwright() as playwright:
        browser, page = _new_page(playwright, args.headed)
        try:
            result = module.run(page)
            if result:
                print(result)
            print("OK: 自定义流程执行完成")
            return 0
        except Exception as exc:
            print(f"FAIL: 自定义流程执行异常: {exc}")
            return 1
        finally:
            browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="playwright-skill 浏览器自动化脚本"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    shot = subparsers.add_parser("screenshot", help="打开页面并截图")
    shot.add_argument("--url", required=True, help="目标页面 URL")
    shot.add_argument(
        "--out", default="shots/screenshot.png", help="截图保存路径"
    )
    shot.add_argument(
        "--headed", action="store_true", help="显示浏览器窗口"
    )

    check = subparsers.add_parser("check", help="检查元素存在且可见")
    check.add_argument("--url", required=True, help="目标页面 URL")
    check.add_argument(
        "--selector", required=True, help="CSS 或 Playwright 选择器"
    )
    check.add_argument(
        "--headed", action="store_true", help="显示浏览器窗口"
    )

    run = subparsers.add_parser("run", help="执行自定义流程脚本")
    run.add_argument(
        "--script", required=True, help="定义 run(page) 的脚本路径"
    )
    run.add_argument(
        "--headed", action="store_true", help="显示浏览器窗口"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "screenshot": cmd_screenshot,
        "check": cmd_check,
        "run": cmd_run,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
