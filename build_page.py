#!/usr/bin/env python3
"""Build site/index.html: the metrics page, encrypted with PAGE_PASSWORD.

The published file contains only ciphertext. The browser asks for the password and
decrypts with the Web Crypto API (PBKDF2-SHA256 -> AES-256-GCM). Nothing readable is
published without the password, and no API key is ever part of the page.
Run with --expired to publish the "this page has expired" placeholder instead.
"""
import base64, html, json, os, sys
from pathlib import Path

ITERATIONS = 600_000
EXPIRES_ON = os.environ.get("EXPIRES_ON", "")

SHELL = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Cambrian API Coverage</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500&family=Inter:wght@500&display=swap" rel="stylesheet">
<style>
:root{--cream:#f3ead6;--ink:#2b2a26;--green:#458937;--deep:#1b3f1f;--muted:#6f6a5c}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--cream);color:var(--ink);font-family:Inter,system-ui,sans-serif;min-height:100vh;padding:56px 16px}
main{max-width:1180px;margin:0 auto}
h1{font-family:'EB Garamond',Georgia,serif;font-weight:400;font-size:clamp(30px,4.2vw,46px);line-height:1.1;margin:0 0 10px}
.sub{color:var(--muted);font-size:13px;letter-spacing:.04em;margin:0 0 36px}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:16px}
.tile{background:var(--green);color:var(--cream);padding:40px 14px 30px;text-align:center;display:flex;flex-direction:column;justify-content:flex-start;min-height:200px}
.tile:nth-child(even){background:var(--deep)}
.num{font-family:'EB Garamond',Georgia,serif;font-size:clamp(40px,4.3vw,58px);line-height:1;font-weight:400;white-space:nowrap}
.label{margin-top:22px;font-size:12.5px;font-weight:500;letter-spacing:.14em;text-transform:uppercase;line-height:1.55;text-wrap:balance}
.exact{margin-top:12px;font-size:11.5px;opacity:.72;font-variant-numeric:tabular-nums}
.foot{margin-top:28px;color:var(--muted);font-size:12.5px;line-height:1.7}
@media (max-width:980px){.grid{grid-template-columns:repeat(2,1fr)}.tile:last-child{grid-column:1/-1}}
@media (max-width:520px){.grid{grid-template-columns:1fr}.tile:last-child{grid-column:auto}}
.gate{max-width:380px;margin:14vh auto 0;text-align:center}
.gate p{color:var(--muted);font-size:14px;line-height:1.6}
.gate form{display:flex;gap:8px;margin-top:22px}
.gate input{flex:1;min-width:0;padding:12px 14px;border:1px solid #cbbf9f;background:#fbf6ea;font:inherit;font-size:15px;color:var(--ink)}
.gate button{padding:12px 20px;border:0;background:var(--deep);color:var(--cream);font:inherit;font-size:12.5px;letter-spacing:.14em;text-transform:uppercase;cursor:pointer}
.gate button:disabled{opacity:.6;cursor:default}
.gate input:focus-visible,.gate button:focus-visible{outline:2px solid var(--green);outline-offset:2px}
.err{color:#9c2f1c;min-height:1.4em;margin-top:12px;font-size:13.5px}
</style></head><body><main id="app">__BODY__</main>__SCRIPT__</body></html>
"""

GATE = """<div class="gate"><h1>Cambrian API Coverage</h1>
<p>This page is private. Enter the password to view the metrics.</p>
<form id="f"><input id="pw" type="password" autocomplete="current-password" aria-label="Password" placeholder="Password" required autofocus>
<button id="go" type="submit">View</button></form><div class="err" id="err" role="alert"></div></div>"""

SCRIPT = """<script>
const P=__PAYLOAD__;
const b=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
document.getElementById('f').addEventListener('submit',async e=>{
  e.preventDefault();
  const btn=document.getElementById('go'),err=document.getElementById('err');
  btn.disabled=true;err.textContent='';
  try{
    const km=await crypto.subtle.importKey('raw',new TextEncoder().encode(document.getElementById('pw').value),'PBKDF2',false,['deriveKey']);
    const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt:b(P.salt),iterations:P.iter,hash:'SHA-256'},km,{name:'AES-GCM',length:256},false,['decrypt']);
    const pt=await crypto.subtle.decrypt({name:'AES-GCM',iv:b(P.iv)},key,b(P.ct));
    document.getElementById('app').innerHTML=new TextDecoder().decode(pt);
  }catch(x){err.textContent='That password did not work. Try again.';btn.disabled=false;}
});
</script>"""


def exact(m):
    v = m["value"]
    if v is None:
        return "not available"
    if m["id"] in ("lending_supply", "weekly_volume"):
        return f"${v / 1e9:,.2f}B"
    return f"{int(v):,}"


def inner(data):
    tiles = []
    for m in data["metrics"]:
        note = " · partly from last good run" if m.get("stale_sources") else ""
        tiles.append(f'<div class="tile"><div class="num">{html.escape(m["display"])}</div>'
                     f'<div class="label">{html.escape(m["label"])}</div>'
                     f'<div class="exact">{html.escape(exact(m))}{note}</div></div>')
    exp = f" This page expires on {html.escape(EXPIRES_ON)}." if EXPIRES_ON else ""
    return (f'<h1>Cambrian API Coverage</h1><p class="sub">UPDATED {html.escape(data["generated_at"])}</p>'
            f'<div class="grid">{"".join(tiles)}</div>'
            f'<p class="foot">Figures are rounded down and refreshed daily from the Cambrian API. '
            f'Pool and token counts are floors where the API caps pagination; weekly volume counts only '
            f'the main wrapped native token on each chain.{exp}</p>')


def encrypt(plaintext, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    e = lambda x: base64.b64encode(x).decode()
    return {"salt": e(salt), "iv": e(iv), "ct": e(ct), "iter": ITERATIONS}


def main():
    Path("site").mkdir(exist_ok=True)
    if "--expired" in sys.argv:
        body = '<div class="gate"><h1>This page has expired</h1><p>The Cambrian API coverage preview is no longer available.</p></div>'
        page = SHELL.replace("__BODY__", body).replace("__SCRIPT__", "")
    else:
        password = os.environ["PAGE_PASSWORD"]
        if len(password) < 12:
            sys.exit("PAGE_PASSWORD must be at least 12 characters.")
        payload = encrypt(inner(json.load(open("metrics.json"))), password)
        page = SHELL.replace("__BODY__", GATE).replace("__SCRIPT__", SCRIPT.replace("__PAYLOAD__", json.dumps(payload)))
    Path("site/index.html").write_text(page, encoding="utf-8")
    Path("site/robots.txt").write_text("User-agent: *\nDisallow: /\n")
    print("wrote site/index.html", len(page), "bytes")


if __name__ == "__main__":
    main()
