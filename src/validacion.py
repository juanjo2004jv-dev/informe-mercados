"""Control de calidad automático de los datos (determinista, en cada ejecución).

  4.1 Coherencia interna: renovables > demanda recalculado desde cero, cuota renovable, captura,
      rendimiento aparente de las baterías y cierre de las cascadas del I3 contra el P48.
  4.2 Contraste entre fuentes: ESIOS 600 frente a OMIE marginalpdbc, IDA1-3 (612-614) frente a OMIE
      marginalpibc, tiempo real de ESIOS frente a demanda.ree.es y energía semanal frente a REData.
Ningún ⚠ tumba la publicación: todos salen en la página «Control de calidad de los datos»."""
import textwrap

import numpy as np
import pandas as pd

from . import analisis as A
from . import fuentes as F
from .narrativa import n

OK, KO = "✔", "⚠"


def _ctrl(grupo, nombre, valor, ref, dif, tol, ok, fmt="{:.2f}", nota="", clave=None):
    f = (lambda x: x if isinstance(x, str) else ("s/d" if x is None or (isinstance(x, float) and np.isnan(x)) else fmt.format(x).replace(".", ",")))
    return {"grupo": grupo, "nombre": nombre, "valor": valor, "ref": ref, "dif": dif, "ok": bool(ok),
            "valor_txt": f(valor), "ref_txt": f(ref), "dif_txt": f(dif), "tol_txt": tol, "nota": nota, "clave": clave}


def marca(res, clave):
    """« ⚠» junto a una cifra mostrada si un control que la afecta no pasó."""
    return f" {KO}" if clave in (res.get("qc") or {}).get("marcas", set()) else ""


def _renovable(datos, cfg, idx):
    """Recalcula desde cero (independiente de analisis.mix_semana) renovable, generación y demanda."""
    g = lambda k: A.alinear(datos.get(k), idx)
    conf = cfg.get("mix") or {}
    turb, cons = g("bal_turb_bombeo").fillna(0), g("bal_cons_bombeo").fillna(0)
    gen = {}
    for k in conf:
        v = g(f"mix_{k}")
        if k == "hidraulica":
            v = (v - turb - cons).clip(lower=0)            # hidráulica convencional
        gen[k] = v.clip(lower=0)
    gen["turb_bombeo"] = g("bal_turb_bombeo").clip(lower=0)
    df = pd.DataFrame(gen)
    ren = df[[k for k, v in conf.items() if v.get("renovable")]].sum(axis=1)
    tot = df.sum(axis=1, min_count=1)
    return ren, tot, g("demanda_real"), df


