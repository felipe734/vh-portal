#!/usr/bin/env python3
"""Puente Airtable <-> portal de propietarios para GitHub Actions.

Subcomandos:
  cambios    sale con 0 si hubo cambios en liquidaciones en los últimos 65 min (3 si no).
  ultimo-cerrado  imprime el último mes con Corrida Cierre B.
  candado    imprime M (AAAA-MM) si el portal de M debe publicarse; sale con 3 si no toca.
  descargar  --work DIR --mes M   baja F_CORTAS, RESERVAS, ADICIONALES y PROPIETARIOS a DIR/raw
             con el mismo formato que usa build_portal.py (links como {id, name}).
  registrar  --mes M --resultado R --encontro TXT --hizo TXT [--pendiente TXT]
             deja la Corrida Portal (y un Pendiente para Felipe si se pasa) en TRAZABILIDAD.

Requiere la variable AIRTABLE_TOKEN (scopes: data.records:read, data.records:write,
schema.bases:read; bases OPERACIÓN 360, INVENTARIO y 9. PENDIENTES).
Solo escribe en TRAZABILIDAD. Nunca escribe contraseñas ni toca otras tablas.
"""
import argparse, datetime, json, os, sys, time, urllib.parse, urllib.request

API = 'https://api.airtable.com/v0'
TZ = datetime.timezone(datetime.timedelta(hours=-5))  # America/Bogota

OP360 = 'appOJopQhmyaON16G'
F_CORTAS, RESERVAS, ADICIONALES = 'tblnF3LRqBiNBQO8A', 'tblVrwSgN0doLGXuq', 'tblhJcjJMw9oaYCBt'
INVENTARIO, PROPIETARIOS = 'appadw52yBDWwHzMU', 'tbl9XtpIj9oYwMIGt'
PEND, TRAZ = 'appylcO9bGU5EBgV2', 'tblXVY1dEl79x3uVW'

FC = ['fldNrIFdC1GOVKe98', 'fld2WlOrsZxMq8jLS', 'fldZN04Va7ZE84YrZ', 'fldXNJurLpC3VsW38', 'fld2QmfCG0F3IofmP',
      'fld3CHBqQOMEgUJqg', 'fldLhWeYeCgL2KkEn', 'fldVrmROYg57Oy8cN', 'fld0jaZOzguFfy6ok']
RS = ['fldx9Lhb6x8ub9OF2', 'fldljxOpEpmoJdulL', 'fldTSJWyU4vVXne5p', 'fldy5DWjTTP6ymbKI', 'fldxz2ERUEAdAb3Na',
      'fldvrD9FyUWlZfoqV', 'fldbw1Oxy4hgt9NxB', 'flduUM7AHFwPKVN4a']
RS_MES = 'flduUM7AHFwPKVN4a'
AD = ['fld5Pd5nYEBmz3SMR', 'fldMJNwdtkLVsW0wI', 'fldKjCC3egUOx55CJ', 'fldCKJitAaHgQudNT', 'fldsRagecvJCXF4Lg',
      'fldr5OqYeRBMxp7gq']
AD_MES = 'fld5Pd5nYEBmz3SMR'
PR = ['fldIo79HDQDR9NZ3t', 'fldk43IQ8ZvVPYCEm', 'fldymnj9nW8YgVC0V', 'fldcFCRxUIamIfQ22', 'fldgqY5qwMuIo0Ksg']

# TRAZABILIDAD
T = dict(asunto='fldppIUsuUrLmlc48', tipo='fldDb4Fb3tp2VXC25', proceso='fldGUOALzCds6je18',
         origen='fldfqQQNCFLsmhYQF', estado='flddfw5b19aj83Csy', resultado='fldxNzjSgklYOdjmx',
         responsable='fldrTXOgKjNWE6pSC', linea='fld2HH8kQsK5ycMUD', fecha='fldz9tEsSyJ9RERDL',
         limite='fld6Ym8eFYJTm2Kjg', cierre='fldI1dhL5bxlC2fa0', mes='fldUTrITzq0FWy0H8',
         accion='fldDJ68jyyUKQpad4', detalle='fld0lNCNf0Hchucvc', corrida='fldIRVUlEO0IXIAy9',
         link='fldOWwqbS3ZQhIDPX', ref='fldJDVZ6VMDuRzJ1k')
DESDE = '2026-05'
EXCLUIR = [["Apto 207 - Open C60", "2026-06"]]
PORTAL = 'https://portal.versehost.co'


