import edge_tts
import os
import uuid
import asyncio
import logging
import random
import hashlib
import shutil
from datetime import datetime
from aiogram.types import FSInputFile

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

from database import db
from config import AZURE_SPEECH_KEY, AZURE_SPEECH_REGION

# Limit simultaneous requests to avoid being blocked
semaphore = asyncio.Semaphore(3)

# 480k characters limit (Azure Free Tier is 500k/mo)
AZURE_MONTHLY_LIMIT = 480000

VOICES = {
    # Azure Voices
    "m": {"voice": "uk-UA-OstapNeural", "pitch": "+0Hz", "rate": "+0%"},
    "f": {"voice": "uk-UA-PolinaNeural", "pitch": "+0Hz", "rate": "+0%"},
    # Joke/Funny (modified parameters)
    "j": {
        "voice": "uk-UA-PolinaNeural",
        "pitch": "+50Hz",
        "rate": "+30%",
    },
    # Anonymous/Robot (modified parameters)
    "r": {
        "voice": "uk-UA-OstapNeural",
        "pitch": "-15%",
        "rate": "-10%",
    },
    # English Voices (Standard)
    "jenny": {"voice": "en-US-JennyNeural", "pitch": "+0Hz", "rate": "+0%"},
    "ryan": {"voice": "en-GB-RyanNeural", "pitch": "+0Hz", "rate": "+0%"},
    # Multilingual Voices (Experimental)
    "ava": {"voice": "en-US-AvaMultilingualNeural", "pitch": "+0Hz", "rate": "+0%"},
    "andrew": {
        "voice": "en-US-AndrewMultilingualNeural",
        "pitch": "+0Hz",
        "rate": "+0%",
    },
}


def get_month_key():
    return datetime.now().strftime("speech_usage_%Y_%m")


async def generate_azure_speech(text: str, voice_config: dict, output_path: str):
    """Generate speech using Azure Cognitive Services SDK."""
    if not speechsdk:
        raise ImportError("Azure Speech SDK not installed")

    speech_config = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
    )
    # Set voice directly
    speech_config.speech_synthesis_voice_name = voice_config["voice"]

    # Configure output to file
    audio_config = speechsdk.audio.AudioOutputConfig(filename=output_path)

    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=audio_config
    )

    # Note: Azure SDK doesn't support pitch/rate modification directly via simple synthesis
    # unless using SSML. We will use SSML for consistent feature support.
    ssml = f"""
    <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="uk-UA">
        <voice name="{voice_config["voice"]}">
            <prosody pitch="{voice_config["pitch"]}" rate="{voice_config["rate"]}">
                {text}
            </prosody>
        </voice>
    </speak>
    """

    # Run in executor to avoid blocking async loop (run_in_executor needed for sync SDK methods)
    loop = asyncio.get_running_loop()

    def _synthesize():
        result = synthesizer.speak_ssml_async(ssml).get()
        return result

    result = await loop.run_in_executor(None, _synthesize)

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        pass
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        error_msg = f"Azure Speech canceled: {cancellation_details.reason}"
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            error_msg += f" Error details: {cancellation_details.error_details}"
        raise Exception(error_msg)


async def text_to_voice(text: str, gender: str = "m", retries: int = 3) -> FSInputFile:
    if gender == "rnd":
        # Filter out 'rnd' itself to avoid recursion if it were in keys (it's not but safe)
        keys = [k for k in VOICES.keys() if k != "rnd"]
        gender = random.choice(keys)

    config = VOICES.get(gender, VOICES["m"])
    text_len = len(text)

    # 1. Setup paths
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    temp_dir = os.path.join(base_dir, "temp")
    cache_dir = os.path.join(base_dir, "cache", "tts")

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # 2. Check Cache
    unique_string = f"{text}_{config['voice']}_{config['pitch']}_{config['rate']}"
    cache_key = hashlib.md5(unique_string.encode("utf-8")).hexdigest()
    cache_path = os.path.join(cache_dir, f"{cache_key}.mp3")

    file_path = os.path.join(temp_dir, f"{uuid.uuid4()}.mp3")

    if os.path.exists(cache_path):
        try:
            shutil.copy(cache_path, file_path)
            logging.info(f"TTS Cache Hit: {cache_key}")
            return FSInputFile(file_path)
        except Exception as e:
            logging.error(f"Cache copy failed: {e}")

    # 3. Check Azure Eligibility
    use_azure = False
    month_key = get_month_key()

    # Only if keys are present
    if AZURE_SPEECH_KEY and AZURE_SPEECH_REGION:
        try:
            current_usage = db.increment_global_config(month_key, 0)
            if current_usage + text_len < AZURE_MONTHLY_LIMIT:
                use_azure = True
            else:
                logging.info(f"Azure limit reached for {month_key}: {current_usage}")
        except Exception as e:
            logging.error(f"DB error checking TTS usage: {e}")

    # 4. Try Azure if eligible
    if use_azure:
        try:
            await generate_azure_speech(text, config, file_path)
            # If success, increment counter AND cache
            db.increment_global_config(month_key, text_len)
            logging.info(f"Azure TTS success. Used: {text_len} chars")

            try:
                shutil.copy(file_path, cache_path)
            except Exception as e:
                logging.error(f"Failed to save to cache: {e}")

            return FSInputFile(file_path)
        except Exception as e:
            logging.error(f"Azure TTS failed, falling back to Edge: {e}")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    pass

    # 5. Fallback to Edge TTS
    async with semaphore:
        for attempt in range(retries):
            try:
                communicate = edge_tts.Communicate(
                    text, config["voice"], pitch=config["pitch"], rate=config["rate"]
                )
                await communicate.save(file_path)

                # Save to cache also for Edge
                try:
                    shutil.copy(file_path, cache_path)
                except Exception as e:
                    logging.error(f"Failed to save to cache (Edge): {e}")

                return FSInputFile(file_path)
            except Exception as e:
                if attempt == retries - 1:
                    raise e
                await asyncio.sleep(2**attempt)

    raise Exception("Failed to generate voice after retries")


async def cleanup_voice(voice_file: FSInputFile):
    if not voice_file or not voice_file.path:
        return
    try:
        if os.path.exists(voice_file.path):
            os.remove(voice_file.path)
    except Exception as e:
        logging.warning(f"Failed to cleanup voice file: {e}")
