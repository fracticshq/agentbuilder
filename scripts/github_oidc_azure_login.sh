#!/usr/bin/env bash
set -euo pipefail

# Sign in to Azure from a GitHub Actions OIDC token. This deliberately avoids a
# long-lived Azure client secret. Configure the matching federated credential in
# Entra ID before enabling the release workflow.

for required in AZURE_CLIENT_ID AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID ACTIONS_ID_TOKEN_REQUEST_URL ACTIONS_ID_TOKEN_REQUEST_TOKEN; do
  if [[ -z "${!required:-}" ]]; then
    echo "Missing required GitHub OIDC/Azure environment variable: $required" >&2
    exit 1
  fi
done

separator="?"
[[ "$ACTIONS_ID_TOKEN_REQUEST_URL" == *"?"* ]] && separator="&"
audience_url="${ACTIONS_ID_TOKEN_REQUEST_URL}${separator}audience=api%3A%2F%2FAzureADTokenExchange"
federated_token="$(python3 - "$audience_url" <<'PY'
import json
import os
import sys
from urllib.request import Request, urlopen

request = Request(
    sys.argv[1],
    headers={"Authorization": f"bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"},
)
with urlopen(request, timeout=20) as response:
    print(json.load(response)["value"])
PY
)"

az login \
  --service-principal \
  --username "$AZURE_CLIENT_ID" \
  --tenant "$AZURE_TENANT_ID" \
  --federated-token "$federated_token" >/dev/null
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
unset federated_token
echo "Azure OIDC login succeeded for subscription $AZURE_SUBSCRIPTION_ID"
