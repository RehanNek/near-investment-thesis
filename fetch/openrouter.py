"""OpenRouter (third-party): daily tokens NEAR AI serves as an inference provider on OpenRouter.

Source: https://openrouter.ai/provider/near-ai ("Tokens processed on OpenRouter" chart). There is
no documented API for this chart; the page embeds its data (chartData: daily tokens per model, and
the provider's model list), so this fetcher saves the raw page and extracts the series.
This is one distribution channel for NEAR AI Cloud, measured independently by OpenRouter. NEAR AI
Cloud's direct API usage is not published.

Also saves, for each model NEAR AI serves, the model's total daily tokens on OpenRouter across all
providers (split into prompt and completion tokens) and every provider's listed price, so NEAR AI's
share of each model's traffic and a revenue estimate can be computed.

Output: data/raw/openrouter/<YYYY-MM-DD>/{page.html.gz, near_ai_tokens_daily.json, near_ai_models.json,
        model_<slug>_chart.json, model_<slug>_endpoints.json}

Usage: python -m fetch.openrouter
"""
from __future__ import annotations

import gzip
import json
import re

from fetch.common import RAW, http_get, record_fetch, utc_now, write_json

URL = "https://openrouter.ai/provider/near-ai"


def extract(blob: str, key: str):
    m = re.search(rf'"{key}":\[\{{', blob)
    if not m:
        raise SystemExit(f"'{key}' not found on the page; layout may have changed.")
    return json.JSONDecoder().raw_decode(blob, m.end() - 2)[0]


def main() -> None:
    html = http_get(URL).text
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    blob = "".join(json.loads('"' + c + '"') for c in chunks)
    chart = extract(blob, "chartData")
    models = [{k: m.get(k) for k in ("slug", "permaslug", "name", "author", "created_at", "context_length")}
              for m in extract(blob, "models")]
    out = RAW / "openrouter" / utc_now()[:10]
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "page.html.gz", "wt", encoding="utf-8") as f:
        f.write(html)
    write_json(out / "near_ai_tokens_daily.json", chart)
    write_json(out / "near_ai_models.json", models)
    print(f"  {len(chart)} days ({chart[0]['x'][:10]}..{chart[-1]['x'][:10]}), {len(models)} models")

    # For each model NEAR AI serves: the model's total daily tokens on OpenRouter across all providers
    # (prompt vs completion), from the model page's embedded `model_chart` (~30 days), and every
    # provider's listed price from the public endpoints API.
    for m in models:
        slug = m["slug"]
        page = http_get(f"https://openrouter.ai/{slug}").text
        chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page)
        mblob = "".join(json.loads('"' + c + '"') for c in chunks)
        try:
            model_chart = extract(mblob, "model_chart")
        except SystemExit:
            model_chart = []
        endpoints = http_get(f"https://openrouter.ai/api/v1/models/{slug}/endpoints").json().get("data", {}).get("endpoints", [])
        name = slug.replace("/", "__")
        write_json(out / f"model_{name}_chart.json", model_chart)
        write_json(out / f"model_{name}_endpoints.json", endpoints)
        print(f"  {slug}: {len(model_chart)} days of model totals, {len(endpoints)} providers")
    record_fetch("openrouter", url=URL, days=len(chart), first=chart[0]["x"][:10], last=chart[-1]["x"][:10],
                 models=[m["slug"] for m in models])


if __name__ == "__main__":
    main()
