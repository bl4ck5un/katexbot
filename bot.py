import os
import re
import tempfile
import subprocess
import asyncio
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from pyppeteer import launch
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

app = AsyncApp(token=SLACK_BOT_TOKEN)

browser = None  # Global browser instance

# === Extract LaTeX from $$...$$ ===
def extract_latex(text):
    match = re.search(r"\$\$(.+?)\$\$", text, re.DOTALL)
    return match.group(1).strip() if match else None

# === Render KaTeX to HTML ===
def katex_html(latex: str) -> str:
    result = subprocess.run(
        ["katex", "--no-throw-on-error", "--display-mode"],
        input=latex.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode()

# === Wrap KaTeX HTML in HTML page ===
def wrap_in_html(katex_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
  <style>
    body {{
      margin: 0;
      padding: 0;
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
    }}
    #math {{
      font-size: 2.5em;
    }}
  </style>
</head>
<body>
  <div id="math">{katex_html}</div>
</body>
</html>"""

# === Use persistent browser to take cropped screenshot ===
async def html_to_png(html: str, output_path: str):
    global browser
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html.encode())
        f.flush()
        html_file = f.name

    if browser is None:
        browser = await launch(handleSIGINT=False, handleSIGTERM=False, handleSIGHUP=False)

    page = await browser.newPage()
    await page.goto(f"file://{html_file}", waitUntil='networkidle0')

    element = await page.querySelector("#math") or await page.querySelector("body")
    box = await element.boundingBox()
    await page.screenshot({
        'path': output_path,
        'clip': {
            'x': box['x'],
            'y': box['y'],
            'width': box['width'],
            'height': box['height']
        },
        'omitBackground': True
    })

    await page.close()
    os.unlink(html_file)

# === Combine all into async render function ===
async def render_latex_to_png(latex: str, output_path: str = "output.png"):
    html = wrap_in_html(katex_html(latex))
    await html_to_png(html, output_path)

# === Slack message handler ===
@app.event("message")
async def handle_message(event, client):
    text = event.get("text", "")
    latex = extract_latex(text)
    if not latex:
        return

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_png:
            await render_latex_to_png(latex, f_png.name)
            await client.files_upload_v2(
                channel=event["channel"],
                thread_ts=event["ts"],
                file=f_png.name,
                filename="equation.png",
                title="Rendered LaTeX",
            )
    except Exception as e:
        await client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["ts"],
            text=f"Error rendering LaTeX: `{e}`"
        )

# === Start the async app ===
async def main():
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    await handler.start_async()

if __name__ == "__main__":
    asyncio.run(main())