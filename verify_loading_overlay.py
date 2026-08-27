# -*- coding: utf-8 -*-
"""验证加载遮罩 loadingOverlay 能完整显示（CSS 补全修复）。"""
import os, sys, time, subprocess, socket, signal

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def wait_http(url, timeout=40):
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

async def main():
    from playwright.async_api import async_playwright
    port = free_port()
    env = dict(os.environ); env['PORT'] = str(port); env['PYTHONIOENCODING'] = 'utf-8'
    proc = subprocess.Popen([sys.executable, '-u', 'app.py'], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}/'
        if not wait_http(url):
            print('FAIL: 服务未启动'); return False
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=['--no-sandbox','--disable-gpu'])
            ctx = await browser.new_context(viewport={'width':1280,'height':800})
            page = await ctx.new_page()
            await page.goto(url, wait_until='networkidle')
            # 等待 compat_prep.js 注入 loadingOverlay
            await page.wait_for_function("()=>document.getElementById('loadingOverlay')!==null", timeout=15000)
            # 调用 showLoading 显示带自定义文本/图标
            await page.evaluate("""()=>showLoading(true,{title:'入宫选秀中…',sub:'正在安排殿选与册封，请稍候',icon:'🏯'})""")
            await page.wait_for_timeout(300)
            res = await page.evaluate("""()=>{
                const ov=document.getElementById('loadingOverlay');
                const box=ov.querySelector('.loading-box');
                const icon=ov.querySelector('.loading-icon');
                const title=ov.querySelector('.loading-title');
                const sub=ov.querySelector('.loading-sub');
                const ovDisp=getComputedStyle(ov).display;
                const boxRect=box.getBoundingClientRect();
                const cs=getComputedStyle(box);
                const iconCs=getComputedStyle(icon);
                return {
                    overlay_display:ovDisp,
                    box_width:Math.round(boxRect.width),
                    box_height:Math.round(boxRect.height),
                    box_padding:cs.padding,
                    box_bg:cs.backgroundColor,
                    box_display:cs.display,
                    box_flexdir:cs.flexDirection,
                    box_align:cs.alignItems,
                    icon_font:iconCs.fontSize,
                    icon_anim:iconCs.animationName,
                    title_text:title.textContent,
                    sub_text:sub.textContent,
                    icon_text:icon.textContent,
                    title_color:getComputedStyle(title).color,
                    all_visible: boxRect.width>0 && boxRect.height>0 && boxRect.width<1280
                };
            }""")
            await page.screenshot(path='loading_overlay.png')
            print('RESULT:', __import__('json').dumps(res, ensure_ascii=False))
            ok = (res['overlay_display']=='flex' and res['box_width']>0 and res['box_height']>0
                  and res['box_flexdir']=='column' and res['box_align']=='center'
                  and res['icon_anim'].startswith('loadingPulse')
                  and res['box_width']<1280)
            print('VISIBLE_OK' if ok else 'VISIBLE_FAIL')
            # 测试隐藏
            await page.evaluate("()=>showLoading(false)")
            await page.wait_for_timeout(100)
            disp = await page.evaluate("()=>getComputedStyle(document.getElementById('loadingOverlay')).display")
            print('HIDE:', disp, 'OK' if disp=='none' else 'FAIL')
            await browser.close()
            return ok and disp=='none'
    finally:
        if proc.poll() is None:
            try: proc.terminate()
            except Exception: pass
            try: proc.wait(timeout=8)
            except Exception: proc.kill()

if __name__=='__main__':
    import asyncio
    ok = asyncio.run(main())
    print('OVERALL:', 'PASS' if ok else 'FAIL')
