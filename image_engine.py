import urllib.parse
import aiohttp
import os
import uuid
import random
import base64

from database import db


async def generate_image_input(prompt: str) -> str:
    file_path = f"gen_{uuid.uuid4().hex}.png"
    errors = []

    # Wrap user prompt with artistic direction
    art_prompt = _build_art_prompt(prompt)
    print(f"🎨 Art prompt: {art_prompt[:80]}...")

    # === Priority 1: Gemini API (key pool from users + .env) ===
    gemini_key = _get_gemini_key()
    if gemini_key:
        key_count = db.get_gemini_key_count()
        print(f"--- [1] Gemini API (key pool: {key_count} keys) ---")
        try:
            result = await _try_gemini(gemini_key, art_prompt, file_path)
            if result:
                return result
        except Exception as e:
            err = f"Gemini: {str(e)}"
            print(f"⚠️ {err}")
            errors.append(err)
            db.mark_gemini_key_failed(gemini_key)

            # Try another key from pool
            second_key = _get_gemini_key()
            if second_key and second_key != gemini_key:
                print("    Trying another Gemini key...")
                try:
                    result = await _try_gemini(second_key, art_prompt, file_path)
                    if result:
                        return result
                except Exception as e2:
                    err2 = f"Gemini (retry): {str(e2)}"
                    print(f"⚠️ {err2}")
                    errors.append(err2)
                    db.mark_gemini_key_failed(second_key)

        # === Priority 1b: Imagen 4 (separate quota, same key) ===
        print("--- [1b] Imagen 4 (separate 25 RPD quota)... ---")
        try:
            result = await _try_imagen4(gemini_key, art_prompt, file_path)
            if result:
                return result
        except Exception as e:
            err = f"Imagen4: {str(e)}"
            print(f"⚠️ {err}")
            errors.append(err)
    else:
        print("--- [1] Gemini: no API keys available, skipping ---")
        errors.append("Gemini: no API keys in pool")

    # === Fallback 2: Pollinations (no key needed, unreliable) ===
    encoded_prompt = urllib.parse.quote(art_prompt)
    seed = random.randint(1, 1000000)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        print("--- [2] Pollinations (image.pollinations.ai)... ---")
        try:
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?seed={seed}&nologo=true&width=1024&height=1024"
            async with session.get(
                url, timeout=45, ssl=False, allow_redirects=True
            ) as response:
                if response.status == 200:
                    data = await response.read()
                    if len(data) > 5000:
                        with open(file_path, "wb") as f:
                            f.write(data)
                        print(f"✅ Pollinations SUCCESS ({len(data)} bytes)")
                        return file_path
                    else:
                        err = f"Pollinations: tiny ({len(data)}b)"
                        print(f"⚠️ {err}")
                        errors.append(err)
                else:
                    err = f"Pollinations status {response.status}"
                    print(f"⚠️ {err}")
                    errors.append(err)
        except Exception as e:
            err = f"Pollinations: {str(e)}"
            print(f"⚠️ {err}")
            errors.append(err)

        # === Fallback 3: Dicebear (guaranteed, but just avatar) ===
        print("--- [3] Dicebear (guaranteed fallback)... ---")
        try:
            dicebear_url = f"https://api.dicebear.com/7.x/bottts/png?seed={urllib.parse.quote(prompt)}"
            async with session.get(dicebear_url, timeout=15, ssl=False) as response:
                if response.status == 200:
                    data = await response.read()
                    with open(file_path, "wb") as f:
                        f.write(data)
                    print("✅ Dicebear SUCCESS")
                    return file_path
        except Exception as e:
            print(f"⚠️ Dicebear: {e}")

    error_summary = "; ".join(errors[-3:])
    raise Exception(f"All providers failed: {error_summary}")


def _get_gemini_key() -> str | None:
    """Get a Gemini API key: from DB pool first, then from .env fallback."""
    key = db.get_random_gemini_key()
    if key:
        return key
    # Fallback to .env
    return os.getenv("GEMINI_API_KEY")


async def _try_imagen4(api_key: str, prompt: str, file_path: str) -> str | None:
    """Generate image via Google Imagen 4 (separate quota from Gemini Flash)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={api_key}"

    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=45, ssl=False) as resp:
            if resp.status == 200:
                data = await resp.json()
                predictions = data.get("predictions", [])
                if predictions:
                    img_b64 = predictions[0].get("bytesBase64Encoded")
                    if img_b64:
                        img_bytes = base64.b64decode(img_b64)
                        if len(img_bytes) > 5000:
                            with open(file_path, "wb") as f:
                                f.write(img_bytes)
                            print(f"✅ Imagen4 SUCCESS ({len(img_bytes)} bytes)")
                            return file_path
                        else:
                            print(f"⚠️ Imagen4: image too small ({len(img_bytes)}b)")
                            return None
                print("⚠️ Imagen4: no predictions in response")
                return None
            elif resp.status == 429:
                error_text = await resp.text()
                raise Exception(f"rate limit: {error_text[:150]}")
            else:
                error_text = await resp.text()
                raise Exception(f"status {resp.status}: {error_text[:150]}")


async def _try_gemini(api_key: str, prompt: str, file_path: str) -> str | None:
    """Generate image via Google Gemini API (gemini-2.5-flash image generation)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            timeout=45,
            ssl=False,
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                # Extract image from response candidates
                candidates = data.get("candidates", [])
                for candidate in candidates:
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        inline_data = part.get("inlineData")
                        if inline_data and inline_data.get("mimeType", "").startswith(
                            "image/"
                        ):
                            img_b64 = inline_data.get("data")
                            if img_b64:
                                img_bytes = base64.b64decode(img_b64)
                                if len(img_bytes) > 5000:
                                    with open(file_path, "wb") as f:
                                        f.write(img_bytes)
                                    print(f"✅ Gemini SUCCESS ({len(img_bytes)} bytes)")
                                    return file_path
                                else:
                                    print(
                                        f"⚠️ Gemini: image too small ({len(img_bytes)}b)"
                                    )
                                    return None
                print("⚠️ Gemini: no image in response")
                return None
            elif resp.status == 429:
                error_text = await resp.text()
                print(f"⚠️ Gemini 429 body: {error_text[:300]}")
                raise Exception(f"rate limit: {error_text[:150]}")
            elif resp.status == 400:
                error_text = await resp.text()
                raise Exception(f"bad request: {error_text[:100]}")
            else:
                error_text = await resp.text()
                raise Exception(f"status {resp.status}: {error_text[:100]}")


def _build_art_prompt(user_text: str) -> str:
    """Wrap user's text into a high-quality, SFW art prompt."""
    return (
        f"A beautiful, heartfelt digital illustration: {user_text}. "
        "Style: watercolor painting, warm pastel colors, gentle golden lighting, "
        "dreamy atmosphere, cozy romantic mood, cute kawaii aesthetic, "
        "highly detailed, trending on artstation, masterpiece, safe for work"
    )


def cleanup_image(file_path: str):
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
