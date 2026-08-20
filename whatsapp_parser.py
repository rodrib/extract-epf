"""
Parser de exports de WhatsApp (.txt) del Instituto de Genética Humana.

Soporta el formato estándar de exportación de WhatsApp:
    [H:MM a. m./p. m., D/M/AAAA] Remitente: mensaje
    [H:MM a. m./p. m., D/M/AAAA] Remitente: mensaje (continúa en varias líneas)

Los mensajes que no empiezan con "[hora, fecha] Remitente:" se consideran
continuación del mensaje anterior (frecuente cuando alguien pega un bloque
de texto con saltos de línea, ej. "Datos:\nNombre\nDNI\n...").
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# Ej: [9:00 p. m., 4/8/2026] Pte. Hermana Flores Ramon: Algún correo o link
LINE_RE = re.compile(
    r"^\[(?P<time>\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?),\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\]\s*"
    r"(?P<sender>[^:]+):\s*(?P<text>.*)$",
    re.IGNORECASE,
)


@dataclass
class Message:
    date: str
    time: str
    sender: str
    text: str


@dataclass
class Conversation:
    source_file: str
    messages: list = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Todo el contenido de texto concatenado, en orden, para pasarle al LLM."""
        return "\n".join(f"[{m.date} {m.time}] {m.sender}: {m.text}" for m in self.messages)

    @property
    def senders(self):
        return sorted(set(m.sender for m in self.messages))


def parse_whatsapp_txt(path: Path) -> Conversation:
    """Parsea un .txt de export de WhatsApp a una Conversation con mensajes estructurados."""
    conv = Conversation(source_file=path.name)
    current: Message | None = None

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue

            # Quita el marcador de mensaje editado si aparece, no afecta el parseo
            line = line.replace("\u200e", "")

            match = LINE_RE.match(line)
            if match:
                if current is not None:
                    conv.messages.append(current)
                current = Message(
                    date=match.group("date"),
                    time=match.group("time"),
                    sender=match.group("sender").strip(),
                    text=match.group("text").strip(),
                )
            else:
                # Línea de continuación (multi-línea del mensaje anterior)
                if current is not None:
                    current.text += "\n" + line.strip()
                # si no hay mensaje previo (raro, ej. metadata del export), se ignora

    if current is not None:
        conv.messages.append(current)

    return conv


def parse_folder(folder: Path) -> list[Conversation]:
    """Parsea todos los .txt de una carpeta (ej. la carpeta descomprimida del zip)."""
    return [parse_whatsapp_txt(p) for p in sorted(folder.glob("*.txt"))]


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    for conv in parse_folder(target):
        print(f"=== {conv.source_file} ({len(conv.messages)} mensajes, remitentes: {conv.senders}) ===")
        print(conv.full_text)
        print()
