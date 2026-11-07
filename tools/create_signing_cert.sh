#!/bin/bash
# One-time setup: creates a self-signed code-signing certificate in your
# login keychain, which build.sh then uses to sign every build.
#
# Why: macOS ties Accessibility permission to an app's signing identity.
# Ad-hoc signing gives every build a brand-new identity, so each update
# would need permission re-granted. Signing every build with this same
# certificate keeps the identity stable, so permission survives updates.
#
# BACK THIS CERTIFICATE UP (Keychain Access > My Certificates > right-click
# "mousephone Code Signing" > Export). If it's lost, a new one can be made,
# but everyone will need to re-grant Accessibility permission once, and
# existing installs will refuse updates signed with the new one.
set -e

IDENTITY="mousephone Code Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if security find-certificate -c "$IDENTITY" "$KEYCHAIN" >/dev/null 2>&1; then
  echo "\"$IDENTITY\" already exists in your login keychain — nothing to do."
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/cert.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $IDENTITY
[ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, codeSigning
EOF

# /usr/bin/openssl (LibreSSL) on purpose: Homebrew's OpenSSL 3 writes .p12
# files with encryption that `security import` can't read.
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -config "$TMP/cert.cnf" -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null

PASS=$(/usr/bin/openssl rand -hex 16)
/usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
  -name "$IDENTITY" -out "$TMP/cert.p12" -passout "pass:$PASS"

# -T lets codesign use the key without a keychain prompt on every build.
security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "$PASS" -T /usr/bin/codesign >/dev/null

echo "Created \"$IDENTITY\" in your login keychain."
echo "Back it up now: Keychain Access > My Certificates > right-click it > Export."
