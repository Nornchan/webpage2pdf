#!/usr/bin/env python3
"""
server.py — local drag-and-drop front end for html2pdf.

    python3 server.py

Opens http://127.0.0.1:8765 in your browser. Nothing leaves your machine except
the page fetches themselves. Standard library only, so there is no web framework
to install.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import converter  # noqa: E402

DEFAULT_PORT = 8765
OUTPUT_DIR = os.path.abspath("converted-pdfs")


# ==========================================================================
# Front end
# ==========================================================================

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Webpage → A4 PDF</title>
<style>
  :root {
    --bg:#f4f2ee; --card:#fff; --ink:#1f2328; --soft:#6b7280; --faint:#9ca3af;
    --line:#e3e0d9; --accent:#2f3f52; --accent-soft:#eef1f5;
    --ok:#1f7a4d; --ok-bg:#e9f5ee; --warn:#8a6d1f; --warn-bg:#fdf6e3;
    --err:#a03028; --err-bg:#fbeceb;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  .wrap { max-width:760px; margin:0 auto; }
  h1 {
    font:600 25px/1.25 Georgia,"Times New Roman",serif;
    margin:0 0 6px; letter-spacing:-.01em;
  }
  .sub { color:var(--soft); font-size:13.5px; margin:0 0 26px; }
  .card {
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:22px; margin-bottom:16px;
  }
  label.field { display:block; font-weight:600; font-size:12.5px; margin-bottom:7px; }
  .hint { color:var(--faint); font-weight:400; font-size:11.5px; }
  textarea {
    width:100%; min-height:104px; padding:12px 13px; border:1px solid var(--line);
    border-radius:8px; font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
    resize:vertical; background:#fdfdfc; color:var(--ink);
  }
  textarea:focus { outline:2px solid var(--accent-soft); border-color:var(--accent); }
  #drop {
    margin-top:12px; border:1.5px dashed var(--line); border-radius:10px;
    padding:20px; text-align:center; color:var(--soft); font-size:13px;
    background:#fbfaf8; transition:.15s; cursor:pointer;
  }
  #drop.hot { border-color:var(--accent); background:var(--accent-soft); color:var(--accent); }
  #queued { margin-top:10px; font-size:12.5px; color:var(--soft); }
  #queued span {
    display:inline-block; background:var(--accent-soft); color:var(--accent);
    border-radius:5px; padding:2px 8px; margin:3px 5px 0 0; font-size:11.5px;
  }
  .opts { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; }
  select {
    width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:7px;
    background:#fdfdfc; font-size:13px; color:var(--ink);
  }
  .checks { display:flex; flex-wrap:wrap; gap:16px; margin-top:16px; font-size:13px; }
  .checks label { display:flex; align-items:center; gap:7px; color:var(--soft); cursor:pointer; }
  input[type=checkbox] { accent-color:var(--accent); width:15px; height:15px; }
  button.go {
    width:100%; margin-top:20px; padding:13px; border:0; border-radius:9px;
    background:var(--accent); color:#fff; font-size:14.5px; font-weight:600;
    cursor:pointer; transition:.15s;
  }
  button.go:hover:not(:disabled) { background:#26313f; }
  button.go:disabled { opacity:.55; cursor:default; }
  .row {
    display:flex; align-items:flex-start; gap:11px; padding:12px 14px;
    border-radius:9px; margin-bottom:8px; font-size:13px; background:#fafaf8;
    border:1px solid var(--line);
  }
  .row .badge { flex:none; font-weight:700; font-size:14px; line-height:1.5; }
  .row.ok    { background:var(--ok-bg);   border-color:#c8e6d5; }
  .row.ok .badge { color:var(--ok); }
  .row.err   { background:var(--err-bg);  border-color:#f2cfcc; }
  .row.err .badge { color:var(--err); }
  .row .body { flex:1; min-width:0; }
  .row .name { font-weight:600; word-break:break-word; }
  .row .meta { color:var(--soft); font-size:11.5px; margin-top:3px; }
  .row .warn { color:var(--warn); background:var(--warn-bg); border-radius:5px;
               padding:4px 7px; margin-top:6px; font-size:11.5px; }
  .row a.dl {
    flex:none; font-size:12px; font-weight:600; color:var(--accent);
    text-decoration:none; border:1px solid var(--accent); padding:5px 11px;
    border-radius:6px; white-space:nowrap;
  }
  .row a.dl:hover { background:var(--accent); color:#fff; }
  .folder { font-size:12px; color:var(--faint); margin-top:14px; word-break:break-all; }
  .folder code { background:#eceae5; padding:2px 6px; border-radius:4px; }
  .spinner {
    display:inline-block; width:13px; height:13px; border:2px solid var(--line);
    border-top-color:var(--accent); border-radius:50%; animation:spin .7s linear infinite;
    vertical-align:-2px; margin-right:7px;
  }
  @keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>
<div class="wrap">

  <h1>Webpage → A4 PDF</h1>
  <p class="sub">Strips the navigation, ads and share bars, then rebuilds the article
  as a clean A4 essay. Images are kept whole instead of being cut across pages.</p>

  <div class="card">
    <label class="field" for="sources">
      Paste links or file paths
      <span class="hint">— one per line; mix URLs and local .html paths freely</span>
    </label>
    <textarea id="sources" placeholder="https://example.com/some-long-article&#10;/Users/you/Downloads/saved-page.html"></textarea>

    <div id="drop">Or drop saved <strong>.html</strong> files here</div>
    <div id="queued"></div>

    <div class="opts" style="margin-top:22px">
      <div>
        <label class="field" for="links">Links in the text</label>
        <select id="links">
          <option value="plain" selected>Plain text — cleanest to read</option>
          <option value="endnotes">Numbered endnotes at the end</option>
          <option value="keep">Keep clickable</option>
        </select>
      </div>
      <div>
        <label class="field" for="style">Layout</label>
        <select id="style"></select>
      </div>
    </div>

    <div class="checks">
      <label><input type="checkbox" id="numbered" checked> Number sections &amp; figures</label>
      <label><input type="checkbox" id="images" checked> Include images</label>
      <label><input type="checkbox" id="showurl" checked> Show source URL</label>
    </div>

    <button class="go" id="go">Convert</button>
  </div>

  <div id="results"></div>
  <div class="folder" id="folder"></div>
</div>

<script>
const $ = id => document.getElementById(id);
const dropped = [];   // { name, html } from drag-and-drop

fetch('/api/info').then(r => r.json()).then(info => {
  $('style').innerHTML = info.styles
    .map(s => `<option value="${s}"${s === 'essay' ? ' selected' : ''}>${s}</option>`).join('');
  $('folder').innerHTML = 'Saving to <code>' + info.output_dir + '</code>';
});

const drop = $('drop');
['dragenter','dragover'].forEach(e =>
  drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('hot'); }));
['dragleave','drop'].forEach(e =>
  drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('hot'); }));

drop.addEventListener('drop', ev => {
  for (const file of ev.dataTransfer.files) {
    if (!/\.(html?|xhtml)$/i.test(file.name)) continue;
    const reader = new FileReader();
    reader.onload = () => { dropped.push({ name: file.name, html: reader.result }); paintQueue(); };
    reader.readAsText(file);
  }
});

drop.addEventListener('click', () => {
  const picker = document.createElement('input');
  picker.type = 'file'; picker.accept = '.html,.htm'; picker.multiple = true;
  picker.onchange = () => {
    for (const file of picker.files) {
      const reader = new FileReader();
      reader.onload = () => { dropped.push({ name: file.name, html: reader.result }); paintQueue(); };
      reader.readAsText(file);
    }
  };
  picker.click();
});

function paintQueue() {
  $('queued').innerHTML = dropped.length
    ? 'Queued: ' + dropped.map((f, i) =>
        `<span>${f.name} <a href="#" onclick="removeFile(${i});return false" style="color:inherit">×</a></span>`).join('')
    : '';
}
function removeFile(i) { dropped.splice(i, 1); paintQueue(); }

$('go').onclick = async () => {
  const lines = $('sources').value.split('\n').map(s => s.trim()).filter(Boolean);
  const jobs = lines.map(v => ({ kind: 'ref', value: v }))
    .concat(dropped.map(f => ({ kind: 'inline', name: f.name, html: f.html })));

  if (!jobs.length) { alert('Add at least one link, path, or file.'); return; }

  const options = {
    links:    $('links').value,
    style:    $('style').value,
    numbered: $('numbered').checked,
    images:   $('images').checked,
    show_url: $('showurl').checked,
  };

  $('go').disabled = true;
  const results = $('results');
  results.innerHTML = '';

  for (let i = 0; i < jobs.length; i++) {
    const job = jobs[i];
    const label = job.kind === 'ref' ? job.value : job.name;
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<span class="badge"><span class="spinner"></span></span>
                     <div class="body"><div class="name">${esc(label)}</div>
                     <div class="meta">converting…</div></div>`;
    results.appendChild(row);

    try {
      const resp = await fetch('/api/convert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job, options }),
      });
      const data = await resp.json();

      if (data.ok) {
        const warns = (data.warnings || [])
          .map(w => `<div class="warn">${esc(w)}</div>`).join('');
        row.className = 'row ok';
        row.innerHTML = `<span class="badge">✓</span>
          <div class="body">
            <div class="name">${esc(data.title)}</div>
            <div class="meta">${data.pages} pages · ${data.words.toLocaleString()} words
              · ${data.images} images · ${data.size_kb} KB</div>${warns}
          </div>
          <a class="dl" href="/download/${encodeURIComponent(data.file)}" download>Download</a>`;
      } else {
        row.className = 'row err';
        row.innerHTML = `<span class="badge">✗</span>
          <div class="body"><div class="name">${esc(label)}</div>
          <div class="meta">${esc(data.error)}</div></div>`;
      }
    } catch (err) {
      row.className = 'row err';
      row.innerHTML = `<span class="badge">✗</span><div class="body">
        <div class="name">${esc(label)}</div>
        <div class="meta">${esc(String(err))}</div></div>`;
    }
  }

  dropped.length = 0; paintQueue();
  $('go').disabled = false;
};

function esc(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
}
</script>
</body>
</html>
"""


