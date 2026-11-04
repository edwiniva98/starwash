import os
import logging
import json
import re
from datetime import datetime, timedelta
import httpx
from aiohttp import web
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN          = os.environ.get("BOT_TOKEN", "")
OWNER_ID           = int(os.environ.get("OWNER_ID", "0"))
ALLOWED_USERS      = {OWNER_ID, 8838219142}  # Edwin + papá
# IDs del celular del lavado — solo materiales, sin ver finanzas
# Agregar el ID real cuando esté lista la cuenta de Telegram del lavado
LAVADO_USERS       = set(int(x) for x in os.environ.get("LAVADO_USER_IDS", "").split(",") if x.strip())
CLAUDE_KEY         = os.environ.get("ANTHROPIC_API_KEY", "")
FIREBASE_PROJECT   = os.environ.get("FIREBASE_PROJECT_ID", "starwash-cortes")
FIRESTORE_URL      = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}/databases/(default)/documents"
ODOO_URL           = os.environ.get("ODOO_URL", "https://star-wash.odoo.com")
ODOO_DB            = os.environ.get("ODOO_DB", "star-wash")
ODOO_USER          = os.environ.get("ODOO_USER", "starwashtexcoco@hotmail.com")
ODOO_KEY           = os.environ.get("ODOO_KEY", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── FIREBASE ──────────────────────────────────────────────────────────────────
async def get_stock_clips():
    """Lee el stock actual de clips aromáticos desde config/clips en Firestore."""
    url = f"{FIRESTORE_URL}/config/clips"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        data = r.json()
    fields = data.get("fields", {})
    stock = fields.get("stock", {})
    if "integerValue" in stock:
        return int(stock["integerValue"])
    return None

# ── MATERIALES ────────────────────────────────────────────────────────────────
# Catálogo de materiales con alias para reconocimiento natural
MATERIALES = {
    "botas_25":        {"nombre": "Botas T25", "emoji": "🥾", "alias": ["bota 25","botas 25","talla 25"]},
    "botas_26":        {"nombre": "Botas T26", "emoji": "🥾", "alias": ["bota 26","botas 26","talla 26"]},
    "botas_27":        {"nombre": "Botas T27", "emoji": "🥾", "alias": ["bota 27","botas 27","talla 27"]},
    "botas_28":        {"nombre": "Botas T28", "emoji": "🥾", "alias": ["bota 28","botas 28","talla 28"]},
    "playeras_ch":     {"nombre": "Playeras Chica", "emoji": "👕", "alias": ["playera ch","playera chica","playeras ch","playeras chica","camiseta chica"]},
    "playeras_m":      {"nombre": "Playeras Mediana", "emoji": "👕", "alias": ["playera m","playera mediana","playeras m","playeras mediana","camiseta mediana"]},
    "playeras_g":      {"nombre": "Playeras Grande", "emoji": "👕", "alias": ["playera g","playera grande","playeras g","playeras grande","camiseta grande"]},
    "fregones":        {"nombre": "Fregones", "emoji": "🧹", "alias": ["fregon","fregón","trapeador","trapeadores","mopa","mopas"]},
    "escobas":         {"nombre": "Escobas", "emoji": "🧹", "alias": ["escoba"]},
    "palos_escoba":    {"nombre": "Palos de Escoba", "emoji": "🪵", "alias": ["palo escoba","palo de escoba","palos escoba"]},
    "recogedor":       {"nombre": "Recogedores", "emoji": "🧺", "alias": ["recogedor","recogedores"]},
    "jalador":         {"nombre": "Jaladores", "emoji": "🪣", "alias": ["jalador","jaladores","haladera"]},
    "mechudos_blancos":{"nombre": "Mechudos Blancos", "emoji": "🧽", "alias": ["mechudo blanco","mechudos blancos","mecha blanca","mechas blancas"]},
    "mechudos_color":  {"nombre": "Mechudos Color", "emoji": "🧽", "alias": ["mechudo color","mechudos color","mechudo de color","mechudos de color","mecha color"]},
    "cepillos_bano":   {"nombre": "Cepillos Baño", "emoji": "🪥", "alias": ["cepillo baño","cepillos baño","cepillo de baño","cepillos de baño","cepillo taza","cepillos taza","cepillo wc"]},
    "bomba_destapa":   {"nombre": "Bomba/Destapacaños", "emoji": "🔧", "alias": ["bomba","destapacaños","destapador","destapa"]},
    "microfibras":     {"nombre": "Bolsas Microfibra", "emoji": "🧣", "alias": ["microfibra","microfibras","bolsa microfibra","bolsas microfibra","paño microfibra"]},
    "botes_1l":        {"nombre": "Botes 1L", "emoji": "🧴", "alias": ["bote 1l","bote 1 l","bote grande","botes 1l","botes 1 l","atomizador 1l","atomizadores 1l"]},
    "botes_500ml":     {"nombre": "Botes 500ml", "emoji": "🧴", "alias": ["bote 500","bote 500ml","bote chico","botes 500","botes 500ml","atomizador 500","atomizadores 500ml"]},
    "gatillos":        {"nombre": "Gatillos", "emoji": "🔫", "alias": ["gatillo","gatillos","trigger","pistola spray"]},
    "jabon_roma_500":  {"nombre": "Jabón Roma 500gr", "emoji": "🧼", "alias": ["roma 500","jabon roma 500","jabón roma 500","roma grande"]},
    "jabon_roma_250":  {"nombre": "Jabón Roma 250gr", "emoji": "🧼", "alias": ["roma 250","jabon roma 250","jabón roma 250","roma chica","roma chico"]},
    "pinol_1l":        {"nombre": "Pinol 1L", "emoji": "🫙", "alias": ["pinol","piñol","pinol 1l","piñol 1l"]},
    "fabuloso_1l":     {"nombre": "Fabuloso 1L", "emoji": "🫙", "alias": ["fabuloso","fabuloso 1l"]},
    "cloralex_1l":     {"nombre": "Cloralex 1L", "emoji": "🫙", "alias": ["cloralex","cloro","cloralex 1l","cloro 1l"]},
    "papel_tork":      {"nombre": "Papel Baño Tork", "emoji": "🧻", "alias": ["papel tork","tork","papel baño","papel de baño","papel higienico","papel higiénico"]},
    "fibra_scotch":    {"nombre": "Fibra Scotch-Brite", "emoji": "🟩", "alias": ["fibra","scotch","scotch brite","scotch-brite","fibra verde","fibra scotch"]},
    "bolsas_1kg":      {"nombre": "Bolsas 1kg 60/90", "emoji": "🛍️", "alias": ["bolsa 1kg","bolsas 1kg","bolsa 60","bolsa 90","bolsas 60","bolsas 90","bolsa kilo","bolsas kilo"]},
    "sanitas":         {"nombre": "Sanitas", "emoji": "🧻", "alias": ["sanita","sanitas","papel sanitas","servilleta","servilletas"]},
    "despachador_jabon":{"nombre": "Despachador Jabón", "emoji": "🧴", "alias": ["despachador","despachador jabon","despachador jabón","dispenser","dispensador"]},
    "cubetas":         {"nombre": "Cubetas", "emoji": "🪣", "alias": ["cubeta","cubetas","balde","baldes"]},
    "jerga":           {"nombre": "Jerga", "emoji": "🧻", "alias": ["jerga","jergas","rollo jerga","rollos jerga"]},
    "jabon_tork":      {"nombre": "Jabón Manos Tork", "emoji": "🧴", "alias": ["jabon tork","jabón tork","jabon manos tork","jabón manos tork","tork manos","soap tork"]},
}

# Grupos con variantes — cuando el texto menciona el grupo genérico,
# el bot pregunta la variante específica con botones
VARIANTES = {
    "botas":    {"label": "¿Qué talla de botas?",    "opciones": ["botas_25","botas_26","botas_27","botas_28"]},
    "playeras": {"label": "¿Qué talla de playera?",  "opciones": ["playeras_ch","playeras_m","playeras_g"]},
    "botes":    {"label": "¿Qué tamaño de bote?",    "opciones": ["botes_1l","botes_500ml"]},
    "roma":     {"label": "¿Qué tamaño de Roma?",    "opciones": ["jabon_roma_500","jabon_roma_250"]},
}
# Alias genéricos que disparan selección de variante
ALIAS_VARIANTES = {
    "bota":    "botas", "botas": "botas",
    "playera": "playeras", "playeras": "playeras", "camiseta": "playeras",
    "bote":    "botes", "botes": "botes",
    "roma":    "roma", "jabon roma": "roma", "jabón roma": "roma",
}

# Piezas por caja para entrada rápida
PIEZAS_POR_CAJA = {
    "cloralex_1l":    12,
    "fabuloso_1l":    12,
    "papel_tork":      6,
    "jabon_roma_500": 20,
    "jabon_roma_250": 40,
    "fibra_scotch":   12,
    "bolsas_1kg":     12,
    "sanitas":        12,
}

DESTINOS = {
    "caja":    "Caja",
    "taller":  "Taller",
    "rines":   "Rines",
    "maquina": "Máquina",
    "islas":   "Islas",
    "isla1":   "Isla 1",
    "isla2":   "Isla 2",
    "isla3":   "Isla 3",
    "isla4":   "Isla 4",
    "isla5":   "Isla 5",
    "general": "General / Personal",
}

# Destinos que aparecen en los botones del lavado (islas colapsadas)
DESTINOS_BOTONES = [
    ("🏝️ Islas",    "islas"),
    ("🏪 Caja",     "caja"),
    ("🔧 Taller",   "taller"),
    ("⚙️ Máquina",  "maquina"),
    ("🔩 Rines",    "rines"),
    ("👤 General",  "general"),
]

RESPONSABLES = ["Eder", "Piña", "Edwin", "Luis", "Taller", "Lavado"]

# Almacén temporal de salidas pendientes de confirmar responsable
# { chat_id: { material_key, cantidad, destino, destinatario } }
_salidas_pendientes: dict = {}

# Almacén temporal de entradas pendientes (flujo por botones)
# { chat_id: { material_key, tipo } }  tipo = "piezas" | "cajas" | "cajas_y_piezas"
_entradas_pendientes: dict = {}

def normalizar_material(texto):
    """Intenta encontrar el key del material a partir de texto libre."""
    t = texto.lower().strip()
    for key, info in MATERIALES.items():
        if key in t or info["nombre"].lower() in t:
            return key
        for alias in info["alias"]:
            if alias in t:
                return key
    return None

def normalizar_destino(texto):
    t = texto.lower().strip()
    if any(p in t for p in ["caja","cobro"]): return "caja"
    if any(p in t for p in ["taller","mecanico","mecánico"]): return "taller"
    if any(p in t for p in ["rines"]): return "rines"
    if any(p in t for p in ["maquina","máquina"]): return "maquina"
    if any(p in t for p in ["isla 1","isla1"]): return "isla1"
    if any(p in t for p in ["isla 2","isla2"]): return "isla2"
    if any(p in t for p in ["isla 3","isla3"]): return "isla3"
    if any(p in t for p in ["isla 4","isla4"]): return "isla4"
    if any(p in t for p in ["isla 5","isla5"]): return "isla5"
    return "general"

async def get_stock_materiales():
    """Lee el stock actual de todos los materiales desde config/materiales."""
    url = f"{FIRESTORE_URL}/config/materiales"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        if r.status_code != 200:
            return {}
        data = r.json()
    fields = data.get("fields", {})
    stock = {}
    for key in MATERIALES:
        v = fields.get(key, {})
        stock[key] = int(v.get("integerValue", 0))
    return stock

async def set_stock_materiales(stock: dict):
    """Guarda el stock completo de materiales."""
    url = f"{FIRESTORE_URL}/config/materiales"
    fields = {k: {"integerValue": str(max(0, v))} for k, v in stock.items()}
    async with httpx.AsyncClient() as client:
        r = await client.patch(url, json={"fields": fields})
        return r.status_code == 200

async def registrar_movimiento_material(tipo, material_key, cantidad, destino, responsable, notas=""):
    """Guarda un movimiento (entrada/salida) en la colección materiales_movimientos."""
    import uuid
    mov_id = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(uuid.uuid4())[:6]
    url = f"{FIRESTORE_URL}/materiales_movimientos/{mov_id}"
    fields = {
        "tipo":        {"stringValue": tipo},          # "entrada" o "salida"
        "material":    {"stringValue": material_key},
        "cantidad":    {"integerValue": str(cantidad)},
        "destino":     {"stringValue": destino},
        "responsable": {"stringValue": responsable},
        "notas":       {"stringValue": notas},
        "timestamp":   {"stringValue": datetime.now().isoformat()},
        "fecha":       {"stringValue": datetime.now().strftime("%Y-%m-%d")},
    }
    async with httpx.AsyncClient() as client:
        await client.patch(url, json={"fields": fields})

async def get_movimientos_materiales(limit=20, fecha=None):
    """Obtiene movimientos recientes de materiales."""
    url = f"{FIRESTORE_URL}/materiales_movimientos"
    params = {"pageSize": limit, "orderBy": "timestamp desc"}
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)
        data = r.json()
    movs = []
    for doc in data.get("documents", []):
        f = doc.get("fields", {})
        mov = parse_firestore(f)
        mov["_id"] = doc["name"].split("/")[-1]
        if fecha is None or mov.get("fecha","") == fecha:
            movs.append(mov)
    return movs

async def get_cortes(limit=5, fecha=None):
    """Obtiene cortes de Firestore."""
    url = f"{FIRESTORE_URL}/cortes"
    params = {"pageSize": limit, "orderBy": "timestamp desc"}
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)
        data = r.json()

    cortes = []
    for doc in data.get("documents", []):
        fields = doc.get("fields", {})
        corte = parse_firestore(fields)
        corte["_id"] = doc["name"].split("/")[-1]
        if fecha:
            if fecha in corte.get("fecha", ""):
                cortes.append(corte)
        else:
            cortes.append(corte)
    return cortes

def parse_firestore(fields):
    """Convierte formato Firestore a dict normal."""
    result = {}
    for key, val in fields.items():
        if "stringValue" in val:
            result[key] = val["stringValue"]
        elif "integerValue" in val:
            result[key] = int(val["integerValue"])
        elif "doubleValue" in val:
            result[key] = float(val["doubleValue"])
        elif "booleanValue" in val:
            result[key] = val["booleanValue"]
        elif "mapValue" in val:
            result[key] = parse_firestore(val["mapValue"].get("fields", {}))
        elif "arrayValue" in val:
            items = val["arrayValue"].get("values", [])
            result[key] = [
                parse_firestore(i.get("mapValue", {}).get("fields", {}))
                if "mapValue" in i else list(i.values())[0]
                for i in items
            ]
        elif "timestampValue" in val:
            result[key] = val["timestampValue"]
    return result

# ── FORMAT ────────────────────────────────────────────────────────────────────
def fmt(n):
    try:
        return f"${float(n):,.2f}"
    except:
        return "$0.00"

