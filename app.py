# ════════════════════════════════════════════════════════════════
#  AuditNexus — Python Backend
#  R.G.N. Price & Co., Chartered Accountants
#  Handles Gemini API calls with retry logic
#  Deploy on Render.com (free tier)
# ════════════════════════════════════════════════════════════════

import os
import time
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
MAX_RETRIES    = 4
BASE_WAIT      = 15  # seconds

# ── Health check ──
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status":  "ok",
        "service": "AuditNexus Python Backend",
        "firm":    "R.G.N. Price & Co., Chartered Accountants",
        "version": "1.0"
    })

# ── Single vouching prompt ──
# Called by Apps Script runAIVouching / runBulkVouching
@app.route("/vouch-prompt", methods=["POST"])
def vouch_prompt():
    try:
        body       = request.get_json(force=True)
        prompt     = body.get("prompt", "")
        file_uris  = body.get("fileUris", [])   # list of {fileUri, mimeType, fileName}
        api_key    = body.get("apiKey") or GEMINI_API_KEY

        if not api_key:
            return jsonify({"success": False, "message": "GEMINI_API_KEY not set on server."}), 400
        if not prompt:
            return jsonify({"success": False, "message": "No prompt provided."}), 400

        # Build parts array
        parts = [{"text": prompt}]
        for doc in file_uris:
            parts.append({
                "text": f"--- DOCUMENT: {doc.get('fileName','document')} ({doc.get('docType','')}) ---"
            })
            parts.append({
                "file_data": {
                    "mime_type": doc.get("mimeType", "application/pdf"),
                    "file_uri":  doc.get("fileUri", "")
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature":    0.1,
                "maxOutputTokens": 4096
            }
        }

        # Retry loop with exponential backoff
        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(
                    f"{GEMINI_URL}?key={api_key}",
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=120
                )
                data = resp.json()

                if "error" in data:
                    err_msg  = data["error"].get("message", "Unknown error")
                    err_code = data["error"].get("code", 0)
                    is_quota = (
                        "quota"    in err_msg.lower() or
                        "rate"     in err_msg.lower() or
                        "limit"    in err_msg.lower() or
                        err_code == 429
                    )
                    if is_quota and attempt < MAX_RETRIES:
                        wait = BASE_WAIT * (2 ** (attempt - 1))
                        print(f"[AuditNexus] Quota error attempt {attempt}, waiting {wait}s…")
                        time.sleep(wait)
                        last_error = err_msg
                        continue
                    return jsonify({"success": False, "message": f"Gemini error: {err_msg}"}), 200

                # Extract text
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                return jsonify({"success": True, "text": raw_text}), 200

            except requests.exceptions.Timeout:
                last_error = "Request timed out"
                if attempt < MAX_RETRIES:
                    time.sleep(BASE_WAIT)
                    continue
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    time.sleep(BASE_WAIT)
                    continue

        return jsonify({
            "success": False,
            "message": f"Failed after {MAX_RETRIES} attempts. Last error: {last_error}"
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


# ── Bulk vouching endpoint ──
# Accepts multiple samples + pre-uploaded fileUris
@app.route("/vouch-bulk", methods=["POST"])
def vouch_bulk():
    try:
        body     = request.get_json(force=True)
        samples  = body.get("samples", [])
        file_uris = body.get("fileUris", [])
        api_key  = body.get("apiKey") or GEMINI_API_KEY
        eng_name = body.get("engName", "")
        area     = body.get("area", "")
        fy       = body.get("fy", "")

        if not api_key:
            return jsonify({"success": False, "message": "GEMINI_API_KEY not set."}), 400

        processed = []
        errors    = []

        for sample in samples:
            sample_id = sample.get("sampleId", "")
            txn_data  = sample.get("txnData", {})

            prompt = _build_prompt(eng_name, area, fy, sample_id, txn_data, file_uris)

            parts = [{"text": prompt}]
            for doc in file_uris:
                parts.append({"text": f"--- DOCUMENT: {doc.get('fileName','doc')} ---"})
                parts.append({
                    "file_data": {
                        "mime_type": doc.get("mimeType", "application/pdf"),
                        "file_uri":  doc.get("fileUri", "")
                    }
                })

            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
            }

            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = requests.post(
                        f"{GEMINI_URL}?key={api_key}",
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=120
                    )
                    data = resp.json()
                    if "error" in data:
                        err_msg  = data["error"].get("message", "")
                        err_code = data["error"].get("code", 0)
                        is_quota = "quota" in err_msg.lower() or "rate" in err_msg.lower() or err_code == 429
                        if is_quota and attempt < MAX_RETRIES:
                            time.sleep(BASE_WAIT * (2 ** (attempt - 1)))
                            continue
                        errors.append(f"{sample_id}: {err_msg}")
                        break
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    processed.append({"sampleId": sample_id, "text": raw_text})
                    success = True
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        time.sleep(BASE_WAIT)
                        continue
                    errors.append(f"{sample_id}: {str(e)}")
                    break

            # Polite delay between samples
            if success:
                time.sleep(5)

        msg = f"{len(processed)} sample(s) processed."
        if errors:
            msg += f" {len(errors)} error(s): {'; '.join(errors)}"

        return jsonify({
            "success":   len(processed) > 0,
            "processed": processed,
            "errors":    errors,
            "message":   msg
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


def _build_prompt(eng_name, area, fy, sample_id, txn_data, docs):
    txn_str  = json.dumps(txn_data, indent=2)
    doc_list = "\n".join([f"{i+1}. {d.get('fileName','')}" for i, d in enumerate(docs)])
    return (
        f"You are a Senior Chartered Accountant (FCA) performing audit vouching.\n"
        f"ENGAGEMENT: {eng_name} | FY: {fy} | AREA: {area} | SAMPLE: {sample_id}\n\n"
        f"LEDGER DATA:\n{txn_str}\n\n"
        f"DOCUMENTS ({len(docs)}):\n{doc_list}\n\n"
        f"Read every document. Extract all fields. Compare vs ledger. Return ONLY valid JSON:\n"
        f'{{"verdict":"PASS"|"EXCEPTION"|"INSUFFICIENT_DOCS","confidence":0-100,'
        f'"summary":"","documentsRead":[],"checks":[],"threeWayMatch":{{}},"exceptions":[]}}'
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
```

---
