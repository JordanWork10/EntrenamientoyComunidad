"""V132.01: comprobación de videos con FFprobe.

Destino: apps/professionals/video_probe_v13201.py
No se confía en duración, formato o códec enviados por el navegador.
"""

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError


SUPPORTED_VIDEO_EXTENSIONS = frozenset({'.mp4', '.webm'})
SUPPORTED_VIDEO_CODECS = frozenset({'h264', 'vp8', 'vp9', 'av1'})


@dataclass(frozen=True)
class VideoProbeResult:
    duration_seconds: int
    codec: str
    extension: str


def probe_local_video(path, extension):
    """Verifica encabezado, contenedor, pista de video y duración positiva.

    Emplea una ruta local temporal controlada por el servidor, nunca una URL
    ni una ruta enviada directamente por el usuario.
    """
    extension = str(extension).lower()
    if extension not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValidationError('Por ahora solo se permiten videos MP4 o WebM.')

    path = Path(path)
    try:
        with path.open('rb') as handle:
            header = handle.read(16)
    except OSError as exc:
        raise ValidationError('No se pudo leer el archivo de video.') from exc

    if extension == '.mp4' and not (
        len(header) >= 12 and header[4:8] == b'ftyp'
    ):
        raise ValidationError('El archivo no tiene un encabezado MP4 válido.')
    if extension == '.webm' and not header.startswith(b'\x1a\x45\xdf\xa3'):
        raise ValidationError('El archivo no tiene un encabezado WebM válido.')

    executable = shutil.which('ffprobe')
    if not executable:
        raise ValidationError(
            'El servidor necesita FFprobe instalado para validar videos.'
        )

    try:
        result = subprocess.run(
            [
                executable,
                '-v', 'error',
                '-show_entries', 'format=duration,format_name:stream=codec_type,codec_name',
                '-of', 'json',
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError('No se pudo analizar el video a tiempo.') from exc

    if result.returncode != 0 or len(result.stdout) > 65536:
        raise ValidationError('El video no es válido o no puede analizarse.')

    try:
        info = json.loads(result.stdout)
        format_data = info['format']
        format_names = set(str(format_data['format_name']).split(','))
        duration = float(format_data['duration'])
        tracks = [
            item for item in info.get('streams', [])
            if item.get('codec_type') == 'video'
        ]
        codec = tracks[0]['codec_name'] if len(tracks) == 1 else None
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ValidationError('No se encontraron metadatos de video completos.') from exc

    if not math.isfinite(duration) or duration <= 0:
        raise ValidationError('La duración del video debe ser positiva.')
    if codec not in SUPPORTED_VIDEO_CODECS:
        raise ValidationError(
            'Códec no compatible. Usa H.264, VP8, VP9 o AV1.'
        )
    if extension == '.mp4' and 'mp4' not in format_names:
        raise ValidationError('La extensión MP4 no coincide con el contenido.')
    if extension == '.webm' and 'webm' not in format_names:
        raise ValidationError('La extensión WebM no coincide con el contenido.')

    # Redondear hacia ARRIBA evita que 120,1 segundos eludan el límite de 120.
    return VideoProbeResult(
        duration_seconds=math.ceil(duration),
        codec=codec,
        extension=extension,
    )