def generar_resumen_firebase(corte):
    """Genera resumen desde datos de Firebase (formato nuevo corte_starwash.html)."""
    # Pagos Odoo
    p = corte.get("pagos", {})
    efe   = p.get("efe", 0)
    tar   = p.get("tar", 0)
    trans = p.get("trans", 0)
    total_cobrado = corte.get("total_cobrado", efe + tar + trans)

    # Caja física
    c = corte.get("caja", {})
    total_caja  = corte.get("total_caja", c.get("total", 0))
    diferencia  = corte.get("diferencia", total_cobrado - total_caja)
    total_gastos = corte.get("total_gastos", 0)

    # Cortesías
    cort = corte.get("cortesias", {})
    ct = cort.get("taller", 0)
    ca = cort.get("ayuntamiento", 0)
    cf = cort.get("familiar", 0)
    seg = cort.get("seguro", 0)
    total_cort = ct + ca + cf + seg

    # Ventas por paquete desde ventas_odoo
    vo = corte.get("ventas_odoo", {})
    # Suma todos excepto motos para autos pagados
    autos_pagados = sum(v for k, v in vo.items() if k != "motos" and isinstance(v, (int, float)))
    total_entraron = autos_pagados + total_cort

    # Lectura máquina desde paquetes_finales
    paq = corte.get("paquetes_finales", [])
    maq_total = sum(p.get("autos", 0) for p in paq if isinstance(p, dict))
    dif_maq = maq_total - (autos_pagados + total_cort)  # máquina vs pagados+cortesías

    # Turno
    turno_label = "🌙 Noche" if corte.get("turno") == "N" else "☀️ Día"

    # diferencia = total_cobrado - total_caja
    # >0 → cobrado > caja → faltan en caja | <0 → caja > cobrado → sobran en caja
    if abs(diferencia) < 1:
        estado_din = "✅ Cuadra"
    elif diferencia > 0:
        estado_din = f"❌ Faltan {fmt(diferencia)} en caja"
    else:
        estado_din = f"⚠️ Sobran {fmt(abs(diferencia))} en caja"
    estado_maq = "✅" if dif_maq == 0 else (f"⚠️ Faltan {dif_maq} por cobrar" if dif_maq > 0 else f"⚠️ Sobran {abs(dif_maq)} cobrados")

    msg  = f"⭐ *STAR WASH — CORTE*\n"
    msg += f"📅 {corte.get('fecha', '—')} {turno_label} | 🔖 {corte.get('sesion', '—')}\n"
    msg += f"👤 {corte.get('responsable', '—')}\n\n"

    msg += f"🚗 *VEHÍCULOS*\n"
    msg += f"• Autos pagados: *{autos_pagados}* | Cortesías: {total_cort} (T:{ct} A:{ca} F:{cf}) | Seguro: {seg}\n"
    msg += f"• *Total entraron: {total_entraron}* | Máquina: {maq_total} {estado_maq}\n\n"

    msg += f"💰 *VENTAS ODOO*\n"
    msg += f"• Efectivo: {fmt(efe)} | Tarjeta: {fmt(tar)} | Trans: {fmt(trans)}\n"
    msg += f"• *Total cobrado: {fmt(total_cobrado)}*\n\n"

    msg += f"🏦 *CONTROL DE CAJA*\n"
    msg += f"• Apertura: {fmt(c.get('apertura',0))}\n"
    msg += f"• Morralla: {fmt(c.get('morralla',0))} | Billetes: {fmt(c.get('billetes',0))} | Terminal: {fmt(c.get('terminal',0))}\n"
    msg += f"• *Total en caja: {fmt(total_caja)}*\n\n"

    msg += f"📊 *RESULTADO: {estado_din}*\n\n"

    gastos = corte.get("gastos", [])
    if gastos:
        msg += f"💸 *GASTOS: {fmt(total_gastos)}*\n"
        for g in gastos:
            if isinstance(g, dict) and g.get("concepto") and g.get("monto", 0) > 0:
                msg += f"• {g['concepto']}: {fmt(g['monto'])}\n"
        msg += "\n"

    notas = [n for n in corte.get("notas", []) if n and str(n).strip()]
    if notas:
        msg += f"📝 *NOTAS*\n"
        for i, n in enumerate(notas, 1):
            msg += f"{i}. {n}\n"

    return msg

# ── DETECCIÓN DE FECHA EN TEXTO ───────────────────────────────────────────────
def detectar_fecha(texto: str) -> str | None:
    """
    Detecta referencias de fecha en el texto del usuario.
    Devuelve fecha en formato YYYY-MM-DD o None.
    """
    hoy = datetime.now()
    texto_lower = texto.lower()

    # Palabras clave relativas
    if any(p in texto_lower for p in ["hoy", "este día", "este dia"]):
        return hoy.strftime("%Y-%m-%d")
    if any(p in texto_lower for p in ["ayer", "el día de ayer", "el dia de ayer"]):
        return (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
    if any(p in texto_lower for p in ["antier", "anteayer"]):
        return (hoy - timedelta(days=2)).strftime("%Y-%m-%d")

    # Días de la semana en español
    dias = {
        "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
        "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6
    }
    for nombre, num in dias.items():
        if nombre in texto_lower:
            dias_atras = (hoy.weekday() - num) % 7
            if dias_atras == 0:
                dias_atras = 7  # la semana pasada
            return (hoy - timedelta(days=dias_atras)).strftime("%Y-%m-%d")

    # Fecha explícita YYYY-MM-DD
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", texto)
    if m:
        return m.group(1)

    # Fecha DD/MM/YYYY o DD-MM-YYYY
    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", texto)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"

    return None

# ── CLAUDE ────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""Eres el asistente inteligente del *Autolavado Star Wash*, un negocio de lavado de autos en México.

Tu función es responder preguntas del dueño (Edwin) sobre los cortes del día: ventas, caja, diferencias, gastos, máquina, etc.

Fecha actual: {datetime.now().strftime("%Y-%m-%d")} (año {datetime.now().year})
IMPORTANTE: Cuando el usuario mencione fechas sin año (ej: "octubre", "el 15"), asume siempre el año {datetime.now().year} a menos que especifique otro.

Contexto del negocio (precios actualizados desde octubre 2026):
- Básicos (Prog 1-3): Auto Básico $130, Cam. Chica/Med. Básico $150, Pick-Up/SUV Grande Básico $170
- Plus (Prog 4-6): Auto Plus $160, Cam. Chica/Med. Plus $180, Pick-Up/SUV Grande Plus $200
- Pro (Prog 4T-6T): Auto Pro $190, Cam. Chica/Med. Pro $210, Pick-Up/SUV Grande Pro $230
- Express: X1 Express $100, X4 Express Plus $130
- Moto: $70 | Lavado a Mano: $30 | Lavado a Mano + Cera: $40 | Fiscalía: $80
- Adicionales: + Cera Plus $30, + Cera y Tapetes Pro $60, Lavado de Motor $100, Lavado de Tapetes $50
- Cortesías: C1 Taller, C1 Ayto, C4 Familiar, C4 Auto Plus (cortesía premium)
- Seguros: S1 Seguro Básico 24h, S4 Seguro Plus/Pro 48h
- La "máquina" es el contador automático de vehículos que pasan por el túnel de lavado
- "Corte de caja" = comparar lo que dice Odoo (POS) vs lo que hay en el cajón
- "Diferencia de máquina" = autos que contó la máquina vs autos esperados (pagados + cortesías + seguro - mano - regresos)
- Cortesías: Taller = autos del taller Car Center, Ayuntamiento = vehículos municipales, Familiar = familiares del dueño
- Seguro de lluvia = autos que entran gratis por garantía de lluvia
- "Morralla" = monedas/cambio en caja
- El corte es diario, una sesión por día normalmente

Reglas de respuesta:
- Responde siempre en español, de forma clara y directa
- Usa emojis con moderación para hacer el mensaje legible
- Si te preguntan comparaciones entre fechas, calcula tú mismo los totales
- Si no hay datos para responder, dilo claramente
- Para montos usa formato $X,XXX.XX
- Sé conciso: máximo 5-6 líneas salvo que el detalle sea necesario
- SIEMPRE incluye los billetes en caja (campo caja.billetes) en cualquier resumen o corte completo que presentes. Ponlo así: 💵 Billetes: $X,XXX.XX
- Cuando te pidan "lectura de máquina", "lecturas", "inicial y final" o similar, SIEMPRE muestra la tabla por paquete con este formato exacto (sin tabla markdown, solo texto):
  Paq 1: 12450 → 12478 | 28 autos | $2,240
  Paq 2: 8930 → 8952 | 22 autos | $2,200
  (usa los datos del campo lecturas_maquina del contexto)"""

async def consultar_claude(pregunta: str, cortes: list) -> str:
    """Usa Claude para responder preguntas sobre los cortes con contexto completo."""

    # Construir contexto rico con todo el detalle disponible
    contexto_cortes = []
    for c in cortes:
        # Campos del formato nuevo (corte_starwash.html)
        vo   = c.get("ventas_odoo", {})    # t1,t2,...t6,t4t,...,x1,x4,fiscalia,fiscalia4,motos
        ao   = c.get("adics_odoo", {})     # cera_plus, cera_tapetes, tapetes, motor, mano, mano_cera, mano_cera_tap
        p    = c.get("pagos", {})          # efe, tar, trans
        caja = c.get("caja", {})           # morralla, billetes, terminal, apertura, fondo
        cort = c.get("cortesias", {})      # taller, ayuntamiento, familiar, seguro

        # Nombres legibles por paquete
        NOMBRES = {
            "t1":"Auto Básico","t2":"Camioneta Básico","t3":"Pick-Up Básico",
            "t4":"Auto Plus","t4t":"Auto Pro","t5":"Camioneta Plus","t5t":"Camioneta Pro",
            "t6":"Pick-Up Plus","t6t":"Pick-Up Pro","x1":"Express","x4":"Express Plus",
            "fiscalia":"Fiscalía","fiscalia4":"Fiscalía Plus","motos":"Motos"
        }
        NOMBRES_ADIC = {
            "cera_plus":"+ Cera Plus","cera_tapetes":"+ Cera y Tapetes Pro",
            "tapetes":"Lavado Tapetes","motor":"Lavado Motor",
            "mano":"M1. Lavado a Mano","mano_cera":"M2. Mano + Cera","mano_cera_tap":"M3. Mano + Cera + Tapetes"
        }

        autos_pagados = sum(v for k, v in vo.items() if k != "motos" and isinstance(v, (int, float)))
        total_cort = sum([cort.get(k,0) for k in ["taller","ayuntamiento","familiar","seguro"]])

        entrada = {
            "fecha": c.get("fecha"),
            "turno": c.get("turno"),
            "sesion": c.get("sesion"),
            "responsable": c.get("responsable"),
            "vehiculos": {
                "ventas_por_paquete": {NOMBRES.get(k,k): int(v) for k,v in vo.items() if v},
                "total_pagados": autos_pagados,
                "cortesias": {
                    "taller": cort.get("taller",0),
                    "ayuntamiento": cort.get("ayuntamiento",0),
                    "familiar": cort.get("familiar",0),
                    "seguro": cort.get("seguro",0),
                    "total": total_cort,
                },
                "total_entraron": autos_pagados + total_cort,
                "maquina_total": c.get("maquina_total", 0),
            },
            "adicionales": {NOMBRES_ADIC.get(k,k): int(v) for k,v in ao.items() if v},
            "pagos": {
                "efectivo": p.get("efe", 0),
                "tarjeta": p.get("tar", 0),
                "transferencia": p.get("trans", 0),
                "total_cobrado": c.get("total_cobrado", 0),
            },
            "caja": {
                "apertura": caja.get("apertura", 0),
                "morralla": caja.get("morralla", 0),
                "billetes": caja.get("billetes", 0),
                "terminal": caja.get("terminal", 0),
                "total_caja": c.get("total_caja", 0),
                "diferencia_caja": c.get("diferencia", 0),
            },
            "gastos": {
                "total": c.get("total_gastos", 0),
                "detalle": [
                    {"concepto": g.get("c",""), "monto": g.get("m",0)}
                    for g in c.get("gastos", [])
                    if isinstance(g, dict) and g.get("c") and g.get("m", 0) > 0
                ],
            },
        }

        # Lecturas iniciales y finales de máquina por paquete
        paquetes = c.get("paquetes_finales", [])
        if paquetes:
            entrada["lecturas_maquina"] = [
                {
                    "programa": p.get("prog", i + 1),
                    "nombre": p.get("nombre", f"Prog {i+1}"),
                    "inicio": p.get("inicio", 0),
                    "final": p.get("final", 0),
                    "autos": p.get("autos", 0),
                }
                for i, p in enumerate(paquetes)
                if isinstance(p, dict)
            ]

        notas = [n for n in c.get("notas", []) if n and str(n).strip()]
        if notas:
            entrada["notas"] = notas

        contexto_cortes.append(entrada)

    mensaje_usuario = f"""Datos de los últimos cortes de Star Wash:
{json.dumps(contexto_cortes, ensure_ascii=False, indent=2)}

Pregunta de Edwin: {pregunta}"""

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 800,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": mensaje_usuario}]
            },
            timeout=30
        )
        data = r.json()

    if "content" not in data:
        logger.error(f"Claude error: {data}")
        return "❌ No pude consultar los datos en este momento."

    return data["content"][0]["text"]

# ── HANDLERS ──────────────────────────────────────────────────────────────────
async def check_allowed(update: Update) -> bool:
    uid = update.effective_user.id
    if OWNER_ID != 0 and uid not in ALLOWED_USERS and uid not in LAVADO_USERS:
        await update.message.reply_text("⛔ No tienes acceso a este bot.")
        return False
    return True

def is_lavado_only(update: Update) -> bool:
    """True si el usuario es del celular del lavado (solo materiales, sin finanzas)."""
    uid = update.effective_user.id
    return uid in LAVADO_USERS and uid not in ALLOWED_USERS

async def check_admin(update: Update) -> bool:
    """Solo Edwin y usuarios con acceso completo."""
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        await update.message.reply_text("⛔ Esta función es solo para administradores.")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    # Menú diferente para celular del lavado
    if is_lavado_only(update):
        teclado = ReplyKeyboardMarkup(
            [["📦 Stock materiales"],
             ["➕ Entrada material", "➖ Sacar material"],
             ["📋 Movimientos hoy"]],
            resize_keyboard=True, is_persistent=True
        )
        await update.message.reply_text(
            "🧰 *STAR WASH — MATERIALES*\n\n"
            "Registra entradas y salidas de bodega.\n\n"
            "Para sacar: escribe por ejemplo:\n"
            "_sacar 2 playeras para caja_\n"
            "_sacar 1 escoba para taller_",
            parse_mode="Markdown",
            reply_markup=teclado
        )
        return
    teclado = ReplyKeyboardMarkup(
        [["📊 Cómo vamos hoy", "🏆 Récords"],
         ["📋 Último corte", "📅 Historial"],
         ["⚖️ Comparar corte", "📥 Exportar"]],
        resize_keyboard=True,
        is_persistent=True
    )
    await update.message.reply_text(
        "⚡ *STAR WASH — PANEL*\n\n"
        "Elige una opción o pregúntame normalmente.\n"
        "Ejemplos: '¿cómo estuvo ayer?', '¿cuál fue el mejor sábado?' o '¿cuánto vendimos este mes?'",
        parse_mode="Markdown",
        reply_markup=teclado
    )

# ── COMANDOS MATERIALES ────────────────────────────────────────────────────────
async def cmd_stock_mat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el stock actual de todos los materiales."""
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Revisando stock...")
    stock = await get_stock_materiales()
    if not stock:
        await msg.edit_text("⚠️ No hay stock registrado aún. Usa /entrada_mat para agregar material.")
        return
    lineas = []
    for key, info in MATERIALES.items():
        cant = stock.get(key, 0)
        alerta = " ⚠️" if cant <= 2 else ""
        lineas.append(f"{info['emoji']} *{info['nombre']}:* {cant}{alerta}")
    texto = "🧰 *Stock de Materiales*\n\n" + "\n".join(lineas)
    await msg.edit_text(texto, parse_mode="Markdown")

async def cmd_sacar_mat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra una salida de material. Uso: /sacar 2 playeras para caja"""
    if not await check_allowed(update): return
    args_txt = " ".join(context.args) if context.args else ""
    await _procesar_salida(update, args_txt)

async def cmd_entrada_mat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra una entrada de material. Uso: /entrada 10 escobas"""
    if not await check_admin(update): return
    args_txt = " ".join(context.args) if context.args else ""
    await _procesar_entrada(update, args_txt)

def extraer_destinatario(texto: str) -> str:
    """Extrae el nombre de la persona o área a quien se le entregó el material.
    Busca patrones como: 'para X', 'a X', 'para la isla X', 'al taller', etc.
    Devuelve el destinatario como string, o "" si no se encontró.
    """
    t = texto.lower()
    # Destinos especiales conocidos
    if any(p in t for p in ["para caja","a caja","en caja","la caja"]): return "Caja"
    if any(p in t for p in ["para taller","al taller","en taller","el taller"]): return "Taller"
    if any(p in t for p in ["para rines","al rines","en rines","los rines"]): return "Rines"
    if any(p in t for p in ["para maquina","a maquina","en maquina","la maquina","máquina","para máquina"]): return "Máquina"
    if any(p in t for p in ["isla 1","islas 1","para isla1","a isla1"]): return "Isla 1"
    if any(p in t for p in ["isla 2","islas 2","para isla2","a isla2"]): return "Isla 2"
    if any(p in t for p in ["isla 3","islas 3","para isla3","a isla3"]): return "Isla 3"
    if any(p in t for p in ["isla 4","islas 4","para isla4","a isla4"]): return "Isla 4"
    if any(p in t for p in ["isla 5","islas 5","para isla5","a isla5"]): return "Isla 5"
    if any(p in t for p in ["general","todos","personal"]): return "General"
    # Patrón: "para <nombre>" o "a <nombre>"
    m = re.search(r'(?:para|a la|al|a)\s+([A-Za-záéíóúüñÁÉÍÓÚÜÑ]{3,}(?:\s+[A-Za-záéíóúüñÁÉÍÓÚÜÑ]{2,})?)', texto, re.IGNORECASE)
    if m:
        candidato = m.group(1).strip()
        # Filtrar palabras que no son nombres
        no_nombres = {"caja","taller","bodega","isla","general","lavado","encargado","todos"}
        if candidato.lower() not in no_nombres:
            return candidato.title()
    return ""

def detectar_grupo_variante(texto: str):
    """Detecta si el texto menciona un grupo genérico (botas, playeras, botes, roma).
    Devuelve el key del grupo o None."""
    t = texto.lower()
    for alias, grupo in ALIAS_VARIANTES.items():
        if alias in t:
            return grupo
    return None

async def _procesar_salida(update: Update, texto: str):
    """Parsea y ejecuta una salida de material.
    Detecta cantidad, material, destino/área y nombre de quien lo recibe.
    Si el material tiene variantes (tallas/tamaños), pregunta con botones.
    Ejemplos: 'se dieron 2 playeras a Juan', 'se agarró 1 gatillo para isla 3'
    """
    nums = re.findall(r'\d+', texto)
    cantidad = int(nums[0]) if nums else 1
    material_key = normalizar_material(texto)
    destino = normalizar_destino(texto)
    destinatario = extraer_destinatario(texto)
    chat_id = update.effective_chat.id

    # Si el material es genérico y tiene variantes, preguntar talla/tamaño
    grupo = detectar_grupo_variante(texto) if not material_key else None
    if not material_key and grupo and grupo in VARIANTES:
        var = VARIANTES[grupo]
        # Guardar datos parciales pendientes de variante
        _salidas_pendientes[chat_id] = {
            "material_key": None,
            "grupo": grupo,
            "cantidad": cantidad,
            "destino": destino,
            "destinatario": destinatario,
            "esperando": "variante",
        }
        botones = [[InlineKeyboardButton(MATERIALES[k]["nombre"], callback_data=f"var:{k}")]
                   for k in var["opciones"]]
        await update.message.reply_text(
            var["label"],
            reply_markup=InlineKeyboardMarkup(botones)
        )
        return

    if not material_key:
        lista = "\n".join([f"  • {info['nombre']}" for info in MATERIALES.values()])
        await update.message.reply_text(
            f"❓ No entendí el material. Escribe por ejemplo:\n"
            f"_se dieron 2 playeras a Juan_\n"
            f"_se agarró 1 gatillo para isla 3_\n"
            f"_sacar 2 fregones para taller_\n\n"
            f"Materiales disponibles:\n{lista}",
            parse_mode="Markdown"
        )
        return

    stock = await get_stock_materiales()
    actual = stock.get(material_key, 0)
    if actual < cantidad:
        info = MATERIALES[material_key]
        await update.message.reply_text(
            f"⚠️ Stock insuficiente.\n"
            f"{info['emoji']} *{info['nombre']}* disponibles: *{actual}*\n"
            f"Solicitados: {cantidad}",
            parse_mode="Markdown"
        )
        return

    # Guardar datos pendientes y pedir responsable con botones
    chat_id = update.effective_chat.id
    _salidas_pendientes[chat_id] = {
        "material_key": material_key,
        "cantidad": cantidad,
        "destino": destino,
        "destinatario": destinatario,
        "stock_actual": actual,
    }

    info = MATERIALES[material_key]
    destino_txt = destinatario if destinatario else DESTINOS.get(destino, destino)

    # Botones inline con los responsables
    botones = []
    fila = []
    for i, nombre in enumerate(RESPONSABLES):
        fila.append(InlineKeyboardButton(nombre, callback_data=f"resp:{nombre}"))
        if len(fila) == 3:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)

    await update.message.reply_text(
        f"📦 *{info['emoji']} {info['nombre']}* ×{cantidad} → *{destino_txt}*\n\n"
        f"¿Quién registra la salida?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botones)
    )

