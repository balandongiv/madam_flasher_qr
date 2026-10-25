"""Image loading (EXIF orientation, colour profile -> sRGB) and export."""
import io

import numpy as np
from PIL import Image, ImageCms, ImageOps

_SRGB = ImageCms.createProfile('sRGB')
SRGB_ICC = ImageCms.ImageCmsProfile(_SRGB).tobytes()

try:                                    # optional HEIC support (iPhone photos)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


def load_rgb(path):
    """Return an RGB uint8 array in sRGB, upright according to EXIF."""
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    icc = im.info.get('icc_profile')
    if im.mode not in ('RGB', 'RGBA', 'L'):
        im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
    if im.mode == 'RGBA':                       # flatten transparency on white
        bg = Image.new('RGB', im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        im = bg
    im = im.convert('RGB')
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, _SRGB, outputMode='RGB')
        except Exception:
            pass                                # broken profile: assume sRGB
    return np.asarray(im).copy()


def save(rgb, path, cfg):
    e, t = cfg['export'], cfg['template']
    im = Image.fromarray(rgb)
    if e['format'] == 'png':
        im.save(path, icc_profile=SRGB_ICC, dpi=(t['dpi'], t['dpi']))
    else:
        im = im.convert('RGB')                  # JPG has no transparency
        im.save(path, quality=e['jpeg_quality'], subsampling=0, icc_profile=SRGB_ICC,
                dpi=(t['dpi'], t['dpi']), optimize=True)
