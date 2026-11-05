# vh-portal

Sitio estático del portal de propietarios de Verse Host (https://portal.versehost.co, Vercel `versehost-portal`).

La raíz (`index.html`, `vercel.json`, `_headers`, `robots.txt`) es lo único que se publica; `tools/` y `.github/` están en `.vercelignore`.

## Publicación (atada al Cierre B)

El flujo `.github/workflows/portal.yml` revisa cada hora, del 4 al 15 de cada mes, si en TRAZABILIDAD ya están el check de Felipe al Cierre A y la Corrida Cierre B del mes anterior, y si no existe una Corrida Portal válida del mes. Si se cumple, baja los datos de Airtable, genera el portal, lo publica, confirma que Vercel sirve el corte nuevo y deja la Corrida Portal. Si no, termina sin hacer nada. También corre a pedido desde Actions → "Portal de propietarios" → Run workflow.

Republicación por cambio: cada hora (minuto 47) el flujo revisa con el mismo AIRTABLE_TOKEN si cambió alguna F_CORTAS, RESERVA, ADICIONAL o PROPIETARIO en la última hora (`airtable_portal.py cambios`); si hubo cambios, republica el último mes con Corrida Cierre B y solo registra Corrida Portal si el sitio cambió. Opcional, para que sea inmediato: la automatización "Portal · liquidación actualizada" de Airtable (base OPERACIÓN 360) manda `repository_dispatch` con tipo `liquidacion-actualizada` cada vez que cambia una F_CORTAS. El flujo espera 3 minutos para agrupar ediciones en lote, republica el último mes con Corrida Cierre B (`airtable_portal.py ultimo-cerrado`) y solo registra Corrida Portal si el sitio cambió. La automatización usa el secreto de Airtable `GITHUB_TOKEN`: token fine-grained con permiso Contents: Read and write sobre `felipe734/vh-portal`.

Requiere el secreto `AIRTABLE_TOKEN` (Settings → Secrets and variables → Actions) con scopes `data.records:read`, `data.records:write` y `schema.bases:read` sobre OPERACIÓN 360, INVENTARIO y 9. PENDIENTES. Solo escribe en TRAZABILIDAD. Las contraseñas nuevas las crea el Cierre B en PROPIETARIOS.

`tools/scripts/build_portal.py` y `tools/assets/template.html` son copia de la skill `vh-portal-propietarios` (repo `felipe734/verse-plugins`): si cambian allá, se copian aquí.

Nunca se suben credenciales, datos crudos ni reportes: se generan en el runner y se descartan.