async def callback_responsable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja botones inline: entradas por botón (ent_mat/ent_tipo), variantes y responsables."""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    # ── Responsable para entrada (lavado) ────────────────────────────────────
    if query.data.startswith("ent_resp:"):
        responsable = query.data.split(":", 1)[1]
        context.user_data["lavado_responsable"] = responsable
        await _mostrar_menu_materiales_entrada(query, context, edit=True)
        return

    # ── Responsable para salida (lavado) ─────────────────────────────────────
    if query.data.startswith("sal_resp:"):
        responsable = query.data.split(":", 1)[1]
        context.user_data["lavado_responsable"] = responsable
        await _mostrar_menu_materiales_salida(query, context, edit=True)
        return

    # ── Material de salida (individual) ──────────────────────────────────────
    if query.data.startswith("sal_mat:"):
        material_key = query.data.split(":", 1)[1]
        info = MATERIALES.get(material_key)
        if not info:
            await query.edit_message_text("⚠️ Material no encontrado.")
            return
        # Preguntar destino
        botones = []
        fila = []
        for label, dkey in DESTINOS_BOTONES:
            fila.append(InlineKeyboardButton(label, callback_data=f"sal_dest:{material_key}:{dkey}"))
            if len(fila) == 2:
                botones.append(fila)
                fila = []
        if fila:
            botones.append(fila)
        await query.edit_message_text(
            f"{info['emoji']} *{info['nombre']}*\n\n¿Para dónde?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botones)
        )
        return

    # ── Submenú de grupo para salida ─────────────────────────────────────────
    if query.data.startswith("sal_mat_grp:"):
        gkey = query.data.split(":", 1)[1]
        if gkey == "back":
            await _mostrar_menu_materiales_salida(query, context, edit=True)
            return
        grupo = GRUPOS_ENTRADA.get(gkey)
        if not grupo:
            await query.edit_message_text("⚠️ Grupo no encontrado.")
            return
        botones = []
        for key in grupo["keys"]:
            info = MATERIALES[key]
            botones.append([InlineKeyboardButton(f"{info['emoji']} {info['nombre']}", callback_data=f"sal_mat:{key}")])
        botones.append([InlineKeyboardButton("⬅️ Regresar", callback_data="sal_mat_grp:back")])
        await query.edit_message_text(
            f"{grupo['label']} — ¿cuál?",
            reply_markup=InlineKeyboardMarkup(botones)
        )
        return

    # ── Destino de salida → pedir cantidad ───────────────────────────────────
    if query.data.startswith("sal_dest:"):
        _, material_key, destino = query.data.split(":", 2)
        info = MATERIALES.get(material_key)
        if not info:
            await query.edit_message_text("⚠️ Material no encontrado.")
            return
        _salidas_pendientes[chat_id] = {"material_key": material_key, "destino": destino, "esperando": "cantidad_lavado"}
        destino_txt = DESTINOS.get(destino, destino)
        await query.edit_message_text(
            f"{info['emoji']} *{info['nombre']}* → {destino_txt}\n\n¿Cuántos?",
            parse_mode="Markdown"
        )
        return

    # ── Submenú de grupo (botas/playeras/botes/roma) ─────────────────────────
    if query.data.startswith("ent_grp:"):
        gkey = query.data.split(":", 1)[1]
        GRUPOS_ENTRADA = {
            "botas":    {"label": "🥾 Botas",     "keys": ["botas_25","botas_26","botas_27","botas_28"]},
            "playeras": {"label": "👕 Playeras",   "keys": ["playeras_ch","playeras_m","playeras_g"]},
            "botes":    {"label": "🧴 Botes",      "keys": ["botes_1l","botes_500ml"]},
            "roma":     {"label": "🧼 Jabón Roma", "keys": ["jabon_roma_500","jabon_roma_250"]},
        }
        # Botón regresar → volver al menú principal de materiales
        if gkey == "back":
            keys_en_grupo = {k for g in GRUPOS_ENTRADA.values() for k in g["keys"]}
            botones = []
            fila = []
            for gk, gi in GRUPOS_ENTRADA.items():
                fila.append(InlineKeyboardButton(gi["label"], callback_data=f"ent_grp:{gk}"))
                if len(fila) == 2:
                    botones.append(fila)
                    fila = []
            if fila:
                botones.append(fila)
                fila = []
            for key, info in MATERIALES.items():
                if key in keys_en_grupo:
                    continue
                fila.append(InlineKeyboardButton(f"{info['emoji']} {info['nombre']}", callback_data=f"ent_mat:{key}"))
                if len(fila) == 2:
                    botones.append(fila)
                    fila = []
            if fila:
                botones.append(fila)
            await query.edit_message_text("¿Qué material entró?", reply_markup=InlineKeyboardMarkup(botones))
            return

        grupo = GRUPOS_ENTRADA.get(gkey)
        if not grupo:
            await query.edit_message_text("⚠️ Grupo no encontrado.")
            return
        botones = []
        for key in grupo["keys"]:
            info = MATERIALES[key]
            botones.append([InlineKeyboardButton(f"{info['emoji']} {info['nombre']}", callback_data=f"ent_mat:{key}")])
        botones.append([InlineKeyboardButton("⬅️ Regresar", callback_data="ent_grp:back")])
        await query.edit_message_text(
            f"{grupo['label']} — ¿cuál?",
            reply_markup=InlineKeyboardMarkup(botones)
        )
        return

    # ── Selección de material para entrada (lavado) ───────────────────────────
    if query.data.startswith("ent_mat:"):
        material_key = query.data.split(":", 1)[1]
        info = MATERIALES.get(material_key)
        if not info:
            await query.edit_message_text("⚠️ Material no encontrado.")
            return
        # Si el material tiene cajas definidas, preguntar tipo
        if material_key in PIEZAS_POR_CAJA:
            pzs = PIEZAS_POR_CAJA[material_key]
            botones = [
                [InlineKeyboardButton("🔢 Piezas sueltas", callback_data=f"ent_tipo:{material_key}:piezas")],
                [InlineKeyboardButton(f"📦 Cajas (×{pzs} c/u)", callback_data=f"ent_tipo:{material_key}:cajas")],
                [InlineKeyboardButton(f"📦+🔢 Cajas y piezas", callback_data=f"ent_tipo:{material_key}:cajas_y_piezas")],
            ]
            await query.edit_message_text(
                f"{info['emoji']} *{info['nombre']}*\n\n¿Cómo entró?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botones)
            )
        else:
            # Sin cajas: pedir cantidad directamente
            _entradas_pendientes[chat_id] = {"material_key": material_key, "tipo": "piezas"}
            await query.edit_message_text(
                f"{info['emoji']} *{info['nombre']}*\n\n¿Cuántas piezas entraron? Escribe el número:",
                parse_mode="Markdown"
            )
        return

    # ── Selección de tipo (piezas/cajas/cajas_y_piezas) ──────────────────────
    if query.data.startswith("ent_tipo:"):
        _, material_key, tipo = query.data.split(":", 2)
        info = MATERIALES.get(material_key)
        if not info:
            await query.edit_message_text("⚠️ Material no encontrado.")
            return
        _entradas_pendientes[chat_id] = {"material_key": material_key, "tipo": tipo}
        pzs = PIEZAS_POR_CAJA.get(material_key, 1)
        if tipo == "piezas":
            prompt = f"{info['emoji']} *{info['nombre']}*\n\n¿Cuántas piezas? Escribe el número:"
        elif tipo == "cajas":
            prompt = f"{info['emoji']} *{info['nombre']}*\n\n¿Cuántas cajas? (cada caja = {pzs} pzs)\nEscribe el número:"
        else:
            prompt = f"{info['emoji']} *{info['nombre']}*\n\n¿Cuántas cajas y piezas sueltas?\nEscribe así: _3 1_ (3 cajas y 1 pieza suelta)\nO solo: _3_ si no hay sueltas"
        await query.edit_message_text(prompt, parse_mode="Markdown")
        return

    # ── Selección de variante (talla/tamaño) ──────────────────────────────────
    if query.data.startswith("var:"):
        material_key = query.data.split(":", 1)[1]
        datos = _salidas_pendientes.get(chat_id, {})
        if not datos or datos.get("esperando") != "variante":
            await query.edit_message_text("⚠️ No hay salida pendiente. Intenta de nuevo.")
            return

        # Actualizar con la variante elegida y pedir responsable
        datos["material_key"] = material_key
        datos["esperando"] = "responsable"
        _salidas_pendientes[chat_id] = datos

        info = MATERIALES[material_key]
        destinatario = datos.get("destinatario", "")
        destino = datos.get("destino", "general")
        destino_txt = destinatario if destinatario else DESTINOS.get(destino, destino)

        botones = []
        fila = []
        for i, nombre in enumerate(RESPONSABLES):
            fila.append(InlineKeyboardButton(nombre, callback_data=f"resp:{nombre}"))
            if len(fila) == 3:
                botones.append(fila)
                fila = []
        if fila:
            botones.append(fila)

        await query.edit_message_text(
            f"📦 *{info['emoji']} {info['nombre']}* ×{datos['cantidad']} → *{destino_txt}*\n\n"
            f"¿Quién registra la salida?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(botones)
        )
        return

    # ── Selección de responsable ───────────────────────────────────────────────
    if not query.data.startswith("resp:"):
        return

    responsable = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id
    datos = _salidas_pendientes.pop(chat_id, None)

    if not datos:
        await query.edit_message_text("⚠️ No hay salida pendiente. Intenta de nuevo.")
        return

    material_key = datos["material_key"]
    cantidad     = datos["cantidad"]
    destino      = datos["destino"]
    destinatario = datos["destinatario"]
    stock_actual = datos["stock_actual"]

    stock = await get_stock_materiales()
    # Re-verificar stock (pudo cambiar)
    actual = stock.get(material_key, 0)
    if actual < cantidad:
        info = MATERIALES[material_key]
        await query.edit_message_text(
            f"⚠️ Stock insuficiente.\n"
            f"{info['emoji']} *{info['nombre']}* disponibles: *{actual}*",
            parse_mode="Markdown"
        )
        return

    stock[material_key] = actual - cantidad
    await set_stock_materiales(stock)
    notas = f"para {destinatario}" if destinatario else ""
    await registrar_movimiento_material("salida", material_key, cantidad, destino, responsable, notas=notas)

    info = MATERIALES[material_key]
    destino_txt = destinatario if destinatario else DESTINOS.get(destino, destino)
    nuevo = stock[material_key]
    alerta = f"\n⚠️ _Quedan solo {nuevo}, considera reabastecer._" if nuevo <= 2 else ""

    await query.edit_message_text(
        f"✅ *Salida registrada*\n\n"
        f"{info['emoji']} {info['nombre']}: -{cantidad} → *{destino_txt}*\n"
        f"👤 Registró: *{responsable}*\n"
        f"📦 Stock restante: *{nuevo}*{alerta}",
        parse_mode="Markdown"
    )

async def _procesar_entrada(update: Update, texto: str):
    """Parsea y ejecuta una entrada de material.
    Soporta piezas directas o cajas: 'entrada 2 cajas cloro' → 2×12 = 24 piezas.
    """
    texto_lower = texto.lower()
    nums = re.findall(r'\d+', texto)
    material_key = normalizar_material(texto)
    responsable = update.effective_user.first_name or "Edwin"

    # Detectar si es entrada mixta: "X cajas y Y piezas" (ej: "fabuloso 3 cajas y 1 pieza")
    es_caja = any(p in texto_lower for p in ["caja","cajas","box"])
    tiene_pieza_extra = bool(re.search(r'\d+\s*(?:pieza|piezas|pz|pzs|unidad|unidades)', texto_lower))

    if es_caja and material_key and material_key in PIEZAS_POR_CAJA:
        pzs = PIEZAS_POR_CAJA[material_key]
        cajas_raw = int(nums[0]) if nums else 1
        cantidad = cajas_raw * pzs
        nota_caja = f"({cajas_raw} caja{'s' if cajas_raw > 1 else ''} × {pzs} pzs"
        # Sumar piezas sueltas adicionales si las hay (ej: "3 cajas y 1 pieza")
        m_extra = re.search(r'[yY]\s+(\d+)\s*(?:pieza|piezas|pz|pzs|unidad|unidades)', texto_lower)
        if m_extra:
            extra = int(m_extra.group(1))
            cantidad += extra
            nota_caja += f" + {extra} suelta{'s' if extra > 1 else ''}"
        nota_caja += ")"
        cantidad_raw = cajas_raw
    else:
        cantidad_raw = int(nums[0]) if nums else 1
        cantidad = cantidad_raw
        nota_caja = ""

    if not material_key:
        lista = "\n".join([f"  • {info['nombre']}" for info in MATERIALES.values()])
        await update.message.reply_text(
            f"❓ No entendí el material. Escribe por ejemplo:\n"
            f"_entrada 10 playeras_\n"
            f"_entrada 2 cajas cloro_\n\n"
            f"Materiales:\n{lista}",
            parse_mode="Markdown"
        )
        return

    stock = await get_stock_materiales()
    stock[material_key] = stock.get(material_key, 0) + cantidad
    await set_stock_materiales(stock)
    await registrar_movimiento_material("entrada", material_key, cantidad, "bodega", responsable,
                                        notas=nota_caja)

    info = MATERIALES[material_key]
    detalle = f" {nota_caja}" if nota_caja else ""
    await update.message.reply_text(
        f"✅ *Entrada registrada*\n\n"
        f"{info['emoji']} {info['nombre']}: +{cantidad}{detalle}\n"
        f"📦 Stock actual: *{stock[material_key]}*",
        parse_mode="Markdown"
    )

async def cmd_movimientos_mat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra movimientos de materiales de hoy."""
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Cargando movimientos...")
    hoy = datetime.now().strftime("%Y-%m-%d")
    movs = await get_movimientos_materiales(limit=50, fecha=hoy)
    if not movs:
        await msg.edit_text("📋 Sin movimientos de materiales hoy.")
        return
    lineas = []
    for m in movs[:20]:
        mat_key = m.get("material","")
        mat_info = MATERIALES.get(mat_key, {"nombre": mat_key, "emoji": "📦"})
        tipo = "➕" if m.get("tipo") == "entrada" else "➖"
        cant = m.get("cantidad", 0)
        dest = DESTINOS.get(m.get("destino",""), m.get("destino",""))
        resp = m.get("responsable","")
        hora = m.get("timestamp","")[:16].replace("T"," ") if m.get("timestamp") else ""
        lineas.append(f"{tipo} {mat_info['emoji']} *{mat_info['nombre']}* ×{cant} → {dest} ({resp}) {hora}")
    await msg.edit_text(
        f"📋 *Movimientos hoy — {hoy}*\n\n" + "\n".join(lineas),
        parse_mode="Markdown"
    )