# ==========================================================================
# Request handling
# ==========================================================================

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "html2pdf/1.0"

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/convert"):
            sys.stderr.write("  · %s\n" % (fmt % args))

    # -- helpers ----------------------------------------------------------

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        route = urllib.parse.urlparse(self.path).path

        if route in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

        elif route == "/api/info":
            self._json(200, {
                "styles": converter.available_styles(),
                "output_dir": OUTPUT_DIR,
            })

        elif route.startswith("/download/"):
            name = os.path.basename(urllib.parse.unquote(route[len("/download/"):]))
            path = os.path.join(OUTPUT_DIR, name)
            # Keep downloads confined to the output directory.
            if not os.path.abspath(path).startswith(OUTPUT_DIR) or not os.path.isfile(path):
                self._send(404, b"Not found", "text/plain")
                return
            with open(path, "rb") as fh:
                data = fh.read()
            self._send(200, data, "application/pdf", {
                "Content-Disposition": f'attachment; filename="{name}"'
            })

        else:
            self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/convert":
            self._send(404, b"Not found", "text/plain")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": f"Bad request: {exc}"})
            return

        job = payload.get("job") or {}
        opts = payload.get("options") or {}
        scratch = None

        try:
            if job.get("kind") == "inline":
                # A file dropped in the browser: we only have its text, so stage
                # it on disk for the converter to read.
                fd, scratch = tempfile.mkstemp(suffix=".html")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(job.get("html", ""))
                source = scratch
            else:
                source = (job.get("value") or "").strip()
                if not source:
                    raise ValueError("Empty source")
                if not source.startswith(("http://", "https://")):
                    source = os.path.expanduser(source)
                    if not os.path.isfile(source):
                        raise FileNotFoundError(
                            f"Not a URL, and no file exists at: {source}"
                        )

            os.makedirs(OUTPUT_DIR, exist_ok=True)
            staging = os.path.join(OUTPUT_DIR, ".w2p-staging.pdf")

            result = converter.convert(
                source, staging,
                style=opts.get("style", "essay"),
                numbered=bool(opts.get("numbered", True)),
                link_mode=opts.get("links", "plain"),
                show_url=bool(opts.get("show_url", True)),
                images=bool(opts.get("images", True)),
            )

            final_name = converter.suggest_filename(result.title)
            final_path = os.path.join(OUTPUT_DIR, final_name)
            if os.path.exists(final_path):
                stem, ext = os.path.splitext(final_path)
                n = 2
                while os.path.exists(f"{stem}-{n}{ext}"):
                    n += 1
                final_path = f"{stem}-{n}{ext}"
                final_name = os.path.basename(final_path)
            os.replace(staging, final_path)

            self._json(200, {
                "ok": True,
                "title": result.title,
                "file": final_name,
                "pages": result.pages,
                "words": result.word_count,
                "images": result.images,
                "size_kb": round(os.path.getsize(final_path) / 1024),
                "warnings": result.warnings,
            })

        except Exception as exc:
            self._json(200, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if scratch and os.path.exists(scratch):
                os.remove(scratch)


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    global OUTPUT_DIR

    parser = argparse.ArgumentParser(description="Local web front end for html2pdf.")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("-o", "--output", default=OUTPUT_DIR,
                        help="where finished PDFs are saved")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't open a browser window on start")
    args = parser.parse_args()

    OUTPUT_DIR = os.path.abspath(os.path.expanduser(args.output))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    url = f"http://127.0.0.1:{args.port}"
    try:
        # 127.0.0.1, not 0.0.0.0 — nothing on the network can reach this.
        server = ThreadedServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"Could not start on port {args.port}: {exc}\n"
              f"Try:  python3 server.py --port {args.port + 1}", file=sys.stderr)
        return 1

    print(f"\n  Webpage → A4 PDF")
    print(f"  {url}")
    print(f"  Saving to {OUTPUT_DIR}")
    print(f"  Ctrl-C to stop\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
