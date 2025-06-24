import os
import asyncio
import re
import tempfile
import subprocess
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from pyppeteer import launch

from dotenv import load_dotenv

load_dotenv()

# Slack tokens from environment
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

app = App(token=SLACK_BOT_TOKEN)

# === Extract LaTeX from message ===
def extract_latex(text):
    match = re.search(r"\$\$(.+?)\$\$", text, re.DOTALL)
    return match.group(1).strip() if match else None

# === Run KaTeX CLI to produce HTML ===
def katex_html(latex: str) -> str:
    print(latex)
    result = subprocess.run(
        ["katex", "--no-throw-on-error", "--display-mode"],
        input=latex.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode()

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

async def html_to_png(html: str, output_path: str):
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(html.encode())
        f.flush()
        html_file = f.name

    browser = await launch(handleSIGINT=False, handleSIGTERM=False, handleSIGHUP=False)
    page = await browser.newPage()
    await page.goto(f"file://{html_file}", waitUntil='networkidle0')

    # Find the KaTeX container (wrap your KaTeX output in a <div id="math">)
    element = await page.querySelector("#math")
    if not element:
        element = await page.querySelector("body")  # fallback

    # Crop to the bounding box of the element
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

    await browser.close()
    os.unlink(html_file)

def render_latex_to_png(latex: str, output_path: str = "output.png"):
    html = wrap_in_html(katex_html(latex))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(html_to_png(html, output_path))
    print(f"✅ Saved to {output_path}")

# === Handle message ===
@app.event("message")
def handle_message(event, client):
    text = event.get("text", "")
    latex = extract_latex(text)
    if not latex:
        return

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_png:
            render_latex_to_png(latex, f_png.name)

            # Upload to Slack as a thread reply
            client.files_upload_v2(
                channel=event["channel"],
                thread_ts=event["ts"],
                file=f_png.name,
                filename="equation.png",
                title="Rendered LaTeX",
            )

    except Exception as e:
        client.chat_postMessage(
            channel=event["channel"],
            thread_ts=event["ts"],
            text=f"Error rendering LaTeX: `{e}`"
        )

# === Entrypoint ===
if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()