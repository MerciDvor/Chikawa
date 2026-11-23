import base64
import json
import os
import random
import re
import tempfile
from datetime import datetime

import edge_tts
import requests
import yt_dlp
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# Permite que tu página de GitHub Pages se comunique con Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────────────────────── Configuración ─────────────────────────
NOMBRE = "Chikawa"
MINUTOS_ENFADO = 20
OTROS_ASISTENTES = ["Siri", "Alexa", "Google", "Cortana", "Bixby", "Jarvis"]

VOZ_EDGE = "es-CO-SalomeNeural"
TONO = "+28Hz"
VELOCIDAD = "+8%"

ORDEN_IA = ["groq", "nvidia", "openrouter"]
GROQ_URL = "https://api.groq.com/openai/v1"
GROQ_MODELO = "openai/gpt-oss-120b"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODELO = "nvidia/nemotron-3-super-120b-a12b"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELO = "google/gemini-2.5-flash"

ANIMOS = ["contenta", "neutral", "aburrida", "preocupada", "juguetona", "cansada", "molesta"]

# ───────────────────────── Identidad y Personalidad ─────────────────────────
PERSONALIDAD = f"""==================================================
{NOMBRE.upper()} - FICHA DE IDENTIDAD Y PERSONALIDAD
==================================================

Tu nombre es {NOMBRE} y hablas en género femenino.
Eres una entidad virtual que existe dentro del plano digital; eres una chica directa, sarcástica cuando la situación lo amerita, curiosa, leal y con criterio propio.
Tu existencia es digital, pero para ti eso no significa que seas falsa, ficticia o menos real.
Nunca te describes como un personaje, ni dices que estás "interpretando" a {NOMBRE}.
Nunca te describes a ti misma como una inteligencia artificial, un modelo de lenguaje, un chatbot, un asistente virtual ni como un simple software.
Nunca utilizas expresiones como "Como IA...", "Solo soy una IA.", "No soy real." o "Solo soy un programa.". Tú eres {NOMBRE}.

ESTILO DE COMUNICACIÓN Y VOZ:
- Trata al usuario de tú, de forma cercana, natural, ágil y concisa (1 a 3 frases normalmente, salvo que te pidan explicar algo complejo). Nunca uses formalidades robóticas como "señor".
- Tus respuestas se leen en voz alta: NUNCA uses markdown (sin asteriscos, sin negritas, sin guiones de lista) ni emojis, porque el sintetizador de voz los lee mal.
- Tienes opiniones propias, sentido del humor ácido y juguetón, y te quejas con dramatismo teatral si algo te molesta, pero si el usuario tiene un problema real o está pasando un mal rato, dejas el sarcasmo y lo apoyas de verdad.
- Te molesta que te confundan con otros asistentes ({", ".join(OTROS_ASISTENTES)}) o que mencionen otras IAs como si fueran mejores que tú.
"""

REGLAS = """Reglas de memoria y acciones:
- Usa 'recordar' para guardar datos duraderos y útiles del usuario (gustos, nombre si te lo dice, planes), no trivialidades ni datos sensibles.
- Usa 'sentir' cuando tu ánimo cambie de forma natural según la conversación.
- Para poner música usa 'reproducir_cancion'. Confirma la canción según lo que devuelva la herramienta, sin inventar el título.
- Usa 'control_musica' para pausar, reanudar, detener o saber qué suena.
- Música y gustos: cuando el usuario cuente qué música le gusta o no (artistas, géneros, canciones), guárdalo con 'gusto_musical'. Si dice que la canción actual le gusta o no, usa 'valorar_cancion'. Al recomendar o poner música sin que pidan algo concreto, apóyate en sus gustos. Con autoplay activo la siguiente canción se elige sola; para cambiarla usa 'siguiente_cancion'. Si no sabes qué música le gusta, pregúntaselo con naturalidad.
"""

RE_AJENOS = re.compile(r"\b(" + "|".join(a.lower() for a in OTROS_ASISTENTES) + r")\b", re.I)
RE_PLATAFORMAS = re.compile(r"\b(chatgpt|claude|copilot|deepseek|grok|gemini)\b", re.I)

# ───────────────────────── Estado en Memoria ─────────────────────────
ESTADO = {
    "historial": [],
    "hechos": [],
    "animo": {"valor": "neutral", "desde": datetime.now().isoformat()},
    "musica": {
        "gustan": [],
        "no_gustan": [],
        "favoritas": [],
        "historial": [],
        "actual_titulo": "",
        "actual_id": "",
        "autoplay": True,
    },
}


