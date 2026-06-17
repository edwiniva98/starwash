import os
import logging
import asyncio
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic
import base64

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8862800216:AAGo_dp-Po2k_NysaY1ct0AodmMHZQ0sKv4")
OWNER_ID    = int(os.environ.get("OWNER_ID", "1159452620"))
CLAUDE_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

anthropic_client = anthropic.Anthropic(api_key=CLAUDE_KEY)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def fmt(n):
    return f"${n:,.2f}"

async def analizar_pdf(pdf_bytes: bytes) -> dict:
    """Extrae datos del Reporte Z usando Claude."""
    b64 = base64.standard_b64encode(pdf_bytes).decode()
    
    prompt = """Extrae datos del Reporte Z de Odoo de Star Wash. Devuelve SOLO JSON válido.

{
  "sesion": "POS/XXXXX",
  "fecha": "DD/MM/YYYY",
  "ventas": {
    "autos": 0, "camionetas": 0, "pickups": 0,
    "express": 0, "fiscalia": 0, "motos": 0
  },
  "adicionales": {
    "tapetes_solo": 0, "motor": 0, "mano": 0,
    "plus_cera": 0, "pro_cera_tapetes": 0
  },
  "pagos": {"efectivo": 0, "tarjeta": 0, "transferencia": 0},
  "total": 0,
  "gastos_odoo": [{"concepto": "", "monto": 0}]
}

Si algo no aparece pon 0. No inventes datos."""

    response = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )
    
    import json
    txt = response.content[0].text.replace("```json", "").replace("```", "").strip()
    return json.loads(txt)

def generar_resumen(data: dict) -> str:
    """Genera el mensaje de resumen para Telegram."""
    v = data.get("ventas", {})
    a = data.get("adicionales", {})
    p = data.get("pagos", {})
    
    autos_pagados = v.get("autos",0) + v.get("camionetas",0) + v.get("pickups",0) + v.get("express",0) + v.get("fiscalia",0)
    total_lavados = autos_pagados + v.get("motos",0)
    
    total_ventas = (
        v.get("autos",0)*110 + v.get("camionetas",0)*120 +
        v.get("pickups",0)*140 + v.get("express",0)*90 +
        v.get("fiscalia",0)*80 + v.get("motos",0)*60
    )
    total_adics = (
        a.get("tapetes_solo",0)*40 + a.get("motor",0)*60 +
        a.get("mano",0)*20 + a.get("plus_cera",0)*20 +
        a.get("pro_cera_tapetes",0)*50
    )
    total_tickets = total_ventas + total_adics
    total_cobrado = p.get("efectivo",0) + p.get("tarjeta",0) + p.get("transferencia",0)
    diferencia = total_cobrado - total_tickets
    
    estado_din = "✅ Cuadra" if diferencia == 0 else (f"⚠️ Sobra {fmt(diferencia)}" if diferencia > 0 else f"❌ Falta {fmt(abs(diferencia))}")
    
    msg = f"""⚡ *STAR WASH — CORTE DEL DÍA*
📅 {data.get('fecha','—')} | 🔖 {data.get('sesion','—')}

🚗 *VEHÍCULOS*
• Autos pagados: *{autos_pagados}*
• Motos: {v.get('motos',0)}
• Total lavados: {total_lavados}

💰 *VENTAS*
• Total tickets: *{fmt(total_tickets)}*
• Efectivo: {fmt(p.get('efectivo',0))}
• Tarjeta: {fmt(p.get('tarjeta',0))}
• Transferencia: {fmt(p.get('transferencia',0))}
• Total cobrado: *{fmt(total_cobrado)}*

📊 *ESTADO: {estado_din}*

➕ *ADICIONALES*
• Plus+Cera: {a.get('plus_cera',0)} uds
• Pro Cera+Tapetes: {a.get('pro_cera_tapetes',0)} uds
• Lavado a mano: {a.get('mano',0)} uds"""

    gastos = data.get("gastos_odoo", [])
    if gastos:
        total_gastos = sum(g.get("monto",0) for g in gastos if g.get("monto",0) > 0)
        msg += f"\n\n💸 *GASTOS: {fmt(total_gastos)}*"
        for g in gastos:
            if g.get("concepto") and g.get("monto",0) > 0:
                msg += f"\n• {g['concepto']}: {fmt(g['monto'])}"

    return msg

# ── HANDLERS ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hola! Soy el bot de Star Wash.\n\n"
        "📄 Mándame el PDF del Reporte Z de Odoo y te doy el resumen del día.\n"
        "📸 También puedes mandarme la foto de la lectura de la máquina."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.mime_type == "application/pdf":
        await update.message.reply_text("Por favor manda un archivo PDF.")
        return
    
    msg = await update.message.reply_text("⏳ Leyendo el reporte Z...")
    
    try:
        file = await context.bot.get_file(doc.file_id)
        pdf_bytes = await file.download_as_bytearray()
        
        data = await analizar_pdf(bytes(pdf_bytes))
        resumen = generar_resumen(data)
        
        await msg.edit_text("✅ Reporte procesado!")
        
        # Mandar resumen al cajero
        await update.message.reply_text(resumen, parse_mode="Markdown")
        
        # Mandar también al dueño si no es él quien mandó
        if update.effective_user.id != OWNER_ID:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"📬 *Corte recibido de {update.effective_user.first_name}*\n\n{resumen}",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error procesando PDF: {e}")
        await msg.edit_text(f"❌ Error procesando el PDF: {str(e)}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reenvía la foto de lectura de máquina al dueño."""
    caption = update.message.caption or "📸 Foto de lectura de máquina"
    sender = update.effective_user.first_name
    
    # Confirmar al cajero
    await update.message.reply_text("✅ Foto recibida, se enviará al dueño.")
    
    # Reenviar al dueño si no es él
    if update.effective_user.id != OWNER_ID:
        photo = update.message.photo[-1]  # mejor calidad
        await context.bot.send_photo(
            chat_id=OWNER_ID,
            photo=photo.file_id,
            caption=f"📸 Lectura de máquina de {sender}\n{caption}"
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Para procesar el corte del día:\n"
        "📄 Manda el PDF del Reporte Z de Odoo\n"
        "📸 Manda foto de la lectura de máquina"
    )

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot iniciado...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
