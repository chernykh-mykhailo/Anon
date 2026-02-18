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


async def generate_image_input(
    text: str,
    custom_bg_path: str = None,
    y_position: str = "center",
    text_color_input: str = None,
    use_bg: bool = True,
) -> str:
    """Choose a random template or use custom image and draw text on it."""
    # 1. Setup paths
    base_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_dir = os.path.join(os.path.dirname(base_src_dir), "temp")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    templates_dir = os.path.join(base_src_dir, "assets", "templates", "generated")
    output_path = os.path.join(temp_dir, f"card_{random.randint(1000, 9999)}.png")

    # 2. Pick template or use custom
    if custom_bg_path and os.path.exists(custom_bg_path):
        img = Image.open(custom_bg_path).convert("RGB")
    else:
        templates = glob.glob(os.path.join(templates_dir, "*.png"))
        if not templates:
            raise Exception("No templates found in assets/templates/generated")
        template_path = random.choice(templates)
        img = Image.open(template_path).convert("RGB")

    draw = ImageDraw.Draw(img)
    width, height = img.size

    # 3. Setup Font
    # Priority: 1. Project font, 2. Windows fonts, 3. Linux fonts, 4. Default
    font_paths = [
        os.path.join(base_src_dir, "assets", "fonts", "font.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]

    font = None
    used_font_path = "default"
    font_size = 50
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                used_font_path = path
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()
        print(
            "⚠️ Warning: No custom fonts found, using default (Cyrillic may not work)."
        )
    else:
        print(f"✅ Using font: {used_font_path}")

    # 4. Text Wrapping & Analysis
    def get_avg_brightness(img):
        """Estimate image brightness to choose text color."""
        stat_img = img.resize((1, 1)).convert("L")
        return stat_img.getpixel((0, 0))

    brightness = get_avg_brightness(img)

    # Choose colors based on brightness or input
    if text_color_input:
        text_color = (255, 255, 255) if text_color_input == "white" else (30, 30, 30)
    else:
        text_color = (255, 255, 255) if brightness < 128 else (30, 30, 30)

    shadow_color = (
        (0, 0, 0, 150) if text_color == (255, 255, 255) else (255, 255, 255, 100)
    )

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
    if used_font_path != "default":
        try:
            font = ImageFont.truetype(used_font_path, font_size)
        except Exception:
            pass

    max_w = width * 0.85
    lines = wrap_text(text, font, max_w)

    line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + 15
    total_text_height = len(lines) * line_height

    # Calculate positioning
    if y_position == "top":
        start_y = height * 0.15
    elif y_position == "bottom":
        start_y = height * 0.85 - total_text_height
    else:  # center
        start_y = (height - total_text_height) // 2

    # 5. Draw background "glow" for readability
    if use_bg:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Calculate box area
        box_padding = 40
        box_y1 = start_y - box_padding
        box_y2 = start_y + total_text_height + box_padding

        # Draw a soft semi-transparent rectangle behind text
        bg_brightness = (0, 0, 0, 60) if brightness >= 128 else (255, 255, 255, 30)
        overlay_draw.rectangle(
            [width * 0.05, box_y1, width * 0.95, box_y2], fill=bg_brightness
        )
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))

    # 6. Final Drawing with Pilmoji
    current_h = start_y
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
