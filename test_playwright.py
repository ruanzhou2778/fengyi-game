"""
Playwright 自动化回归测试脚本
=============================
流程: 启动Flask后端 -> 入宫选秀 -> 翻牌 -> 转旬 -> 控制台检查
"""
import asyncio, os, subprocess, sys, time, json, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    os.environ["PYTHONIOENCODING"] = "utf-8"
from playwright.async_api import async_playwright

# ============ 配置 ============
BASE_DIR = r"d:\新建文件夹 (2)"
INDEX_URL = "http://localhost:5000"
BACKEND_PORT = 5000
FLASK_CMD = [sys.executable, "-u", "app.py"]

# ============ 终端着色 ============
class Colors:
    GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"
    CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"

def ok(msg):
    print(f"  {Colors.GREEN}✓{Colors.RESET} {msg}")

def fail(msg):
    print(f"  {Colors.RED}✗{Colors.RESET} {msg}")

def info(msg):
    print(f"  {Colors.CYAN}ℹ{Colors.RESET} {msg}")

def warn(msg):
    print(f"  {Colors.YELLOW}⚠{Colors.RESET} {msg}")

def heading(n, title):
    print(f"\n{'=' * 60}")
    print(f"{Colors.BOLD}{'  ' * n}{title}{Colors.RESET}")
    print(f"{'=' * 60}")
# ============ 测试结果收集 ============
class TestResults:
    def __init__(self):
        self.passed = 0; self.failed = 0; self.warnings = []
        self.console_errors = []; self.console_warnings = []
        self.modal_appeared = False; self.flip_clicked = False
        self.next_period_clicked = False; self.game_started = False
        self.start_time = time.time()

    def assert_true(self, cond, desc, detail=None):
        if cond:
            self.passed += 1; ok(desc)
        else:
            self.failed += 1; fail(desc)
            if detail:
                print(f"    详情: {detail}")

    def summary(self):
        dur = time.time() - self.start_time
        print(f"\n{'=' * 60}")
        print(f"{Colors.BOLD}📊 测试报告{Colors.RESET}  耗时 {dur:.1f}s")
        print(f"  通过: {Colors.GREEN}{self.passed}{Colors.RESET}"
              f"  失败: {Colors.RED}{self.failed}{Colors.RESET}")
        if self.console_errors:
            print(f"  控制台错误: {Colors.RED}{len(self.console_errors)} 条{Colors.RESET}")
            for e in self.console_errors:
                print(f"    {Colors.RED}❌{Colors.RESET} {e[:120]}")
        if self.console_warnings:
            print(f"  控制台警告: {Colors.YELLOW}{len(self.console_warnings)} 条{Colors.RESET}")
        print(f"  翻牌弹窗: "
              f"{'出现 ✓' if self.modal_appeared else '未出现（玩家未被选中，正常）'}")
        print(f"{'=' * 60}")
        if self.failed == 0 and not self.console_errors:
            print(f"{Colors.BOLD}结论: {Colors.GREEN}✅ 全部通过！{Colors.RESET}")
            result = True
        else:
            print(f"{Colors.BOLD}结论: {Colors.RED}❌ {self.failed} 个断言失败, "
                  f"{len(self.console_errors)} 个控制台错误{Colors.RESET}")
            result = False
        print(f"{'=' * 60}\n")
        return result