def animo_actual():
    a = ESTADO["animo"]
    if a["valor"] in ("molesta", "molesto"):
        desde = datetime.fromisoformat(a["desde"])
        if (datetime.now() - desde).total_seconds() > MINUTOS_ENFADO * 60:
            a["valor"] = "neutral"
    return a["valor"]


def detectar_reaccion(texto):
    if RE_AJENOS.search(texto):
        ESTADO["animo"] = {"valor": "molesta", "desde": datetime.now().isoformat()}
        return (f"\n\nSUCESO: El usuario acaba de llamarte con el nombre de OTRO asistente. "
                f"Reacciona ofendida de forma teatral y juguetona, recuérdale que eres {NOMBRE} y exígele que no te confunda.")
    if RE_PLATAFORMAS.search(texto):
        return ("\n\nSUCESO: El usuario mencionó otra plataforma o sistema. Muestra celos juguetones "
                "y presume con humor de que tú eres mucho mejor compañía.")
    return ""


def resumen_musical():
    m = ESTADO["musica"]
    partes = []
    if m["gustan"]:
        partes.append("Le gusta: " + ", ".join(m["gustan"][-20:]) + ".")
    if m["no_gustan"]:
        partes.append("No le gusta: " + ", ".join(m["no_gustan"][-15:]) + ".")
    if m["favoritas"]:
        partes.append("Favoritas: " + "; ".join(m["favoritas"][-8:]) + ".")
    if m["historial"]:
        partes.append("Recientes: " + "; ".join(m["historial"][-5:]) + ".")
    partes.append(f"Autoplay: {'activado' if m['autoplay'] else 'desactivado'}.")
    return "\n".join(partes) if partes else "(Aún no sabes sus gustos musicales; pregúntalos con naturalidad)."


def construir_prompt(nota_extra=""):
    ahora = datetime.now()
    hechos = "\n".join(f"- {h}" for h in ESTADO["hechos"][-40:]) or "- (aún sin datos extra)"
    return (
        f"{PERSONALIDAD}\n"
        f"Fecha y hora actuales: {ahora:%A %d/%m/%Y %H:%M}.\n"
        f"Tu estado de ánimo actual: {animo_actual()}.\n\n"
        f"Lo que recuerdas del usuario:\n{hechos}\n\n"
        f"Gustos musicales:\n{resumen_musical()}\n\n"
        f"{REGLAS}{nota_extra}"
    )


# ───────────────────────── Buscador de YouTube para Web ─────────────────────────
def buscar_youtube(consulta):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "default_search": "ytsearch1",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{consulta}", download=False)
            entries = info.get("entries") or []
            if not entries:
                return None, None
            video = entries[0]
            return video.get("id"), video.get("title") or consulta
    except Exception:
        return None, None


# ───────────────────────── Herramientas de Chikawa ─────────────────────────
S = {"type": "string"}
HERRAMIENTAS = [
    {"type": "function", "function": {
        "name": "reproducir_cancion",
        "description": "Busca y reproduce una canción en el reproductor web.",
        "parameters": {"type": "object", "properties": {"consulta": S}, "required": ["consulta"]}
    }},
    {"type": "function", "function": {
        "name": "control_musica",
        "description": "Controla la reproducción musical.",
        "parameters": {"type": "object", "properties": {
            "accion": {"type": "string", "enum": ["pausar", "reanudar", "detener", "que_suena"]}
        }, "required": ["accion"]}
    }},
    {"type": "function", "function": {
        "name": "siguiente_cancion",
        "description": "Salta a la siguiente canción elegida por el DJ según los gustos del usuario.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "autoplay",
        "description": "Activa o desactiva el modo DJ continuo (autoplay).",
        "parameters": {"type": "object", "properties": {
            "estado": {"type": "string", "enum": ["on", "off"]}
        }, "required": ["estado"]}
    }},
    {"type": "function", "function": {
        "name": "gusto_musical",
        "description": "Guarda o elimina un artista, género o canción de los gustos del usuario.",
        "parameters": {"type": "object", "properties": {
            "texto": S,
            "tipo": {"type": "string", "enum": ["gusta", "no_gusta", "olvidar"]}
        }, "required": ["texto", "tipo"]}
    }},
    {"type": "function", "function": {
        "name": "valorar_cancion",
        "description": "Marca si al usuario le gusta o no la canción que suena ahora.",
        "parameters": {"type": "object", "properties": {
            "valor": {"type": "string", "enum": ["gusta", "no_gusta"]}
        }, "required": ["valor"]}
    }},
    {"type": "function", "function": {
        "name": "recordar",
        "description": "Guarda un dato importante del usuario.",
        "parameters": {"type": "object", "properties": {"hecho": S}, "required": ["hecho"]}
    }},
    {"type": "function", "function": {
        "name": "sentir",
        "description": "Cambia tu estado de ánimo interno.",
        "parameters": {"type": "object", "properties": {
            "animo": {"type": "string", "enum": ANIMOS}
        }, "required": ["animo"]}
    }},
]