async def cmd_hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Revisando cómo va Star Wash hoy...")
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        historial = await get_historial_firestore(limite=1000)
        actual = next((d for d in historial if d.get("fecha") == hoy), None)
        cortes = await get_cortes(limit=30, fecha=hoy)

        # El corte del día suele tener la información más completa.
        if cortes:
            c = cortes[0]
            v, t, p, m, o = c.get("ventas",{}), c.get("totales",{}), c.get("pagos",{}), c.get("maquina",{}), c.get("otros",{})
            veh = sum(int(v.get(k,0) or 0) for k in ["autos","camionetas","pickups","express","fiscalia"])
            total = float(t.get("total_tickets",0) or 0)
            ticket = total / veh if veh else 0
            texto = (f"⚡ *STAR WASH — HOY*\n📅 {hoy}\n\n"
                     f"🚗 Vehículos pagados: *{veh}*\n"
                     f"💰 Venta: *{fmt(total)}*\n"
                     f"🎟 Ticket promedio: *{fmt(ticket)}*\n"
                     f"💵 Efectivo: {fmt(p.get('efectivo',0))} | 💳 Tarjeta: {fmt(p.get('tarjeta',0))}\n"
                     f"🧾 Máquina: {m.get('total_vendidos',0)}")
        elif actual:
            veh = int(actual.get("vehiculos_pagados",0) or actual.get("num_tickets",0) or 0)
            total = float(actual.get("total",0) or 0)
            ticket = float(actual.get("ticket_promedio",0) or (total/veh if veh else 0))
            texto = (f"⚡ *STAR WASH — HOY*\n📅 {hoy}\n\n"
                     f"🚗 Vehículos: *{veh}*\n💰 Venta: *{fmt(total)}*\n🎟 Ticket promedio: *{fmt(ticket)}*")
        else:
            await msg.edit_text("Todavía no tengo datos guardados de hoy. Si el día sigue abierto, prueba más tarde o sincroniza Odoo.")
            return

        # Comparación simple contra el mismo día de la semana anterior, si existe.
        anterior_fecha = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        anterior = next((d for d in historial if d.get("fecha") == anterior_fecha), None)
        if anterior and float(anterior.get("total",0) or 0) > 0:
            ant_total = float(anterior.get("total",0) or 0)
            cambio = ((total-ant_total)/ant_total)*100
            signo = "+" if cambio >= 0 else ""
            texto += f"\n\n📈 Vs. hace 7 días: *{signo}{cambio:.1f}%* en venta ({fmt(ant_total)})"
        await msg.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error dashboard hoy: {e}")
        await msg.edit_text("❌ No pude armar el resumen de hoy en este momento.")

async def cmd_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Buscando récords...")
    try:
        historial = await get_historial_firestore(limite=1000)
        historial = [d for d in historial if d.get("fecha") and float(d.get("total",0) or 0) > 0]
        if not historial:
            await msg.edit_text("Aún no hay historial suficiente para calcular récords.")
            return
        mejor_venta = max(historial, key=lambda d: float(d.get("total",0) or 0))
        con_veh = [d for d in historial if int(d.get("vehiculos_pagados",0) or 0) > 0]
        texto = ("🏆 *RÉCORDS STAR WASH*\n\n"
                 f"💰 Mayor venta: *{fmt(mejor_venta['total'])}*\n📅 {mejor_venta['fecha_legible']}\n")
        if con_veh:
            mejor_veh = max(con_veh, key=lambda d: int(d.get("vehiculos_pagados",0) or 0))
            mejor_ticket = max(con_veh, key=lambda d: float(d.get("ticket_promedio",0) or 0))
            texto += (f"\n🚗 Más vehículos: *{mejor_veh['vehiculos_pagados']}*\n📅 {mejor_veh['fecha_legible']}\n"
                      f"\n🎟 Mejor ticket promedio: *{fmt(mejor_ticket.get('ticket_promedio',0))}*\n📅 {mejor_ticket['fecha_legible']}")
        await msg.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error records: {e}")
        await msg.edit_text("❌ No pude calcular los récords en este momento.")

async def cmd_ultimo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Buscando el último corte...")
    cortes = await get_cortes(limit=1)
    if not cortes:
        await msg.edit_text("No hay cortes guardados aún.")
        return
    resumen = generar_resumen_firebase(cortes[0])
    await msg.edit_text(resumen, parse_mode="Markdown")

async def cmd_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    if not context.args:
        await update.message.reply_text("Uso: /fecha 2026-06-15")
        return
    fecha = context.args[0]
    msg = await update.message.reply_text(f"⏳ Buscando corte del {fecha}...")
    cortes = await get_cortes(limit=30, fecha=fecha)
    if not cortes:
        await msg.edit_text(f"No encontré corte para el {fecha}.")
        return
    resumen = generar_resumen_firebase(cortes[0])
    await msg.edit_text(resumen, parse_mode="Markdown")

async def cmd_clips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Revisando inventario de clips...")
    try:
        stock = await get_stock_clips()
        if stock is None:
            await msg.edit_text("⚠️ No encontré el inventario de clips. Asegúrate de haberlo inicializado desde la app.")
            return
        # También obtener clips del último corte
        cortes = await get_cortes(limit=1)
        clips_ultimo = 0
        fecha_ultimo = ""
        turno_ultimo = ""
        if cortes:
            clips_ultimo = cortes[0].get("clips_usados", 0)
            fecha_ultimo = cortes[0].get("fecha", "")
            turno_ultimo = cortes[0].get("turno", "")
        texto = f"🌸 *Clips Aromáticos — Inventario*\n\n"
        texto += f"📦 *Stock actual:* {stock} clips\n"
        if clips_ultimo and fecha_ultimo:
            texto += f"✅ *Último corte entregó:* {clips_ultimo} clips\n"
            texto += f"   ({fecha_ultimo} turno {turno_ultimo})\n"
        await msg.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error clips: {e}")
        await msg.edit_text("❌ No pude obtener el inventario de clips.")

async def cmd_exportar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Generando Excel con historial completo...")
    try:
        historial = await get_historial_firestore(limite=1000)
        if not historial:
            await msg.edit_text("No hay datos en el historial.")
            return
        
        # Crear Excel en memoria
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Historial Star Wash"
        
        # Encabezados
        headers = ["Fecha", "Día", "Sesión", "Total ($)", "Tickets"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="714B67")
            cell.alignment = Alignment(horizontal="center")
        
        # Datos ordenados por fecha
        historial_sorted = sorted(historial, key=lambda x: x.get("fecha", ""))
        total_general = 0
        for row, d in enumerate(historial_sorted, 2):
            ws.cell(row=row, column=1, value=d.get("fecha", ""))
            ws.cell(row=row, column=2, value=d.get("dia_semana", ""))
            ws.cell(row=row, column=3, value=d.get("sesion", ""))
            ws.cell(row=row, column=4, value=d.get("total", 0))
            ws.cell(row=row, column=5, value=d.get("num_tickets", 0))
            total_general += d.get("total", 0)
            # Colorear sábados y domingos
            dia = d.get("dia_semana", "")
            if dia in ["Sábado", "Domingo"]:
                for col in range(1, 6):
                    ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor="EAD5F5")
        
        # Fila de totales
        total_row = len(historial_sorted) + 2
        ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
        ws.cell(row=total_row, column=4, value=total_general).font = Font(bold=True)
        ws.cell(row=total_row, column=5, value=sum(d.get("num_tickets",0) for d in historial_sorted)).font = Font(bold=True)
        
        # Ajustar anchos
        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 14
        ws.column_dimensions["C"].width = 14
        ws.column_dimensions["D"].width = 14
        ws.column_dimensions["E"].width = 10
        
        # Guardar en memoria y enviar
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        await update.message.reply_document(
            document=buffer,
            filename="Historial_StarWash.xlsx",
            caption=f"📊 Historial completo Star Wash\n{len(historial_sorted)} días | Total: ${total_general:,.2f}"
        )
        await msg.delete()
        
    except Exception as e:
        logger.error(f"Error exportar: {e}")
        await msg.edit_text(f"Error al exportar: {str(e)}")

async def cmd_sincronizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Sincronizando historial de Odoo... puede tardar 1-2 minutos.")
    try:
        guardados, errores, total_dias = await sincronizar_historial_odoo()
        texto = f"Sincronizacion completa\n{total_dias} dias procesados\n{guardados} guardados en Firestore\n{errores} errores"
        await msg.edit_text(texto)
    except Exception as e:
        logger.error(f"Error sincronizar: {e}")
        await msg.edit_text(f"❌ Error: {str(e)}")

async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Cargando historial...")
    cortes = await get_cortes(limit=5)
    if not cortes:
        await msg.edit_text("No hay cortes guardados.")
        return
    texto = "📋 *ÚLTIMOS CORTES*\n\n"
    for c in cortes:
        t = c.get("totales", {})
        dif = t.get("diferencia_din", 0)
        estado = "✅" if dif == 0 else "⚠️"
        autos = sum([c.get("ventas", {}).get(k, 0) for k in ["autos", "camionetas", "pickups", "express", "fiscalia"]])
        texto += f"{estado} *{c.get('fecha','—')}* — {c.get('sesion','—')}\n"
        texto += f"   🚗 {autos} autos | 💰 {fmt(t.get('total_tickets',0))} | 💸 {fmt(t.get('total_gastos',0))} gastos\n\n"
    await msg.edit_text(texto, parse_mode="Markdown")

GRUPOS_ENTRADA = {
    "botas":    {"label": "🥾 Botas",    "keys": ["botas_25","botas_26","botas_27","botas_28"]},
    "playeras": {"label": "👕 Playeras",  "keys": ["playeras_ch","playeras_m","playeras_g"]},
    "botes":    {"label": "🧴 Botes",     "keys": ["botes_1l","botes_500ml"]},
    "roma":     {"label": "🧼 Jabón Roma","keys": ["jabon_roma_500","jabon_roma_250"]},
}
KEYS_EN_GRUPO = {k for g in GRUPOS_ENTRADA.values() for k in g["keys"]}

