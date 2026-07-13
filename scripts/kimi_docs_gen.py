#!/usr/bin/env python3
"""kimi_docs_gen.py — Generate images via Kimi Docs Agent mode using direct CDP.

Usage:
    python3 kimi_docs_gen.py --prompt "..." --output /tmp/output.jpg
"""

import argparse
import asyncio
import json
import subprocess
import sys
import urllib.request

import websockets


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    prompt = args.prompt
    output_path = args.output

    # 1. Get CDP WebSocket URL
    resp = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5)
    ws_url = json.loads(resp.read())["webSocketDebuggerUrl"]
    print(f"[1] CDP: {ws_url[:60]}...")

    async with websockets.connect(ws_url) as ws:
        msg_id = 0

        async def send(method, params=None):
            nonlocal msg_id
            msg_id += 1
            payload = {"id": msg_id, "method": method}
            if params:
                payload["params"] = params
            await ws.send(json.dumps(payload))

        async def recv(expected_id=None):
            resp = json.loads(await ws.recv())
            return resp

        async def eval_(expr, target_id=None, session_id=None):
            params = {"expression": expr, "returnByValue": True}
            if session_id:
                params["sessionId"] = session_id
            await send("Runtime.evaluate", params)
            # We need the session_id in the params, but Runtime.evaluate won't accept
            # sessionId there in some CDP implementations. Let's use Target.attachToTarget.
            # Actually for websockets, the standard approach is to send sessionId
            # as part of the message, not params.
            # Let me use the simpler approach: attach, eval, get result
            return None

        # Simpler approach: use a single attach-then-eval pattern
        # 2. Find Kimi page tab
        await send("Target.getTargets")
        r = await recv()
        targets = r.get("result", {}).get("targetInfos", [])

        target_id = None
        for t in targets:
            if t.get("type") == "page" and "kimi.com" in t.get("url", ""):
                target_id = t["targetId"]
                break

        if not target_id:
            print("[2] No Kimi page found.")
            return False
        print(f"[2] Found Kimi page: {target_id[:20]}...")

        # 3. Attach to target and get session
        await send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        sess = None
        for _ in range(5):
            r = await recv()
            if r.get("method") == "Target.attachedToTarget":
                sess = r.get("params", {}).get("sessionId")
                break
            # May also be a direct response
            if "result" in r:
                sess = r.get("result", {}).get("sessionId")
                break
        if not sess:
            print("[3] Failed to attach.")
            return False
        print(f"[3] Attached, session: {sess[:20]}...")

        # Helper: eval on the attached target
        async def eval_target(expr):
            await send("Runtime.evaluate",
                       {"expression": expr, "returnByValue": True, "sessionId": sess})
            expected = msg_id
            for _ in range(50):
                r = await recv()
                if r.get("id") == expected:
                    res = r.get("result", {}).get("result", {})
                    return res.get("value")

        # 4. Navigate to docs
        await eval_target("window.location.href = 'https://www.kimi.com/docs'; 'ok'")
        await asyncio.sleep(4)

        # 5. Check login
        body = await eval_target("document.body.innerText.substring(0,300)")
        if body and "Frank li" not in body:
            print(f"[4] NOT logged in. Page starts: {(body or '')[:80]}")
            return False
        print("[4] Logged in ✓")

        # 6. New Chat
        await eval_target("document.querySelector('a.new-chat-btn')?.click()")
        await asyncio.sleep(2)
        print("[5] New Chat clicked")

        # 7. Paste prompt
        escaped = prompt.replace("`", "\\`").replace("$", "\\$").replace("\\", "\\\\")
        result = await eval_target(f"""
        (() => {{
            const e = document.querySelector('.chat-input-editor');
            if (!e) return 'no editor';
            e.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, clientX:100, clientY:100}}));
            e.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true, clientX:100, clientY:100}}));
            e.dispatchEvent(new Event('click', {{bubbles: true}}));
            e.focus();
            const dt = new DataTransfer();
            dt.setData('text/plain', `{escaped}`);
            e.dispatchEvent(new ClipboardEvent('paste', {{bubbles: true, cancelable: true, clipboardData: dt}}));
            return 'ok ' + e.textContent.length + ' chars';
        }})();
        """)
        print(f"[6] Paste: {result}")

        # 8. Submit Enter
        await eval_target("""
        (() => {
            const e = document.querySelector('.chat-input-editor');
            if (!e) return 'no editor';
            ['keydown','keypress','keyup'].forEach(ev => {
                e.dispatchEvent(new KeyboardEvent(ev, {key:'Enter', code:'Enter', bubbles: true, cancelable: true}));
            });
            return 'submitted';
        })();
        """)
        await asyncio.sleep(1)
        print("[7] Submitting...")

        # 9. Wait for All files
        print("[8] Waiting for generation (up to 300s)...")
        for i in range(300):
            has = await eval_target("document.body.innerText.includes('All files')")
            if has:
                print(f"  Ready! ~{i+1}s")
                break
            if i % 30 == 0:
                length = await eval_target("document.body.innerText.length")
                print(f"  ...{i}s, {length} chars")
            await asyncio.sleep(1)
        else:
            print("  Timed out.")
            return False

        await asyncio.sleep(1)

        # 10. Click Preview
        await eval_target("""
        document.querySelector('button.km-button-secondary.action-button')?.click();
        """)
        await asyncio.sleep(1)

        # 11. Extract URL
        img_url = await eval_target("""
        (() => {
            const c = document.querySelector('.file-container');
            if (!c) return null;
            const img = c.querySelector('img');
            return img ? img.src : null;
        })();
        """)
        if not img_url:
            print("[9] No image URL found.")
            return False
        print(f"[9] URL: {img_url[:80]}...")

        # 12. Download
        r = subprocess.run(["curl", "-sL", "-o", output_path, str(img_url)],
                          capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"  Download failed: {r.stderr}")
            return False

        r2 = subprocess.run(["file", output_path], capture_output=True, text=True)
        print(f"[10] Saved: {r2.stdout.strip()}")
        return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
