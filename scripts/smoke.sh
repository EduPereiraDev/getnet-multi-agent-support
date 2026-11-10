#!/usr/bin/env bash
# Sends the 10 brief scenarios to a running API and prints route + answer.
set -euo pipefail
URL="${URL:-http://localhost:8000/chat}"

messages=(
  "What's the difference between the Get Clássica and the Get Smart?"
  "What's the weather forecast in Porto Alegre tomorrow?"
  "When will the money from yesterday's sales be deposited?"
  "Do I need a bank account to receive my sales via Pix?"
  "My card machine won't connect to the internet, what should I do?"
  "How does receivables advance (antecipação) work with Getnet?"
  "What's the euro exchange rate today?"
  "My card machine is showing a transaction decline error."
  "How many installments can I split a sale into with the crediário?"
  "Can I sell through WhatsApp using the Payment Link?"
)

for m in "${messages[@]}"; do
  echo "=== $m"
  curl -sf -X POST "$URL" -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"message": sys.argv[1], "user_id": "cliente1988"}))' "$m")" \
    | python3 -c 'import json,sys; b=json.load(sys.stdin); assert b["route"] and b["answer"], b; print(b["route"], b["agents"], "escalated=%s" % b["escalated"]); print(b["answer"][:400])'
done
echo "smoke: ${#messages[@]}/${#messages[@]} scenarios returned 200 with a route"
