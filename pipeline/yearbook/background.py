"""Optional stage: background removal on the GPU (rembg + onnxruntime CUDA).

Runs on the aligned portrait, so the eye/mouth positions are unchanged.
"""
import numpy as np


class Remover:
    def __init__(self, bg):
        import onnxruntime as ort
        try:
            ort.preload_dlls()          # CUDA/cuDNN from the nvidia-* pip wheels
        except Exception:
            pass
        from rembg import new_session
        want = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        if not bg.get('use_gpu', True):
            want = want[1:]
        providers = [p for p in want if p in ort.get_available_providers()]
        self.session = new_session(bg['model'], providers=providers)
        self.device = 'GPU' if 'CUDAExecutionProvider' in self.session.inner_session.get_providers() else 'CPU'
        self.bg = bg

    def apply(self, rgb):
        """Return RGB on a solid colour, or RGBA if mode = "transparent"."""
        from rembg import remove
        from PIL import Image
        cut = np.asarray(remove(Image.fromarray(rgb), session=self.session,
                                alpha_matting=self.bg.get('alpha_matting', False)).convert('RGBA'))
        if self.bg['mode'] == 'transparent':
            return cut
        a = cut[..., 3:4].astype(np.float32) / 255
        color = np.array(self.bg['color'], np.float32)
        return (cut[..., :3] * a + color * (1 - a)).round().astype(np.uint8)