def ejecutar(res, datos, meta, cfg, lunes, info_tr, i3=None):
    tolc = cfg.get("validacion") or {}
    t_pre = float(tolc.get("precio_eur_mwh", 0.01))
    t_tr = float(tolc.get("tiempo_real_pct", 1.0))
    t_i3 = float(tolc.get("cascada_i3_pct", 0.1))
    idx = A.rejilla(res["ini"], res["fin"])
    C_, marcas = [], set()

    # ---------------- 4.1 coherencia interna
    m = res.get("mix")
    if m:
        ren, tot, dem, gen = _renovable(datos, cfg, idx)
        ok = dem.notna() & (dem > 0) & tot.notna()
        h = float(((ren / dem).where(ok) > 1).sum() / 4)
        C_.append(_ctrl("Coherencia", "Horas con renovables > demanda (recalculado)", h, m.get("horas_ren_demanda"),
                        h - (m.get("horas_ren_demanda") or 0), "0 h", abs(h - (m.get("horas_ren_demanda") or 0)) < 0.01, "{:.2f}",
                        f"máx. {n(m.get('ren_dem_max'), 1)} %", clave="renovables"))
        cu = float(ren.sum() / tot.sum() * 100) if tot.sum() else np.nan
        C_.append(_ctrl("Coherencia", "Cuota renovable = Σ renovables / Σ generación (%)", cu, m.get("renovable_pct"),
                        cu - m.get("renovable_pct", np.nan), "0,01 pp", abs(cu - m.get("renovable_pct", np.nan)) < 0.01, clave="renovables"))
    for k, nom in (("gen_solar_fv", "FV"), ("gen_eolica", "eólica")):
        c = res["captura"].get(k)
        if not c:
            continue
        p, g = res["spot"].values, A.alinear(datos.get(k), idx).values
        mk = ~np.isnan(p) & ~np.isnan(g) & (g > 0)
        v = float((p[mk] * g[mk]).sum() / g[mk].sum()) if mk.any() else np.nan
        C_.append(_ctrl("Coherencia", f"Captura {nom} = Σ(p·g)/Σg (€/MWh)", v, c["precio"], v - c["precio"], "0,01 €/MWh",
                        abs(v - c["precio"]) <= 0.01, clave="captura"))
    b = res.get("baterias")
    if b:
        r = b.get("rendimiento", np.nan)
        lo, hi = tolc.get("rendimiento_baterias_pct", [70, 95])
        okb = lo <= r <= hi
        C_.append(_ctrl("Coherencia", "Rendimiento aparente de las baterías (%)", r, f"{lo}-{hi} %", "—", "rango", okb, "{:.1f}",
                        "entregada / cargada en la semana", clave="baterias"))
        if not okb:
            marcas.add("baterias")
    if i3 is not None and len(i3):
        from .i3 import cascada

        for tec, nom in ((None, "sistema"), ("Solar fotovoltaica", "FV"), ("Eólica", "eólica"), ("Solar térmica", "solar térmica")):
            c = cascada(i3, tec)
            C_.append(_ctrl("Coherencia", f"Cascada del I3 contra el P48 ({nom}) (%)", c["dif_pct"], 0.0, c["dif_pct"], f"{n(t_i3, 1)} %",
                            c["dif_pct"] == c["dif_pct"] and c["dif_pct"] <= t_i3, "{:.3f}"))

    # ---------------- 4.2 contraste entre fuentes
    omie, err_o = F.omie_semana(lunes)
    for k, nom, ide, fich in (("spot", "Diario", 600, "marginalpdbc"), ("ida1", "IDA1", 612, "marginalpibc 01"),
                              ("ida2", "IDA2", 613, "marginalpibc 02"), ("ida3", "IDA3", 614, "marginalpibc 03")):
        e = res["spot"] if k == "spot" else res["series"].get(k)
        o = omie.get(k)
        if e is None or o is None or not len(o):
            C_.append(_ctrl("Fuentes", f"ESIOS {ide} frente a OMIE {fich} (España)", None, None, None, f"{n(t_pre, 2)} €/MWh", False,
                            nota=("OMIE no respondió: " + (err_o or "sin datos")) if o is None else "sin serie de ESIOS", clave="spot" if k == "spot" else None))
            continue
        o = o.reindex(idx)
        cm = e.notna() & o.notna()
        dmax = float((e[cm] - o[cm]).abs().max()) if cm.any() else np.nan
        sin_omie = int((e.notna() & o.isna()).sum())
        okp = cm.any() and dmax <= t_pre + 1e-9 and sin_omie == 0
        C_.append(_ctrl("Fuentes", f"ESIOS {ide} frente a OMIE {fich} (España), máx. |dif| (€/MWh)", dmax, 0.0, dmax, f"{n(t_pre, 2)} €/MWh", okp,
                        nota=f"{int(cm.sum())} cuartos comunes" + (f"; {sin_omie} sin dato en OMIE" if sin_omie else ""),
                        clave="spot" if k == "spot" else None))
        if not okp and k == "spot":
            marcas.add("spot")
    if info_tr.get("ok"):
        for v in info_tr.get("validacion", []):
            rel = v["rel"] * 100 if v["rel"] == v["rel"] else np.nan
            nom = meta.get(v["clave"], {}).get("nombre", v["clave"])
            okt = rel == rel and rel <= t_tr
            C_.append(_ctrl("Fuentes", f"ESIOS {v['id']} ({textwrap.shorten(str(nom), 26)}) frente a REE «{v['campo']}» (%)", rel, 0.0, rel,
                            f"{n(t_tr, 0)} %", okt, "{:.2f}",
                            f"{v['n']} cuartos comunes; rellena el {n(v['rellenado_pct'], 1)} %" + ("" if v["usada"] else "; NO se usa para rellenar (difiere > 5 %)"),
                            clave="tr"))
    else:
        C_.append(_ctrl("Fuentes", "Tiempo real de ESIOS frente a demanda.ree.es", None, None, None, f"{n(t_tr, 0)} %", False,
                        nota=f"REE en tiempo real no respondió ({info_tr.get('error') or 'sin datos'}): huecos sin rellenar"))
    rd = F.redata_semana(lunes)
    tabla = tabla_redata(res, rd)
    if tabla:
        peor = max(tabla, key=lambda f: abs(f[3]) if f[3] == f[3] else -1)
        C_.append(_ctrl("Fuentes", "Energía semanal por tecnología, tiempo real frente a REData (%)", peor[3], 0.0, peor[3], "informativo", True,
                        "{:+.1f}", f"mayor diferencia: {peor[0]} (tabla «Contraste con el balance diario de REE»)"))
    else:
        C_.append(_ctrl("Fuentes", "Energía semanal, tiempo real frente a REData", None, None, None, "informativo", True,
                        nota=f"REData no respondió ({rd.get('error') or 'sin datos'})"))
    for c in C_:
        if not c["ok"] and c.get("clave"):
            marcas.add(c["clave"])
    res["qc"] = {"controles": C_, "marcas": marcas, "redata": rd, "tabla_redata": tabla, "omie_error": err_o, "tr": info_tr}
    return res["qc"]


