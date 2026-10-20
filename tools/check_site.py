"""静态站验收：六入口、演示投递、D timeline、标注台送包（file:// 与 http 各一遍）。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "tools" / "_shots"
SHOTS.mkdir(exist_ok=True)
PIECES = ["a", "b", "c", "d", "mv"]
fails: list[str] = []


def check_player(br, base: str, p: str) -> None:
    errs: list[str] = []
    ctx = br.new_context(viewport={"width": 1600, "height": 940})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    # 装置里 new Audio() 不进 DOM：包住构造器，记录 blob 音频是否真的建出来
    pg.add_init_script("""(()=>{const O=window.Audio;window.__audios=[];
      window.Audio=function(...a){const x=new O(...a);window.__audios.push(x);return x;};
      window.Audio.prototype=O.prototype;})()""")
    pg.goto(base + "/player.html?p=%s&demo=1" % p, wait_until="load")
    fr = None
    for _ in range(40):
        fr = next((f for f in pg.frames if "devices/%s.html" % p in f.url), None)
        if fr:
            break
        pg.wait_for_timeout(250)
    if not fr:
        fails.append("%s: 没有找到装置 iframe" % p)
        ctx.close()
        return
    try:
        fr.wait_for_function("() => window.__BUNDLE__ && window.__BUNDLE__.received", timeout=90000)
        st = fr.evaluate("() => ({b:window.__BUNDLE__, s:window.__M.state()})")
        dur = float(st["s"].get("dur") or 0)
        if abs(dur - 30.0) > 0.1:
            fails.append("%s: 演示数据 dur=%s（应为 30）" % (p, dur))
        if st["b"].get("error"):
            fails.append("%s: BUNDLE.error=%s" % (p, st["b"]["error"]))
        pg.wait_for_timeout(1200)
        try:
            fr.wait_for_function("""() => !!(window.__M.state && window.__M.state().audio)
              || !!(window.__audios && window.__audios.some(a=>/^blob:/.test(a.src||'')))""",
              timeout=90000)
        except Exception:
            pass
        # 音频是否真的进了装置：找 audio 元素或 blob src
        audio = fr.evaluate("""() => !!(window.__M.state && window.__M.state().audio)
          || !!(window.__audios && window.__audios.some(a=>/^blob:/.test(a.src||'')))""")
        if p == "d":
            tim = fr.evaluate("() => (document.getElementById('btnTim')||{}).textContent||''")
            hud = fr.evaluate("() => (document.getElementById('hud')||{}).innerText||''")
            if "✔" not in tim:
                fails.append("d: timeline 未装载（#btnTim=%r）" % tim)
            if "timeline 未装载" in hud:
                fails.append("d: 顶栏仍报 timeline 未装载")
        else:
            tim = ""
        fr.evaluate("(t) => window.__M.setTime(t)", 20.0)
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(SHOTS / ("%s_%s.png" % (p, "file" if base.startswith("file") else "http"))))
        print("  %-2s ok  dur=%.1f  audio=%s  timeline=%r  errs=%s" %
              (p, dur, audio, "yes" if "✔" in tim else ("n/a" if p != "d" else "no"), errs[:1]))
        if errs:
            fails.append("%s: pageerror %s" % (p, errs[0]))
    except Exception as e:
        fails.append("%s: %s" % (p, repr(e)[:200]))
    ctx.close()


def check_hub(br, base: str) -> None:
    ctx = br.new_context(viewport={"width": 1600, "height": 940})
    pg = ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
    pg.goto(base + "/index.html", wait_until="load")
    pg.wait_for_timeout(600)
    links = pg.eval_on_selector_all("a.card", "els=>els.map(e=>e.getAttribute('href'))")
    print("  hub links:", links)
    if len(links) != 6:
        fails.append("hub: 卡片数 %d≠6" % len(links))
    if errs:
        fails.append("hub: pageerror %s" % errs[0])
    pg.screenshot(path=str(SHOTS / ("hub_%s.png" % ("file" if base.startswith("file") else "http"))))
    ctx.close()


def check_annotator(br, base: str) -> None:
    ctx = br.new_context(viewport={"width": 1600, "height": 940})
    pg = ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.goto(base + "/annotator.html", wait_until="load")
    pg.wait_for_timeout(1200)
    pg.set_input_files("#inAudio", str(ROOT / "demo/demo.mp3"))
    try:
        pg.wait_for_function("() => RT && RT.C && RT.C.n > 0", timeout=180000)
    except Exception as e:
        fails.append("标注台浏览器分析超时: %r" % (e,))
        ctx.close()
        return
    pg.wait_for_timeout(800)
    try:
        with pg.expect_popup(timeout=20000) as pi:
            pg.click("#toDev")
            pg.click('#ctxMenu button[data-i="0"]')
        dp = pi.value
    except Exception as e:
        fails.append("标注台没有弹出装置窗口: %r（toast=%r）" %
                     (e, pg.evaluate("()=>document.getElementById('toast').textContent")))
        ctx.close(); return
    try:
        dp.wait_for_function("() => window.__BUNDLE__ && window.__BUNDLE__.received", timeout=30000)
        dp.wait_for_timeout(1500)
        st = dp.evaluate("() => window.__BUNDLE__")
        dur = dp.evaluate("() => window.__M.state().dur")
        print("  annotator→A: received=%s ack=%s dur=%.1f sec=%s" %
              (st["received"], st["ack_sent"], dur, st["sec_mode"] ))
        if not st["received"] or not st["ack_sent"]:
            fails.append("标注台送包: received/ack 不完整")
        if abs(float(dur) - 30.0) > 0.2:
            fails.append("标注台送包: 装置 dur=%s" % dur)
        if st.get("error"):
            fails.append("标注台送包: BUNDLE.error=%s" % st["error"])
        dp.close()
    except Exception as e:
        fails.append("标注台送包失败: %r" % (e,))
    if errs:
        fails.append("标注台 pageerror: %s" % errs[0])
    ctx.close()


def run(br, base: str) -> None:
    print("== %s" % base)
    check_hub(br, base)
    for p in PIECES:
        check_player(br, base, p)
    check_annotator(br, base)


def main() -> int:
    p = Path()
    srv = subprocess.Popen([sys.executable, "-m", "http.server", "8765", "--bind", "127.0.0.1"],
                           cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(channel="msedge", headless=True)
            only = os.environ.get("SITE_BASE")
            if only:
                run(br, only.rstrip("/"))
            else:
                run(br, ROOT.as_uri())
                run(br, "http://127.0.0.1:8765")
            br.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
    print("\n验收: " + ("通过" if not fails else "失败 %d 项" % len(fails)))
    for f in fails:
        print("  [失败] " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
