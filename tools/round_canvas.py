"""Replace the rectangular glowing frame in canvas.png with a round glowing frame."""
import sys
import cv2
import numpy as np

src, dst = sys.argv[1], sys.argv[2]
img = cv2.imread(src)
h, w = img.shape[:2]
L, T, R, B = 108, 92, 571, 777          # outer gold line of the old rectangle

# 1. Erase the rectangle and its halo (wide band), sparing the pattern strip on the left.
band = np.zeros((h, w), np.uint8)
cv2.rectangle(band, (L, T), (R, B), 255, 120)
band[:, :86] = 0
# fill from surrounding blue background only (normalized convolution; gold/warm pixels ignored)
f = img.astype(np.float32)
valid = ((band == 0) & (f[..., 2] < f[..., 0])).astype(np.float32)
num = cv2.GaussianBlur(f * valid[..., None], (0, 0), 35)
den = cv2.GaussianBlur(valid, (0, 0), 35)[..., None]
soft = num / np.maximum(den, 1e-3)
rng = np.random.default_rng(1)
grain = rng.normal(0, 2.0, img.shape)
a = (cv2.GaussianBlur(band, (0, 0), 12).astype(np.float32) / 255)[..., None]
out = img * (1 - a) + (soft + grain) * a
cv2.imwrite(dst.replace('.png', '_clean.png'), np.clip(out, 0, 255).astype(np.uint8))

# 2. Draw the round frame: double gold ring with a soft glow (screen blend), like the original rectangle.
base = np.clip(out, 0, 255).astype(np.float32) / 255
cx, cy, r = (L + R) // 2, (T + B) // 2, 236
SS = 4                                   # supersample for smooth anti-aliased rings
def ring(radius, thick):
    m = np.zeros((h * SS, w * SS), np.uint8)
    cv2.circle(m, (cx * SS, cy * SS), radius * SS, 255, thick * SS, cv2.LINE_AA)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
outer, inner = ring(r, 4), ring(r - 13, 2)
lines = np.maximum(outer, inner * 0.8)
glow = (cv2.GaussianBlur(lines, (0, 0), 4) * 1.6 + cv2.GaussianBlur(lines, (0, 0), 14) * 2.2
        + cv2.GaussianBlur(lines, (0, 0), 40) * 2.5)
gold = np.array([60, 170, 255], np.float32) / 255          # BGR warm gold
core = np.array([200, 240, 255], np.float32) / 255         # near-white hot core
light = glow[..., None] * gold + lines[..., None] * core
# flares at the four points of the ring, like the original frame's highlights
flare = np.zeros((h, w), np.float32)
for ang in (0, 90, 180, 270):
    t = np.deg2rad(ang)
    px, py = int(cx + r * np.cos(t)), int(cy + r * np.sin(t))
    cv2.circle(flare, (px, py), 3, 1.0, -1)
flare = cv2.GaussianBlur(flare, (0, 0), 6) * 6 + cv2.GaussianBlur(flare, (0, 0), 22) * 8
light += flare[..., None] * gold
light = np.clip(light, 0, 1)
res = 1 - (1 - base) * (1 - light)
cv2.imwrite(dst, (res * 255).round().astype(np.uint8))
print('circle centre', (cx, cy), 'outer radius', r, 'inner line radius', r - 13)
