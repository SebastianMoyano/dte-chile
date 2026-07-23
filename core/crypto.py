"""
core/crypto.py

Módulo de Criptografía y Firma Digital para DTE Chile.

Maneja:
 - Carga de certificados PKCS#12 (.p12 / .pfx)
 - Firma digital XMLDSig (enveloped / detached)
 - Canonicalización C14N
 - Verificación de firmas
"""

import base64
import hashlib
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import Certificate
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from lxml import etree


# Namespaces XML estándar
XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
SII_NS = "http://www.sii.cl/SiiDte"


class CertificadoDigital:
    """
    Representa un certificado digital PKCS#12 con su clave privada y certificado público.
    Provee métodos para firmar datos y documentos XML.
    """

    def __init__(self, pfx_data: bytes, password: str):
        """
        Carga un certificado digital desde datos PKCS#12 en memoria.

        Args:
            pfx_data: Contenido del archivo .p12 / .pfx en bytes.
            password: Contraseña del certificado digital.

        Raises:
            ValueError: Si el certificado no puede cargarse con la contraseña dada.
        """
        try:
            pwd = password.encode("utf-8") if isinstance(password, str) else password
            private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                pfx_data, pwd
            )
        except Exception as e:
            raise ValueError(f"No se pudo cargar el certificado: {e}") from e

        if private_key is None or certificate is None:
            raise ValueError("El certificado o la clave privada no fueron encontrados en el archivo PFX.")

        self._private_key: RSAPrivateKey = private_key  # type: ignore
        self._certificate: Certificate = certificate

    @classmethod
    def desde_archivo(cls, path: str, password: str) -> "CertificadoDigital":
        """
        Carga un certificado desde un archivo .p12 / .pfx en disco.
        """
        data = Path(path).read_bytes()
        return cls(data, password)

    @property
    def clave_privada(self) -> RSAPrivateKey:
        return self._private_key

    @property
    def certificado(self) -> Certificate:
        return self._certificate

    @property
    def certificado_b64(self) -> str:
        """Retorna el certificado público codificado en Base64 (DER format)."""
        der = self._certificate.public_bytes(serialization.Encoding.DER)
        return base64.b64encode(der).decode("ascii")

    @property
    def rut_emisor(self) -> str:
        """
        Extrae el RUT del emisor del certificado.
        Busca primero en el CN (Common Name) y si no lo encuentra, en el
        Subject Alternative Name usando el OID chileno (1.3.6.1.4.1.8321.1).
        """
        import re
        
        # 1. Intentar con el Common Name (CN)
        subject = self._certificate.subject
        for attr in subject:
            from cryptography.x509.oid import NameOID
            if attr.oid == NameOID.COMMON_NAME:
                cn = attr.value
                match = re.search(r"(\d{7,8}-[\dkK])", cn)
                if match:
                    return match.group(1)
                parts = cn.split("-")
                if len(parts) >= 2:
                    rut_num = parts[-2]
                    dv = parts[-1]
                    # Validar formato mínimo de RUT chileno
                    if rut_num.isdigit() and len(dv) == 1:
                        return f"{rut_num}-{dv}"
                        
        # 2. Intentar con el Subject Alternative Name (SAN) usando el OID oficial chileno
        try:
            from cryptography.x509 import ExtensionOID
            san = self._certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
            for name in san.value:
                # name es generalmente una instancia de OtherName para OIDs personalizados
                if hasattr(name, "type_id") and name.type_id.dotted_string == "1.3.6.1.4.1.8321.1":
                    val = name.value
                    if isinstance(val, bytes):
                        s_val = val.decode("utf-8", errors="ignore")
                        match = re.search(r"(\d{7,8}-[\dkK])", s_val)
                        if match:
                            return match.group(1)
        except Exception:
            pass
            
        return "SIN-RUT"

    def firmar_datos(self, datos: bytes) -> bytes:
        """
        Firma datos crudos con la clave privada RSA usando SHA-1
        (requerido por el SII de Chile).

        Args:
            datos: Los datos a firmar.

        Returns:
            Firma digital en bytes (formato RSA PKCS#1 v1.5).
        """
        signature = self._private_key.sign(
            datos,
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        return signature

    def firmar_datos_sha256(self, datos: bytes) -> bytes:
        """
        Firma datos con SHA-256 (para usar con sistemas que soporten SHA-256).
        """
        signature = self._private_key.sign(
            datos,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return signature

    def hash_sha1_b64(self, datos: bytes) -> str:
        """Calcula SHA-1 de datos y retorna en Base64."""
        h = hashlib.sha1(datos).digest()
        return base64.b64encode(h).decode("ascii")

    def hash_sha256_b64(self, datos: bytes) -> str:
        """Calcula SHA-256 de datos y retorna en Base64."""
        h = hashlib.sha256(datos).digest()
        return base64.b64encode(h).decode("ascii")


def canonicalizar_xml(elemento: etree._Element) -> bytes:
    """
    Canonicaliza un elemento XML usando el método C14N estándar
    requerido por XMLDSig y el SII de Chile.

    Args:
        elemento: El elemento XML a canonicalizar.

    Returns:
        Representación canónica en bytes del elemento XML.
    """
    import io
    output = io.BytesIO()
    elemento.getroottree().write_c14n(output, exclusive=False, with_comments=False)
    return output.getvalue()


def canonicalizar_elemento(elemento: etree._Element) -> bytes:
    """
    Canonicaliza un solo elemento XML (no todo el árbol).
    Útil cuando necesitas canonicalizar un subelemento específico.
    """
    import io
    # Crear un árbol temporal solo con este elemento
    nuevo_arbol = etree.ElementTree(elemento)
    output = io.BytesIO()
    nuevo_arbol.write_c14n(output, exclusive=False, with_comments=False)
    return output.getvalue()


def firmar_documento_xml(
    elemento_raiz: etree._Element,
    certificado: CertificadoDigital,
    uri: str = "",
    id_referencia: str = "",
) -> etree._Element:
    """
    Agrega una firma XMLDSig a un documento XML (Enveloped Signature).

    Este es el formato requerido por el SII para firmar contenedores
    como EnvioDTE y EnvioBoleta.

    Args:
        elemento_raiz: Elemento raíz del documento a firmar.
        certificado: Certificado digital con la clave privada para firmar.
        uri: URI de referencia para la firma (generalmente "" para el documento completo).
        id_referencia: ID del elemento firmado (para firmas referenciadas por ID).

    Returns:
        El elemento raíz con el nodo <Signature> inyectado al final.
    """
    # El DigestValue se calcula sobre el elemento REFERENCIADO por la URI, no
    # sobre el raíz. Con URI="#ID" el SII resuelve el elemento con ese ID
    # (<Documento ID="DTE-33-1"> o <SetDTE ID="SetDoc">) y canonicaliza ese
    # subárbol; con URI="" es el documento completo (enveloped). REQUISITO: el
    # árbol debe estar ya con los namespaces finales (serializado+reparseado),
    # de lo contrario el C14N en memoria no calza con lo que el SII recalcula.
    elemento_ref = elemento_raiz
    if uri and uri.startswith("#"):
        ref_id = uri[1:]
        for el in elemento_raiz.iter():
            if el.get("ID") == ref_id:
                elemento_ref = el
                break

    datos_c14n = canonicalizar_elemento(elemento_ref)
    digest_valor = certificado.hash_sha1_b64(datos_c14n)

    # Construir el SignedInfo y firmarlo canonicalizado (standalone: es el formato
    # que el SII acepta para el getToken; sin xsi y con el árbol normalizado el
    # C14N standalone coincide con el que verá el SII, sin fuga de namespaces).
    signed_info_xml = f"""<SignedInfo xmlns="{XMLDSIG_NS}">
<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>
<Reference URI="{uri}">
<Transforms>
<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>
</Transforms>
<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>
<DigestValue>{digest_valor}</DigestValue>
</Reference>
</SignedInfo>"""
    signed_info_elem = etree.fromstring(signed_info_xml)
    signed_info_c14n = canonicalizar_elemento(signed_info_elem)
    firma_bytes = certificado.firmar_datos(signed_info_c14n)
    firma_b64 = base64.b64encode(firma_bytes).decode("ascii")

    signature_xml = f"""<Signature xmlns="{XMLDSIG_NS}">
{etree.tostring(signed_info_elem, encoding="unicode")}
<SignatureValue>{firma_b64}</SignatureValue>
<KeyInfo>
<KeyValue>
<RSAKeyValue>
<Modulus></Modulus>
<Exponent></Exponent>
</RSAKeyValue>
</KeyValue>
<X509Data>
<X509Certificate>{certificado.certificado_b64}</X509Certificate>
</X509Data>
</KeyInfo>
</Signature>"""
    signature_elem = etree.fromstring(signature_xml)

    # Rellenar Modulus / Exponent de la clave pública RSA.
    pub_numbers = certificado.certificado.public_key().public_numbers()
    modulus_bytes = pub_numbers.n.to_bytes((pub_numbers.n.bit_length() + 7) // 8, "big")
    exponent_bytes = pub_numbers.e.to_bytes((pub_numbers.e.bit_length() + 7) // 8, "big")
    mnode = signature_elem.find(f".//{{{XMLDSIG_NS}}}Modulus")
    enode = signature_elem.find(f".//{{{XMLDSIG_NS}}}Exponent")
    if mnode is not None:
        mnode.text = base64.b64encode(modulus_bytes).decode("ascii")
    if enode is not None:
        enode.text = base64.b64encode(exponent_bytes).decode("ascii")

    # Inyectar la firma como último hijo del elemento raíz.
    elemento_raiz.append(signature_elem)
    return elemento_raiz


def _c14n_en_contexto(elemento: etree._Element) -> bytes:
    """
    Canonicaliza `elemento` tal como aparece DENTRO del C14N del documento
    completo: hereda los namespaces de la raíz sin redeclararlos en su propio ápex.

    ⚠️ **NO ES EL MÉTODO DEL SII. No usar para firmar.** Este docstring afirmaba *"El SII
    digesta y firma así (comprobado contra el ejemplo oficial del SII)"* — **es falso**:
    probado contra el SII vivo con CAF real (2026-07-16) → ``DTE-3-505``. El oráculo que lo
    respaldaba (el ejemplo oficial de 2003) trae **firmas placeholder**, no byte-fieles, y
    despistó durante días. El método bueno es ``_c14n_reparse``, para ambos niveles
    (TrackID 253113966 → ``ACEPTADOS: 1``).

    Se conserva **solo como herramienta de diagnóstico** (comparar digests al depurar). Su
    único llamador es ``dry_run_certificacion.py``.
    """
    import re as _re

    tree = elemento.getroottree()
    full = etree.tostring(tree, method="c14n").decode("utf-8")
    local = etree.QName(elemento).localname
    ref_id = elemento.get("ID")
    if ref_id:
        m = _re.search(rf'<{local}\b[^>]*\bID="{_re.escape(ref_id)}"', full)
        start = m.start()
    else:
        # Sin ID (p.ej. SignedInfo, que aparece más de una vez): ubicar por la
        # posición del elemento entre todos los del mismo localname en el árbol.
        mismos = [e for e in tree.getroot().iter() if etree.QName(e).localname == local]
        idx = mismos.index(elemento)
        pos = 0
        for _ in range(idx + 1):
            m = _re.search(rf'<{local}\b', full[pos:])
            start = pos + m.start()
            pos = start + 1
    end = full.index(f'</{local}>', start) + len(f'</{local}>')
    return full[start:end].encode("utf-8")


def _c14n_reparse(elemento: etree._Element) -> bytes:
    """
    Canonicaliza `elemento` como nodo INDEPENDIENTE, renderizando en su ápice los
    namespaces heredados de los ancestros (``xmlns="http://www.sii.cl/SiiDte"`` y
    ``xmlns:xsi``), igual que ``DOMNode::C14N()`` de PHP/libxml (el método que usa
    LibreDTE y con el que el SII revalida la firma del SOBRE).

    Se reparsea el subárbol (serializar→fromstring) ANTES del C14N: hacerlo directo
    con ``etree.tostring(el, method='c14n')`` sobre un subárbol aún enganchado a su
    documento introduce un ``xmlns=""`` espurio en los descendientes (artefacto de
    lxml) y produce un digest distinto. Reparsear lo evita.

    Verificado empíricamente: reproduce el DigestValue del SetDTE del ejemplo oficial
    del SII F60T33 (``4OTW...``) y del EnvioDTE real de OpenFactura (``wzl9...``), y la
    SignatureValue real del sobre de OpenFactura verifica con el SignedInfo así
    canonicalizado.

    **Se usa para AMBOS niveles** (sobre y DTE interno) — ver la nota extensa en
    ``firmar_xml_sii``. Verificado contra el SII vivo: TrackID 253113966 → ``ACEPTADOS: 1``.

    ⚠️ Este docstring decía antes *"NO usar para el DTE interno: ese va con
    ``_c14n_en_contexto`` (substring), que reproduce el digest del Documento del ejemplo
    oficial (hlmQtu)"*. **Era falso y contradecía al propio ``firmar_xml_sii``.** El dato del
    ``hlmQtu`` puede ser cierto, pero ese oráculo no servía: el ejemplo oficial de 2003 trae
    **firmas placeholder**, no byte-fieles. Substring probado contra el SII vivo con CAF real
    (2026-07-16) → ``DTE-3-505``.
    """
    reparsed = etree.fromstring(etree.tostring(elemento))
    return etree.tostring(reparsed, method="c14n")


def firmar_xml_sii(
    elemento_raiz: etree._Element,
    certificado: "CertificadoDigital",
    uri: str = "",
) -> etree._Element:
    """
    Firma enveloped XMLDSig para DTE/EnvioDTE del SII (RSA-SHA1 + C14N 1.0).

    Diferencia clave con firmar_documento_xml: el SignedInfo se canonicaliza y
    firma EN SU FORMA FINAL (ya inyectado en el árbol), lo que hace que la firma
    sobreviva a la serialización posterior. REQUISITO: `elemento_raiz` debe estar
    ya normalizado (serializado+reparseado) para que los namespaces sean los
    finales; de lo contrario el C14N no coincidirá con el XML enviado.

    Esta función NO se usa para la semilla del token (que sí funciona con
    firmar_documento_xml y su firmado standalone).
    """
    # 1. Elemento referenciado por la URI (para el DigestValue).
    elemento_ref = elemento_raiz
    if uri and uri.startswith("#"):
        ref_id = uri[1:]
        for el in elemento_raiz.iter():
            if el.get("ID") == ref_id:
                elemento_ref = el
                break

    # El SII (backend Java/Apache Santuario) usa C14N XMLDSig ESTÁNDAR (inclusiva).
    # Al dereferenciar una Reference `URI="#ID"` canonicaliza el subárbol como
    # node-set renderizando en el ápex del nodo los namespaces EN ALCANCE heredados de
    # los ancestros (xmlns SiiDte, xmlns:xsi). Eso es exactamente `_c14n_reparse`
    # (reparsear el subárbol y C14N). Se usa para AMBOS niveles y para AMBOS cómputos
    # (DigestValue del nodo referenciado y SignedInfo):
    #   - SOBRE  (#SetDoc  -> SetDTE):    verificado, SII vivo pasó de RFR a EPR.
    #   - DTE    (#DTE-..  -> Documento): mismo método; dos References del mismo
    #     documento NO pueden usar C14N distinta bajo XMLDSig estándar.
    #   - SignedInfo: siempre cuelga de <Signature xmlns=".../xmldsig#">; reparse rinde
    #     `<SignedInfo xmlns="...xmldsig#" xmlns:xsi="...">`.
    # NO usar substring (`_c14n_en_contexto`): NO redeclara los namespaces heredados en
    # el ápex -> el SII recomputa otro digest -> RFR (sobre) o DTE-3-505 "Firma DTE
    # Incorrecta" (DTE). Los oráculos que sugerían substring (ejemplo oficial 2003 con
    # firmas placeholder, y el XML de OpenFactura RE-SERIALIZADO por su API) no eran
    # byte-fieles y despistaron; el digest 4OTW/wzl9 del SetDTE sí lo reproduce reparse.
    digest_valor = certificado.hash_sha1_b64(_c14n_reparse(elemento_ref))

    # 2. Construir la <Signature> con SignatureValue vacío (se llena en el paso 4).
    signature_xml = (
        f'<Signature xmlns="{XMLDSIG_NS}">'
        '<SignedInfo>'
        '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        '<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>'
        f'<Reference URI="{uri}">'
        '<Transforms>'
        # Transform = C14N (como el EJEMPLO OFICIAL del SII F60T33, la referencia
        # autoritativa). Sus DigestValue reales coinciden con _c14n_en_contexto
        # (digest del elemento referenciado tal como aparece dentro del C14N del
        # documento completo, sin xmlns en el ápex).
        '<Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        '</Transforms>'
        '<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>'
        f'<DigestValue>{digest_valor}</DigestValue>'
        '</Reference>'
        '</SignedInfo>'
        '<SignatureValue></SignatureValue>'
        '<KeyInfo><KeyValue><RSAKeyValue><Modulus></Modulus><Exponent></Exponent>'
        '</RSAKeyValue></KeyValue>'
        f'<X509Data><X509Certificate>{certificado.certificado_b64}</X509Certificate>'
        '</X509Data></KeyInfo>'
        '</Signature>'
    )
    signature_elem = etree.fromstring(signature_xml)

    pub_numbers = certificado.certificado.public_key().public_numbers()
    modulus_bytes = pub_numbers.n.to_bytes((pub_numbers.n.bit_length() + 7) // 8, "big")
    exponent_bytes = pub_numbers.e.to_bytes((pub_numbers.e.bit_length() + 7) // 8, "big")
    signature_elem.find(f".//{{{XMLDSIG_NS}}}Modulus").text = base64.b64encode(modulus_bytes).decode("ascii")
    signature_elem.find(f".//{{{XMLDSIG_NS}}}Exponent").text = base64.b64encode(exponent_bytes).decode("ascii")

    # 3. Inyectar la firma en su posición final.
    elemento_raiz.append(signature_elem)

    # 4. Firmar el SignedInfo canonicalizado EN SU POSICIÓN FINAL y setear el
    #    SignatureValue (setear texto no reorganiza namespaces -> la firma
    #    sobrevive a la serialización). El SignedInfo se canonicaliza con `_c14n`
    #    (reparse para el sobre, en-contexto para el DTE interno; ver nota arriba).
    # SignedInfo SIEMPRE con reparse (renderiza xmlns xmldsig# + xsi en el ápex), en
    # ambos niveles — ver nota arriba. (Para el sobre coincide con _c14n_digest.)
    signed_info = signature_elem.find(f"{{{XMLDSIG_NS}}}SignedInfo")
    firma = certificado.firmar_datos(_c14n_reparse(signed_info))
    signature_elem.find(f"{{{XMLDSIG_NS}}}SignatureValue").text = base64.b64encode(firma).decode("ascii")

    # Envolver a 64 chars/línea SOLO el base64 largo de KeyInfo (X509Certificate,
    # Modulus, Exponent), como hace el ejemplo oficial del SII, para no exceder el
    # límite de línea ("CHR-00002: Line too long"). NO se envuelve la
    # SignatureValue (el ejemplo oficial la deja en una línea); envolverla con \n
    # metía saltos dentro del SetDTE que digesta el sobre y descuadraba la firma.
    for tag in ("X509Certificate", "Modulus", "Exponent"):
        el = signature_elem.find(f".//{{{XMLDSIG_NS}}}{tag}")
        if el is not None and el.text and len(el.text.strip()) > 64:
            b = el.text.strip()
            el.text = "\n" + "\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + "\n"

    return elemento_raiz
