# Radar del mercado eléctrico · informe semanal automático

Genera cada semana un **PDF de ~58 páginas** (formato presentación, 16:9) con precios, servicios de ajuste,
restricciones técnicas (cascada de programas, Sankey por tecnología, COT/SOT, Operación Reforzada) y una
sección propia de **almacenamiento y renovables** (techo de arbitraje de baterías, banda aFRR vs arbitraje,
precio capturado, canibalización, demanda residual, señales de la semana…).
Todo con **Python y GitHub Actions: 0 €** (solo pagas Claude Pro). No usa IA al ejecutarse.

Fuentes públicas: ESIOS (REE) —indicadores e I3—, OMIE. Colores y marca propios (edítalos en `config.yml` y `src/pdf.py`).

## Pasos (una sola vez, ~30 min)

1. **Cuenta GitHub** (gratis) → *New repository* → nombre `informe-mercados`, **Public** → sube el contenido de este zip
   (*Add file → Upload files*, arrastra todas las carpetas incluida `.github`).
2. **Token ESIOS** (gratis): pídelo en https://api.esios.ree.es (formulario "solicitar token", llega por email).
3. En el repo: *Settings → Secrets and variables → Actions → New repository secret* → nombre `ESIOS_TOKEN`, valor = tu token.
4. *Settings → Pages* → Source: **Deploy from a branch**, rama `main`, carpeta `/docs`.
5. *Actions → "Informe semanal" → Run workflow* con **demo** marcado → comprueba que se genera `docs/demo.pdf` (datos sintéticos).
6. **Diagnóstico I3 (opcional)**: *Actions → "I3 diagnóstico"* con un día de hace ≥5 días genera `data/i3_estructura.txt` para revisar la estructura. El lector (`src/i3_real.py`) ya está validado contra el I3 real (la cascada cierra contra P48).
7. **Histórico I3**: *Actions → "I3 histórico" → Run workflow*. Repítelo hasta que diga que no quedan días
   (necesario para el "año a año" de la Operación Reforzada).
8. **IDs de series**: ya están rellenados en `config.yml` (los que tienen datos). *Actions → "Descubrir indicadores"* permite buscar otros por texto o `ids:630,631`.
9. *Actions → "Informe semanal" → Run workflow* con semana `anterior` → PDF real. Después sale solo **los lunes a las 07:00-08:00 (hora de Madrid; el martes es un reintento)**.
   Si el I3 de la semana aún no está completo o no valida, el informe sale igualmente **sin** las secciones I3 y lo dice en "Cómo leer".
10. (Opcional) Correo: secretos `EMAIL_USER`, `EMAIL_PASS` (contraseña de aplicación de Gmail) y `EMAIL_TO`
    (una o varias direcciones separadas por coma; van en **copia oculta**).

El PDF queda en `https://TU_USUARIO.github.io/informe-mercados/ultimo.pdf` y el archivo de semanas en `/archivo.html`.

## Si quieres cobrar por él
- Cita siempre ESIOS/REE y OMIE (ya está en cada pie) y revisa sus condiciones de reutilización de datos.
- No uses nombre ni logo de UNEF ni de nadie; el informe no es oficial: añade tu descargo de responsabilidad.
- Con Gmail el envío tiene límite diario (~500); para suscriptores de pago usa Substack/Ghost/Buttondown (gratis al inicio)
  y adjunta el PDF; o la lista en `EMAIL_TO` mientras sean pocos.
- El repo es público: si cobras, publica solo el enlace a PDFs por suscripción o pasa a repo privado (Pages privado requiere plan de pago;
  alternativa: no publicar `docs/` y enviar solo por correo).

## Limitaciones honestas
- El acta del GT de Almacenamiento es contenido privado: no se puede replicar. Se ofrece en su lugar análisis propio.
- El I3 de REE se publica con ~4 días de retraso: el domingo ya está el jueves, así que el lunes la semana anterior está completa. Si por cualquier motivo falta algún día, el informe sale igualmente sin las secciones I3 y el martes se reintenta.
- La demo usa datos sintéticos (marcados como tales en el PDF).
