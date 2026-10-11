#!/bin/sh
# Arma los binarios de una versión en dist/: los nucleo-* para macOS (universal), Linux y
# Windows (amd64), el .mcpb de la app de Claude y, en macOS con wails, la app de escritorio.
#
#   ./tools/release.sh 1.0.0              # dist/1.0.0/*
#   gh release create v1.0.0 dist/1.0.0/* --title "DTE Chile 1.0.0" --notes-file …
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
if [ "$(uname)" = Darwin ] && command -v wails >/dev/null 2>&1 || [ -x "$HOME/go/bin/wails" ]; then
  echo "→ app de escritorio (macOS, universal, sin firmar)"
  (cd app && PATH="$PATH:$HOME/go/bin" wails build -platform darwin/universal -s >/dev/null)
  (cd app/build/bin && zip -qr "$OLDPWD/$OUT/DTE-Chile-$V-macos.zip" "DTE Chile.app")
fi
(cd "$OUT" && shasum -a 256 ./* > SHA256SUMS.txt)
ls -la "$OUT" | awk 'NR>1{printf "   %-40s %6.1f MB\n", $NF, $5/1048576}'
echo "listo: $OUT"
