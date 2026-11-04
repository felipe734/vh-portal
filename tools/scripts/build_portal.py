#!/usr/bin/env python3
"""Genera el portal de propietarios de Verse Host como HTML estático (sin backend).

Uso:
  python3 build_portal.py --work <dir_trabajo> [--verify]

<dir_trabajo> contiene:
  config.json                 parámetros del corte (ver references/datos.md)
  raw/fcortas*.json           respuestas de list_records_for_table de F_CORTAS
  raw/reservas*.json          respuestas de RESERVAS
  raw/adicionales*.json       respuestas de ADICIONALES
  raw/propietarios*.json      respuestas de PROPIETARIOS
Cada archivo raw puede ser la respuesta tal cual ({"records":[...]}) o una lista de records.

Salida en <dir_trabajo>/out/:
  portal-propietarios-<hasta>/index.html, vercel.json, _headers, robots.txt   (carpeta del sitio: se copia a la raíz del repo vh-portal)
  portal-propietarios-<hasta>.zip                                  (respaldo)
  reporte.json / reporte.md                                        (validaciones y faltantes)
  privado/credenciales-<hasta>.csv                                 (NUNCA se publica)
"""
import argparse, base64, csv, glob, hashlib, json, os, secrets, shutil, sys, zipfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'assets', 'template.html')
ITER = 200000
TOL = 2  # pesos de tolerancia en cuadres

# ---- field IDs (fuente: references/datos.md) ----
FC = dict(und='fldNrIFdC1GOVKe98', m='fld2WlOrsZxMq8jLS', al='fldZN04Va7ZE84YrZ', cb='fldXNJurLpC3VsW38',
          iva='fld2QmfCG0F3IofmP', ad='fld3CHBqQOMEgUJqg', af='fldLhWeYeCgL2KkEn', ne='fldVrmROYg57Oy8cN',
          cp='fld0jaZOzguFfy6ok')
RS = dict(und='fldx9Lhb6x8ub9OF2', i='fldljxOpEpmoJdulL', s='fldTSJWyU4vVXne5p', n='fldy5DWjTTP6ymbKI',
          a='fldxz2ERUEAdAb3Na', af='fldvrD9FyUWlZfoqV', p='fldbw1Oxy4hgt9NxB', m='flduUM7AHFwPKVN4a')
AD = dict(m='fld5Pd5nYEBmz3SMR', und='fldMJNwdtkLVsW0wI', c='fldKjCC3egUOx55CJ', f='fldCKJitAaHgQudNT',
          v='fldsRagecvJCXF4Lg', d='fldr5OqYeRBMxp7gq')
PR = dict(nombre='fldIo79HDQDR9NZ3t', email='fldk43IQ8ZvVPYCEm', pw='fldymnj9nW8YgVC0V',
          props='fldcFCRxUIamIfQ22', estado='fldgqY5qwMuIo0Ksg')


