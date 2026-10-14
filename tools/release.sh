#!/bin/sh
# Arma los binarios de una versión en dist/: los nucleo-* para macOS (universal), Linux y
# Windows (amd64), el .mcpb de la app de Claude y, en macOS con cargo tauri, la app de escritorio
# Faro (app-rs, motor Rust adentro: es la que se publica; universal si está el target x86_64,
# si no, solo Apple Silicon).
#
#   ./tools/release.sh 1.0.0              # dist/1.0.0/*
#   gh release create v1.0.0 dist/1.0.0/* --title "Faro 1.0.0" --notes-file …
set -eu
cd "$(dirname "$0")/.."
V="${1:?versión, ej. 1.0.0}"
OUT="dist/$V"; rm -rf "$OUT"; mkdir -p "$OUT"
BINS="nucleo-servidor nucleo-mcp nucleo-keystore nucleo-sii nucleo-rvd nucleo-cafs nucleo-portal nucleo-certificacion nucleo-siiengine nucleo-emitir nucleo-pdf nucleo-dorado"
LD="-s -w -X main.version=$V"
build() { # sistema arquitectura sufijo
  T="$(mktemp -d)"
  for b in $BINS; do
    (cd nucleo && CGO_ENABLED=0 GOOS="$1" GOARCH="$2" go build -trimpath -ldflags="$LD" -o "$T/$b$3" "./cmd/$b")
  done
  echo "$T"
}
echo "→ macOS universal"
A="$(build darwin arm64 "")"; X="$(build darwin amd64 "")"; M="$(mktemp -d)"
for b in $BINS; do
  if command -v lipo >/dev/null; then lipo -create "$A/$b" "$X/$b" -output "$M/$b"; else cp "$A/$b" "$M/$b"; fi
done
(cd "$M" && tar -czf "$OLDPWD/$OUT/nucleo-$V-macos-universal.tar.gz" .)
echo "→ Linux amd64"
L="$(build linux amd64 "")"; (cd "$L" && tar -czf "$OLDPWD/$OUT/nucleo-$V-linux-amd64.tar.gz" .)
echo "→ Windows amd64"
W="$(build windows amd64 ".exe")"; (cd "$W" && zip -qr "$OLDPWD/$OUT/nucleo-$V-windows-amd64.zip" .)
rm -rf "$A" "$X" "$M" "$L" "$W"
echo "→ .mcpb (app de Claude)"
./tools/empaquetar_mcpb.sh >/dev/null && cp nucleo/bin/dte-chile.mcpb "$OUT/dte-chile-$V.mcpb"
if [ "$(uname)" = Darwin ] && command -v cargo >/dev/null 2>&1 && cargo tauri --version >/dev/null 2>&1; then
  if rustup target list --installed 2>/dev/null | grep -q x86_64-apple-darwin; then
    echo "→ app de escritorio Faro (macOS, universal, sin firmar)"
    (cd app-rs && cargo tauri build --target universal-apple-darwin --bundles app >/dev/null)
    APP="app-rs/target/universal-apple-darwin/release/bundle/macos"
  else
    echo "→ app de escritorio Faro (macOS, Apple Silicon, sin firmar; instala el target x86_64-apple-darwin para universal)"
    (cd app-rs && cargo tauri build --bundles app >/dev/null)
    APP="app-rs/target/release/bundle/macos"
  fi
  (cd "$APP" && zip -qr "$OLDPWD/$OUT/Faro-$V-macos.zip" "Faro.app")
fi
(cd "$OUT" && shasum -a 256 ./* > SHA256SUMS.txt)
ls -la "$OUT" | awk 'NR>1{printf "   %-40s %6.1f MB\n", $NF, $5/1048576}'
echo "listo: $OUT"
