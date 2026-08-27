# -*- coding: utf-8 -*-
"""
openModal isHtml 永久修复验证脚本
================================
验证：将 openModal 默认 isHtml 改为 true 后，
即便调用方遗漏第5参数(isHtml)，HTML 富文本也能正确渲染为 DOM，
而不会把 <div>/<b> 等标签当作纯文本字面显示。
"""
import asyncio, subprocess, sys, time, urllib.request
from playwright.async_api import async_playwright

BASE_DIR = r"d:\新建文件夹 (2)"
URL = "http://localhost:5000/"

def wait_for_server(timeout=45):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(URL, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

async def main():
    proc = subprocess.Popen(
        [sys.executable, "-u", "app.py"],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        if not wait_for_server():
            print("✗ 后端启动失败（端口 5000 无响应）")
            return 1
        print("✓ 后端已启动")
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded")
            await page.wait_for_function("typeof openModal === 'function'", timeout=15000)

            results = []
            def check(cond, desc, detail=""):
                results.append(cond)
                print(f"  {'✓' if cond else '✗'} {desc}" + (f"  ({detail})" if detail else ""))

            # 测试1：不传 isHtml（走默认值）。修复后默认 true -> HTML 被解析为 DOM
            r1 = await page.evaluate("""
            () => {
              openModal('T1', '<div id="probe1"><b>HTML渲染测试</b></div>');
              const body = document.getElementById('modalBody');
              return {
                hasProbe: !!document.querySelector('#modalBody #probe1'),
                bText: (document.querySelector('#modalBody b')||{}).textContent || null,
                rawText: body.textContent,
                tagLiteral: body.textContent.includes('<b') || body.textContent.includes('<div')
              };
            }
            """)
            check(r1.get('hasProbe'), "默认(不传isHtml): HTML被解析为DOM(#probe1存在)", str(r1))
            check(r1.get('bText')=='HTML渲染测试', "默认: <b>渲染为粗体元素而非字面文本", str(r1.get('bText')))
            check(not r1.get('tagLiteral'), "默认: 标签未当作纯文本字面显示", str(r1.get('rawText')))

            # 测试2：显式传 true
            r2 = await page.evaluate("""
            () => {
              openModal('T2', '<div id="probe2"><i>显式true</i></div>', '关闭', null, true);
              return { hasItag: !!document.querySelector('#modalBody #probe2 i') };
            }
            """)
            check(r2.get('hasItag'), "显式isHtml=true: HTML正常渲染", str(r2))

            # 测试3：显式传 false（保留纯文本转义能力）
            r3 = await page.evaluate("""
            () => {
              openModal('T3', '<b>显式false</b>', '关闭', null, false);
              const body = document.getElementById('modalBody');
              return {
                hasB: !!document.querySelector('#modalBody b'),
                rawText: body.textContent,
                tagLiteral: body.textContent.includes('<b')
              };
            }
            """)
            check(not r3.get('hasB'), "显式isHtml=false: 标签被转义(无<b>元素)", str(r3))
            check(r3.get('tagLiteral'), "显式isHtml=false: textContent含字面<b>(转义生效)", str(r3.get('rawText')))

            await browser.close()
            passed = sum(1 for c in results if c)
            print(f"\n结果: {passed}/{len(results)} 通过")
            return 0 if passed == len(results) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

sys.exit(asyncio.run(main()))