def load_records(work, prefix):
    recs = []
    for f in sorted(glob.glob(os.path.join(work, 'raw', prefix + '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        if isinstance(d, dict):
            d = d.get('records', [])
        recs.extend(d)
    seen, out = set(), []
    for r in recs:  # dedup por id (páginas solapadas)
        rid = r.get('id')
        if rid and rid in seen:
            continue
        seen.add(rid)
        out.append(r)
    return out


def cell(r, fid):
    v = (r.get('cellValuesByFieldId') or r.get('fields') or {}).get(fid)
    return v


def txt(v):
    if v is None:
        return None
    if isinstance(v, list):
        return txt(v[0]) if v else None
    if isinstance(v, dict):
        return v.get('name') or v.get('value') or v.get('text')
    return str(v).strip()


def names(v):
    if not v:
        return []
    if not isinstance(v, list):
        v = [v]
    return [txt(x) for x in v if txt(x)]


def num(v):
    v = txt(v) if isinstance(v, (list, dict)) else v
    if v in (None, ''):
        return None
    try:
        return float(v)
    except Exception:
        return None


def r0(x):
    return round(x or 0, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--verify', action='store_true')
    a = ap.parse_args()
    work = a.work
    cfg = json.load(open(os.path.join(work, 'config.json'), encoding='utf-8'))
    desde, hasta = cfg['desde'], cfg['hasta']
    alias = cfg.get('alias', {})            # nombre en PROPIETARIOS/INVENTARIO -> nombre en F_CORTAS
    excluir = {(u, m) for u, m in cfg.get('excluir', [])}
    ne_override = cfg.get('ne_override', {})  # "Unidad|AAAA-MM": valor
    meta_und = cfg.get('unidades', {})        # "Unidad": {edificio, ciudad, dir}
    ciudad_def = cfg.get('ciudad_default', 'Bogotá')
    U = lambda n: alias.get(n, n)
    inrange = lambda m: m and desde <= m <= hasta

    rep = dict(corte=hasta, desde=desde, avisos=[], bloqueos=[], faltantes=[], info=[])

    # ---------- F_CORTAS ----------
    ops = defaultdict(list)
    for r in load_records(work, 'fcortas'):
        und, m = U(txt(cell(r, FC['und']))), txt(cell(r, FC['m']))
        if not und or not inrange(m) or (und, m) in excluir:
            continue
        o = {k: num(cell(r, FC[k])) for k in ('al', 'cb', 'iva', 'ad', 'af', 'ne', 'cp')}
        for k in ('al', 'cb', 'iva', 'ad', 'af'):
            o[k] = o[k] or 0
        key = f'{und}|{m}'
        if key in ne_override:
            o['ne'] = float(ne_override[key])
            rep['info'].append(f'{und} {m}: Neto fijado por config = {o["ne"]:,.0f}')
        if o['ne'] is None:
            o['ne'] = o['al'] - o['cb'] - o['iva'] - o['ad'] - o['af']
            rep['avisos'].append(f'{und} {m}: Neto Propietario vacío en F_CORTAS; calculado al−cb−iva−ad−af = {o["ne"]:,.0f}. Confirmar antes de publicar')
        if o['ne'] <= 0:
            rep['avisos'].append(f'{und} {m}: Neto Propietario = {o["ne"]:,.0f} (≤ 0). Revisar si debe mostrarse')
        if o['al'] > 0 and o['af'] and abs(o['af'] - o['al'] * 0.155) > max(5, o['al'] * 0.002):
            rep['info'].append(f'{und} {m}: Airbnb fee {o["af"]:,.0f} ≠ 15,5% del alojamiento ({o["al"]*0.155:,.0f})')
        if any(x['m'] == m for x in ops[und]):
            rep['bloqueos'].append(f'{und} {m}: hay más de una liquidación en F_CORTAS para el mismo mes')
            continue
        o['cp'] = o['cp'] if o['cp'] is not None else 0
        if o['cp'] and o['cp'] <= 1:
            o['cp'] = o['cp'] * 100  # porcentaje guardado como fracción
        o['tvh'] = o['cb'] + o['iva'] + o['ad']
        ops[und].append(dict(und=und, m=m, **{k: r0(o[k]) for k in ('al', 'cb', 'iva', 'ad', 'af', 'ne', 'cp', 'tvh')}))

    # ---------- RESERVAS ----------
    res = defaultdict(list)
    for r in load_records(work, 'reservas'):
        und, m = U(txt(cell(r, RS['und']))), txt(cell(r, RS['m']))
        if und not in ops or not inrange(m) or (und, m) in excluir:
            continue
        res[und].append(dict(m=m, i=txt(cell(r, RS['i'])) or '', s=txt(cell(r, RS['s'])) or '',
                             n=int(num(cell(r, RS['n'])) or 0), p=txt(cell(r, RS['p'])) or '',
                             a=r0(num(cell(r, RS['a']))), af=r0(num(cell(r, RS['af'])))))

    # ---------- ADICIONALES ----------
    adi = defaultdict(list)
    for r in load_records(work, 'adicionales'):
        und, m = U(txt(cell(r, AD['und']))), txt(cell(r, AD['m']))
        if und not in ops or not inrange(m) or (und, m) in excluir:
            continue
        c = txt(cell(r, AD['c'])) or ''
        d = txt(cell(r, AD['d']))
        adi[und].append(dict(m=m, f=txt(cell(r, AD['f'])) or '', c=(c + ' — ' + d) if d and d != c else c,
                             v=r0(num(cell(r, AD['v'])))))

    # ---------- Cuadres: el detalle debe sumar lo de F_CORTAS ----------
    for und, lst in ops.items():
        for o in lst:
            m = o['m']
            rm = [x for x in res[und] if x['m'] == m]
            sa = sum(x['a'] for x in rm)
            if rm and abs(sa - o['al']) > TOL:
                rep['avisos'].append(f'{und} {m}: Σ reservas {sa:,.0f} ≠ alojamiento F_CORTAS {o["al"]:,.0f}. Tabla de reservas oculta en el portal')
                res[und] = [x for x in res[und] if x['m'] != m]
            elif not rm and o['al'] > 0:
                rep['info'].append(f'{und} {m}: sin reservas de detalle (alojamiento {o["al"]:,.0f})')
            am = [x for x in adi[und] if x['m'] == m]
            sv = sum(x['v'] for x in am)
            if am and abs(sv - o['ad']) > TOL:
                rep['avisos'].append(f'{und} {m}: Σ ADICIONALES {sv:,.0f} ≠ Adicional F_CORTAS {o["ad"]:,.0f}. Tabla de adicionales oculta en el portal')
                adi[und] = [x for x in adi[und] if x['m'] != m]
            elif not am and o['ad'] > 0:
                rep['avisos'].append(f'{und} {m}: F_CORTAS cobra adicionales {o["ad"]:,.0f} pero no hay detalle en ADICIONALES')
        lst.sort(key=lambda x: x['m'])
    for d in (res, adi):
        for und in d:
            d[und].sort(key=lambda x: (x['m'], x.get('i') or x.get('f') or ''))

    # ---------- Propietarios ----------
    owners_by_unit = defaultdict(list)
    accounts = defaultdict(lambda: {'names': [], 'units': [], 'pws': set()})
    for r in load_records(work, 'propietarios'):
        nombre = (txt(cell(r, PR['nombre'])) or '').strip()
        email = (txt(cell(r, PR['email'])) or '').strip().lower()
        pw = (txt(cell(r, PR['pw'])) or '').strip()
        units = [U(n) for n in names(cell(r, PR['props']))]
        live = [u for u in units if u in ops]
        for u in live:
            owners_by_unit[u].append(nombre)
        if not live:
            continue
        if not email or '@' not in email or '..' in email:
            rep['faltantes'].append(dict(tipo='sin_email', propietario=nombre, record=r.get('id'), unidades=live))
            continue
        if not pw:
            rep['faltantes'].append(dict(tipo='sin_password', propietario=nombre, email=email, record=r.get('id'), unidades=live))
            continue
        acc = accounts[(email, pw)]
        acc['names'].append(nombre)
        for u in live:
            if u not in acc['units']:
                acc['units'].append(u)
    for u in ops:
        if not owners_by_unit.get(u):
            rep['faltantes'].append(dict(tipo='unidad_sin_propietario', unidad=u,
                                         nota='Ninguna fila de PROPIETARIOS enlaza esta unidad (revisar nombre o alias)'))
    unidades_con_acceso = {u for acc in accounts.values() for u in acc['units']}
    for u in ops:
        if u not in unidades_con_acceso and owners_by_unit.get(u):
            rep['faltantes'].append(dict(tipo='unidad_sin_acceso', unidad=u, propietarios=owners_by_unit[u]))

    # ---------- Cifrado por propietario ----------
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    pepper = secrets.token_hex(16)
    vault = defaultdict(list)
    creds = []
    for (email, pw), acc in sorted(accounts.items()):
        units = []
        for u in acc['units']:
            mu = meta_und.get(u, {})
            parts = u.split(' - ', 1)
            units.append(dict(und=u, edificio=mu.get('edificio', parts[1].strip() if len(parts) > 1 else u),
                              ciudad=mu.get('ciudad', ciudad_def), dir=mu.get('dir', '')))
        payload = dict(n=acc['names'][0], u=units,
                       o={u: ops[u] for u in acc['units']},
                       r={u: res.get(u, []) for u in acc['units']},
                       a={u: adi.get(u, []) for u in acc['units']})
        salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
        key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
        ct = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode(), None)
        eid = hashlib.sha256((pepper + email).encode()).hexdigest()[:32]
        vault[eid].append(dict(s=base64.b64encode(salt).decode(), v=base64.b64encode(iv).decode(),
                               c=base64.b64encode(ct).decode()))
        creds.append(dict(email=email, password=pw, nombre=acc['names'][0], unidades=' | '.join(acc['units']),
                          liquidaciones=sum(len(ops[u]) for u in acc['units'])))

    MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre',
             'Octubre', 'Noviembre', 'Diciembre']
    act = cfg.get('actualizado') or ''
    try:
        y, mo, dd = act.split('-')
        act_txt = f'{int(dd):02d} {MESES[int(mo)-1]} {y}'
    except Exception:
        act_txt = act
    html = open(TEMPLATE, encoding='utf-8').read()
    html = (html.replace('__VAULT__', json.dumps(vault, separators=(',', ':')))
                .replace('__PEPPER__', pepper).replace('__ITER__', str(ITER))
                .replace('__ACTUALIZADO__', act_txt).replace('__ANIO__', hasta[:4]))

    out = os.path.join(work, 'out')
    site = os.path.join(out, f'portal-propietarios-{hasta}')
    shutil.rmtree(site, ignore_errors=True)
    os.makedirs(site)
    os.makedirs(os.path.join(out, 'privado'), exist_ok=True)
    open(os.path.join(site, 'index.html'), 'w', encoding='utf-8').write(html)
    open(os.path.join(site, '_headers'), 'w').write(
        '/*\n  X-Robots-Tag: noindex, nofollow\n  X-Frame-Options: DENY\n  Referrer-Policy: no-referrer\n'
        '  Cache-Control: no-cache\n')
    open(os.path.join(site, 'robots.txt'), 'w').write('User-agent: *\nDisallow: /\n')
    # Vercel (proyecto versehost-portal) lee los encabezados de vercel.json; _headers queda como respaldo.
    vercel_cfg = {"cleanUrls": True, "headers": [{"source": "/(.*)", "headers": [
        {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
        {"key": "X-Frame-Options", "value": "DENY"},
        {"key": "Referrer-Policy", "value": "no-referrer"},
        {"key": "Cache-Control", "value": "no-cache"}]}]}
    with open(os.path.join(site, 'vercel.json'), 'w', encoding='utf-8') as f:
        json.dump(vercel_cfg, f, indent=2)
        f.write('\n')
    zp = os.path.join(out, f'portal-propietarios-{hasta}.zip')
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in ('index.html', '_headers', 'robots.txt', 'vercel.json'):
            z.write(os.path.join(site, f), f)
    cp = os.path.join(out, 'privado', f'credenciales-{hasta}.csv')
    with open(cp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['email', 'password', 'nombre', 'unidades', 'liquidaciones'])
        w.writeheader()
        w.writerows(creds)

    # ---------- Reporte ----------
    meses = sorted({o['m'] for l in ops.values() for o in l})
    corte_units = [u for u, l in ops.items() if any(o['m'] == hasta for o in l)]
    rep['cifras'] = dict(cuentas=len(creds), unidades=len(ops), liquidaciones=sum(len(l) for l in ops.values()),
                         reservas=sum(len(l) for l in res.values()), adicionales=sum(len(l) for l in adi.values()),
                         meses=meses, unidades_mes_corte=len(corte_units),
                         neto_mes_corte=round(sum(o['ne'] for l in ops.values() for o in l if o['m'] == hasta)),
                         html_kb=round(len(html) / 1024))
    rep['prueba'] = [dict(email=c['email'], password=c['password']) for c in creds[:2]]
    json.dump(rep, open(os.path.join(out, 'reporte.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    c = rep['cifras']
    md = [f'# Portal propietarios · corte {hasta}', '',
          f'Cuentas {c["cuentas"]} · Unidades {c["unidades"]} · Liquidaciones {c["liquidaciones"]} · '
          f'Reservas {c["reservas"]} · Adicionales {c["adicionales"]}',
          f'Meses: {", ".join(meses)} · Unidades con liquidación en {hasta}: {c["unidades_mes_corte"]} · '
          f'Neto {hasta}: ${c["neto_mes_corte"]:,.0f}', '']
    for k, t in (('bloqueos', 'BLOQUEOS'), ('avisos', 'AVISOS'), ('info', 'INFO')):
        if rep[k]:
            md += [f'## {t}'] + [f'- {x}' for x in rep[k]] + ['']
    if rep['faltantes']:
        md += ['## FALTANTES'] + [f'- {json.dumps(x, ensure_ascii=False)}' for x in rep['faltantes']] + ['']
    open(os.path.join(out, 'reporte.md'), 'w', encoding='utf-8').write('\n'.join(md))
    print('\n'.join(md))
    print(f'\nSITE  {site}\nZIP   {zp}\nCREDS {cp}')

    if a.verify:
        verify(os.path.join(site, 'index.html'), creds)
    if rep['bloqueos']:
        sys.exit(2)


def verify(path, creds):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print('VERIFY omitido: playwright no disponible')
        return
    tests = creds[:2] + creds[-1:]
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        for c in tests:
            pg.goto('file://' + path)
            pg.fill('#emailIn', c['email'])
            pg.fill('#pwIn', c['password'])
            pg.click('.login-btn')
            pg.wait_for_selector('#dashboard', state='visible', timeout=20000)
            hero = pg.inner_text('#heroVal')
            print(f'VERIFY OK  {c["email"]} -> {hero}')
        pg.goto('file://' + path)
        pg.fill('#emailIn', tests[0]['email'])
        pg.fill('#pwIn', 'clave-incorrecta')
        pg.click('.login-btn')
        pg.wait_for_selector('#loginErr', state='visible', timeout=20000)
        print('VERIFY OK  clave incorrecta rechazada')
        b.close()


if __name__ == '__main__':
    main()