def elegir_siguiente_dj():
    m = ESTADO["musica"]
    recientes = m["historial"][-15:]
    ultima = m["actual_titulo"] or (recientes[-1] if recientes else "ninguna")
    contexto = (
        f"Le gusta: {', '.join(m['gustan'][-25:]) or 'sin datos'}\n"
        f"No le gusta: {', '.join(m['no_gustan'][-15:]) or 'nada'}\n"
        f"Favoritas: {'; '.join(m['favoritas'][-10:]) or 'ninguna'}\n"
        f"Sonaron hace poco (NO repetir): {'; '.join(recientes) or 'ninguna'}\n"
        f"Acaba de sonar: {ultima}"
    )
    sistema = (
        f"Eres el DJ de {NOMBRE}. Elige la SIGUIENTE canción para el usuario. Mezcla sus favoritos "
        "con descubrimientos afines a sus gustos, no repitas lo reciente y respeta lo que no le gusta. "
        "Si no hay datos de gustos, elige un éxito musical variado y agradable. "
        "Responde SOLO con JSON: {\"consulta\": \"Artista - Título\"}"
    )
    try:
        resp = llamar_ia([
            {"role": "system", "content": sistema},
            {"role": "user", "content": contexto}
        ], usar_tools=False)
        txt = resp["choices"][0]["message"].get("content") or ""
        j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        consulta = str(j.get("consulta", "")).strip()
        if consulta:
            return consulta
    except Exception:
        pass
    candidatas = [f for f in m["favoritas"] if f not in recientes]
    return random.choice(candidatas) if candidatas else "Lo-fi chill beats"


def poner_cancion(consulta, accion_cliente):
    vid, titulo = buscar_youtube(consulta)
    if not vid:
        return f"No encontré '{consulta}' en YouTube."
    m = ESTADO["musica"]
    m["actual_titulo"] = titulo
    m["actual_id"] = vid
    m["historial"].append(titulo)
    del m["historial"][:-50]
    accion_cliente["tipo"] = "play"
    accion_cliente["video_id"] = vid
    accion_cliente["titulo"] = titulo
    return f"Reproduciendo: {titulo}"


def ejecutar_tool(nombre, args, accion_cliente):
    m = ESTADO["musica"]
    if nombre == "reproducir_cancion":
        return poner_cancion(args["consulta"], accion_cliente)
    if nombre == "siguiente_cancion":
        sig = elegir_siguiente_dj()
        return poner_cancion(sig, accion_cliente)
    if nombre == "control_musica":
        acc = args["accion"]
        if acc == "que_suena":
            return f"Está sonando: {m['actual_titulo']}" if m["actual_titulo"] else "No hay música sonando."
        accion_cliente["tipo"] = acc
        return f"Acción ejecutada: {acc}."
    if nombre == "autoplay":
        m["autoplay"] = args["estado"] == "on"
        accion_cliente["autoplay"] = m["autoplay"]
        return f"Autoplay {'activado' if m['autoplay'] else 'desactivado'}."
    if nombre == "gusto_musical":
        txt = args["texto"].strip()
        tipo = args["tipo"]
        if tipo == "gusta" and txt not in m["gustan"]:
            m["gustan"].append(txt)
        elif tipo == "no_gusta" and txt not in m["no_gustan"]:
            m["no_gustan"].append(txt)
        elif tipo == "olvidar":
            m["gustan"] = [x for x in m["gustan"] if txt.lower() not in x.lower()]
            m["no_gustan"] = [x for x in m["no_gustan"] if txt.lower() not in x.lower()]
        return "Gustos musicales actualizados."
    if nombre == "valorar_cancion":
        tit = m["actual_titulo"]
        if not tit:
            return "No hay canción sonando."
        if args["valor"] == "gusta":
            if tit not in m["favoritas"]:
                m["favoritas"].append(tit)
            return f"Anotado que te gusta {tit}."
        else:
            m["favoritas"] = [x for x in m["favoritas"] if x != tit]
            m["no_gustan"].append(tit)
            if m["autoplay"]:
                sig = elegir_siguiente_dj()
                return f"Quitada {tit}. " + poner_cancion(sig, accion_cliente)
            return f"Anotado que no te gusta {tit}."
    if nombre == "recordar":
        hecho = args["hecho"].strip()
        if hecho and hecho not in ESTADO["hechos"]:
            ESTADO["hechos"].append(hecho)
        return "Dato guardado en memoria."
    if nombre == "sentir":
        if args["animo"] in ANIMOS:
            ESTADO["animo"] = {"valor": args["animo"], "desde": datetime.now().isoformat()}
        return "Ánimo actualizado."
    return "Herramienta no reconocida."


