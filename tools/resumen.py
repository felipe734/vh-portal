#!/usr/bin/env python3
"""Imprime en formato GITHUB_OUTPUT (clave=valor) el resumen del reporte del portal, sin claves ni montos."""
import json, sys

try:
    rep = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    print('encontro=sin reporte del script')
    print('faltantes=0')
    sys.exit(0)
mes = sys.argv[2]
c = rep.get('cifras', {})
av = [a for a in rep.get('avisos', []) if f' {mes}:' in a]
falt = rep.get('faltantes', [])
txt = (f"{c.get('cuentas', 0)} cuentas, {c.get('unidades', 0)} unidades, {c.get('liquidaciones', 0)} liquidaciones "
       f"desde {rep.get('desde', '')}; {len(av)} avisos de {mes}; {len(falt)} faltantes; "
       f"{len(rep.get('bloqueos', []))} bloqueos")
print('encontro=' + txt.replace('\n', ' '))
print(f'faltantes={len(falt)}')
