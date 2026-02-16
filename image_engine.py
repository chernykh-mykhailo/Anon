import os
import random
import glob
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji


def cleanup_image(file_path: str):
    """Delete generated image after sending."""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error cleaning up image: {e}")


async def generate_image_input(text: str) -> str:
    """Choose a random template and draw text on it."""
    # 1. Setup paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(base_dir, "assets", "templates", "generated")
    output_path = f"card_{random.randint(1000, 9999)}.png"

    # Check if templates exist
    templates = glob.glob(os.path.join(templates_dir, "*.png"))
    if not templates:
        raise Exception("No templates found in assets/templates/generated")

    # 2. Pick random template
    template_path = random.choice(templates)
    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size

    # 3. Setup Font
    # Priority: 1. Project font, 2. Windows fonts, 3. Linux fonts, 4. Default
    font_paths = [
        os.path.join(base_dir, "assets", "fonts", "font.ttf"),
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]

    font = None
    font_size = 50
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()

    # 4. Text Wrapping & Analysis
    def get_avg_brightness(img):
        """Estimate image brightness to choose text color."""
        stat_img = img.resize((1, 1)).convert("L")
        return stat_img.getpixel((0, 0))

    brightness = get_avg_brightness(img)
    text_color = (255, 255, 255) if brightness < 128 else (30, 30, 30)
    shadow_color = (0, 0, 0, 150) if brightness >= 128 else (255, 255, 255, 100)

    def wrap_text(text, font, max_width):
        lines = []
        words = text.split()
        while words:
            line = ""
            while (
                words
                and draw.textbbox((0, 0), line + words[0], font=font)[2] < max_width
            ):
                line += words.pop(0) + " "
            lines.append(line.strip())
        return lines

    # Make font bigger for short messages
    if len(text) < 20:
        font_size = 70
    elif len(text) > 100:
        font_size = 40

    # Reload font with new size
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue

    max_w = width * 0.85
    lines = wrap_text(text, font, max_w)

    line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + 15
    total_text_height = len(lines) * line_height

    # 5. Draw background "glow" for readability
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Calculate box area
    box_padding = 40
    box_y1 = (height - total_text_height) // 2 - box_padding
    box_y2 = (height + total_text_height) // 2 + box_padding

    # Draw a soft semi-transparent rectangle behind text
    bg_brightness = (0, 0, 0, 60) if brightness >= 128 else (255, 255, 255, 30)
    overlay_draw.rectangle(
        [width * 0.05, box_y1, width * 0.95, box_y2], fill=bg_brightness
    )
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))

    # 6. Final Drawing with Pilmoji
    current_h = (height - total_text_height) // 2
    with Pilmoji(img) as pilmoji:
        for line in lines:
            line_w = draw.textbbox((0, 0), line, font=font)[2]
            x = (width - line_w) // 2

            # Draw subtle outline or shadow for contrast
            pilmoji.text((x + 1, current_h + 1), line, font=font, fill=shadow_color)
            pilmoji.text((x, current_h), line, font=font, fill=text_color)

            current_h += line_height

    img.save(output_path)
    return output_path
