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

    # 4. Text Wrapping & Drawing
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

    # Wrap text to 80% of image width
    max_w = width * 0.8
    lines = wrap_text(text, font, max_w)

    # Calculate total height of text block
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + 10
    total_text_height = len(lines) * line_height

    # Start drawing from center
    current_h = (height - total_text_height) // 2

    # Use Pilmoji to draw text with emoji support
    with Pilmoji(img) as pilmoji:
        for line in lines:
            # Center horizontally
            line_w = draw.textbbox((0, 0), line, font=font)[2]
            x = (width - line_w) // 2

            # Draw shadow for readability (shadow doesn't need pilmoji usually but for consistency we use it)
            pilmoji.text(
                (x + 2, current_h + 2), line, font=font, fill=(50, 50, 50, 100)
            )
            # Draw main text with colored emojis
            pilmoji.text((x, current_h), line, font=font, fill=(0, 0, 0))

            current_h += line_height

    img.save(output_path)
    return output_path