# --------------------------------------------------------------------- REData
PAREJAS_RD = [  # (fila, clave del mix de tiempo real, títulos de REData que se suman)
    ("Hidráulica convencional", "hidraulica", ["Hidráulica"]),
    ("Eólica", "eolica", ["Eólica"]),
    ("Solar fotovoltaica", "solar_fv", ["Solar fotovoltaica"]),
    ("Solar térmica", "solar_ter", ["Solar térmica"]),
    ("Térmica renovable / otras renovables", "term_ren", ["Otras renovables"]),
    ("Nuclear", "nuclear", ["Nuclear"]),
    ("Ciclo combinado", "ciclo", ["Ciclo combinado"]),
    ("Carbón", "carbon", ["Carbón"]),
    ("Cogeneración (y resto)", "cogen", ["Cogeneración"]),
    ("Turbina de vapor", "vapor", ["Turbina de vapor"]),
]


def tabla_redata(res, rd):
    """[(tecnología, tiempo real GWh, REData GWh, diferencia %)]; vacío si no hay datos."""
    m, gen, bal = res.get("mix"), rd.get("gen") or {}, rd.get("balance") or {}
    if not m or not gen:
        return []
    filas = []
    for nom, k, tit in PAREJAS_RD:
        if k not in m["gwh"] or not any(t in gen for t in tit):
            continue
        tr, r = float(m["gwh"][k]), float(sum(gen.get(t, 0) for t in tit))
        filas.append((nom, tr, r, (tr / r - 1) * 100 if r else np.nan))
    if "turb_bombeo" in m["gwh"] and "Turbinación bombeo" in bal:
        tr, r = float(m["gwh"]["turb_bombeo"]), float(bal["Turbinación bombeo"])
        filas.append(("Turbinación bombeo", tr, r, (tr / r - 1) * 100 if r else np.nan))
    return filas


def _tabla(fig, C, cols, filas, xs, al, y0, alto, fs=8.6):
    from matplotlib.patches import Rectangle

    fig.add_artist(Rectangle((0.045, y0 - alto / 2), 0.91, alto + 0.004, color=C["verde"], transform=fig.transFigure))
    for x, c, a in zip(xs, cols, al):
        fig.text(x, y0, c, color="white", fontsize=fs, fontweight="bold", va="center", ha=a)
    for i, fila in enumerate(filas):
        y = y0 - (i + 1) * alto
        if i % 2 == 0:
            fig.add_artist(Rectangle((0.045, y - alto / 2), 0.91, alto, color=C["panel"], transform=fig.transFigure))
        for x, v, a in zip(xs, fila, al):
            col = C["coral"] if v == KO else (C["musgo"] if v == OK else C["tinta"])
            fig.text(x, y, str(v), fontsize=fs, va="center", ha=a, color=col, fontweight="bold" if v in (OK, KO) else "normal")
    return y0 - (len(filas) + 1) * alto


