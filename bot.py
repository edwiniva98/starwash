import os
import logging
import json
import base64
from datetime import datetime
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN          = os.environ.get("BOT_TOKEN", "")
OWNER_ID           = int(os.environ.get("OWNER_ID", "0"))
CLAUDE_KEY         = os.environ.get("ANTHROPIC_API_KEY", "")
FIREBASE_PROJECT   = os.environ.get("FIREBASE_PROJECT_ID", "starwash-cortes")
FIRESTORE_URL      = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}/databases/(default)/documents"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── FIREBASE ──────────────────────────────────────────────────────────────────
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
            if fecha in corte.get("fecha",""):
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
            result[key] = [parse_firestore(i.get("mapValue",{}).get("fields",{})) if "mapValue" in i else list(i.values())[0] for i in items]
        elif "timestampValue" in val:
            result[key] = val["timestampValue"]
    return result

# ── FORMAT ────────────────────────────────────────────────────────────────────
def fmt(n):
    try: return f"${float(n):,.2f}"
    except: return "$0.00"

def generar_resumen_firebase(corte):
    """Genera resumen completo desde datos de Firebase."""
    v = corte.get("ventas", {})
    a = corte.get("adicionales", {})
    p = corte.get("pagos", {})
    c = corte.get("caja", {})
    t = corte.get("totales", {})
    m = corte.get("maquina", {})
    o = corte.get("otros", {})

    autos_pagados = sum([v.get("autos",0), v.get("camionetas",0), v.get("pickups",0), v.get("express",0), v.get("fiscalia",0)])
    total_entraron = autos_pagados + o.get("cortes_taller",0) + o.get("cortes_ayto",0) + o.get("seguro",0)
    dif_din = t.get("diferencia_din", 0)
    dif_maq = m.get("diferencia", 0)

    estado_din = "✅ Cuadra exacto" if dif_din == 0 else (f"⚠️ Sobra {fmt(abs(dif_din))}" if dif_din > 0 else f"❌ Falta {fmt(abs(dif_din))}")
    estado_maq = "✅ Cuadra exacto" if dif_maq == 0 else (f"⚠️ +{dif_maq} en máquina (posible sin cobrar)" if dif_maq > 0 else f"⚠️ {abs(dif_maq)} menos en máquina")

    msg = f"⚡ *STAR WASH — CORTE DEL DÍA*\n"
    msg += f"📅 {corte.get('fecha','—')} | 🔖 {corte.get('sesion','—')}\n"
    msg += f"👤 {corte.get('responsable','—')}\n\n"

    msg += f"🚗 *VEHÍCULOS*\n"
    msg += f"• Autos: {v.get('autos',0)} | Camionetas: {v.get('camionetas',0)} | Pick-Ups: {v.get('pickups',0)}\n"
    msg += f"• Express: {v.get('express',0)} | Fiscalía: {v.get('fiscalia',0)} | Motos: {v.get('motos',0)}\n"
    msg += f"• *Autos pagados: {autos_pagados}* | Cortesías: {o.get('cortes_taller',0)+o.get('cortes_ayto',0)} | Seguro: {o.get('seguro',0)}\n"
    msg += f"• *Total entraron: {total_entraron}* | Máquina: {m.get('total_vendidos',0)}\n"
    msg += f"• {estado_maq}\n\n"

    msg += f"💰 *VENTAS ODOO*\n"
    msg += f"• Total tickets: *{fmt(t.get('total_tickets',0))}*\n"
    msg += f"• Efectivo: {fmt(p.get('efectivo',0))} | Tarjeta: {fmt(p.get('tarjeta',0))} | Trans: {fmt(p.get('transferencia',0))}\n"
    msg += f"• Total cobrado: *{fmt(t.get('total_cobrado',0))}*\n\n"

    msg += f"🏦 *CONTROL DE CAJA*\n"
    msg += f"• Apertura: {fmt(c.get('apertura',0))}\n"
    msg += f"• Morralla: {fmt(c.get('morralla',0))} | Billetes: {fmt(c.get('billetes',0))} | Terminal: {fmt(c.get('terminal',0))}\n"
    msg += f"• *Total en caja: {fmt(t.get('total_caja',0))}*\n\n"

    msg += f"📊 *RESULTADO: {estado_din}*\n\n"

    gastos = corte.get("gastos", [])
    if gastos:
        total_g = t.get("total_gastos", 0)
        msg += f"💸 *GASTOS: {fmt(total_g)}*\n"
        for g in gastos:
            if isinstance(g, dict) and g.get("concepto") and g.get("monto",0) > 0:
                msg += f"• {g['concepto']}: {fmt(g['monto'])}\n"

    svc = corte.get("servicios_manuales", [])
    if svc:
        msg += f"\n✨ *SERVICIOS MANUALES*\n"
        for s in svc:
            if isinstance(s, dict) and s.get("nombre") and s.get("total",0) > 0:
                msg += f"• {s['nombre']}: {fmt(s['total'])}\n"

    notas = [n for n in corte.get("notas", []) if n and str(n).strip()]
    if notas:
        msg += f"\n📝 *NOTAS*\n"
        for i, n in enumerate(notas, 1):
            msg += f"{i}. {n}\n"

    return msg

