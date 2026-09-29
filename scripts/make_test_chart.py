"""Generate a labeled, fictional chart for manual vision acceptance testing."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test-chart.png")
image = Image.new("RGB", (1000, 680), "white")
draw = ImageDraw.Draw(image)
title = ImageFont.load_default(size=32)
font = ImageFont.load_default(size=23)
draw.text((65, 35), "SYNTHETIC TEST — EV deliveries, 2025", font=title, fill="#172f39")
draw.text((65, 88), "Fictional market · electric passenger cars · vehicles", font=font, fill="#61717a")
draw.line((100, 150, 100, 550, 930, 550), fill="#172f39", width=3)
for value in range(0, 16001, 4000):
    y = 550 - value / 16000 * 350
    draw.line((100, y, 930, y), fill="#dce3e6", width=1)
    draw.text((12, y - 12), str(value), font=font, fill="#61717a")
for x, name, value in [(225, "Northstar", 15000), (485, "Meridian", 9000), (745, "Cobalt", 6000)]:
    top = 550 - value / 16000 * 350
    draw.rectangle((x, top, x + 115, 549), fill="#176649")
    draw.text((x, top - 34), str(value), font=font, fill="#172f39")
    draw.text((x - 8, 566), name, font=font, fill="#172f39")
draw.text((100, 624), "All companies and values are fictional. Expected labels: 15000, 9000, 6000.", font=ImageFont.load_default(size=19), fill="#61717a")
output.parent.mkdir(parents=True, exist_ok=True)
image.save(output)
print(output.resolve())