def pag_redata(d, res):
    from .pdf import C

    qc = res.get("qc") or {}
    filas, rd = qc.get("tabla_redata") or [], qc.get("redata") or {}
    m = res.get("mix") or {}
    if not filas:
        return False
    bal = rd.get("balance") or {}
    ren_rd = bal.get("Generación renovable"), bal.get("Generación no renovable")
    cuota_rd = ren_rd[0] / (ren_rd[0] + ren_rd[1]) * 100 if all(ren_rd) else np.nan
    fig = d.diapositiva("Contraste con el balance diario de REE (REData)",
                        f"Energía de la semana por tecnología: tiempo real de REE (la serie del informe) frente al balance diario oficial de REData. Cuota renovable: "
                        f"{n(m.get('renovable_pct'), 1)} % en tiempo real y {n(cuota_rd, 1)} % con REData. La diferencia mayor suele ser la FV: el tiempo real es telemedida "
                        "más estimación y el balance se cierra después con medidas.",
                        "Tiempo real de REE (telemedida y estimación, cada 5 min). El balance oficial (REData) puede diferir, sobre todo en FV; las cuotas y capturas se calculan "
                        "sobre tiempo real porque es la única serie cuartohoraria. REData: apidatos.ree.es, generacion/estructura-generacion y balance/balance-electrico, peninsular, diario.")
    rows = [(f[0], n(f[1], 1), n(f[2], 1), n(f[3], 1, True) + " %") for f in filas]
    dem = res.get("demanda") or {}
    if dem.get("real") is not None and "Demanda en b.c." in bal:
        e_dem = float(dem["real"].sum() / 4 / 1000)
        rows.append(("Demanda real (ID 1293) / demanda en b.c.", n(e_dem, 1), n(bal["Demanda en b.c."], 1), n((e_dem / bal["Demanda en b.c."] - 1) * 100, 1, True) + " %"))
    if "saldo_intercambios_gwh" in m and "Saldo I. internacionales" in bal:
        rows.append(("Saldo exterior: físico (TR) / programado", n(m["saldo_intercambios_gwh"], 1), n(bal["Saldo I. internacionales"], 1),
                     n((m["saldo_intercambios_gwh"] / bal["Saldo I. internacionales"] - 1) * 100, 1, True) + " %"))
    y = _tabla(fig, C, ["Tecnología", "Tiempo real (GWh)", "REData (GWh)", "Diferencia"], rows, [0.06, 0.55, 0.72, 0.90],
               ["left", "right", "right", "right"], 0.75, 0.036, fs=9)
    nota = ("Hidráulica: el campo «hid» de REE y el indicador 546 de ESIOS son la hidráulica NETA (incluyen la turbinación de bombeo y restan su consumo). "
            "Aquí, hidráulica convencional = 546 − turbinación (2079) − consumo de bombeo (2078), que es la que cuenta como renovable; REData publica "
            "la hidráulica sin bombeo como balance cerrado con medidas, por eso no coincide con ninguno de los dos. La demanda real (1293) y la demanda en barras "
            "de central de REData son magnitudes distintas. El saldo físico es la medida en tiempo real; el programado, el de REData.")
    fig.text(0.05, max(0.07, y - 0.01), textwrap.fill(nota, 190), fontsize=7.8, color=C["gris"], va="top", linespacing=1.35)
    d.guardar(fig)
    return True


# --------------------------------------------------------------------- tabla de fuentes ampliada
CATALOGO = [  # (serie, ID o endpoint, publicador, granularidad, latencia, carácter, clave de cobertura, enlace)
    ("Precio diario", "600", "OMIE vía ESIOS", "15 min", "D-1", "definitivo", "spot", "esios.ree.es"),
    ("Precio IDA1 / IDA2 / IDA3", "612 / 613 / 614", "OMIE vía ESIOS", "15 min", "D-1 / D", "definitivo", "ida1", "esios.ree.es"),
    ("Contraste diario e IDA", "marginalpdbc / marginalpibc", "OMIE", "15 min", "D-1 / D", "definitivo", None, "omie.es/es/file-download"),
    ("Continuo (referencia)", "1727", "OMIE vía ESIOS", "1 h", "D", "provisional", "continuo", "esios.ree.es"),
    ("Banda aFRR precio / asignada", "2130, 634 / 632, 633", "REE (ESIOS)", "1 h", "D-1", "provisional", "afrr_banda_p_subir", "esios.ree.es"),
    ("Banda aFRR requerida / coste", "630, 631 / 712, 2127", "REE (ESIOS)", "1 h", "D-1", "provisional", "afrr_req_subir", "esios.ree.es"),
    ("aFRR energía: precio y activada", "682, 683 / 680, 681", "REE (ESIOS)", "15 min", "D+1", "provisional", "afrr_subir", "esios.ree.es"),
    ("mFRR precio y asignación", "2197 / 674, 675", "REE (ESIOS)", "15 min", "D+1", "provisional", "mfrr_subir", "esios.ree.es"),
    ("Demanda real / prevista / programada", "1293 / 544 / 545", "REE (ESIOS)", "5 min / 15 min", "minutos", "tiempo real", "demanda_real", "esios.ree.es"),
    ("Generación FV / eólica", "1295 / 551", "REE (ESIOS)", "5 min", "minutos", "tiempo real", "gen_solar_fv", "esios.ree.es"),
    ("Mix: hidráulica, nuclear, CC…", "546, 549, 550, 547, 548, 1294, 1296, 1297, 2344", "REE (ESIOS)", "5 min", "minutos", "tiempo real", "mix_ciclo", "esios.ree.es"),
    ("Bombeo, intercambios, enlace", "2078, 2079 / 553 / 554", "REE (ESIOS)", "5 min", "minutos", "tiempo real", "bal_intercambios", "esios.ree.es"),
    ("Baterías carga / entrega", "2166 / 2167", "REE (ESIOS)", "5 min", "minutos", "tiempo real", "bal_bat_carga", "esios.ree.es"),
    ("Relleno del tiempo real", "demandaGeneracionPeninsula", "REE", "5 min", "minutos", "tiempo real", None, "demanda.ree.es"),
    ("Balance diario de contraste", "estructura-generacion, balance-electrico", "REE (REData)", "1 día", "D+1", "provisional", None, "apidatos.ree.es"),
    ("Liquidación por tecnología", "I3 (archivo 32)", "REE (ESIOS)", "15 min, agregado", "D+4", "liquidación provisional", None, "esios.ree.es"),
]