def req(method, path, body=None, params=None):
    url = API + path
    if params:
        url += '?' + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    for intento in range(5):
        r = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + os.environ['AIRTABLE_TOKEN'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < 4:
                time.sleep(30)
                continue
            sys.stderr.write(f'Airtable {e.code} en {path}: {e.read().decode()[:300]}\n')
            raise


def listar(base, tabla, campos, formula=None):
    out, offset = [], None
    while True:
        p = {'pageSize': 100, 'returnFieldsByFieldId': 'true', 'fields[]': campos}
        if formula:
            p['filterByFormula'] = formula
        if offset:
            p['offset'] = offset
        d = req('GET', f'/{base}/{tabla}', params=p)
        out += d.get('records', [])
        offset = d.get('offset')
        if not offset:
            return out
        time.sleep(0.25)


def esquema(base):
    return req('GET', f'/meta/bases/{base}/tables')['tables']


def nombres_de(base, tabla_id, tablas):
    t = next(x for x in tablas if x['id'] == tabla_id)
    prim = t['primaryFieldId']
    return {r['id']: str(r.get('fields', {}).get(prim, '')).strip() for r in listar(base, tabla_id, [prim])}


def links_a_nombres(recs, campo, mapa):
    for r in recs:
        f = r.get('fields', {})
        v = f.get(campo)
        if isinstance(v, list):
            f[campo] = [{'id': x, 'name': mapa.get(x, x)} if isinstance(x, str) else x for x in v]


def nombre_campo(tablas, tabla_id, campo_id):
    t = next(x for x in tablas if x['id'] == tabla_id)
    return next(f['name'] for f in t['fields'] if f['id'] == campo_id)


def linked_table(tablas, tabla_id, campo_id):
    t = next(x for x in tablas if x['id'] == tabla_id)
    f = next(f for f in t['fields'] if f['id'] == campo_id)
    return f['options']['linkedTableId']


def mes_anterior():
    hoy = datetime.datetime.now(TZ).date().replace(day=1)
    return (hoy - datetime.timedelta(days=1)).strftime('%Y-%m')


def val(r, fid):
    v = r.get('fields', {}).get(fid)
    if isinstance(v, dict):
        return v.get('name')
    return v


def cmd_candado(a):
    m = a.mes or mes_anterior()
    filas = listar(PEND, TRAZ, [T['tipo'], T['proceso'], T['mes'], T['estado'], T['resultado'], T['accion']],
                   formula=None)
    filas = [r for r in filas if val(r, T['mes']) == m]

    def hay(tipo, proceso, ok=None, accion=None, estado=None):
        for r in filas:
            if val(r, T['tipo']) != tipo or val(r, T['proceso']) != proceso:
                continue
            if val(r, T['estado']) == 'Descartado':
                continue
            if ok and val(r, T['resultado']) not in ok:
                continue
            if accion and not str(val(r, T['accion']) or '').startswith(accion):
                continue
            if estado and val(r, T['estado']) != estado:
                continue
            return True
        return False

    validos = ('OK', 'Con pendientes')
    if not hay('Pendiente', 'Cierre A', accion='Check cierre A', estado='Hecho'):
        print(f'Portal de {m}: esperando el check de Felipe al Cierre A', file=sys.stderr)
        sys.exit(3)
    if not hay('Corrida', 'Cierre B', ok=validos):
        print(f'Portal de {m}: esperando el Cierre B', file=sys.stderr)
        sys.exit(3)
    if hay('Corrida', 'Portal', ok=validos) and not a.forzar:
        print(f'Portal de {m}: ya publicado', file=sys.stderr)
        sys.exit(3)
    print(m)


def cmd_ultimo_cerrado(a):
    """Último mes con Corrida Cierre B válida (OK o Con pendientes) en TRAZABILIDAD."""
    filas = listar(PEND, TRAZ, [T['tipo'], T['proceso'], T['mes'], T['estado'], T['resultado']], formula=None)
    ms = sorted({val(r, T['mes']) for r in filas
                 if val(r, T['tipo']) == 'Corrida' and val(r, T['proceso']) == 'Cierre B'
                 and val(r, T['estado']) != 'Descartado' and val(r, T['resultado']) in ('OK', 'Con pendientes')
                 and val(r, T['mes'])})
    if not ms:
        print('Sin mes con Cierre B', file=sys.stderr)
        sys.exit(3)
    print(ms[-1])


def cmd_cambios(a):
    """Sale con 0 si alguna liquidación, reserva, adicional o propietario cambió en los últimos N minutos; 3 si no."""
    f = f"IS_AFTER(LAST_MODIFIED_TIME(), DATEADD(NOW(), -{a.minutos}, 'minutes'))"
    for base, tabla, campo in ((OP360, F_CORTAS, FC[0]), (OP360, RESERVAS, RS[0]),
                               (OP360, ADICIONALES, AD[0]), (INVENTARIO, PROPIETARIOS, PR[0])):
        d = req('GET', f'/{base}/{tabla}', params={'pageSize': 1, 'returnFieldsByFieldId': 'true',
                                                   'fields[]': [campo], 'filterByFormula': f})
        if d.get('records'):
            print(f'Cambio detectado en {tabla}', file=sys.stderr)
            return
    print('Sin cambios en liquidaciones', file=sys.stderr)
    sys.exit(3)


def meses(desde, hasta):
    y, mm = map(int, desde.split('-'))
    out = []
    while f'{y:04d}-{mm:02d}' <= hasta:
        out.append(f'{y:04d}-{mm:02d}')
        mm += 1
        if mm == 13:
            y, mm = y + 1, 1
    return out


def cmd_descargar(a):
    raw = os.path.join(a.work, 'raw')
    os.makedirs(raw, exist_ok=True)
    t360, tinv = esquema(OP360), esquema(INVENTARIO)
    und360 = nombres_de(OP360, linked_table(t360, F_CORTAS, FC[0]), t360)
    undinv = nombres_de(INVENTARIO, linked_table(tinv, PROPIETARIOS, 'fldcFCRxUIamIfQ22'), tinv)

    def guardar(nombre, recs):
        with open(os.path.join(raw, nombre), 'w', encoding='utf-8') as f:
            json.dump({'records': recs}, f, ensure_ascii=False)

    fc = listar(OP360, F_CORTAS, FC)
    links_a_nombres(fc, FC[0], und360)
    guardar('fcortas_1.json', fc)
    n_rs, n_ad = nombre_campo(t360, RESERVAS, RS_MES), nombre_campo(t360, ADICIONALES, AD_MES)
    for m in meses(DESDE, a.mes):
        rs = listar(OP360, RESERVAS, RS, formula=f"{{{n_rs}}}='{m}'")
        links_a_nombres(rs, RS[0], und360)
        guardar(f'reservas_{m}.json', rs)
        ad = listar(OP360, ADICIONALES, AD, formula=f"{{{n_ad}}}='{m}'")
        links_a_nombres(ad, AD[1], und360)
        guardar(f'adicionales_{m}.json', ad)
    pr = listar(INVENTARIO, PROPIETARIOS, PR)
    links_a_nombres(pr, 'fldcFCRxUIamIfQ22', undinv)
    guardar('propietarios.json', pr)
    hoy = datetime.datetime.now(TZ).date().isoformat()
    with open(os.path.join(a.work, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'desde': DESDE, 'hasta': a.mes, 'actualizado': hoy, 'excluir': EXCLUIR,
                   'alias': {}, 'ne_override': {}, 'unidades': {}, 'ciudad_default': 'Bogotá'}, f, ensure_ascii=False)
    print(f'{len(fc)} F_CORTAS · {len(pr)} propietarios · meses {DESDE}..{a.mes}')


def cmd_registrar(a):
    hoy = datetime.datetime.now(TZ).date().isoformat()
    corrida = {T['asunto']: a.asunto, T['tipo']: 'Corrida', T['proceso']: 'Portal', T['origen']: 'Tarea',
               T['estado']: 'Hecho', T['resultado']: a.resultado, T['linea']: 'Verse Host', T['fecha']: hoy,
               T['cierre']: hoy, T['mes']: a.mes, T['link']: PORTAL,
               T['detalle']: f'Encontró: {a.encontro}\nHizo: {a.hizo}'}
    d = req('POST', f'/{PEND}/{TRAZ}', body={'records': [{'fields': corrida}], 'typecast': True})
    rid = d['records'][0]['id']
    for p in a.pendiente or []:
        asunto, accion = (p.split('|', 1) + [p])[:2]
        fila = {T['asunto']: asunto.strip(), T['tipo']: 'Pendiente', T['proceso']: 'Portal', T['origen']: 'Tarea',
                T['estado']: 'Abierto', T['responsable']: 'Felipe', T['linea']: 'Verse Host', T['fecha']: hoy,
                T['limite']: hoy, T['mes']: a.mes, T['accion']: accion.strip(), T['corrida']: [rid],
                T['link']: PORTAL}
        req('POST', f'/{PEND}/{TRAZ}', body={'records': [{'fields': fila}], 'typecast': True})
    print(rid)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('candado')
    c.add_argument('--mes')
    c.add_argument('--forzar', action='store_true')
    sub.add_parser('ultimo-cerrado')
    ch = sub.add_parser('cambios')
    ch.add_argument('--minutos', type=int, default=65)
    d = sub.add_parser('descargar')
    d.add_argument('--work', required=True)
    d.add_argument('--mes', required=True)
    r = sub.add_parser('registrar')
    r.add_argument('--mes', required=True)
    r.add_argument('--resultado', required=True)
    r.add_argument('--asunto', required=True)
    r.add_argument('--encontro', required=True)
    r.add_argument('--hizo', required=True)
    r.add_argument('--pendiente', action='append', help='"Asunto|Acción"')
    a = ap.parse_args()
    {'candado': cmd_candado, 'cambios': cmd_cambios, 'ultimo-cerrado': cmd_ultimo_cerrado, 'descargar': cmd_descargar, 'registrar': cmd_registrar}[a.cmd](a)


if __name__ == '__main__':
    main()
