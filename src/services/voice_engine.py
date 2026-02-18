import edge_tts
import os
import uuid
import asyncio
from aiogram.types import FSInputFile

# Limit simultaneous requests to avoid being blocked
semaphore = asyncio.Semaphore(3)

VOICES = {
    "m": {"voice": "uk-UA-OstapNeural", "pitch": "+0Hz", "rate": "+0%"},
    "f": {"voice": "uk-UA-PolinaNeural", "pitch": "+0Hz", "rate": "+0%"},
    "j": {
        "voice": "uk-UA-PolinaNeural",
        "pitch": "+50Hz",
        "rate": "+30%",
    },  # Joke/Funny
}


async def text_to_voice(text: str, gender: str = "m", retries: int = 3) -> FSInputFile:
    config = VOICES.get(gender, VOICES["m"])

    # Create temp directory if not exists
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    temp_dir = os.path.join(base_dir, "temp")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    file_path = os.path.join(temp_dir, f"{uuid.uuid4()}.mp3")

    # Use semaphore to queue requests
    async with semaphore:
        for attempt in range(retries):
            try:
                communicate = edge_tts.Communicate(
                    text, config["voice"], pitch=config["pitch"], rate=config["rate"]
                )
                await communicate.save(file_path)
                return FSInputFile(file_path)
            except Exception as e:
                if attempt == retries - 1:
                    raise e
                # Exponential backoff: wait 1s, then 2s, then 4s...
                await asyncio.sleep(2**attempt)

    raise Exception("Failed to generate voice after retries")


def cleanup_voice(file_path: str):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error cleaning up audio: {e}")