def _cob_txt(res, meta, clave):
    if clave is None:
        return "contraste"
    c = (res.get("cobertura") or {}).get(clave)
    o = (meta.get(clave) or {}).get("origen")
    if o:
        return f"ESIOS {o['esios'] * 100:.0f} % · REE {o['ree'] * 100:.0f} % · sin dato {o['sin'] * 100:.0f} %"
    return f"ESIOS {c * 100:.0f} %" if c is not None else "—"


def pag_fuentes(d, res, meta):
    from .pdf import C

    fig = d.diapositiva("Series y fuentes utilizadas", "Una fila por serie: identificador, quién la publica, cada cuánto, cuándo se publica, qué carácter tiene y "
                        "qué parte de la semana sale de cada origen. Las fuentes de contraste (OMIE, REData) no entran en los cálculos: los validan.",
                        "Latencia: cuándo está disponible respecto al día D de la energía. «Tiempo real» = telemedida y estimación; «liquidación provisional» = I3 de REE, "
                        "que se revisa después en liquidaciones posteriores. Todas las fuentes son públicas y gratuitas; ESIOS pide un token personal gratuito.")
    rows = [(textwrap.shorten(a, 34), textwrap.shorten(b, 40), c, g, l, k, _cob_txt(res, meta, ck), e) for a, b, c, g, l, k, ck, e in CATALOGO]
    _tabla(fig, C, ["Serie", "ID o endpoint", "Publicador", "Granul.", "Latencia", "Carácter", "Cobertura por origen", "Enlace"], rows,
           [0.05, 0.21, 0.405, 0.49, 0.555, 0.615, 0.715, 0.875], ["left"] * 8, 0.765, 0.0385, fs=7.2)
    d.guardar(fig)
    return True


# --------------------------------------------------------------------- página final
def pag_control(d, res):
    from .pdf import C

    qc = (res.get("qc") or {}).get("controles") or []
    if not qc:
        return False
    por = 17
    tot_ko = sum(not c["ok"] for c in qc)
    for i in range(0, len(qc), por):
        parte = f" ({i // por + 1}/{(len(qc) - 1) // por + 1})" if len(qc) > por else ""
        fig = d.diapositiva("Control de calidad de los datos" + parte,
                            f"Comprobaciones automáticas de esta ejecución: {len(qc) - tot_ko} {OK} y {tot_ko} {KO}. Ninguna detiene la publicación; las que fallan se "
                            f"señalan también junto a la cifra afectada. Coherencia = recálculo independiente de cifras del informe; fuentes = la misma magnitud en dos publicadores.",
                            "Fuentes de contraste: OMIE (marginalpdbc y marginalpibc, columna España; la 5 es Portugal), demanda.ree.es (tiempo real, 5 min) y REData. "
                            "Tolerancias en config.yml (validacion).")
        rows = [(c["grupo"], textwrap.shorten(c["nombre"], 70), c["valor_txt"], c["ref_txt"], c["tol_txt"], OK if c["ok"] else KO,
                 textwrap.shorten(c.get("nota") or "", 62)) for c in qc[i:i + por]]
        _tabla(fig, C, ["Grupo", "Control", "Valor", "Referencia", "Tolerancia", "Estado", "Nota"], rows,
               [0.05, 0.12, 0.47, 0.54, 0.62, 0.69, 0.725], ["left"] * 7, 0.76, 0.036, fs=7.4)
        d.guardar(fig)
    return True