# ── CLAUDE ────────────────────────────────────────────────────────────────────
async def consultar_claude(pregunta, cortes):
    """Usa Claude para responder preguntas sobre los cortes."""
    resumen = []
    for c in cortes:
        t = c.get("totales", {})
        resumen.append({
            "fecha": c.get("fecha"),
            "sesion": c.get("sesion"),
            "autos_pagados": sum([c.get("ventas",{}).get(k,0) for k in ["autos","camionetas","pickups","express","fiscalia"]]),
            "total_tickets": t.get("total_tickets",0),
            "total_caja": t.get("total_caja",0),
            "total_gastos": t.get("total_gastos",0),
            "diferencia": t.get("diferencia_din",0),
            "maquina_dif": c.get("maquina",{}).get("diferencia",0),
        })

    prompt = f"""Eres el asistente del Autolavado Star Wash. El dueño (Edwin) te hace una pregunta sobre los cortes del negocio.

Datos disponibles de los últimos cortes:
{json.dumps(resumen, ensure_ascii=False, indent=2)}

Pregunta de Edwin: {pregunta}

Responde de forma concisa y directa en español. Usa emojis. Si no tienes los datos para responder dilo claramente."""

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]},
            timeout=30
        )
        data = r.json()
    return data["content"][0]["text"]

# ── HANDLERS ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hola! Soy el bot de *Star-Wash Cortes*.\n\n"
        "Puedo hacer lo siguiente:\n"
        "📊 /ultimo — Ver el último corte guardado\n"
        "📅 /fecha 2026-06-15 — Ver corte de una fecha\n"
        "📋 /historial — Ver últimos 5 cortes\n"
        "💬 O pregúntame algo: _¿cómo estuvo ayer?_\n\n"
        "📸 También mándame foto de la lectura de máquina y te la registro.",
        parse_mode="Markdown"
    )

async def cmd_ultimo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Buscando el último corte...")
    cortes = await get_cortes(limit=1)
    if not cortes:
        await msg.edit_text("No hay cortes guardados aún.")
        return
    resumen = generar_resumen_firebase(cortes[0])
    await msg.edit_text(resumen, parse_mode="Markdown")

async def cmd_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def cmd_historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        autos = sum([c.get("ventas",{}).get(k,0) for k in ["autos","camionetas","pickups","express","fiscalia"]])
        texto += f"{estado} *{c.get('fecha','—')}* — {c.get('sesion','—')}\n"
        texto += f"   🚗 {autos} autos | 💰 {fmt(t.get('total_tickets',0))} | 💸 {fmt(t.get('total_gastos',0))} gastos\n\n"
    await msg.edit_text(texto, parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.lower()
    msg = await update.message.reply_text("⏳ Consultando datos...")
    try:
        cortes = await get_cortes(limit=10)
        respuesta = await consultar_claude(update.message.text, cortes)
        await msg.edit_text(respuesta, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Error consultando datos: {str(e)}")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ultimo", cmd_ultimo))
    app.add_handler(CommandHandler("fecha", cmd_fecha))
    app.add_handler(CommandHandler("historial", cmd_historial))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot iniciado...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