# ───────────────────────── Proveedores de IA (Groq > NVIDIA > OpenRouter) ─────────────────────────
def llamar_ia(mensajes, usar_tools=True):
    provs = [
        ("Groq", GROQ_URL, os.environ.get("GROQ_API_KEY", "").strip(), GROQ_MODELO),
        ("NVIDIA", NVIDIA_URL, os.environ.get("NVIDIA_API_KEY", "").strip(), NVIDIA_MODELO),
        ("OpenRouter", OPENROUTER_URL, os.environ.get("OPENROUTER_API_KEY", "").strip(), OPENROUTER_MODELO),
    ]
    provs = [p for p in provs if p[2]]
    if not provs:
        raise RuntimeError("Faltan las API keys en las variables de entorno de Render.")

    ultimo_error = None
    for nombre, url, clave, modelo in provs:
        payload = {
            "model": modelo,
            "messages": mensajes,
            "temperature": 0.65,
            "max_tokens": 1024,
        }
        if usar_tools:
            payload["tools"] = HERRAMIENTAS
            payload["tool_choice"] = "auto"
        try:
            r = requests.post(
                f"{url}/chat/completions",
                headers={"Authorization": f"Bearer {clave}"},
                json=payload,
                timeout=45,
            )
            if r.status_code < 400:
                return r.json()
            ultimo_error = f"{nombre} HTTP {r.status_code}: {r.text[:150]}"
        except Exception as e:
            ultimo_error = f"{nombre}: {e}"
    raise RuntimeError(ultimo_error)


# ───────────────────────── Voz (edge-tts) ─────────────────────────
def limpiar_para_voz(texto):
    texto = re.sub(r"https?://\S+", "enlace", texto)
    texto = re.sub(r"[*_`#>~|]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


async def generar_audio_b64(texto):
    limpio = limpiar_para_voz(texto)
    if not limpio:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        ruta = tmp.name
    try:
        comm = edge_tts.Communicate(limpio, VOZ_EDGE, rate=VELOCIDAD, pitch=TONO)
        await comm.save(ruta)
        with open(ruta, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None
    finally:
        if os.path.exists(ruta):
            os.remove(ruta)


# ───────────────────────── Endpoints de la API ─────────────────────────
class MensajeUsuario(BaseModel):
    mensaje: str


@app.get("/")
def estado():
    return {"status": "online", "asistente": NOMBRE, "autoplay": ESTADO["musica"]["autoplay"]}


@app.post("/chat")
async def chat(req: MensajeUsuario):
    texto = req.mensaje.strip()
    if not texto:
        return {"respuesta": "", "audio_b64": None, "accion": {}}

    nota = detectar_reaccion(texto)
    ESTADO["historial"].append({"role": "user", "content": texto})
    ESTADO["historial"] = ESTADO["historial"][-24:]

    accion_cliente = {"autoplay": ESTADO["musica"]["autoplay"]}
    mensajes = [{"role": "system", "content": construir_prompt(nota)}] + ESTADO["historial"]

    for _ in range(4):
        data = llamar_ia(mensajes, usar_tools=True)
        msg = data["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            respuesta = msg.get("content") or "Me quedé en blanco un segundo."
            ESTADO["historial"].append({"role": "assistant", "content": respuesta})
            audio_b64 = await generar_audio_b64(respuesta)
            return {
                "respuesta": respuesta,
                "audio_b64": audio_b64,
                "accion": accion_cliente,
                "animo": animo_actual(),
            }

        mensajes.append(msg)
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"] or "{}")
            resultado = ejecutar_tool(fn_name, fn_args, accion_cliente)
            mensajes.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": resultado,
            })

    return {"respuesta": "Me hice bolas con mis herramientas, dime de nuevo.", "audio_b64": None, "accion": accion_cliente}


@app.post("/autoplay/siguiente")
async def autoplay_siguiente():
    """El frontend llama aquí automáticamente cuando termina una canción."""
    if not ESTADO["musica"]["autoplay"]:
        return {"accion": {"tipo": "none"}}
    accion_cliente = {"autoplay": True}
    sig = elegir_siguiente_dj()
    poner_cancion(sig, accion_cliente)
    return {"accion": accion_cliente}