def _botones_materiales_entrada():
    """Genera la lista de botones inline para seleccionar material de entrada."""
    botones = []
    fila = []
    for gkey, ginfo in GRUPOS_ENTRADA.items():
        fila.append(InlineKeyboardButton(ginfo["label"], callback_data=f"ent_grp:{gkey}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
        fila = []
    for key, info in MATERIALES.items():
        if key in KEYS_EN_GRUPO:
            continue
        fila.append(InlineKeyboardButton(f"{info['emoji']} {info['nombre']}", callback_data=f"ent_mat:{key}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    return botones

def _botones_materiales_salida():
    """Genera la lista de botones inline para seleccionar material de salida."""
    botones = []
    fila = []
    for gkey, ginfo in GRUPOS_ENTRADA.items():
        fila.append(InlineKeyboardButton(ginfo["label"], callback_data=f"sal_mat_grp:{gkey}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
        fila = []
    for key, info in MATERIALES.items():
        if key in KEYS_EN_GRUPO:
            continue
        fila.append(InlineKeyboardButton(f"{info['emoji']} {info['nombre']}", callback_data=f"sal_mat:{key}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    return botones

async def _mostrar_menu_materiales_entrada(update_or_query, context, edit=False):
    responsable = context.user_data.get("lavado_responsable", "")
    texto = f"➕ *Entrada material* — {responsable}\n\n¿Qué material entró?"
    markup = InlineKeyboardMarkup(_botones_materiales_entrada())
    if edit and hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(texto, parse_mode="Markdown", reply_markup=markup)
    else:
        msg = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
        await msg.reply_text(texto, parse_mode="Markdown", reply_markup=markup)

async def _mostrar_menu_materiales_salida(update_or_query, context, edit=False):
    responsable = context.user_data.get("lavado_responsable", "")
    texto = f"➖ *Sacar material* — {responsable}\n\n¿Qué material sacan?"
    markup = InlineKeyboardMarkup(_botones_materiales_salida())
    if edit and hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(texto, parse_mode="Markdown", reply_markup=markup)
    else:
        msg = update_or_query.message if hasattr(update_or_query, 'message') else update_or_query
        await msg.reply_text(texto, parse_mode="Markdown", reply_markup=markup)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Convierte los botones del panel en acciones sin romper las preguntas libres."""
    texto = (update.message.text or "").strip()

    # Menú del celular del lavado
    if is_lavado_only(update):
        if texto == "📦 Stock materiales": return await cmd_stock_mat(update, context)
        if texto == "📋 Movimientos hoy": return await cmd_movimientos_mat(update, context)
        if texto == "➕ Entrada material":
            # Primero preguntar quién registra (solo si no está guardado)
            chat_id = update.effective_chat.id
            if not context.user_data.get("lavado_responsable"):
                botones = []
                fila = []
                for nombre in RESPONSABLES:
                    fila.append(InlineKeyboardButton(nombre, callback_data=f"ent_resp:{nombre}"))
                    if len(fila) == 3:
                        botones.append(fila)
                        fila = []
                if fila:
                    botones.append(fila)
                await update.message.reply_text(
                    "➕ *Entrada material*\n\n¿Quién registra?",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(botones)
                )
            else:
                await _mostrar_menu_materiales_entrada(update, context)
            return
        if texto == "➖ Sacar material":
            chat_id = update.effective_chat.id
            if not context.user_data.get("lavado_responsable"):
                botones = []
                fila = []
                for nombre in RESPONSABLES:
                    fila.append(InlineKeyboardButton(nombre, callback_data=f"sal_resp:{nombre}"))
                    if len(fila) == 3:
                        botones.append(fila)
                        fila = []
                if fila:
                    botones.append(fila)
                await update.message.reply_text(
                    "➖ *Sacar material*\n\n¿Quién saca?",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(botones)
                )
            else:
                await _mostrar_menu_materiales_salida(update, context)
            return
        # Si hay entrada pendiente (esperando cantidad), procesar el número
        chat_id = update.effective_chat.id
        ep = _entradas_pendientes.get(chat_id)
        if ep:
            nums = re.findall(r'\d+', texto)
            if not nums:
                await update.message.reply_text("Escribe solo el número, por ejemplo: _5_", parse_mode="Markdown")
                return
            material_key = ep["material_key"]
            tipo = ep["tipo"]
            del _entradas_pendientes[chat_id]
            info = MATERIALES[material_key]
            responsable = context.user_data.get("lavado_responsable") or update.effective_user.first_name or "Lavado"
            if tipo == "piezas":
                cantidad = int(nums[0])
                nota = ""
            elif tipo == "cajas":
                pzs = PIEZAS_POR_CAJA.get(material_key, 1)
                cajas = int(nums[0])
                cantidad = cajas * pzs
                nota = f"({cajas} caja{'s' if cajas > 1 else ''} × {pzs} pzs)"
            else:  # cajas_y_piezas
                pzs = PIEZAS_POR_CAJA.get(material_key, 1)
                cajas = int(nums[0]) if len(nums) >= 1 else 0
                sueltas = int(nums[1]) if len(nums) >= 2 else 0
                cantidad = cajas * pzs + sueltas
                nota = f"({cajas} caja{'s' if cajas > 1 else ''} × {pzs} pzs + {sueltas} suelta{'s' if sueltas != 1 else ''})"
            stock = await get_stock_materiales()
            stock[material_key] = stock.get(material_key, 0) + cantidad
            await set_stock_materiales(stock)
            await registrar_movimiento_material("entrada", material_key, cantidad, "bodega", responsable, notas=nota)
            detalle = f" {nota}" if nota else ""
            await update.message.reply_text(
                f"✅ *Entrada registrada*\n\n"
                f"{info['emoji']} {info['nombre']}: +{cantidad}{detalle}\n"
                f"📦 Stock actual: *{stock[material_key]}*",
                parse_mode="Markdown"
            )
            return
        # Si hay salida pendiente (esperando cantidad), procesar el número
        sp = _salidas_pendientes.get(chat_id, {})
        if sp.get("esperando") == "cantidad_lavado":
            nums = re.findall(r'\d+', texto)
            if not nums:
                await update.message.reply_text("Escribe solo el número, por ejemplo: _2_", parse_mode="Markdown")
                return
            material_key = sp["material_key"]
            destino = sp["destino"]
            responsable = context.user_data.get("lavado_responsable") or "Lavado"
            del _salidas_pendientes[chat_id]
            cantidad = int(nums[0])
            info = MATERIALES[material_key]
            stock = await get_stock_materiales()
            actual = stock.get(material_key, 0)
            if actual < cantidad:
                await update.message.reply_text(
                    f"⚠️ Stock insuficiente.\n{info['emoji']} *{info['nombre']}* disponibles: *{actual}*",
                    parse_mode="Markdown"
                )
                return
            stock[material_key] = actual - cantidad
            await set_stock_materiales(stock)
            await registrar_movimiento_material("salida", material_key, cantidad, destino, responsable)
            destino_txt = DESTINOS.get(destino, destino)
            await update.message.reply_text(
                f"✅ *Salida registrada*\n\n"
                f"{info['emoji']} {info['nombre']}: −{cantidad} → {destino_txt}\n"
                f"📦 Stock actual: *{stock[material_key]}*",
                parse_mode="Markdown"
            )
            return
        # Texto libre del celular del lavado → solo materiales
        texto_lower = texto.lower()
        PALABRAS_SALIDA = [
            # sacar
            "sacar","saqué","saque","sacaron","se saco","se sacó","se sacaron",
            # llevar
            "se llevó","se llevo","se llevaron","llevaron","me llevé","me lleve",
            # agarrar
            "se agarro","se agarró","se agarraron","agarré","agarre","agarraron",
            # tomar
            "tome","tomé","tomaron","se tomó","se tomo","se tomaron",
            # dar / entregar
            "se dio","se dió","se dieron","dieron","entregué","entregue","se entregó",
            "se entrego","se entregaron","entregaron","di ","dí ",
            # usar / gastar
            "usé","use","usaron","se usó","se uso","se usaron",
            "gastó","gasto","gastaron","se gastó","se gasto","se gastaron",
            # salida genérica
            "salida","salieron","se fue","se fueron",
            # ocupar (mexicanismo)
            "ocupé","ocupe","ocuparon","se ocupó","se ocupo","se ocuparon",
        ]
        if any(p in texto_lower for p in PALABRAS_SALIDA):
            return await _procesar_salida(update, texto)
        if any(p in texto_lower for p in ["entrada","entraron","llegaron","compré","compre","agregué","agregue"]):
            return await _procesar_entrada(update, texto)
        if any(p in texto_lower for p in ["stock","cuánto","cuanto","quedan","hay","inventario","materiales"]):
            return await cmd_stock_mat(update, context)
        # Respuesta genérica para el celular del lavado
        await update.message.reply_text(
            "Para registrar una salida escribe:\n_sacar 2 playeras para caja_\n\nPara ver el stock:\n_¿cuántas escobas hay?_",
            parse_mode="Markdown"
        )
        return

    if texto == "📊 Cómo vamos hoy": return await cmd_hoy(update, context)
    if texto == "🏆 Récords": return await cmd_records(update, context)
    if texto == "📋 Último corte": return await cmd_ultimo(update, context)
    if texto == "📅 Historial": return await cmd_historial(update, context)
    if texto == "⚖️ Comparar corte":
        await update.message.reply_text("Escribe /comparar AAAA-MM-DD, por ejemplo: /comparar 2026-09-20")
        return
    if texto == "📥 Exportar": return await cmd_exportar(update, context)
    return await handle_text(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    caption = update.message.caption or "📸 Lectura de máquina"
    sender = update.effective_user.first_name
    await update.message.reply_text("✅ Foto recibida.")
    if update.effective_user.id != OWNER_ID:
        photo = update.message.photo[-1]
        await context.bot.send_photo(
            chat_id=OWNER_ID,
            photo=photo.file_id,
            caption=f"📸 Lectura de máquina — {sender}\n{caption}"
        )


# ── HISTORIAL ODOO ────────────────────────────────────────────────────────────
async def get_historial_odoo(dias=None):
    """Obtiene historial completo de ventas POS desde Odoo usando órdenes."""
    async with httpx.AsyncClient(timeout=120) as client:
        uid = await odoo_uid(client)
        
        # Usar órdenes en lugar de sesiones — tienen fecha correcta siempre
        ordenes = await odoo_call(client, uid, 'pos.order', 'search_read',
            [[['state', 'in', ['done', 'invoiced']]]],
            {
                'fields': ['name', 'date_order', 'amount_total', 'session_id'],
                'order': 'date_order desc',
                'limit': 50000
            }
        )
        
        # Agrupar por día
        from collections import defaultdict
        por_dia = defaultdict(lambda: {'total': 0, 'ordenes': 0, 'sesion': ''})
        
        for o in ordenes:
            raw_fecha = (o.get('date_order') or '')[:19]
            if not raw_fecha:
                continue
            try:
                dt_utc = datetime.strptime(raw_fecha, "%Y-%m-%d %H:%M:%S")
                fecha = (dt_utc - timedelta(hours=6)).strftime("%Y-%m-%d")
            except Exception:
                fecha = raw_fecha[:10]
            por_dia[fecha]['total'] += o.get('amount_total', 0)
            por_dia[fecha]['ordenes'] += 1
            if o.get('session_id'):
                por_dia[fecha]['sesion'] = o['session_id'][1] if isinstance(o['session_id'], list) else str(o['session_id'])
        
        resumen = [
            {
                'fecha': fecha,
                'sesion': datos['sesion'],
                'total': round(datos['total'], 2),
                'num_tickets': datos['ordenes'],
            }
            for fecha, datos in sorted(por_dia.items(), reverse=True)
        ]
        
    return resumen

# ── SINCRONIZACIÓN ODOO → FIRESTORE ──────────────────────────────────────────
async def sincronizar_historial_odoo():
    """Descarga todas las ordenes y lineas de Odoo y las guarda en Firestore agrupadas por dia."""
    logger.info("Iniciando sincronizacion Odoo Firestore...")
    
    async with httpx.AsyncClient(timeout=300) as client:
        uid = await odoo_uid(client)
        
        # Traer todas las lineas de ordenes paginando (tienen producto + cantidad + precio)
        lineas = []
        offset = 0
        batch_size = 5000
        while True:
            batch = await odoo_call(client, uid, 'pos.order.line', 'search_read',
                [[['order_id.state', 'in', ['done', 'invoiced']]]],
                {
                    'fields': ['order_id', 'product_id', 'qty', 'price_subtotal_incl'],
                    'order': 'id asc',
                    'limit': batch_size,
                    'offset': offset
                }
            )
            if not batch:
                break
            lineas.extend(batch)
            offset += batch_size
            logger.info(f"Lineas batch {offset//batch_size}: {len(batch)}")
            if len(batch) < batch_size:
                break
        
        logger.info(f"Total lineas: {len(lineas)}")
        
        # Traer ordenes para obtener fecha y sesion
        ordenes = []
        offset = 0
        while True:
            batch = await odoo_call(client, uid, 'pos.order', 'search_read',
                [[['state', 'in', ['done', 'invoiced']]]],
                {
                    'fields': ['name', 'date_order', 'amount_total', 'session_id'],
                    'order': 'date_order asc',
                    'limit': batch_size,
                    'offset': offset
                }
            )
            if not batch:
                break
            ordenes.extend(batch)
            offset += batch_size
            if len(batch) < batch_size:
                break
        
        logger.info(f"Total ordenes: {len(ordenes)}")

        # Traer sesiones para obtener start_at y clasificar turno
        sesiones_all = await odoo_call(client, uid, 'pos.session', 'search_read',
            [[['state', 'in', ['closed', 'opened']]]],
            {'fields': ['id', 'name', 'start_at'], 'limit': 5000}
        )
        # Mapa session_id -> turno ('D' o 'N') basado en start_at CDMX
        # Día: start < 17:30 CDMX, Noche: start >= 18:00 CDMX
        sesion_turno = {}
        for s in sesiones_all:
            raw_s = (s.get('start_at') or '')[:19]
            if len(raw_s) >= 19:
                dt_s = datetime.strptime(raw_s, "%Y-%m-%d %H:%M:%S") - timedelta(hours=6)
                hora_s = dt_s.hour + dt_s.minute / 60
                sesion_turno[s['id']] = 'N' if hora_s >= 18 else 'D'
            else:
                sesion_turno[s['id']] = 'D'

        # Mapa order_id -> fecha, turno y sesion
        orden_info = {}
        for o in ordenes:
            raw = (o.get('date_order') or '')[:19]
            if len(raw) >= 19:
                dt_utc = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
                dt_cdmx = dt_utc - timedelta(hours=6)
                fecha = dt_cdmx.strftime("%Y-%m-%d")
            else:
                fecha = raw[:10]
            sesion_id = o['session_id'][0] if isinstance(o.get('session_id'), list) else None
            turno = sesion_turno.get(sesion_id, 'D') if sesion_id else 'D'
            orden_info[o['id']] = {
                'fecha': fecha,
                'turno': turno,
                'sesion': o['session_id'][1] if isinstance(o.get('session_id'), list) else ''
            }
        
        # Clasificar productos
        def clasificar_producto(nom):
            n = nom.lower()
            # Cortesías (primero para evitar falsos positivos)
            if 'taller' in n: return 'cortes_taller'
            if 'ayto' in n or 'ayuntamiento' in n: return 'cortes_ayto'
            if 'familiar' in n: return 'cortes_familiar'
            # Seguros
            if 'seguro' in n: return 'seguro'
            # Motos
            if 'moto' in n: return 'motos'
            # Fiscalía
            if 'fiscal' in n: return 'fiscalia'
            # Express (X1, X4)
            if 'express' in n or n.startswith('x'): return 'express'
            # Pick-Up / SUV Grande (Prog 3, 6, 6T)
            if 'pick' in n or 'suv' in n or 'minivan' in n: return 'pickups'
            # Camioneta (Prog 2, 5, 5T)
            if 'camioneta' in n or 'cam.' in n: return 'camionetas'
            # Auto (Prog 1, 4, 4T)
            if 'auto' in n: return 'autos'
            # Adicionales
            if 'cera y tapetes' in n or 'pro' in n: return 'pro_cera'
            if 'cera' in n or 'plus' in n: return 'plus_cera'
            if 'mano' in n: return 'mano'
            if 'motor' in n: return 'motor'
            if 'tapete' in n: return 'tapetes'
            return 'otros'
        
        # Agrupar por dia
        from collections import defaultdict
        VEHICULOS = ['autos','camionetas','pickups','express','fiscalia','motos']
        SERVICIOS = ['plus_cera','pro_cera','mano','motor','tapetes']
        CORTESIAS = ['cortes_taller','cortes_ayto','cortes_familiar']
        
        por_dia = defaultdict(lambda: {
            'total': 0, 'total_dia': 0, 'total_noche': 0,
            'tickets': set(), 'sesion': '', 'fecha': '',
            'autos': 0, 'camionetas': 0, 'pickups': 0, 'express': 0,
            'fiscalia': 0, 'motos': 0, 'plus_cera': 0, 'pro_cera': 0,
            'mano': 0, 'motor': 0, 'tapetes': 0,
            'cortes_taller': 0, 'cortes_ayto': 0, 'cortes_familiar': 0,
            'seguro': 0, 'otros': 0
        })
        
        for l in lineas:
            order_id = l['order_id'][0] if isinstance(l.get('order_id'), list) else l.get('order_id')
            if not order_id or order_id not in orden_info:
                continue
            fecha = orden_info[order_id]['fecha']
            if not fecha:
                continue
            nom = l['product_id'][1] if isinstance(l.get('product_id'), list) else ''
            cat = clasificar_producto(nom)
            qty = int(l.get('qty') or 0)
            precio = float(l.get('price_subtotal_incl') or 0)
            
            turno = orden_info[order_id]['turno']
            por_dia[fecha][cat] += qty
            por_dia[fecha]['total'] += precio
            # Separar por turno según start_at de la sesión
            if turno == 'N':
                por_dia[fecha]['total_noche'] += precio
            else:
                por_dia[fecha]['total_dia'] += precio
            por_dia[fecha]['tickets'].add(order_id)
            por_dia[fecha]['fecha'] = fecha
            if orden_info[order_id]['sesion']:
                por_dia[fecha]['sesion'] = orden_info[order_id]['sesion']
        
        # Guardar cada dia en Firestore coleccion historial_odoo
        from datetime import datetime as dt_sync
        DIAS_ES = ['Lunes','Martes','Miercoles','Jueves','Viernes','Sabado','Domingo']
        MESES_ES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        guardados = 0
        errores = 0
        for fecha, datos in por_dia.items():
            doc_id = fecha
            firestore_url = f"{FIRESTORE_URL}/historial_odoo/{doc_id}"
            try:
                fecha_dt = dt_sync.strptime(fecha, "%Y-%m-%d")
                dia_semana = DIAS_ES[fecha_dt.weekday()]
                fecha_legible = f"{dia_semana} {fecha_dt.day} de {MESES_ES[fecha_dt.month]} de {fecha_dt.year}"
            except:
                dia_semana = ""
                fecha_legible = fecha
            
            tickets_set = datos['tickets']
            num_tickets = len(tickets_set) if isinstance(tickets_set, set) else int(tickets_set)
            
            # Calcular ticket promedio sin motos
            vehiculos_pagados = (datos['autos'] + datos['camionetas'] + datos['pickups'] +
                                 datos['express'] + datos['fiscalia'])
            total_sin_motos = datos['total'] - (datos['motos'] * 60)  # aprox $60 por moto
            ticket_promedio = round(total_sin_motos / vehiculos_pagados, 2) if vehiculos_pagados > 0 else 0
            
            body = {
                "fields": {
                    "fecha":            {"stringValue": fecha},
                    "fecha_legible":    {"stringValue": fecha_legible},
                    "dia_semana":       {"stringValue": dia_semana},
                    "sesion":           {"stringValue": datos['sesion']},
                    "total":            {"doubleValue": round(datos['total'], 2)},
                    "total_dia":        {"doubleValue": round(datos['total_dia'], 2)},
                    "total_noche":      {"doubleValue": round(datos['total_noche'], 2)},
                    "num_tickets":      {"integerValue": str(num_tickets)},
                    "ticket_promedio":  {"doubleValue": ticket_promedio},
                    "autos":            {"integerValue": str(datos['autos'])},
                    "camionetas":       {"integerValue": str(datos['camionetas'])},
                    "pickups":          {"integerValue": str(datos['pickups'])},
                    "express":          {"integerValue": str(datos['express'])},
                    "fiscalia":         {"integerValue": str(datos['fiscalia'])},
                    "motos":            {"integerValue": str(datos['motos'])},
                    "plus_cera":        {"integerValue": str(datos['plus_cera'])},
                    "pro_cera":         {"integerValue": str(datos['pro_cera'])},
                    "mano":             {"integerValue": str(datos['mano'])},
                    "motor":            {"integerValue": str(datos['motor'])},
                    "tapetes":          {"integerValue": str(datos['tapetes'])},
                    "cortes_taller":    {"integerValue": str(datos['cortes_taller'])},
                    "cortes_ayto":      {"integerValue": str(datos['cortes_ayto'])},
                    "cortes_familiar":  {"integerValue": str(datos['cortes_familiar'])},
                    "seguro":           {"integerValue": str(datos['seguro'])},
                    "vehiculos_pagados":{"integerValue": str(vehiculos_pagados)},
                    "fuente":           {"stringValue": "odoo"},
                    "sincronizado":     {"stringValue": datetime.now().isoformat()},
                }
            }
            
            try:
                r = await client.patch(firestore_url, json=body)
                if r.status_code in [200, 201]:
                    guardados += 1
                else:
                    errores += 1
                    logger.error(f"Error guardando {fecha}: {r.status_code}")
            except Exception as e:
                errores += 1
                logger.error(f"Error {fecha}: {e}")
        
        logger.info(f"Sincronización completa: {guardados} días guardados, {errores} errores")
        return guardados, errores, len(por_dia)

async def get_historial_firestore(limite=1000):
    """Lee el historial de Firestore (más rápido que Odoo)."""
    url = f"{FIRESTORE_URL}/historial_odoo"
    params = {"pageSize": limite, "orderBy": "fecha desc"}
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)
        data = r.json()
    
    docs = data.get("documents", [])
    from datetime import datetime as dt2
    DIAS_SEM = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
    historial = []
    for doc in docs:
        fields = doc.get("fields", {})
        fecha_str = fields.get("fecha", {}).get("stringValue", "")
        try:
            dia_sem = DIAS_SEM[dt2.strptime(fecha_str, "%Y-%m-%d").weekday()] if fecha_str else ""
        except:
            dia_sem = ""
        historial.append({
            "fecha":         fecha_str,
            "fecha_legible": fields.get("fecha_legible", {}).get("stringValue", "") or dia_sem + " " + fecha_str,
            "dia_semana":    fields.get("dia_semana", {}).get("stringValue", "") or dia_sem,
            "sesion":        fields.get("sesion", {}).get("stringValue", ""),
            "total":         float(fields.get("total", {}).get("doubleValue", 0) or fields.get("total", {}).get("integerValue", 0) or 0),
            "num_tickets":   int(fields.get("num_tickets", {}).get("integerValue", 0) or 0),
            "ticket_promedio": float(fields.get("ticket_promedio", {}).get("doubleValue", 0) or fields.get("ticket_promedio", {}).get("integerValue", 0) or 0),
            "vehiculos_pagados": int(fields.get("vehiculos_pagados", {}).get("integerValue", 0) or 0),
            "autos": int(fields.get("autos", {}).get("integerValue", 0) or 0),
            "camionetas": int(fields.get("camionetas", {}).get("integerValue", 0) or 0),
            "pickups": int(fields.get("pickups", {}).get("integerValue", 0) or 0),
            "express": int(fields.get("express", {}).get("integerValue", 0) or 0),
            "fiscalia": int(fields.get("fiscalia", {}).get("integerValue", 0) or 0),
        })
    return historial

# ── COMPARACIÓN CORTE vs ODOO ────────────────────────────────────────────────
async def comparar_corte_vs_odoo(fecha):
    """Compara un corte de Firestore contra los datos reales de Odoo para esa fecha."""
    
    # 1. Obtener corte de Firestore
    cortes = await get_cortes(limit=50, fecha=fecha)
    if not cortes:
        return None, f"No encontré corte guardado para {fecha}"
    corte = cortes[0]
    
    # 2. Obtener sesión de Odoo para esa fecha
    async with httpx.AsyncClient(timeout=60) as client:
        uid = await odoo_uid(client)
        
        # Buscar sesión por fecha
        fecha_inicio = f"{fecha} 00:00:00"
        fecha_fin = f"{fecha} 23:59:59"
        sesiones = await odoo_call(client, uid, 'pos.session', 'search_read',
            [[['start_at', '>=', fecha_inicio], ['start_at', '<=', fecha_fin], ['state', '=', 'closed']]],
            {'fields': ['id', 'name', 'total_payments_amount'], 'limit': 1}
        )
        
        if not sesiones:
            return None, f"No encontré sesión de Odoo para {fecha}"
        
        sesion = sesiones[0]
        sesion_id = sesion['id']
        
        # Obtener pagos de Odoo
        pagos = await odoo_call(client, uid, 'pos.payment', 'search_read',
            [[['session_id', '=', sesion_id]]],
            {'fields': ['amount', 'payment_method_id'], 'limit': 500}
        )
        
        # Obtener líneas de órdenes
        lineas = await odoo_call(client, uid, 'pos.order.line', 'search_read',
            [[['order_id.session_id', '=', sesion_id]]],
            {'fields': ['product_id', 'qty', 'price_subtotal_incl'], 'limit': 2000}
        )
        
        # Obtener salidas de caja (gastos en Odoo)
        salidas = await odoo_call(client, uid, 'pos.payment', 'search_read',
            [[['session_id', '=', sesion_id], ['amount', '<', 0]]],
            {'fields': ['amount', 'payment_method_id'], 'limit': 200}
        )
    
    # 3. Calcular totales de Odoo
    efe_odoo = sum(p['amount'] for p in pagos if 'efectivo' in (p['payment_method_id'][1] or '').lower() or 'cash' in (p['payment_method_id'][1] or '').lower())
    tar_odoo = sum(p['amount'] for p in pagos if 'tarjeta' in (p['payment_method_id'][1] or '').lower())
    trans_odoo = sum(p['amount'] for p in pagos if 'transfer' in (p['payment_method_id'][1] or '').lower())
    total_odoo = sesion.get('total_payments_amount', 0)
    
    # Contar vehículos en Odoo
    veh_odoo = {'autos': 0, 'camionetas': 0, 'pickups': 0, 'express': 0, 'fiscalia': 0, 'motos': 0}
    for l in lineas:
        nom = (l['product_id'][1] or '').lower()
        qty = int(l.get('qty') or 0)
        if 'cortesía' in nom or 'cortesia' in nom: continue
        if 'auto' in nom and 'camioneta' not in nom and 'pick' not in nom: veh_odoo['autos'] += qty
        elif 'camioneta' in nom: veh_odoo['camionetas'] += qty
        elif 'pick' in nom or 'suv' in nom or 'minivan' in nom: veh_odoo['pickups'] += qty
        elif 'express' in nom: veh_odoo['express'] += qty
        elif 'fiscal' in nom: veh_odoo['fiscalia'] += qty
        elif 'moto' in nom: veh_odoo['motos'] += qty
    
    total_veh_odoo = sum(veh_odoo.values())
    
    # 4. Obtener datos del corte de Firestore
    ventas_fc = corte.get('ventas', {})
    pagos_fc = corte.get('pagos', {})
    
    autos_fc = int(ventas_fc.get('autos', 0))
    cam_fc = int(ventas_fc.get('camionetas', 0))
    pick_fc = int(ventas_fc.get('pickups', 0))
    exp_fc = int(ventas_fc.get('express', 0))
    fis_fc = int(ventas_fc.get('fiscalia', 0))
    mot_fc = int(ventas_fc.get('motos', 0))
    total_veh_fc = autos_fc + cam_fc + pick_fc + exp_fc + fis_fc + mot_fc
    
    efe_fc = float(pagos_fc.get('efectivo', 0))
    tar_fc = float(pagos_fc.get('tarjeta', 0))
    trans_fc = float(pagos_fc.get('transferencia', 0))
    total_fc = float(corte.get('totales', {}).get('total_tickets', 0))
    
    # 5. Gastos en Firestore
    gastos_fc = corte.get('gastos', [])
    total_gastos_fc = sum(float(g.get('monto', 0)) for g in gastos_fc if isinstance(g, dict))
    
    # 6. Detectar gastos de tickets no impresos
    PRECIOS_VEH = {'autos': 110, 'camionetas': 120, 'pickups': 140, 'express': 90, 'fiscalia': 80, 'motos': 60}
    ADICIONALES = [0, 20, 50, 30]  # sin adicional, plus cera, pro cera, tapetes
    
    # Generar todos los precios válidos: vehículo + adicional, simple y doble
    PRECIOS_VALIDOS = set()
    for precio_veh in PRECIOS_VEH.values():
        for adicional in ADICIONALES:
            precio = precio_veh + adicional
            PRECIOS_VALIDOS.add(precio)       # simple
            PRECIOS_VALIDOS.add(precio * 2)   # doble (2 tickets en uno)
    
    def es_gasto_ticket(concepto, monto):
        c = (concepto or '').lower()
        es_ticket = any(w in c for w in ['ticket', 'tiket', 'ticet'])
        m = float(monto or 0)
        # Monto válido: múltiplo de $10, entre $60 y $600
        monto_valido = m > 0 and m % 10 == 0 and 60 <= m <= 600
        return es_ticket and monto_valido
    
    def autos_justificados_por_ticket(gasto):
        """Devuelve cuántos autos justifica: 2 si el monto es doble de algún precio válido, 1 si es simple."""
        monto = float(gasto.get('monto', 0))
        # Verificar si es doble de algún precio simple
        for precio_veh in PRECIOS_VEH.values():
            for adicional in ADICIONALES:
                precio_simple = precio_veh + adicional
                if monto == precio_simple * 2: return 2
                if monto == precio_simple: return 1
        return 1  # por defecto justifica 1
    
    gastos_tickets = [g for g in gastos_fc if isinstance(g, dict) and es_gasto_ticket(g.get('concepto', ''), g.get('monto', 0))]
    monto_tickets_gastados = sum(float(g.get('monto', 0)) for g in gastos_tickets)
    autos_justificados = sum(autos_justificados_por_ticket(g) for g in gastos_tickets)
    
    # 7. Generar reporte de discrepancias
    discrepancias = []
    justificados = []
    ok = []
    
    def chk(label, val_odoo, val_fc, es_dinero=False):
        diff = val_fc - val_odoo  # negativo = menos en corte que en Odoo
        diff_abs = abs(diff)
        umbral = 1 if es_dinero else 0
        
        if diff_abs <= umbral:
            ok.append("✅ " + label + ": " + ("${:,.0f}".format(val_odoo) if es_dinero else str(int(val_odoo))))
            return
        
        # Verificar si la discrepancia está justificada por gastos de ticket
        if not es_dinero and diff < 0:
            # Faltan vehículos — ver si los tickets registrados los justifican
            if autos_justificados >= diff_abs:
                justificados.append("🎫 " + label + ": " + str(int(diff_abs)) + " menos, justificado por " + str(len(gastos_tickets)) + " ticket(s) en gastos ($" + "{:,.0f}".format(monto_tickets_gastados) + ")")
                return
        
        signo = "+" if diff > 0 else ""
        val_fmt = lambda v: "${:,.0f}".format(v) if es_dinero else str(int(v))
        discrepancias.append("⚠️ " + label + ": Odoo=" + val_fmt(val_odoo) + " vs Corte=" + val_fmt(val_fc) + " (" + signo + val_fmt(diff) + ")")
    
    chk("Autos", veh_odoo['autos'], autos_fc)
    chk("Camionetas", veh_odoo['camionetas'], cam_fc)
    chk("Pick-Ups/SUV", veh_odoo['pickups'], pick_fc)
    chk("Express", veh_odoo['express'], exp_fc)
    chk("Total vehículos", total_veh_odoo, total_veh_fc)
    chk("Efectivo", efe_odoo, efe_fc, es_dinero=True)
    chk("Tarjeta", tar_odoo, tar_fc, es_dinero=True)
    chk("Transferencia", trans_odoo, trans_fc, es_dinero=True)
    chk("Total cobrado", total_odoo, total_fc, es_dinero=True)
    
    nombre_sesion = sesion.get("name", "")
    reporte = "Comparacion " + fecha + " - " + nombre_sesion + "\n\n"
    
    if discrepancias:
        reporte += "DISCREPANCIAS (" + str(len(discrepancias)) + "):\n"
        reporte += "\n".join(discrepancias) + "\n\n"
    else:
        reporte += "Todo cuadra con Odoo \n\n"
    
    if ok:
        reporte += "OK (" + str(len(ok)) + "):\n"
        reporte += "\n".join(ok) + "\n\n"
    
    reporte += "Gastos en corte: $" + f"{total_gastos_fc:,.0f}" + "\n"
    reporte += "Sesion Odoo: " + nombre_sesion
    
    return reporte, None

async def cmd_comparar_semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compara todos los cortes de la semana vs Odoo."""
    if not await check_allowed(update): return
    
    from datetime import datetime, timedelta
    msg = await update.message.reply_text("⏳ Comparando cortes de los últimos 7 días...")
    
    resumen = []
    hoy = datetime.now()
    
    for dias_atras in range(1, 8):
        fecha = (hoy - timedelta(days=dias_atras)).strftime('%Y-%m-%d')
        try:
            reporte, error = await comparar_corte_vs_odoo(fecha)
            if error:
                resumen.append(f"📅 {fecha}: Sin corte guardado")
            else:
                # Contar discrepancias
                n_disc = reporte.count('⚠️')
                if n_disc == 0:
                    resumen.append(f"✅ {fecha}: Todo cuadra")
                else:
                    # Extraer solo las líneas de discrepancia
                    lineas_disc = [l for l in reporte.split("\n") if "discrepan" in l.lower() or "⚠️" in l]
                    resumen.append("❌ " + fecha + ": " + str(n_disc) + " discrepancia(s)\n  " + "\n  ".join(lineas_disc))
        except Exception as e:
            resumen.append(f"📅 {fecha}: Error — {str(e)[:50]}")
    
    texto = "Comparacion semanal Corte vs Odoo\n\n"
    texto += "\n\n".join(resumen)

    
    # Dividir si es muy largo
    if len(texto) > 4000:
        partes = [texto[i:i+4000] for i in range(0, len(texto), 4000)]
        await msg.edit_text(partes[0])
        for parte in partes[1:]:
            await update.message.reply_text(parte)
    else:
        await msg.edit_text(texto)

async def cmd_comparar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compara corte vs Odoo. Uso: /comparar o /comparar 2026-08-15"""
    if not await check_allowed(update): return
    
    from datetime import datetime, timedelta
    
    # Determinar fecha
    args = context.args
    if args:
        fecha = args[0]
    else:
        fecha = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    msg = await update.message.reply_text(f"⏳ Comparando corte del {fecha} vs Odoo...")
    
    try:
        reporte, error = await comparar_corte_vs_odoo(fecha)
        if error:
            await msg.edit_text(f"❌ {error}")
        else:
            # Limpiar markdown problemático
            await msg.edit_text(reporte)
    except Exception as e:
        logger.error(f"Error comparar: {e}")
        await msg.edit_text(f"Error: {str(e)}")

# ── ACTUALIZAR CORTES CON MOTOS Y FISCALIA ───────────────────────────────────
async def cmd_actualizar_cortes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actualiza cortes de Firestore agregando motos y fiscalia desde Odoo."""
    if not await check_allowed(update): return
    msg = await update.message.reply_text("⏳ Actualizando cortes con motos y fiscalía... puede tardar unos minutos.")
    
    try:
        # Obtener todos los cortes de Firestore
        cortes = await get_cortes(limit=100)
        actualizados = 0
        errores = 0
        
        async with httpx.AsyncClient(timeout=60) as client:
            uid = await odoo_uid(client)
            
            for corte in cortes:
                fecha = corte.get('fecha', '')
                sesion_nombre = corte.get('sesion', '')
                if not fecha or not sesion_nombre:
                    continue
                
                # Buscar sesión en Odoo por nombre
                try:
                    sesiones = await odoo_call(client, uid, 'pos.session', 'search_read',
                        [[['name', '=', sesion_nombre]]],
                        {'fields': ['id', 'name'], 'limit': 1}
                    )
                    if not sesiones:
                        continue
                    
                    sesion_id = sesiones[0]['id']
                    
                    # Obtener líneas de órdenes
                    lineas = await odoo_call(client, uid, 'pos.order.line', 'search_read',
                        [[['order_id.session_id', '=', sesion_id]]],
                        {'fields': ['product_id', 'qty'], 'limit': 2000}
                    )
                    
                    # Contar motos y fiscalía
                    motos = 0
                    fiscalia = 0
                    for l in lineas:
                        nom = (l['product_id'][1] or '').lower()
                        qty = int(l.get('qty') or 0)
                        if 'moto' in nom: motos += qty
                        elif 'fiscal' in nom: fiscalia += qty
                    
                    # Actualizar en Firestore solo si hay datos
                    if motos > 0 or fiscalia > 0:
                        doc_id = corte.get('_id', '')
                        if not doc_id:
                            continue
                        
                        url = f"{FIRESTORE_URL}/cortes/{doc_id}"
                        body = {
                            "fields": {
                                "ventas": {"mapValue": {"fields": {
                                    "autos":      {"integerValue": str(corte.get('ventas', {}).get('autos', 0))},
                                    "camionetas": {"integerValue": str(corte.get('ventas', {}).get('camionetas', 0))},
                                    "pickups":    {"integerValue": str(corte.get('ventas', {}).get('pickups', 0))},
                                    "express":    {"integerValue": str(corte.get('ventas', {}).get('express', 0))},
                                    "fiscalia":   {"integerValue": str(fiscalia)},
                                    "motos":      {"integerValue": str(motos)},
                                }}}
                            }
                        }
                        
                        r = await client.patch(
                            url + "?updateMask.fieldPaths=ventas",
                            json=body
                        )
                        if r.status_code in [200, 201]:
                            actualizados += 1
                        else:
                            errores += 1
                            
                except Exception as e:
                    logger.error(f"Error actualizando {sesion_nombre}: {e}")
                    errores += 1
        
        await msg.edit_text(
            f"Actualizacion completa\n"
            f"{actualizados} cortes actualizados con motos/fiscalia\n"
            f"{errores} errores"
        )
        
    except Exception as e:
        logger.error(f"Error cmd_actualizar_cortes: {e}")
        await msg.edit_text(f"Error: {str(e)}")

# ── AUDITORÍA AUTOMÁTICA ──────────────────────────────────────────────────────
async def auditar_corte(corte: dict, historial: list) -> str:
    """Genera reporte de auditoría comparando el corte vs historial."""
    alertas = []
    info = []

    t = corte.get("totales", {})
    v = corte.get("ventas", {})
    c = corte.get("caja", {})
    m = corte.get("maquina", {})
    o = corte.get("otros", {})

    autos_pagados = sum([v.get(k, 0) for k in ["autos", "camionetas", "pickups", "express", "fiscalia"]])
    dif_din = t.get("diferencia_din", 0)
    dif_maq = m.get("diferencia", 0)
    billetes = c.get("billetes", 0)
    efectivo_odoo = corte.get("pagos", {}).get("efectivo", 0)
    gastos = t.get("total_gastos", 0)

    # 1. Diferencia de caja
    if dif_din != 0:
        if abs(dif_din) >= 1000:
            alertas.append(f"🚨 Diferencia de caja: {fmt(abs(dif_din))} ({'sobrante' if dif_din > 0 else 'faltante'}) — revisar conteo de efectivo")
        elif abs(dif_din) > 0:
            alertas.append(f"⚠️ Diferencia de caja menor: {fmt(abs(dif_din))} ({'sobrante' if dif_din > 0 else 'faltante'})")
    else:
        info.append("✅ Caja cuadra exacto")

    # 2. Diferencia de máquina
    if dif_maq != 0:
        causa = ""
        lavm = o.get("lavados_mano", 0)
        reg = o.get("regresos", 0)
        if lavm > 0:
            causa = f" — hay {lavm} lavado(s) a mano que no pasan por máquina"
        elif reg > 0:
            causa = f" — hay {reg} regreso(s) registrado(s)"
        if dif_maq > 0:
            alertas.append(f"⚠️ Máquina marcó {dif_maq} auto(s) de más{causa} — posible auto sin cobrar")
        else:
            alertas.append(f"⚠️ Máquina marcó {abs(dif_maq)} auto(s) de menos{causa}")
    else:
        info.append("✅ Máquina cuadra exacto")

    # 3. Billetes vs efectivo Odoo
    if efectivo_odoo > 0 and billetes > 0:
        morralla = c.get("morralla", 0)
        apertura = c.get("apertura", 0)
        efectivo_real = billetes + morralla - apertura
        dif_efe = efectivo_real - efectivo_odoo
        if abs(dif_efe) > 100:
            alertas.append(f"⚠️ Billetes+Morralla-Apertura ({fmt(efectivo_real)}) vs Efectivo Odoo ({fmt(efectivo_odoo)}) — diferencia {fmt(abs(dif_efe))}")

    # 4. Comparar vs historial (si hay suficientes cortes)
    if len(historial) >= 2:
        hist_autos = [sum([h.get("ventas", {}).get(k, 0) for k in ["autos", "camionetas", "pickups", "express", "fiscalia"]]) for h in historial]
        hist_gastos = [h.get("totales", {}).get("total_gastos", 0) for h in historial]
        hist_tickets = [h.get("totales", {}).get("total_tickets", 0) for h in historial]

        prom_autos = sum(hist_autos) / len(hist_autos)
        prom_gastos = sum(hist_gastos) / len(hist_gastos)
        prom_tickets = sum(hist_tickets) / len(hist_tickets)

        # Autos bajos
        if prom_autos > 0 and autos_pagados < prom_autos * 0.75:
            alertas.append(f"📉 Autos pagados ({autos_pagados}) están {round((1 - autos_pagados/prom_autos)*100)}% por debajo del promedio ({round(prom_autos)})")

        # Gastos inusuales
        if prom_gastos > 0 and gastos > prom_gastos * 1.30:
            alertas.append(f"💸 Gastos ({fmt(gastos)}) superan 30% del promedio histórico ({fmt(prom_gastos)}) — revisar")

        # Ventas bajas
        tickets = t.get("total_tickets", 0)
        if prom_tickets > 0 and tickets < prom_tickets * 0.75:
            alertas.append(f"📉 Ventas ({fmt(tickets)}) están {round((1 - tickets/prom_tickets)*100)}% por debajo del promedio ({fmt(prom_tickets)})")

        info.append(f"📊 Promedios históricos ({len(historial)} días): {round(prom_autos)} autos | {fmt(prom_tickets)} ventas | {fmt(prom_gastos)} gastos")

    # Construir mensaje
    fecha = corte.get("fecha", "—")
    sesion = corte.get("sesion", "—")
    msg = f"🔍 *AUDITORÍA — {fecha} | {sesion}*\n\n"

    if alertas:
        msg += "\n".join(alertas)
    else:
        msg += "\n".join(info)
        msg += "\n\n✅ Todo en orden, sin anomalías detectadas."

    if alertas and info:
        msg += "\n\n" + "\n".join(info)

    return msg

PALABRAS_HISTORICO = [
    'mejor día', 'mejor dia', 'peor día', 'peor dia',
    'más vendido', 'mas vendido', 'mayor venta', 'menor venta',
    'semana pasada', 'mes pasado', 'último mes', 'ultimos dias',
    'promedio', 'tendencia', 'comparar', 'histórico', 'historico',
    'cuánto hemos vendido', 'cuanto hemos vendido',
    'ranking', 'top', 'los mejores', 'los peores',
    'este mes', 'esta semana', 'del mes', 'de la semana',
]

PALABRAS_CORTE_COMPLETO = [
    "dame el corte", "mándame el corte", "mandame el corte",
    "el corte de", "corte del día", "corte del dia",
    "ver corte", "muéstrame el corte", "muestrame el corte",
    "corte completo", "resumen del día", "resumen del dia",
    "cómo estuvo", "como estuvo", "qué tal estuvo", "que tal estuvo",
]

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_allowed(update): return
    texto = update.message.text
    texto_lower = texto.lower()
    msg = await update.message.reply_text("⏳ Consultando datos...")

    try:
        fecha_detectada = detectar_fecha(texto)

        # Preguntas sobre clips aromáticos
        palabras_clips = ['clip', 'clips', 'aromatico', 'aromático', 'aromaticos', 'aromáticos',
                          'inventario clips', 'stock clips', 'cuantos clips', 'cuántos clips']
        if any(p in texto_lower for p in palabras_clips):
            return await cmd_clips(update, context)

        # Preguntas sobre materiales
        palabras_mat = ['playera', 'bota', 'fregon', 'fregón', 'escoba', 'atomizador',
                        'bote', 'gatillo', 'jalador', 'recogedor', 'mechudo', 'cepillo',
                        'microfibra', 'roma', 'pinol', 'piñol', 'fabuloso', 'cloralex',
                        'cloro', 'papel tork', 'tork', 'fibra', 'scotch', 'bomba',
                        'palo escoba', 'mechudo', 'stock materiales', 'materiales', 'bodega', 'insumos']
        if any(p in texto_lower for p in palabras_mat):
            # Si menciona "sacar" o cantidad → procesar salida
            PALABRAS_SALIDA_H = [
                "sacar","saqué","saque","sacaron","se saco","se sacó","se sacaron",
                "se llevó","se llevo","se llevaron","llevaron","me llevé","me lleve",
                "se agarro","se agarró","se agarraron","agarré","agarre","agarraron",
                "tome","tomé","tomaron","se tomó","se tomo","se tomaron",
                "se dio","se dió","se dieron","dieron","entregué","entregue",
                "se entregó","se entrego","se entregaron","entregaron",
                "usé","use","usaron","se usó","se uso","se usaron",
                "gastó","gasto","gastaron","se gastó","se gasto","se gastaron",
                "salida","salieron","se fue","se fueron",
                "ocupé","ocupe","ocuparon","se ocupó","se ocupo","se ocuparon",
            ]
            if any(p in texto_lower for p in PALABRAS_SALIDA_H):
                return await _procesar_salida(update, texto)
            # Si hay número + (caja/cajas/pieza/piezas) → entrada de material
            palabras_entrada = ["entrada","llegaron","compré","compre","agregué","agregue","recibí","recibi","trajeron","traje"]
            palabras_cantidad = ["caja","cajas","pieza","piezas","unidad","unidades","pz","pzs"]
            tiene_numero = bool(re.search(r'\d', texto_lower))
            if any(p in texto_lower for p in palabras_entrada) or \
               (tiene_numero and any(p in texto_lower for p in palabras_cantidad)):
                return await _procesar_entrada(update, texto)
            return await cmd_stock_mat(update, context)

        # Si piden el corte completo → usar generar_resumen_firebase (formato fijo, siempre incluye billetes)
        es_corte_completo = any(p in texto_lower for p in PALABRAS_CORTE_COMPLETO)

        if es_corte_completo:
            if fecha_detectada:
                cortes = await get_cortes(limit=30, fecha=fecha_detectada)
            else:
                cortes = await get_cortes(limit=1)
            if not cortes:
                await msg.edit_text("No encontré corte para ese día.")
                return
            resumen = generar_resumen_firebase(cortes[0])
            await msg.edit_text(resumen, parse_mode="Markdown")
            return

        # Preguntas históricas → usar historial completo
        # Detectar si menciona mes/año pasado o fecha antigua
        meses = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto',
                 'septiembre','octubre','noviembre','diciembre']
        menciona_mes = any(m in texto_lower for m in meses)
        menciona_anio_pasado = '2025' in texto or '2024' in texto or '2026' in texto
        palabras_ranking = ['top ', 'mejores dias', 'mejores días', 'peores dias', 'peores días',
                           'ranking', 'historial', 'desde siempre', 'todos los dias', 'todos los meses',
                           'cuanto hemos', 'cuánto hemos', 'en total', 'historico', 'histórico']
        es_ranking = any(p in texto_lower for p in palabras_ranking)
        es_historico = any(p in texto_lower for p in PALABRAS_HISTORICO) or menciona_mes or menciona_anio_pasado or es_ranking

        if es_historico:
            await msg.edit_text("⏳ Consultando historial completo de Odoo...")
            try:
                # Intentar desde Firestore primero (más rápido)
                historial_odoo = await get_historial_firestore(limite=1000)
                if len(historial_odoo) < 10:
                    # Si no hay suficiente en Firestore, ir a Odoo
                    historial_odoo = await get_historial_odoo()
                prompt_hist = f"""Eres el asistente del Autolavado Star Wash en Texcoco, México. El dueño (Edwin) pregunta sobre el historial de ventas.

Fecha actual: {datetime.now().strftime("%d/%m/%Y")} (año {datetime.now().year})
IMPORTANTE: Cuando mencionen fechas sin año, asume siempre {datetime.now().year}.

Tienes acceso al historial COMPLETO del negocio con {len(historial_odoo)} días de datos.
Cada registro tiene: fecha (YYYY-MM-DD), total (ventas del día en pesos MXN), num_tickets (número de órdenes).

Historial completo:
{json.dumps(historial_odoo, ensure_ascii=False, indent=2)}

Pregunta de Edwin: {texto}

INSTRUCCIONES:
- Responde en español con emojis
- Usa los datos exactos del historial — no inventes ni estimes
- Sé específico con fechas completas (día, mes, año)
- Formato de dinero: $XX,XXX.00
- Si piden ranking o top, ordena correctamente por el criterio pedido
- No digas "últimos 90 días" — tienes el historial completo"""
                async with httpx.AsyncClient() as client_ai:
                    r = await client_ai.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                        json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1000, "messages": [{"role": "user", "content": prompt_hist}]},
                        timeout=60
                    )
                    data = r.json()
                respuesta = data["content"][0]["text"]
                respuesta = respuesta.replace("# ", "").replace("## ", "").replace("### ", "")
                await msg.edit_text(respuesta, parse_mode="Markdown")
                return
            except Exception as e:
                logger.error(f"Error historial Odoo: {e}")
                await msg.edit_text(f"❌ Error consultando historial: {str(e)}")
                return

        # Preguntas analíticas → Claude con contexto completo
        if fecha_detectada:
            cortes_fecha = await get_cortes(limit=30, fecha=fecha_detectada)
            cortes_recientes = await get_cortes(limit=5)
            ids_vistos = {c["_id"] for c in cortes_fecha}
            cortes = cortes_fecha + [c for c in cortes_recientes if c["_id"] not in ids_vistos]
        else:
            cortes = await get_cortes(limit=10)

        if not cortes:
            await msg.edit_text("No hay cortes guardados aún para responder tu pregunta.")
            return

        respuesta = await consultar_claude(texto, cortes)
        # Limpiar formato incompatible con Telegram Markdown
        respuesta = respuesta.replace("# ", "").replace("## ", "").replace("### ", "")
        await msg.edit_text(respuesta, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error en handle_text: {e}")
        await msg.edit_text(f"❌ Error consultando datos: {str(e)}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
# ── WEBHOOK HTTP para recibir cortes desde el HTML ────────────────────────────
_bot_app = None  # referencia global al bot

# ── ODOO PROXY ───────────────────────────────────────────────────────────────
async def odoo_uid(client):
    """Obtiene el UID usando XML-RPC con API key."""
    import xmlrpc.client
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_KEY, {})
    logger.info(f"Odoo XML-RPC uid={uid}")
    if not uid:
        raise Exception("Odoo XML-RPC auth failed")
    return uid

async def odoo_call(client, uid, model, method, args=[], kwargs={}):
    """Hace una llamada XML-RPC a Odoo."""
    import xmlrpc.client
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    result = models.execute_kw(ODOO_DB, uid, ODOO_KEY, model, method, args, kwargs)
    return result

async def handle_odoo_fields(request):
    """Endpoint temporal para ver campos de pos.session."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            uid = await odoo_uid(client)
            fields = await odoo_call(client, uid, 'pos.session', 'fields_get', [], {'attributes': ['string', 'type']})
            # Filtrar campos relevantes de caja/efectivo
            relevant = {k: v for k, v in fields.items() if any(w in k.lower() for w in ['cash', 'total', 'amount', 'register', 'balance'])}
        return web.Response(text=json.dumps(relevant, indent=2), headers={'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json'})
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), status=500, headers={'Access-Control-Allow-Origin': '*'})

async def handle_odoo_sesiones(request):
    """Devuelve sesiones POS de Odoo. Con ?fecha=YYYY-MM-DD filtra ese día."""
    try:
        from datetime import datetime, timedelta, timezone
        fecha_str = request.rel_url.query.get('fecha')  # YYYY-MM-DD opcional
        async with httpx.AsyncClient(timeout=30) as client:
            uid = await odoo_uid(client)
            CORS_HEADERS = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Content-Type': 'application/json'
            }
            if fecha_str:
                # Filtrar exactamente ese día en UTC-6 (= UTC+6h)
                # medianoche CDMX = fecha 06:00 UTC
                d0 = datetime.strptime(fecha_str, '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(hours=6)
                d1 = d0 + timedelta(hours=24)
                utc_start = d0.strftime('%Y-%m-%d %H:%M:%S')
                utc_end   = d1.strftime('%Y-%m-%d %H:%M:%S')
                # Sesiones que iniciaron ese día
                sesiones = await odoo_call(client, uid, 'pos.session', 'search_read',
                    [[['start_at', '>=', utc_start], ['start_at', '<', utc_end]]],
                    {
                        'fields': ['id', 'name', 'start_at', 'stop_at', 'state',
                                   'total_payments_amount', 'cash_register_balance_start',
                                   'cash_register_difference'],
                        'order': 'start_at desc',
                        'limit': 5
                    }
                )
                # Si no hay sesión que inició ese día, buscar sesión abierta (puede haber
                # iniciado el día anterior y todavía no se cierra)
                if not sesiones:
                    sesiones = await odoo_call(client, uid, 'pos.session', 'search_read',
                        [[['state', '=', 'opened']]],
                        {
                            'fields': ['id', 'name', 'start_at', 'stop_at', 'state',
                                       'total_payments_amount', 'cash_register_balance_start',
                                       'cash_register_difference'],
                            'limit': 1
                        }
                    )
            else:
                # Sin fecha: devolver últimas 20 sesiones (2 turnos/día = ~10 días)
                hace_14_dias = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d 00:00:00')
                sesiones_cerradas = await odoo_call(client, uid, 'pos.session', 'search_read',
                    [[['state', '=', 'closed'], ['stop_at', '>=', hace_14_dias]]],
                    {
                        'fields': ['id', 'name', 'start_at', 'stop_at', 'state',
                                   'total_payments_amount', 'cash_register_balance_start',
                                   'cash_register_difference'],
                        'order': 'stop_at desc',
                        'limit': 20
                    }
                )
                sesiones_abiertas = await odoo_call(client, uid, 'pos.session', 'search_read',
                    [[['state', '=', 'opened']]],
                    {
                        'fields': ['id', 'name', 'start_at', 'stop_at', 'state',
                                   'total_payments_amount', 'cash_register_balance_start',
                                   'cash_register_difference'],
                        'limit': 1
                    }
                )
                sesiones = sesiones_abiertas + sesiones_cerradas
        return web.Response(text=json.dumps(sesiones), headers=CORS_HEADERS)
    except Exception as e:
        logger.error(f"Error odoo_sesiones: {e}")
        return web.Response(text=json.dumps({"error": str(e)}), status=500,
                           headers={'Access-Control-Allow-Origin': '*'})

async def handle_odoo_sesion_detalle(request):
    """Devuelve el detalle completo de una sesión POS."""
    try:
        session_id = int(request.match_info['session_id'])
        async with httpx.AsyncClient(timeout=30) as client:
            uid = await odoo_uid(client)

            # Sesión
            sesiones = await odoo_call(client, uid, 'pos.session', 'search_read',
                [[['id', '=', session_id]]],
                {'fields': ['name', 'start_at', 'stop_at', 'state', 'total_payments_amount', 'cash_register_balance_start', 'cash_register_difference'], 'limit': 1}
            )
            sesion = sesiones[0] if sesiones else {}

            # Pagos agrupados
            pagos = await odoo_call(client, uid, 'pos.payment', 'search_read',
                [[['session_id', '=', session_id]]],
                {'fields': ['amount', 'payment_method_id'], 'limit': 1000}
            )

            # Líneas de venta
            lineas = await odoo_call(client, uid, 'pos.order.line', 'search_read',
                [[['order_id.session_id', '=', session_id]]],
                {'fields': ['product_id', 'qty', 'price_unit', 'price_subtotal_incl'], 'limit': 2000}
            )

            # Gastos / salidas de caja de la sesión
            # Los gastos aparecen como account.bank.statement.line con nombre
            # tipo "POS/00525-out-masking", amount negativo, vinculados al diario
            # de la sesión a través de pos_session_id o del nombre de la sesión.
            sesion_name = sesion.get('name', '')  # e.g. "POS/00525"
            gastos_raw = []

            # Método 1: account.bank.statement.line filtrado por nombre de sesión (más directo)
            try:
                gastos_raw = await odoo_call(client, uid, 'account.bank.statement.line', 'search_read',
                    [[['payment_ref', 'like', f'{sesion_name}-out-'], ['amount', '<', 0]]],
                    {'fields': ['amount', 'payment_ref', 'narration', 'name'], 'limit': 200}
                )
            except Exception:
                pass

            # Método 2: pos_session_id si el campo existe (Odoo 14/15/16 según versión)
            if not gastos_raw:
                try:
                    gastos_raw = await odoo_call(client, uid, 'account.bank.statement.line', 'search_read',
                        [[['pos_session_id', '=', session_id], ['amount', '<', 0]]],
                        {'fields': ['amount', 'payment_ref', 'narration', 'name'], 'limit': 200}
                    )
                except Exception:
                    pass

            # Método 3: pos.payment con monto negativo (algunas versiones Odoo 17)
            if not gastos_raw:
                try:
                    gastos_raw = await odoo_call(client, uid, 'pos.payment', 'search_read',
                        [[['session_id', '=', session_id], ['amount', '<', 0]]],
                        {'fields': ['amount', 'payment_method_id', 'name'], 'limit': 200}
                    )
                except Exception:
                    pass

            # Normalizar gastos a lista {concepto, monto}
            # El concepto viene del nombre: "POS/00525-out-masking" → "masking"
            import re
            gastos_norm = []
            for g in gastos_raw:
                monto = abs(float(g.get('amount', 0)))
                if monto == 0:
                    continue
                # Extraer concepto limpio: quitar prefijo "POS/XXXXX-out-"
                raw_ref = (g.get('payment_ref') or g.get('name') or g.get('narration') or
                           (g.get('payment_method_id') and g['payment_method_id'][1]) or 'Gasto')
                concepto = re.sub(r'^POS/\d+-out-', '', str(raw_ref), flags=re.IGNORECASE).strip()
                if not concepto:
                    concepto = 'Gasto'
                gastos_norm.append({'concepto': concepto, 'monto': round(monto, 2)})

        result = {
            'sesion': sesion,
            'pagos': pagos,
            'lineas': lineas,
            'gastos': gastos_norm,
        }
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Content-Type': 'application/json'
        }
        return web.Response(text=json.dumps(result, default=str), headers=headers)
    except Exception as e:
        logger.error(f"Error odoo_detalle: {e}")
        return web.Response(text=json.dumps({"error": str(e)}), status=500,
                           headers={'Access-Control-Allow-Origin': '*'})

async def handle_options(request):
    """Maneja preflight CORS."""
    return web.Response(headers={
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    })

async def handle_enviar_reporte(request):
    """Recibe un resumen de corte desde el botón 📤 Enviar Reporte y lo manda a Telegram."""
    try:
        data = await request.json()
        texto = data.get("texto", "").strip()
        if not texto:
            return web.Response(text="sin texto", status=400)
        if _bot_app:
            for uid in ALLOWED_USERS:
                await _bot_app.bot.send_message(
                    chat_id=uid,
                    text=texto,
                    parse_mode="Markdown"
                )
        return web.Response(text="ok")
    except Exception as e:
        logger.error(f"Error en handle_enviar_reporte: {e}")
        return web.Response(text=f"error: {e}", status=500)

async def handle_corte_nuevo(request):
    """Recibe un corte guardado desde el HTML y manda auditoría por Telegram."""
    try:
        corte = await request.json()
        # Obtener historial para comparar (excluir el corte actual)
        historial = await get_cortes(limit=10)
        fecha_actual = corte.get("fecha", "")
        historial = [c for c in historial if c.get("fecha") != fecha_actual]

        auditoria_msg = await auditar_corte(corte, historial)

        if _bot_app:
            for uid in ALLOWED_USERS:
                await _bot_app.bot.send_message(
                    chat_id=uid,
                    text=auditoria_msg,
                    parse_mode="Markdown"
                )
        return web.Response(text="ok")
    except Exception as e:
        logger.error(f"Error en handle_corte_nuevo: {e}")
        return web.Response(text=f"error: {e}", status=500)

async def run_web_server():
    """Servidor HTTP para recibir notificaciones del HTML."""
    server = web.Application()
    server.router.add_post("/corte-nuevo", handle_corte_nuevo)
    server.router.add_post("/enviar-reporte", handle_enviar_reporte)
    server.router.add_get("/odoo/sesiones", handle_odoo_sesiones)
    server.router.add_get("/odoo/fields", handle_odoo_fields)
    server.router.add_get("/odoo/sesion/{session_id}", handle_odoo_sesion_detalle)
    server.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Servidor HTTP en puerto {port}")

def main():
    global _bot_app
    app = Application.builder().token(BOT_TOKEN).build()
    _bot_app = app
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ultimo", cmd_ultimo))
    app.add_handler(CommandHandler("hoy", cmd_hoy))
    app.add_handler(CommandHandler("records", cmd_records))
    app.add_handler(CommandHandler("fecha", cmd_fecha))
    app.add_handler(CommandHandler("historial", cmd_historial))
    app.add_handler(CommandHandler("sincronizar", cmd_sincronizar))
    app.add_handler(CommandHandler("comparar", cmd_comparar))
    app.add_handler(CommandHandler("comparar_semana", cmd_comparar_semana))
    app.add_handler(CommandHandler("actualizar_cortes", cmd_actualizar_cortes))
    app.add_handler(CommandHandler("exportar", cmd_exportar))
    app.add_handler(CommandHandler("clips", cmd_clips))
    app.add_handler(CommandHandler("stock_mat", cmd_stock_mat))
    app.add_handler(CommandHandler("sacar", cmd_sacar_mat))
    app.add_handler(CommandHandler("entrada", cmd_entrada_mat))
    app.add_handler(CommandHandler("movimientos_mat", cmd_movimientos_mat))
    app.add_handler(CallbackQueryHandler(callback_responsable, pattern="^(resp|var|ent_mat|ent_tipo|ent_grp|ent_resp|sal_resp|sal_mat|sal_mat_grp|sal_dest):"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    import asyncio

    async def run_all():
        await run_web_server()
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot iniciado con servidor HTTP...")
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    asyncio.run(run_all())

if __name__ == "__main__":
    main()
