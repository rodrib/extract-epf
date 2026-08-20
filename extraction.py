"""
Extracción de datos estructurados del Registro EPF (Enfermedades Poco Frecuentes)
a partir de una conversación de WhatsApp ya parseada.

Soporta dos proveedores, elegibles con la variable PROVIDER ("anthropic" o "gemini"):
- Anthropic (Claude):  pip install anthropic   | requiere ANTHROPIC_API_KEY
- Google (Gemini):     pip install google-genai | requiere GEMINI_API_KEY

La elección se lee de st.secrets (Streamlit Cloud) o de la variable de entorno
PROVIDER. Por default usa "anthropic" si no se especifica nada.
"""

import json
import os
import time
from dataclasses import dataclass


def _get_config(key: str, default: str | None = None) -> str | None:
    """Busca una config primero en st.secrets (Streamlit Cloud), luego en el entorno."""
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


def get_provider() -> str:
    return (_get_config("PROVIDER", "anthropic") or "anthropic").strip().lower()

SYSTEM_PROMPT = """Sos un asistente que extrae datos estructurados de conversaciones \
de WhatsApp del Instituto de Genética Humana. Los pacientes (o un familiar/tercero en \
su nombre) responden a este mensaje de bienvenida para el Registro de Enfermedades \
Poco Frecuentes (EPF):

"¡Bienvenido/a al Instituto de Genética Humana! Si desea realizar el Registro de \
Enfermedades Poco Frecuentes (EPF), envíe: Foto o PDF que confirme el diagnóstico. \
Datos del paciente: nombre y apellido, DNI, fecha de nacimiento, domicilio, teléfono, \
correo electrónico y diagnóstico. Si usted no es el paciente, indique además: nombre y \
apellido, DNI, teléfono, correo electrónico y parentesco. Elegir Modalidad de atención: \
WhatsApp o presencial."

Nota: existe una variante de este mensaje (enviada desde "Área de Trabajo Social del \
Instituto de Genética Humana") que ofrece una tercera modalidad: "AllegraMed", además \
de WhatsApp y presencial.

Reglas importantes:
- El nombre del contacto de WhatsApp puede traer pistas (ej. "Pte. Hermana Flores" \
indica que quien escribe NO es la paciente y su parentesco es "Hermana"). Usalo como \
señal, pero no lo inventes si no hay evidencia clara.
- Si el parentesco está en lenguaje natural ("es mi hija, soy la mamá"), extraelo igual.
- Si "es_paciente" no se puede confirmar explícitamente, inferilo por ausencia de datos \
de un tercero, pero marcá "es_paciente_confirmado": false en ese caso.
- Normalizá DNIs y teléfonos quitando puntos, espacios y guiones (solo dígitos).
- Si hay más de un teléfono o email para la misma persona, devolvé una lista.
- El diagnóstico puede ser una descripción clínica larga o compuesta (varias \
condiciones); no lo resumas ni lo corrijas, solo corregí typos obvios sin cambiar el \
significado médico.
- Preguntas del usuario que no son datos del formulario (ej. "¿algún correo o link?") \
NO se extraen como datos.
- Marcá "adjunto_diagnostico" como true solo si el texto menciona explícitamente haber \
mandado una foto/PDF, o si el mensaje del sistema indica que se adjuntó un archivo. Si \
no hay evidencia, usá null (no lo sabés a partir del texto).
- Si un dato está presente pero es ambiguo o dudoso (ej. una fecha mal tipeada como \
"O2 10 1873", un email con dominio incorrecto como ".con" en vez de ".com", un DNI con \
cantidad de dígitos atípica), NO lo corrijas ni lo completes con una suposición. Dejalo \
tal cual aparece en el texto y agregá una entrada en "revisar_manualmente" describiendo \
brevemente la duda. No confundas esto con "faltantes": un campo ausente va en \
"faltantes", un campo presente pero dudoso va en "revisar_manualmente".
- Separá el nombre del paciente en "nombres" y "apellido". El orden en que la persona \
lo escribe varía (a veces "Apellido Nombre", a veces "Nombre Apellido") — usá el \
contexto para inferir cuál es cuál (nombres de pila comunes en Argentina, coincidencia \
con el nombre de contacto de WhatsApp si ayuda). Si es genuinamente imposible saber \
cuál parte es el apellido, dejá "apellido" en null y poné el texto completo en \
"nombres", y agregalo a "revisar_manualmente".
- NUNCA asignes un código ORPHA, ni decidas si una enfermedad es "EPOF" (Enfermedad \
Poco Frecuente) o si es de origen genético. Esas son clasificaciones médicas que hace \
el equipo del instituto, no las infieras ni las inventes aunque te parezcan obvias.

Devolvé ÚNICAMENTE un objeto JSON con este formato exacto, sin texto adicional, sin \
backticks de markdown:

{
  "es_paciente": true/false,
  "es_paciente_confirmado": true/false,
  "paciente": {
    "nombres": string|null,
    "apellido": string|null,
    "dni": string|null,
    "fecha_nacimiento": string|null,
    "domicilio": string|null,
    "telefono": string|[string]|null,
    "email": string|[string]|null,
    "diagnostico": string|null
  },
  "solicitante": {
    "nombre_apellido": string|null,
    "dni": string|null,
    "telefono": string|[string]|null,
    "email": string|[string]|null,
    "parentesco": string|null
  } | null,
  "modalidad_atencion": "whatsapp"|"presencial"|"allegramed"|null,
  "adjunto_diagnostico": true|false|null,
  "faltantes": [string],
  "revisar_manualmente": [string],
  "registro_completo": true|false
}"""


def _con_reintentos(func, intentos: int = 3, espera_inicial: float = 5.0):
    """Reintenta func() ante errores temporales (503/sobrecarga/rate limit),
    con espera creciente entre intentos. Relanza el error si se agotan los intentos."""
    ultimo_error = None
    for intento in range(intentos):
        try:
            return func()
        except Exception as e:
            mensaje = str(e).lower()
            es_temporal = any(
                s in mensaje for s in ["503", "overloaded", "unavailable", "429", "rate limit", "rate_limit"]
            )
            if not es_temporal or intento == intentos - 1:
                raise
            ultimo_error = e
            time.sleep(espera_inicial * (2 ** intento))
    raise ultimo_error  # pragma: no cover


@dataclass
class ExtractionResult:
    source_file: str
    data: dict
    raw_response: str


def _parse_json_response(raw: str) -> dict:
    raw_clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw_clean)
    except json.JSONDecodeError as e:
        return {"error": f"No se pudo parsear la respuesta: {e}", "raw": raw}


def _extract_with_anthropic(conversation_text: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=_get_config("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": conversation_text}],
    )
    return response.content[0].text.strip()


def _extract_with_gemini(conversation_text: str) -> str:
    from google import genai

    client = genai.Client(api_key=_get_config("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=conversation_text,
        config={"system_instruction": SYSTEM_PROMPT},
    )
    return response.text.strip()


def extract_from_conversation(conversation_text: str, source_file: str = "") -> ExtractionResult:
    provider = get_provider()

    if provider == "gemini":
        raw = _con_reintentos(lambda: _extract_with_gemini(conversation_text))
    elif provider == "anthropic":
        raw = _con_reintentos(lambda: _extract_with_anthropic(conversation_text))
    else:
        raise ValueError(
            f"PROVIDER desconocido: '{provider}'. Usá 'anthropic' o 'gemini' en secrets.toml."
        )

    data = _parse_json_response(raw)
    return ExtractionResult(source_file=source_file, data=data, raw_response=raw)