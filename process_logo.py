import pygame
from collections import deque
import os

pygame.init()

src_path = r'C:\Users\Dylan\.gemini\antigravity\brain\b5a860ed-1691-4f5a-8f2d-ad2b4e7701e4\.user_uploaded\media_1790582729224.jpg'
surf = pygame.image.load(src_path)
w, h = surf.get_size()

# Content bounding box: x=[160, 863], y=[144, 335]
# Let's add padding of 8px
pad = 8
crop_x1 = max(0, 160 - pad)
crop_y1 = max(0, 144 - pad)
crop_x2 = min(w - 1, 863 + pad)
crop_y2 = min(h - 1, 335 + pad)

crop_w = crop_x2 - crop_x1 + 1
crop_h = crop_y2 - crop_y1 + 1

# Subsurface
cropped_surf = pygame.Surface((crop_w, crop_h), pygame.SRCALPHA)
cropped_surf.blit(surf, (0, 0), (crop_x1, crop_y1, crop_w, crop_h))

# Flood fill outer white to transparent
# Queue of boundary points
visited = [[False]*crop_h for _ in range(crop_w)]
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
    # Background in JPEG might have slight compression artifacts (e.g. 248..255)
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
        # If avg is close to 255, alpha is low
        alpha = int((255 - avg) * (255.0 / 25.0))
        cropped_surf.set_at((cx, cy), (r, g, b, min(255, max(0, alpha))))

os.makedirs('static/images', exist_ok=True)
# Save transparent cropped PNG
transparent_path = 'static/images/ratesift-logo.png'
pygame.image.save(cropped_surf, transparent_path)

# Also save cropped version with white background
cropped_white = pygame.Surface((crop_w, crop_h))
cropped_white.blit(surf, (0, 0), (crop_x1, crop_y1, crop_w, crop_h))
pygame.image.save(cropped_white, 'static/images/ratesift-logo-white-bg.png')

# Also copy original
with open(src_path, 'rb') as f_in, open('static/images/ratesift-logo-original.jpg', 'wb') as f_out:
    f_out.write(f_in.read())

print(f"Saved: {transparent_path} (size: {crop_w}x{crop_h})")
print(f"Saved: static/images/ratesift-logo-white-bg.png")
print(f"Saved: static/images/ratesift-logo-original.jpg")
