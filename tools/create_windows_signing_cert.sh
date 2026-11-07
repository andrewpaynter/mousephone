#!/bin/bash
# One-time setup: creates the self-signed certificate Windows builds are
# signed with — the Windows counterpart of create_signing_cert.sh.
#
# Why: the in-app updater on Windows only installs an update signed by the
# same certificate as the running app, which rejects tampered downloads.
# (Being self-signed, it doesn't stop Windows SmartScreen's "unknown
# publisher" warning on first install — only a paid certificate does.)
#
# Writes the certificate (.pfx) and its password to OUT_DIR (default
# ~/mousephone-windows-signing). With --upload, also stores both as the
# repo secrets the GitHub Actions build signs with.
#
# BACK UP OUT_DIR somewhere safe and private. If it's lost, a new
# certificate can be made, but installed Windows copies will refuse
# updates signed with it and need a manual reinstall once.
#
#   tools/create_windows_signing_cert.sh [--upload] [OUT_DIR]
set -e
cd "$(dirname "$0")/.."

UPLOAD=0
if [ "$1" = "--upload" ]; then UPLOAD=1; shift; fi
OUT_DIR="${1:-$HOME/mousephone-windows-signing}"
PFX="$OUT_DIR/mousephone-windows-signing.pfx"
PASS_FILE="$OUT_DIR/password.txt"

if [ -f "$PFX" ]; then
  echo "$PFX already exists — not overwriting it."
else
  mkdir -p "$OUT_DIR"
  chmod 700 "$OUT_DIR"
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT

  cat > "$TMP/cert.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = mousephone
[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
EOF

  # /usr/bin/openssl (LibreSSL) on purpose: its .pfx encryption is the
  # older kind that every Windows version and signtool accept.
  /usr/bin/openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
    -config "$TMP/cert.cnf" -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null
  /usr/bin/openssl rand -hex 24 > "$PASS_FILE"
  /usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
    -name "mousephone" -out "$PFX" -passout "file:$PASS_FILE"
  chmod 600 "$PFX" "$PASS_FILE"

  echo "Created $PFX"
  echo "Thumbprint (SHA-1, what Windows shows): $(/usr/bin/openssl x509 -in "$TMP/cert.pem" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d :)"
fi

if [ "$UPLOAD" = 1 ]; then
  base64 < "$PFX" | tr -d '\n' | gh secret set WINDOWS_SIGNING_PFX_BASE64
  gh secret set WINDOWS_SIGNING_PASSWORD < "$PASS_FILE"
  echo "Stored WINDOWS_SIGNING_PFX_BASE64 and WINDOWS_SIGNING_PASSWORD as repo secrets."
fi

echo ""
echo "Back up $OUT_DIR somewhere safe and private (a password manager works)."
