# Radar del mercado eléctrico · informe semanal automático

Informe semanal del mercado eléctrico peninsular con foco en **almacenamiento (BESS) y renovables**:
un **PDF de ~60 páginas** (presentación 16:9) y una **web resumida** con gráficos interactivos.
Todo con **Python y GitHub Actions: 0 €**. Sin IA al ejecutarse: todo el cálculo es determinista.

Fuentes públicas: ESIOS (REE) —indicadores e I3— y OMIE (vía ESIOS). Marca y colores propios.

## Qué incluye
- **Mercados**: diario, IDA1-3, continuo, energía casada, aFRR (energía y banda), mFRR, demanda real/prevista/programada.
- **Mix de generación y cuota renovable** (tiempo real) y saldo de intercambios.
- **Baterías del sistema**: qué cargaron y entregaron las baterías reales, a qué precio y con qué spread; y su liquidación en el I3.
- **Sector por tecnología (I3)**: energía, ingreso y precio capturado por mercado (solar, eólica, almacenamiento…).
- **Restricciones técnicas (I3)**: cascada de programas PBF → P48, recortes de renovables, fases y tipologías, COT/SOT y Operación Reforzada.
- **Lectura propia para BESS**: mapa de precios, techo de arbitraje (1/2/4/6 h), curva de duración, banda aFRR frente a arbitraje,
  primas de cada mercado por hora, captura solar y eólica, canibalización, demanda residual e **histórico semanal** desde 2025.

## Calendario (automático)
- **Lunes 07:00-08:00 (Madrid)**: edición **provisional** de la semana anterior (todo menos el I3, que REE publica a D+4).
- **Martes a sábado** a la misma hora: si la semana está provisional y el I3 de los siete días ya está publicado, el informe se
  **regenera solo** con todas las secciones (normalmente el viernes). Si ya está completa, no hace nada.
- Si una ejecución falla, la siguiente lo vuelve a intentar. GitHub avisa por correo al dueño del repositorio de los fallos.

## Puesta en marcha (una sola vez)
1. Repositorio público en GitHub con este contenido (incluida la carpeta `.github`).
2. Token de ESIOS (gratis, https://api.esios.ree.es) como secreto `ESIOS_TOKEN` (*Settings → Secrets and variables → Actions*).
3. *Settings → Pages*: rama `main`, carpeta `/docs`.
4. *Actions → «I3 histórico»* (una vez): descarga el I3 desde 2025-01-01 (≈ 40 min).
5. *Actions → «Histórico semanal»* (una vez): rellena el histórico de indicadores semanales desde 2025.
6. *Actions → «Informe semanal» → Run workflow* con semana `anterior` (o una fecha) y «forzar» si ya existe.
7. (Opcional) Correo: secretos `EMAIL_USER`, `EMAIL_PASS` (contraseña de aplicación de Gmail) y `EMAIL_TO` (copia oculta).
   Se envía cada vez que se genera el PDF (lunes provisional y, después, el completo).

Resultados: `https://TU_USUARIO.github.io/informe-mercados/` (web), `/ultimo.pdf` (PDF) y `/archivo.html` (semanas anteriores).

## Herramientas
- **Auditoría de fuentes** (`src/auditoria.py`): vuelca datos crudos de ESIOS (los IDs que se le pidan) y zips del I3 en
  `data/auditoria/` para validar unidades, resolución y zona fuera de GitHub.
- **Descubrir / Volcar indicadores**: buscar IDs de ESIOS.
- **I3 diagnóstico**: estructura real de un día del I3.

## Cómo se toman los datos (validado contra las tablas de UNEF, semanas 42 y 43)
- Datos **crudos** de ESIOS agregados en local (ESIOS suma por defecto al agrupar).
- Energías (MWh por periodo) → MW medios; series de 5 minutos → media del cuarto de hora; zona España (3) o Península (8741).
- I3: cada valor en el periodo que dice su cabecera; precios ESIOS alineados por fecha y hora.
- Banda aFRR: precio 2130/634 y asignada 632/633. ESIOS no las publicó entre el 25-oct y el 4-nov-2026; esos días quedan sin
  dato (el respaldo 10388/10463 publicó cifras que no son €/MW y se descartan).
- Dependencias con versión fijada en `requirements.txt` (probadas): una versión nueva no puede romper el informe del lunes.

## Limitaciones honestas
- El I3 va agregado por tecnología (no por unidad). El reparto entre intradiarios (PHF-k ↔ IDA k) incluye lo negociado en el continuo entre subastas.
- El techo de arbitraje es una cota con previsión perfecta, no un ingreso. El parque de baterías se valora al precio del diario, no es su liquidación.
- La demo usa datos sintéticos (marcados como tales).
- Si se reutiliza o se cobra: citar siempre ESIOS/REE y OMIE, revisar sus condiciones de reutilización y no usar marcas de terceros.
