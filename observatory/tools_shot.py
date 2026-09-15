# -*- coding: utf-8 -*-
"""Screenshot a URL at a given viewport, over the DevTools protocol.

Chrome's --screenshot flag hangs on a fresh --user-data-dir on this machine,
and it also floors the layout at ~500px so a true 390 check is impossible
through it. Driving the browser over CDP avoids both: the viewport is set with
Emulation.setDeviceMetricsOverride, which is honoured exactly, and the capture
is an explicit command rather than a race against page load.

    python tools_shot.py <url> <out.png> [width] [height] [dpr]
"""
import asyncio, base64, json, os, subprocess, sys, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


async def shoot(url, out, width, height, dpr, port, profile, dark=False):
    import websockets
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--no-first-run", "--no-default-browser-check",
         "--remote-debugging-port=%d" % port,
         "--user-data-dir=%s" % profile, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(80):
            try:
                v = json.load(urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/version" % port, timeout=1))
                ws_url = v["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.25)
        if not ws_url:
            raise RuntimeError("Chrome did not open a debugging port")

        async with websockets.connect(ws_url, max_size=200 * 1024 * 1024) as ws:
            i = [0]

            async def cmd(method, params=None, session=None):
                i[0] += 1
                msg = {"id": i[0], "method": method, "params": params or {}}
                if session:
                    msg["sessionId"] = session
                await ws.send(json.dumps(msg))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == i[0]:
                        if "error" in r:
                            raise RuntimeError("%s: %s" % (method, r["error"]))
                        return r.get("result", {})

            t = await cmd("Target.createTarget", {"url": "about:blank"})
            s = (await cmd("Target.attachToTarget",
                           {"targetId": t["targetId"], "flatten": True}))["sessionId"]
            await cmd("Page.enable", {}, s)
            await cmd("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height,
                "deviceScaleFactor": dpr, "mobile": width < 500}, s)
            if dark:
                await cmd("Emulation.setEmulatedMedia", {
                    "features": [{"name": "prefers-color-scheme", "value": "dark"}]}, s)
            await cmd("Page.navigate", {"url": url}, s)
            # settle: give fonts, fetches and chart draws a chance
            await asyncio.sleep(3.0)
            r = await cmd("Page.captureScreenshot", {"format": "png"}, s)
            with open(out, "wb") as f:
                f.write(base64.b64decode(r["data"]))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def main():
    url, out = sys.argv[1], sys.argv[2]
    args = [a for a in sys.argv[3:] if not a.startswith("--")]
    width = int(args[0]) if args else 1440
    height = int(args[1]) if len(args) > 1 else 900
    dpr = float(args[2]) if len(args) > 2 else 2.0
    port = 9400 + (os.getpid() % 200)
    profile = "/tmp/pa-shot-profile-%d" % port
    os.makedirs(profile, exist_ok=True)
    dark = "--dark" in sys.argv
    asyncio.get_event_loop().run_until_complete(
        shoot(url, out, width, height, dpr, port, profile, dark))
    print("wrote %s (%dx%d @%gx)" % (out, width, height, dpr))


if __name__ == "__main__":
    main()
