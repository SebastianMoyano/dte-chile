"""tools/generar_pdf417.py — Regenera nucleo/pdf417/tablas.go y testdata/vectores.json desde pdf417gen (Python).
Las tablas son las del estándar PDF417 (patrones de 17 módulos, factores Reed-Solomon, submodos de texto);
los vectores son los códigos de barra exactos que produce Python para un juego de entradas, y el test de Go
exige igualdad fila por fila. Uso: .venv/bin/python tools/generar_pdf417.py"""
import json, pathlib, random, sys
import pdf417gen, pdf417gen.data as d, pdf417gen.codes as c
RAIZ = pathlib.Path(__file__).resolve().parent.parent
modos = ['UPPER', 'LOWER', 'MIXED', 'PUNCT']
out = ['// Code generated from pdf417gen (Python) by tools/generar_pdf417.py; DO NOT EDIT.', '', 'package pdf417', '',
       '// caracteresLookup[ascii][submodo] = valor interino (-1 = no existe en ese submodo).', 'var caracteresLookup = map[byte][4]int{']
for ch in sorted(d.CHARACTERS_LOOKUP):
    out.append(f'\t{ch}: {{{", ".join(str(d.CHARACTERS_LOOKUP[ch].get(m, -1)) for m in modos)}}},')
out += ['}', '', '// switchCodes[desde][hasta] = códigos interinos para cambiar de submodo.', 'var switchCodes = [4][4][]int{']
for a in modos:
    out.append('\t{' + ', '.join('{' + ', '.join(map(str, d.SWITCH_CODES.get(a, {}).get(b, []))) + '}' for b in modos) + '},')
out += ['}', '', 'var factoresEC = [9][]int{'] + ['\t{' + ', '.join(map(str, f)) + '},' for f in d.ERROR_CORRECTION_FACTORS] + ['}', '']
out += ['// codigos[tabla][palabra] = patrón de barras de 17 módulos (bits).', 'var codigos = [3][929]int{'] + ['\t{' + ', '.join(str(x) for x in t) + '},' for t in c.CODES] + ['}']
(RAIZ / 'nucleo/pdf417/tablas.go').write_text('\n'.join(out) + '\n', encoding='utf-8')
entradas = [a for a in sys.argv[1:]] or []
entradas += ["hola", "HOLA MUNDO 12345", "a", "A", "1234567890123456789", "mezcla: ñandú & <xml/> 2026-10-11 $ 1.234.567",
             "MAYUS minus 12 punt.!?", "\t\n\r x", "0" * 50, "The quick brown fox jumps over the lazy dog 0123456789", "x" * 300,
             '<TED version="1.0"><DD><RE>77777777-7</RE><TD>39</TD><F>1</F><FE>2026-10-11</FE><RR>66666666-6</RR><RSR>CONSUMIDOR FINAL</RSR><MNT>1190</MNT><IT1>Café</IT1><CAF version="1.0"><DA><RE>77777777-7</RE><RS>EMPRESA DEMO SPA</RS><TD>39</TD><RNG><D>1</D><H>100</H></RNG><FA>2026-10-05</FA><RSAPK><M>m/iZsYgDIgOLQ/p+ljIq6lVEoAZLVMPPZCJreJgWgcuZBDUBYyV9l5kw5+d+8bKWRtedj3L9oYhfC9T0WbAGLpC1pEnMYMxaiMmSjSCvkCflPWAxLYxHkWjlW2WTlKhptjb17duJV9TBGTTbOUFc6OXAwpxER8q+cBAexiB/AjU=</M><E>AQAB</E></RSAPK><IDK>100</IDK></DA><FRMA algoritmo="SHA1withRSA">U0lNVUxBQ0lPTi1OTy1FUy1VTkEtRklSTUEtREVMLVNJSQ==</FRMA></CAF><TSTED>2026-10-11T12:00:00</TSTED></DD><FRMT algoritmo="SHA1withRSA">AAAA</FRMT></TED>']
random.seed(7)
alfabeto = [chr(i) for i in range(9, 127)] + ['ñ', 'á', 'É', '€']
for n in (5, 40, 200, 700):
    entradas.append(''.join(random.choice(alfabeto) for _ in range(n)))
vec = []
for s in entradas:
    data = s.encode('utf-8')
    for cols, sec in ((12, 5), (6, 2), (3, 8)):
        try:
            vec.append({"datos": s, "columnas": cols, "seguridad": sec, "filas": pdf417gen.encode(data, columns=cols, security_level=sec)})
        except ValueError as e:
            vec.append({"datos": s, "columnas": cols, "seguridad": sec, "error": str(e)[:40]})
json.dump(vec, open(RAIZ / 'nucleo/pdf417/testdata/vectores.json', 'w'), ensure_ascii=False)
print('tablas.go y', len(vec), 'vectores')
