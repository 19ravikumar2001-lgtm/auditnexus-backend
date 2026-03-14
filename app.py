import os
import time
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("GEMINI_API_KEY", "")
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "AuditNexus Backend", "version": "1.0"})

@app.route("/vouch-prompt", methods=["POST"])
def vouch_prompt():
    try:
        body = request.get_json(force=True)
        prompt = body.get("prompt", "")
        file_uris = body.get("fileUris", [])
        api_key = body.get("apiKey") or API_KEY

        if not api_key:
            return jsonify({"success": False, "message": "No API key"})
        if not prompt:
            return jsonify({"success": False, "message": "No prompt"})

        parts = [{"text": prompt}]
        for doc in file_uris:
            parts.append({"text": "--- " + doc.get("fileName", "doc") + " ---"})
            parts.append({
                "file_data": {
                    "mime_type": doc.get("mimeType", "application/pdf"),
                    "file_uri": doc.get("fileUri", "")
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
        }

        for attempt in range(3):
            try:
                resp = requests.post(
                    URL + "?key=" + api_key,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=120
                )
                data = resp.json()

                if "error" in data:
                    msg = data["error"].get("message", "error")
                    code = data["error"].get("code", 0)
                    if ("quota" in msg.lower() or code == 429) and attempt < 2:
                        time.sleep(30)
                        continue
                    return jsonify({"success": False, "message": msg})

                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return jsonify({"success": True, "text": text})

            except Exception as ex:
                if attempt < 2:
                    time.sleep(15)
                    continue
                return jsonify({"success": False, "message": str(ex)})

        return jsonify({"success": False, "message": "Failed after retries"})

    except Exception as ex:
        return jsonify({"success": False, "message": str(ex)})


@app.route("/vouch-bulk", methods=["POST"])
def vouch_bulk():
    try:
        body = request.get_json(force=True)
        samples = body.get("samples", [])
        file_uris = body.get("fileUris", [])
        api_key = body.get("apiKey") or API_KEY
        eng = body.get("engName", "")
        area = body.get("area", "")
        fy = body.get("fy", "")

        if not api_key:
            return jsonify({"success": False, "message": "No API key"})

        processed = []
        errors = []

        for sample in samples:
            sid = sample.get("sampleId", "")
            txn = json.dumps(sample.get("txnData", {}))
            docs = "\n".join([d.get("fileName", "") for d in file_uris])

            prompt = (
                "You are a Senior CA performing audit vouching.\n"
                "ENGAGEMENT: " + eng + " | FY: " + fy + " | AREA: " + area + " | SAMPLE: " + sid + "\n"
                "LEDGER: " + txn + "\n"
                "DOCUMENTS:\n" + docs + "\n"
                "Return ONLY valid JSON: "
                "{\"verdict\":\"PASS\",\"confidence\":90,\"summary\":\"\","
                "\"documentsRead\":[],\"checks\":[],\"threeWayMatch\":{},\"exceptions\":[]}"
            )

            parts = [{"text": prompt}]
            for doc in file_uris:
                parts.append({"text": "--- " + doc.get("fileName", "doc") + " ---"})
                parts.append({
                    "file_data": {
                        "mime_type": doc.get("mimeType", "application/pdf"),
                        "file_uri": doc.get("fileUri", "")
                    }
                })

            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
            }

            ok = False
            for attempt in range(3):
                try:
                    resp = requests.post(
                        URL + "?key=" + api_key,
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=120
                    )
                    data = resp.json()
                    if "error" in data:
                        msg = data["error"].get("message", "")
                        code = data["error"].get("code", 0)
                        if ("quota" in msg.lower() or code == 429) and attempt < 2:
                            time.sleep(30)
                            continue
                        errors.append(sid + ": " + msg)
                        break
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    processed.append({"sampleId": sid, "text": text})
                    ok = True
                    break
                except Exception as ex:
                    if attempt < 2:
                        time.sleep(15)
                        continue
                    errors.append(sid + ": " + str(ex))
                    break

            if ok:
                time.sleep(5)

        return jsonify({
            "success": len(processed) > 0,
            "processed": processed,
            "errors": errors,
            "message": str(len(processed)) + " processed"
        })

    except Exception as ex:
        return jsonify({"success": False, "message": str(ex)})
```

---

## After pasting — also do these 3 things:

**1. requirements.txt** — make sure it is just these 4 lines, nothing else:
```
flask
flask-cors
requests
gunicorn
```

**2. runtime.txt** — make sure it exists with just:
```
python-3.11.0
```

**3. Render → Settings → Start Command** — set to just:
```
gunicorn app:app
