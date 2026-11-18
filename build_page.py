#!/usr/bin/env python3
"""Build site/: a copy of the cambrian.org homepage with the metrics strip, behind a password.

The finished homepage is encrypted with PAGE_PASSWORD (PBKDF2-SHA256 -> AES-256-GCM) and only
the ciphertext is published in site/index.html. The browser asks for the password, decrypts,
and swaps the page in. Images, fonts and stylesheets are copies of public cambrian.org assets.
No API key is ever part of the page. Run with --expired to publish an "expired" page instead.
"""
import base64, html, json, os, shutil, sys
from pathlib import Path

ITERATIONS = 600_000
HOME = Path("homepage")
SITE = Path("site")
EYEBROW = "DATA FOR EXECUTION, NOT JUST ANALYSIS"

GATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Cambrian</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>
@font-face{font-family:"Crimson Text";src:url(assets/media/6c7b277d2518c12b-s.p.woff2) format("woff2");font-display:swap}
*{box-sizing:border-box}
html,body{margin:0}
body{min-height:100vh;background:#1a2f11;color:#F6EBD3;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;align-items:center;justify-content:center;padding:24px 16px}
.gate{width:100%;max-width:380px;text-align:center}
.gate img{height:40px;width:auto;margin-bottom:28px}
.gate p{opacity:.8;font-size:15px;line-height:1.6;margin:0 0 22px}
form{display:flex;gap:8px}
input{flex:1;min-width:0;padding:12px 14px;border:1px solid #4b6b3d;background:#22391a;color:#F6EBD3;font:inherit;font-size:15px;border-radius:6px}
button{padding:12px 20px;border:0;border-radius:6px;background:#4b9328;color:#F6EBD3;font:inherit;font-size:15px;cursor:pointer}
button:disabled{opacity:.6;cursor:default}
input:focus-visible,button:focus-visible{outline:2px solid #ecdfc3;outline-offset:2px}
.err{color:#f2b8a8;min-height:1.4em;margin-top:12px;font-size:14px}
</style></head><body>
<div class="gate"><img src="cambrian-logo-wordmark-beige.svg" alt="Cambrian">
__BODY__
</div>__SCRIPT__</body></html>
"""

FORM = """<p>This preview is private. Enter the password to view it.</p>
<form id="f"><input id="pw" type="password" autocomplete="current-password" aria-label="Password" placeholder="Password" required autofocus>
<button id="go" type="submit">View</button></form><div class="err" id="err" role="alert"></div>"""

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
    const page=new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:b(P.iv)},key,b(P.ct)));
    document.open();document.write(page);document.close();
  }catch(x){err.textContent='That password did not work. Try again.';btn.disabled=false;}
});
</script>"""


def strip(data):
    tiles = "".join(
        f'<li class="cm-tile"><span class="cm-num">{html.escape(m["display"])}</span>'
        f'<span class="cm-label">{html.escape(m["label"])}</span></li>'
        for m in data["metrics"])
    return (f'<section class="cm-metrics" aria-labelledby="cm-eyebrow"><div class="section-container">'
            f'<p id="cm-eyebrow" class="cm-eyebrow">{EYEBROW}</p><ul class="cm-grid">{tiles}</ul></div></section>')


def encrypt(plaintext, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())
    e = lambda x: base64.b64encode(x).decode()
    return {"salt": e(salt), "iv": e(iv), "ct": e(AESGCM(key).encrypt(iv, plaintext.encode(), None)), "iter": ITERATIONS}


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    if "--expired" in sys.argv:
        SITE.mkdir()
        for f in ("cambrian-logo-wordmark-beige.svg", "favicon.svg"):
            shutil.copy(HOME / f, SITE / f)
        page = GATE.replace("__BODY__", "<p>This preview has expired.</p>").replace("__SCRIPT__", "")
    else:
        password = os.environ["PAGE_PASSWORD"]
        if len(password) < 12:
            sys.exit("PAGE_PASSWORD must be at least 12 characters.")
        shutil.copytree(HOME, SITE, ignore=shutil.ignore_patterns("index.template.html"))
        homepage = (HOME / "index.template.html").read_text(encoding="utf-8")
        homepage = homepage.replace("<!--CAMBRIAN_METRICS-->", strip(json.load(open("metrics.json"))), 1)
        payload = encrypt(homepage, password)
        page = GATE.replace("__BODY__", FORM).replace("__SCRIPT__", SCRIPT.replace("__PAYLOAD__", json.dumps(payload)))
    (SITE / "index.html").write_text(page, encoding="utf-8")
    (SITE / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    print("wrote", SITE / "index.html", len(page), "bytes")


if __name__ == "__main__":
    main()
