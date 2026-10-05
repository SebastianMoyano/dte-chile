#!/usr/bin/env python3
"""
Corpus dorado PRIVADO: los XML reales que el motor ya produjo (y el SII aceptó) como casos.

Todo lo que toca vive en `storage/` (fuera de git, ley L14): los XML de `storage/dtes/`, el CAF
real desde la base, el certificado real (`firma_<rut>.pfx`) con su clave desde el Llavero
(`sii-clave-certificado`). Nada se imprime ni se copia al repo.

Para cada `EnvioDTE_*.xml` / `EnvioBOLETA_*.xml` con su `DTE_*`/`BOLETA_*`:
  1. reconstruye la entrada (emisor, receptor, ítems, referencias, fecha, folio, resolución, hora)
     a partir del propio XML;
  2. corre el pipeline puro de Python con esa entrada → debe dar los MISMOS bytes que el archivo;
  3. corre el port en Go (nucleo-dorado) con la misma entrada → mismos bytes.

    .venv/bin/python tests/dorado/privado.py            # todos los sobres de storage/dtes
    .venv/bin/python tests/dorado/privado.py 34_111     # solo ese
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from core import database, reloj  # noqa: E402
import test_dorado as td  # noqa: E402

NS = "{http://www.sii.cl/SiiDte}"
DTES = RAIZ / "storage" / "dtes"
PRIV = RAIZ / "storage" / "dorado_privado"
GO = RAIZ / "nucleo" / "bin" / "nucleo-dorado"


def clave_llavero() -> str:
    r = subprocess.run(["security", "find-generic-password", "-s", "sii-clave-certificado", "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("No encuentro la clave del certificado en el Llavero (servicio sii-clave-certificado)")
    return r.stdout.strip()


def t(el, tag):
    x = el.find(NS + tag)
    return x.text if x is not None else None


def reconstruir(envio_path: Path, doc_path: Path) -> dict:
    """La entrada que produjo este sobre, leída del propio XML."""
    envio = etree.fromstring(envio_path.read_bytes())
    car = envio.find(f".//{NS}Caratula")
    doc = etree.fromstring(doc_path.read_bytes()).find(NS + "Documento")
    enc = doc.find(NS + "Encabezado")
    idd, em, rc = enc.find(NS + "IdDoc"), enc.find(NS + "Emisor"), enc.find(NS + "Receptor")
    es_boleta = t(idd, "TipoDTE") in ("39", "41")
    emisor = {"rut": t(em, "RUTEmisor"), "razon_social": t(em, "RznSoc") or t(em, "RznSocEmisor"),
              "giro": t(em, "GiroEmis") or t(em, "GiroEmisor"), "codigo_actividad": int(t(em, "Acteco") or 0),
              "direccion": t(em, "DirOrigen") or "", "comuna": t(em, "CmnaOrigen") or "", "ciudad": t(em, "CiudadOrigen") or "",
              "telefono": t(em, "Telefono"), "email": t(em, "CorreoEmisor")}
    receptor = {"rut": t(rc, "RUTRecep"), "razon_social": t(rc, "RznSocRecep") or "CONSUMIDOR FINAL",
                "giro": t(rc, "GiroRecep"), "direccion": t(rc, "DirRecep"), "comuna": t(rc, "CmnaRecep"),
                "ciudad": t(rc, "CiudadRecep"), "email": t(rc, "CorreoRecep")}
    items = []
    for det in doc.findall(NS + "Detalle"):
        it = {"numero_linea": int(t(det, "NroLinDet")), "nombre": t(det, "NmbItem"),
              "cantidad": float(t(det, "QtyItem")) if t(det, "QtyItem") else (1 if not es_boleta else 0),
              "precio_unitario": float(t(det, "PrcItem")) if t(det, "PrcItem") else 0,
              "exento": t(det, "IndExe") == "1"}
        if t(det, "DscItem"):
            it["descripcion"] = t(det, "DscItem")
        if t(det, "UnmdItem"):
            it["unidad_medida"] = t(det, "UnmdItem")
        if t(det, "DescuentoPct"):
            it["descuento_pct"] = float(t(det, "DescuentoPct"))
        if t(det, "DescuentoMonto"):
            it["descuento_monto"] = float(t(det, "DescuentoMonto"))
        cod = det.find(NS + "CdgItem")
        if cod is not None:
            it["codigo_producto"] = t(cod, "VlrCodigo")
        items.append(it)
    refs = []
    for r in doc.findall(NS + "Referencia"):
        if t(r, "TpoDocRef") and t(r, "FchRef"):
            refs.append({"numero_linea": int(t(r, "NroLinRef")), "tipo_doc_ref": int(t(r, "TpoDocRef")),
                         "folio_ref": int(t(r, "FolioRef")), "fecha_doc_ref": t(r, "FchRef"),
                         "codigo_ref": int(t(r, "CodRef")), "razon_ref": t(r, "RazonRef")})
    caso = {"tipo_dte": int(t(idd, "TipoDTE")), "folio": int(t(idd, "Folio")), "fecha_emision": t(idd, "FchEmis"),
            "emisor": emisor, "receptor": receptor, "items": items,
            "_hora": t(doc, "TmstFirma"), "_resolucion": [t(car, "FchResol"), int(t(car, "NroResol"))],
            "_rut_envia": t(car, "RutEnvia")}
    if refs:
        caso["referencias"] = refs
    if t(idd, "FmaPago"):
        caso["forma_pago"] = int(t(idd, "FmaPago"))
    if t(idd, "FchVenc"):
        caso["fecha_vencimiento"] = t(idd, "FchVenc")
    if t(idd, "IndServicio"):
        caso["ind_servicio"] = int(t(idd, "IndServicio"))
    return caso


def caf_real(doc_path: Path, rut: str, tipo: int, folio: int) -> str:
    """El CAF con que se timbró ESTE documento: se identifica por el módulo <M> de la clave
    pública que el TED lleva incrustado, y se busca en la base y en storage/cafs/ (hay CAF que
    se usaron sin cargarlos en la base, p. ej. los de producción de boletas)."""
    import re
    m = re.search(rb"<RSAPK><M>([^<]+)</M>", doc_path.read_bytes())
    modulo = m.group(1).decode() if m else None
    conn = sqlite3.connect(str(database.DATABASE_PATH))
    filas = conn.execute("SELECT caf_xml FROM cafs WHERE rut_emisor=? AND tipo_dte=? ORDER BY id DESC", (rut, tipo)).fetchall()
    conn.close()
    candidatos = [f[0] for f in filas]
    for ruta in sorted((RAIZ / "storage" / "cafs").glob("*.xml")):
        try:
            candidatos.append(ruta.read_text(encoding="iso-8859-1"))
        except OSError:
            pass
    if modulo:
        for c in candidatos:
            if modulo in c:
                return c
    for c in candidatos[:len(filas)]:  # sin módulo: el de la base que cubra el folio
        import re as _re
        rng = _re.search(r"<D>(\d+)</D>\s*<H>(\d+)</H>", c)
        if rng and int(rng.group(1)) <= folio <= int(rng.group(2)):
            return c
    raise LookupError(f"no encuentro el CAF de {rut} tipo {tipo} folio {folio} (módulo {str(modulo)[:12]}…)")


def correr(nombre: str, envio_path: Path, doc_path: Path, clave: str) -> bool:
    caso = reconstruir(envio_path, doc_path)
    rut, tipo, folio = caso["emisor"]["rut"], caso["tipo_dte"], caso["folio"]
    pfx = RAIZ / f"firma_{caso['_rut_envia']}.pfx"
    if not pfx.exists():
        print(f"  – {nombre}: no está {pfx.name}, se omite"); return True
    if doc_path.read_bytes().startswith(b"<?xml"):
        print(f"  – {nombre}: formato antiguo (anterior a core/sobre.py), se omite"); return True
    try:
        caf = caf_real(doc_path, rut, tipo, folio)
    except LookupError as e:
        print(f"  – {nombre}: {e}, se omite"); return True
    carpeta = PRIV / nombre
    fix = carpeta / "fixtures"
    fix.mkdir(parents=True, exist_ok=True)
    shutil.copy(pfx, fix / "cert_demo.p12")
    (fix / f"caf_{tipo}.xml").write_text(caf, encoding="iso-8859-1")
    entrada = {k: v for k, v in caso.items() if not k.startswith("_")}
    (carpeta / "entrada.json").write_text(json.dumps(entrada, ensure_ascii=False, indent=1), encoding="utf-8")
    esperado = {"dte.xml": doc_path.read_bytes(), "envio.xml": envio_path.read_bytes()}

    # 2. Python puro
    td.FIX, td.RESOLUCION, td.CERT_CLAVE = fix, tuple(caso["_resolucion"]), clave
    reloj.fijar(caso["_hora"])
    salida = td.correr_caso(entrada)
    ok_py = all(salida[k] == v for k, v in esperado.items())
    print(f"  {'✓' if ok_py else '✗'} {nombre}: Python puro {'==' if ok_py else '!='} archivo real")
    for k in esperado:
        if salida[k] != esperado[k]:
            print("      " + k + ": " + td.primer_byte_distinto(esperado[k], salida[k]).replace("\n", "\n      "))
    # 3. Go
    ok_go = False
    if GO.exists():
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, RELOJ_FIJO=caso["_hora"], DORADO_RESOLUCION_FECHA=caso["_resolucion"][0],
                       DORADO_RESOLUCION_NUMERO=str(caso["_resolucion"][1]), DORADO_CERT_CLAVE=clave)
            r = subprocess.run([str(GO), str(carpeta / "entrada.json"), str(fix), tmp], env=env, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  ✗ {nombre}: Go falló: {r.stderr.strip()[-300:]}")
            else:
                go = {k: (Path(tmp) / k).read_bytes() for k in esperado if (Path(tmp) / k).exists()}
                ok_go = all(go.get(k) == v for k, v in esperado.items())
                print(f"  {'✓' if ok_go else '✗'} {nombre}: Go {'==' if ok_go else '!='} archivo real")
                for k in esperado:
                    if go.get(k) != esperado[k] and k in go:
                        print("      " + k + ": " + td.primer_byte_distinto(esperado[k], go[k]).replace("\n", "\n      "))
    return ok_py and ok_go


def main() -> int:
    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    clave = clave_llavero()
    pares = []
    for env in sorted(DTES.glob("Envio*_*.xml")):
        base = env.name.replace("EnvioDTE_", "DTE_").replace("EnvioBOLETA_", "BOLETA_")
        doc = DTES / base
        if doc.exists() and filtro in env.name:
            pares.append((env.stem.split("_", 1)[1], env, doc))
    if not pares:
        print("No hay sobres en storage/dtes"); return 1
    print(f"Corpus privado: {len(pares)} sobre(s) en {DTES} (resultados en {PRIV})")
    buenos = sum(correr(n, e, d, clave) for n, e, d in pares)
    print(f"\n{buenos}/{len(pares)} reproducidos byte a byte por Python y por Go (los omitidos cuentan como OK)")
    return 0 if buenos == len(pares) else 1


if __name__ == "__main__":
    sys.exit(main())