# ============ 后端管理 ============
class BackendManager:
    def __init__(self):
        self.process = None

    def start(self):
        info("正在启动后端服务...")
        env = os.environ.copy(); env["FLASK_DEBUG"] = "false"
        self.process = subprocess.Popen(
            FLASK_CMD, cwd=BASE_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1)
        for i in range(45):
            try:
                req = urllib.request.Request(
                    f"http://localhost:{BACKEND_PORT}/api/health",
                    headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if json.loads(resp.read().decode()).get("status") == "ok":
                        ok(f"后端就绪 (pid={self.process.pid})")
                        return True
            except Exception:
                pass
            time.sleep(1)
        self._print_output()
        return False

    def _print_output(self):
        if self.process and self.process.stdout:
            try:
                out = self.process.stdout.read(2048)
                if out:
                    print(f"  后端输出: {out[:800]}")
            except Exception:
                pass

    def stop(self):
        if self.process:
            info("正在停止后端服务...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5); ok("后端已停止")
            except subprocess.TimeoutExpired:
                self.process.kill(); warn("后端强制停止")
            self.process = None

    def __enter__(self):
        self.start(); return self

    def __exit__(self, *args):
        self.stop()
# ============ 控制台消息收集 ============
class ConsoleCollector:
    def __init__(self, results):
        self.results = results

    def on_message(self, msg):
        level = msg.type; text = msg.text.strip()
        low = text.lower()
        if "favicon" in low:
            return
        if "404" in text and "api" not in low:
            return
        if level == "error":
            self.results.console_errors.append(text)
        elif level == "warning":
            self.results.console_warnings.append(text)


# ============ 主测试流程 ============
async def run_test():
    results = TestResults()
    backend = BackendManager()
    heading(0, "🚀 凤仪天下 · Playwright 自动化测试")

    # ---- 1. 启动后端 ----
    if not backend.start():
        fail("后端启动失败，终止测试")
        results.assert_true(False, "后端启动", "无法连接后端")
        results.summary(); return False
    results.assert_true(True, "后端启动")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-extensions"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
        page = await context.new_page()

        collector = ConsoleCollector(results)
        page.on("console", collector.on_message)
        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # ---- 2. 打开页面 ----
        heading(1, "打开页面")
        try:
            await page.goto(INDEX_URL, wait_until="networkidle", timeout=30000)
            ok(f"页面加载完成: {INDEX_URL}")
            results.assert_true(True, "页面加载")
        except Exception as e:
            results.assert_true(False, "页面加载", str(e))
            await browser.close(); backend.stop()
            results.summary(); return False

        await page.wait_for_selector("#startBtn", timeout=10000)
        ok("页面关键元素 (startBtn) 已就绪")

        # ---- 3. 点击「入宫选秀」 ----
        heading(1, "点击「入宫选秀」")
        try:
            await page.click("#startBtn")
            ok("已点击「入宫选秀」")
            results.assert_true(True, "点击「入宫选秀」")
        except Exception as e:
            results.assert_true(False, "点击「入宫选秀」", str(e))
            await browser.close(); backend.stop()
            results.summary(); return False
# 等待游戏加载完成
        info("等待游戏加载...")
        game_started = False
        for i in range(80):
            try:
                # 最可靠：后端返回 player_id 后前端会设置全局 playerId
                pid = await page.evaluate(
                    "() => (typeof playerId !== 'undefined' && playerId) "
                    "|| window.playerId || null")

                if pid:
                    game_started = True; break
                s_name = await page.query_selector("#sName")
                if s_name:
                    text = (await s_name.text_content() or "").strip()
                    if text and text != "-":
                        game_started = True; break
            except Exception:
                pass
            await asyncio.sleep(0.5)
        if not game_started:
            await asyncio.sleep(5)
            try:
                pid = await page.evaluate(
                    "() => (typeof playerId !== 'undefined' && playerId) "
                    "|| window.playerId || null")
                if pid:
                    game_started = True
                else:
                    await page.wait_for_selector("#sName", timeout=3000)
                    text = (await page.text_content("#sName") or "").strip()
                    game_started = bool(text and text != "-")
            except Exception:
                game_started = False


        results.game_started = game_started
        results.assert_true(game_started, "游戏启动成功", "等待玩家名出现")
        if not game_started:
            warn("游戏可能未成功启动，继续执行以收集控制台错误")

        # ---- 4. 点击「翻牌」 ----
        heading(1, "点击「翻牌」")
        # 入宫后可能残留 loadingOverlay 或初印象弹窗，先行关闭以免遮挡翻牌按钮
        try:
            for _ in range(8):
                blocked = await page.evaluate(
                    "() => {"
                    " const lo=document.getElementById('loadingOverlay');"
                    " const mo=document.getElementById('modalOverlay');"
                    " const loShown = lo && getComputedStyle(lo).display!=='none';"
                    " const moShown = mo && mo.classList.contains('active');"
                    " return loShown || moShown;"
                    "}")
                if not blocked:
                    break
                cbtn = await page.query_selector("#modalConfirmBtn")
                if cbtn and await cbtn.is_visible():
                    await cbtn.click()
                else:
                    await page.keyboard.press("Escape")
                await asyncio.sleep(0.6)
        except Exception:
            pass
        flip_btn = await page.query_selector("button.qa-btn.primary")
        if not flip_btn:
            flip_btn = await page.query_selector('[onclick*="doFlip"]')
        if not flip_btn:
            flip_btn = await page.query_selector("button:has-text('翻牌')")
        if flip_btn:
            try:
                await flip_btn.click()
                results.flip_clicked = True
                ok("已点击「翻牌」")
                results.assert_true(True, "点击翻牌按钮")
            except Exception as e:
                results.assert_true(False, "点击翻牌按钮", str(e))
        else:
            results.assert_true(False, "找到翻牌按钮", "未找到翻牌按钮")

        await asyncio.sleep(3)

        # 弹窗检测
        modal_overlay = await page.query_selector("#modalOverlay.active")
        modal_visible = False
        modal_src = None
        for sel in ["#flipResultModal", "#eventResultModal"]:
            m = await page.query_selector(sel)
            if m:
                disp = await m.get_attribute("style") or ""
                if "display: none" not in disp:
                    modal_visible = True; modal_src = sel
        if modal_overlay or modal_visible:
            results.modal_appeared = True
            src = "modalOverlay" if modal_overlay else modal_src
            ok(f"翻牌弹窗出现 ({src})")
            results.assert_true(True, "翻牌弹窗检测")
            try:
                close_btn = await page.query_selector("#modalConfirmBtn")
                if close_btn and await close_btn.is_visible():
                    await close_btn.click(); ok("已关闭弹窗 (modalConfirmBtn)")
                else:
                    await page.keyboard.press("Escape"); ok("已关闭弹窗 (Escape)")
            except Exception:
                pass
        else:
            info("翻牌后未出现弹窗（玩家未被选中，属正常情况）")
            results.assert_true(True, "翻牌弹窗检测（未出现，正常路径）")
        await asyncio.sleep(1)
# ---- 5. 点击「转旬」 ----
        heading(1, "点击「转旬」")
        next_btn = await page.query_selector("#nextPeriodBtn")
        if not next_btn:
            next_btn = await page.query_selector("button:has-text('转旬')")
        if next_btn:
            try:
                if await next_btn.get_attribute("disabled") is not None:
                    warn("转旬按钮已禁用，跳过点击")
                    results.assert_true(True, "转旬按钮状态", "已禁用（跳过）")
                else:
                    await next_btn.click()
                    results.next_period_clicked = True
                    ok("已点击「转旬」")
                    results.assert_true(True, "点击转旬按钮")
                    await asyncio.sleep(4)
            except Exception as e:
                results.assert_true(False, "点击转旬按钮", str(e))
        else:
            results.assert_true(False, "找到转旬按钮", "未找到转旬按钮")

        # ---- 6. 控制台错误检查 ----
        heading(1, "控制台错误检查")
        filtered = [e for e in results.console_errors if "favicon" not in e.lower()]
        if filtered:
            results.assert_true(False, "控制台错误", f"{len(filtered)} 条")
            for e in filtered[:10]:
                fail(f"  Console: {e[:150]}")
        else:
            results.assert_true(True, "控制台错误", "无错误")
        if page_errors:
            results.assert_true(False, "页面异常错误", f"{len(page_errors)} 个")
            for e in page_errors[:10]:
                fail(f"  PageError: {e[:150]}")
        else:
            results.assert_true(True, "页面异常错误", "无错误")

        # ---- 7. 关键元素检查 ----
        heading(1, "页面关键元素检查")
        for sel, name in [("#userInput", "输入框"), ("#sendBtn", "发送按钮"),
                          ("#nextPeriodBtn", "转旬按钮"), ("#sName", "玩家名"),
                          ("#sRank", "位份"), ("#sSilver", "银两"),
                          ("#miniActions", "行动点"), ("#miniCalendar", "日历")]:
            el = await page.query_selector(sel)
            results.assert_true(el is not None, f"元素存在: {name} ({sel})")

        # 输入框联动
        heading(1, "输入框联动检查")
        # 先关闭可能遗留的模态框（翻牌后侍寝/赏赐弹窗会延迟弹出并遮挡 sendBtn）
        try:
            for _ in range(4):
                active = await page.query_selector("#modalOverlay.active")
                if not active:
                    break
                closed = False
                cbtn = await page.query_selector("#modalConfirmBtn")
                if cbtn and await cbtn.is_visible():
                    await cbtn.click()
                    closed = True
                if not closed:
                    await page.keyboard.press("Escape")
                await asyncio.sleep(0.6)
            still = await page.query_selector("#modalOverlay.active")
            results.assert_true(still is None, "输入框检查前弹窗已关闭",
                                "modalOverlay 仍处于 active")
        except Exception as e:
            results.assert_true(False, "关闭遗留弹窗", str(e))
        try:
            ui = page.locator("#userInput")
            if await ui.count() > 0:
                if (await ui.input_value()).strip():
                    await ui.fill("")
                await ui.fill("给太后请安，求平安")
                await page.click("#sendBtn")
                # /api/act 可能调用 AI，耗时不定；轮询等待输入框被清空
                cleared = False
                for _ in range(40):  # 最多约 20s
                    await asyncio.sleep(0.5)
                    processing = await page.evaluate(
                        "() => (typeof isProcessing !== 'undefined') "
                        "? isProcessing : false")
                    after = await ui.input_value()
                    if not processing and after.strip() == "":
                        cleared = True
                        break
                after = await ui.input_value()
                results.assert_true(cleared and after.strip() == "",
                                    "发送后输入框已清空",
                                    f"残留: {after[:30]}")
            else:
                results.assert_true(False, "找到输入框", "userInput 不存在")
        except Exception as e:
            results.assert_true(False, "输入框联动检查", str(e))
# ---- 8. 游戏结束锁定检查 ----
        heading(1, "游戏结束锁定检查")
        try:
            has_lock = await page.evaluate(
                "() => typeof applyGameOverLock !== 'undefined'")
            if has_lock:
                await page.evaluate(
                    "() => applyGameOverLock({key:'测试结局', title:'测试'})")
                send_disabled = await page.evaluate(
                    "() => document.getElementById('sendBtn')"
                    " ? document.getElementById('sendBtn').disabled : null")
                next_disabled = await page.evaluate(
                    "() => document.getElementById('nextPeriodBtn')"
                    " ? document.getElementById('nextPeriodBtn').disabled : null")
                results.assert_true(
                    send_disabled is True and next_disabled is True,
                    "游戏结束后按钮禁用",
                    f"sendBtn={send_disabled}, nextPeriodBtn={next_disabled}")
            else:
                warn("applyGameOverLock 未定义，跳过锁定检查")
                results.assert_true(True, "锁定检查（跳过）", "函数不存在")
        except Exception as e:
            results.assert_true(False, "游戏结束锁定检查", str(e))

        await browser.close()
        ok("浏览器已关闭")

    # ---- 停止后端 ----
    backend.stop()

    return results.summary()


# ============ 入口 ============
if __name__ == "__main__":
    os.chdir(BASE_DIR)
    sys.path.insert(0, BASE_DIR)
    sys.exit(0 if asyncio.run(run_test()) else 1)
