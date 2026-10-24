#!/usr/bin/env bash
# Throwaway development PKI for the compose stack: one CA, the broker's server certificate (mosquitto, localhost,
# 127.0.0.1) and client certificates whose CN is the broker username: the ingest service and each simulated
# device. EC P-256 keys, clientAuth/serverAuth usages, as CoSE-Care-Agent's make_pki. Never use these in
# production: a production CA lives off the server and device keys are made on the device.
#   deploy/compose/make_dev_pki.sh [extra-device-uuid ...]
set -euo pipefail
cd "$(dirname "$0")"
OUT=pki
CLIENTS=("cose-cloud-ingest" "xseed-sim-0001" "$@")
mkdir -p "$OUT/broker" "$OUT/clients"
cnf="$OUT/openssl.cnf"
cat > "$cnf" <<'CNF'
[req]
distinguished_name = dn
[dn]
[ca]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
[server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
authorityKeyIdentifier = keyid
subjectAltName = DNS:mosquitto,DNS:localhost,IP:127.0.0.1
[client]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = clientAuth
authorityKeyIdentifier = keyid
CNF
if [ ! -f "$OUT/ca.key" ]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$OUT/ca.key"
  openssl req -x509 -new -sha256 -key "$OUT/ca.key" -subj "/CN=CoSE Cloud dev CA" -days 825 -config "$cnf" -extensions ca -out "$OUT/ca.crt"
fi
issue() {  # dir cn extensions
  local dir=$1 cn=$2 ext=$3
  mkdir -p "$dir"
  [ -f "$dir/$4.crt" ] && return 0
  openssl ecparam -name prime256v1 -genkey -noout -out "$dir/$4.key"
  openssl req -new -sha256 -key "$dir/$4.key" -subj "/CN=$cn" -config "$cnf" -out "$dir/$4.csr"
  openssl x509 -req -sha256 -in "$dir/$4.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" -CAcreateserial -days 825 \
    -extfile "$cnf" -extensions "$ext" -out "$dir/$4.crt" 2>/dev/null
  rm -f "$dir/$4.csr"
  cp "$OUT/ca.crt" "$dir/ca.crt"
}
issue "$OUT/broker" mosquitto server server
for cn in "${CLIENTS[@]}"; do issue "$OUT/clients/$cn" "$cn" client client; done
# the containers run as other users; dev keys only
chmod 644 "$OUT"/broker/* "$OUT"/clients/*/*
echo "dev PKI in $(pwd)/$OUT: broker + ${CLIENTS[*]}"
