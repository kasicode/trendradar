from flask import Flask, request, jsonify
import anthropic
import os

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/chat", methods=["GET", "POST", "OPTIONS"])
def chat():
    if request.method in ["GET", "OPTIONS"]:
        return jsonify({"status": "ok"})

    body = request.json
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=body.get("max_tokens", 2000),
        messages=body.get("messages", [])
    )
    return jsonify({"content": [{"type": "text", "text": message.content[0].text}]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
