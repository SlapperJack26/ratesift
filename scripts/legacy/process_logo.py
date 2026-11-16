import pygame
from collections import deque
import os
import shutil

pygame.init()

src_path = r'C:\Users\Dylan\.gemini\antigravity\brain\ec698020-a512-4f06-ab67-4069143a572d\quotelytics_logo_concept_1_1792265235093.jpg'
surf = pygame.image.load(src_path)
w, h = surf.get_size()

# Detect bounding box of non-white pixels
min_x, max_x = w, 0
min_y, max_y = h, 0

for x in range(w):
    for y in range(h):
        r, g, b, a = surf.get_at((x, y))
        # Non-white threshold
        if r < 240 or g < 240 or b < 240:
            if x < min_x: min_x = x
            if x > max_x: max_x = x
            if y < min_y: min_y = y
            if y > max_y: max_y = y

pad = 12
crop_x1 = max(0, min_x - pad)
crop_y1 = max(0, min_y - pad)
crop_x2 = min(w - 1, max_x + pad)
crop_y2 = min(h - 1, max_y + pad)

crop_w = crop_x2 - crop_x1 + 1
crop_h = crop_y2 - crop_y1 + 1

print(f"Detected bounding box: ({min_x}, {min_y}) to ({max_x}, {max_y})")
print(f"Cropped dimension with padding: {crop_w} x {crop_h}")

# Subsurface
cropped_surf = pygame.Surface((crop_w, crop_h), pygame.SRCALPHA)
cropped_surf.blit(surf, (0, 0), (crop_x1, crop_y1, crop_w, crop_h))

# Flood fill outer white to transparent
visited = [[False] * crop_h for _ in range(crop_w)]
queue = deque()

# Add all 4 borders of the cropped image
for x in range(crop_w):
    queue.append((x, 0))
    queue.append((x, crop_h - 1))
for y in range(crop_h):
    queue.append((0, y))
    queue.append((crop_w - 1, y))

while queue:
    cx, cy = queue.popleft()
    if cx < 0 or cx >= crop_w or cy < 0 or cy >= crop_h:
        continue
    if visited[cx][cy]:
        continue
    visited[cx][cy] = True

    r, g, b, a = cropped_surf.get_at((cx, cy))
    # Check if nearly white background (r,g,b > 245)
    if r >= 245 and g >= 245 and b >= 245:
        # Make transparent
        cropped_surf.set_at((cx, cy), (r, g, b, 0))
        # Push 4 neighbors
        queue.append((cx + 1, cy))
        queue.append((cx - 1, cy))
        queue.append((cx, cy + 1))
        queue.append((cx, cy - 1))
    elif r >= 230 and g >= 230 and b >= 230:
        # Smooth alpha edge
        avg = (r + g + b) / 3.0
        alpha = int((255 - avg) * (255.0 / 25.0))
        cropped_surf.set_at((cx, cy), (r, g, b, min(255, max(0, alpha))))

os.makedirs('static/images', exist_ok=True)

# 1. Quotelytics logo files
ql_transparent = 'static/images/quotelytics-logo.png'
pygame.image.save(cropped_surf, ql_transparent)

cropped_white = pygame.Surface((crop_w, crop_h))
cropped_white.blit(surf, (0, 0), (crop_x1, crop_y1, crop_w, crop_h))
ql_white = 'static/images/quotelytics-logo-white-bg.png'
pygame.image.save(cropped_white, ql_white)

ql_orig = 'static/images/quotelytics-logo-original.jpg'
with open(src_path, 'rb') as f_in, open(ql_orig, 'wb') as f_out:
    f_out.write(f_in.read())

# 2. Backward compatibility alias files
rs_transparent = 'static/images/quotelytics-logo.png'
pygame.image.save(cropped_surf, rs_transparent)

rs_white = 'static/images/quotelytics-logo-white-bg.png'
pygame.image.save(cropped_white, rs_white)

rs_orig = 'static/images/quotelytics-logo-original.jpg'
shutil.copyfile(ql_orig, rs_orig)

print(f"Saved: {ql_transparent} ({crop_w}x{crop_h})")
print(f"Saved: {ql_white}")
print(f"Saved: {ql_orig}")
print(f"Saved alias: {rs_transparent}")
print(f"Saved alias: {rs_white}")
print(f"Saved alias: {rs_orig}")
