"""Assemble the single offline HTML page from a payload: inline the pinned renderer assets,
escape the payload, write the one-line status banner, refuse external requests and a page over the
16 MB Artifact limit, write atomically.

Unlike the finance page (finance/embed.py), the GTM page embeds the whole payload: every deal and
customer list in the engine is capped (top 10 to 30), so the payload stays in the hundreds of KB
whatever the deal count, and compare.py reads the previous page's whole payload as the record of
the previous run. The size gate is the backstop if an uncapped list is ever added."""
import json
import os
import tempfile

from .common import BuildError

PAGE_LIMIT_BYTES = 16_000_000          # Artifact page cap is 16 MB; same margin under 16 MiB as the finance renderer
ART = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "artifacts", "gtm_analytics")


def render(p, out):
    read = lambda f: open(os.path.join(ART, f), encoding="utf-8").read()
    html = read("template.html")
    data = json.dumps(p, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = f"GTM review · {p['meta']['as_of']['name']}" + (" (sample)" if p["meta"]["data_mode"] == "local" else "")
    for marker, value in (("<!-- SDA:TITLE -->", title), ("<!-- SDA:CSS -->", f"<style>\n{read('gtm_analytics.css')}\n</style>"),
                          ("<!-- SDA:BANNER -->", ""), ("<!-- SDA:PAYLOAD -->", f"<script>window.__SDA_PAYLOAD__={data};</script>"),
                          ("<!-- SDA:JS -->", f"<script>\n{read('gtm_analytics.js')}\n</script>")):
        if marker not in html:
            raise BuildError(f"template marker {marker} missing")
        html = html.replace(marker, value, 1)
    if 'src="http' in html or 'href="http' in html:
        raise BuildError("the page would make an external request")
    n = len(html.encode("utf-8"))
    if n > PAGE_LIMIT_BYTES:
        raise BuildError(f"the page is {n:,} bytes, over the {PAGE_LIMIT_BYTES:,}-byte Artifact limit; no page written "
                         "(a list in the payload is not capped: cap it in gtm/engine.py, or narrow the scope)")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(out)), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, out)
    return n
