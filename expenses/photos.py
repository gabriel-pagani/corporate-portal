"""
As fotos da nota: conferência do envio e regravação com o Pillow.

Toda foto é regravada em JPEG, de pé e com o lado maior em STORED_SIDE: legível
para a auditoria, com cerca de 1 MB, e sem nada do arquivo original além da
imagem. A IA recebe uma cópia menor, só para a análise.
"""
import hashlib
import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from PIL import Image, ImageOps


MIN_PHOTOS = 1

MAX_PHOTOS = 3

MAX_PHOTO_SIZE = 20 * 1024 * 1024

ACCEPTED_FORMATS = ['JPEG', 'PNG', 'WEBP']

ACCEPTED_TYPES = 'image/jpeg,image/png,image/webp'

STORED_SIDE = 3000

STORED_QUALITY = 90

# Sobra para ler um cupom, e a chamada à IA fica leve
AI_SIDE = 2000

AI_QUALITY = 85


@dataclass(frozen=True)
class Photo:
    content: bytes
    sha256: str
    # Do arquivo como o funcionário enviou, antes da regravação
    source_sha256: str
    # A cópia reduzida que vai para a IA
    ai_content: bytes


def jpeg(image, side, quality):
    copy = image.copy()
    copy.thumbnail((side, side))
    output = io.BytesIO()
    copy.save(output, 'JPEG', quality=quality, optimize=True)
    return output.getvalue()


def normalize(file):
    """A foto regravada; ValidationError se não for uma imagem aceita."""
    source = hashlib.sha256()
    for chunk in file.chunks():
        source.update(chunk)
    file.seek(0)
    try:
        image = Image.open(file, formats=ACCEPTED_FORMATS)
        # No JPEG já decodifica perto do tamanho final, sem abrir a foto inteira na memória
        image.draft('RGB', (STORED_SIDE, STORED_SIDE))
        # O celular grava a foto deitada e anota a rotação no EXIF, que não vai para o arquivo novo
        image = ImageOps.exif_transpose(image).convert('RGB')
    except Image.DecompressionBombError as error:
        raise ValidationError('A foto tem resolução grande demais. Envie uma foto menor.') from error
    except (OSError, ValueError, SyntaxError) as error:
        raise ValidationError('Envie apenas fotos nos formatos JPEG, PNG ou WEBP.') from error

    content = jpeg(image, STORED_SIDE, STORED_QUALITY)
    return Photo(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        source_sha256=source.hexdigest(),
        ai_content=jpeg(image, AI_SIDE, AI_QUALITY),
    )


def prepare_photos(files):
    """Confere a quantidade e o tamanho das fotos e devolve cada uma regravada."""
    if len(files) < MIN_PHOTOS:
        raise ValidationError('Envie ao menos uma foto da nota.')
    if len(files) > MAX_PHOTOS:
        raise ValidationError(f'Envie no máximo {MAX_PHOTOS} fotos por nota.')
    for file in files:
        if file.size > MAX_PHOTO_SIZE:
            raise ValidationError(f'Cada foto pode ter até {MAX_PHOTO_SIZE // (1024 * 1024)} MB.')
    return [normalize(file) for file in files]
