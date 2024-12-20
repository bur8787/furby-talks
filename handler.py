import RPi.GPIO as GPIO
import pyaudio
import webrtcvad
import openai
import requests
import subprocess
import wave
from google.cloud import speech
from os import environ
import asyncio
import pvporcupine
from collections import deque

# OpenAI APIキーの設定
openai.api_key = environ["OPENAI_API_KEY"]

# VOICEVOX LambdaのAPIエンドポイント（環境変数から取得）
VOICEVOX_API_URL = environ["VOICEVOX_API_URL"]

# GPIO設定
MOTOR_PIN = 17  # GPIOピン番号を指定（例：17番ピン）
GPIO.setmode(GPIO.BCM)
GPIO.setup(MOTOR_PIN, GPIO.OUT)

# 音声録音設定
RATE = 16000  # サンプリングレート
FRAME_DURATION_MS = 20  # フレーム長（ms）
CHUNK = int(RATE * FRAME_DURATION_MS / 1000)  # フレームサイズ

# PyAudioとVADの初期化
audio = pyaudio.PyAudio()
vad = webrtcvad.Vad(3)  # 感度を0（低）から3（高）まで調整可能

# Porcupineの初期化
porcupine = pvporcupine.create(
    access_key=environ["PICOVOICE_ACCESS_KEY"],  # Picovoice Consoleで取得したアクセスキー
    keyword_paths=[environ["PICOVOICE_KEYWORD_PATH"]],  # "プリン"のウェイクワードモデルのファイルパス
    model_path=environ["PICOVOICE_MODEL_PATH"]
)

# Google Speech-to-Text クライアントの初期化
speech_client = speech.SpeechClient()

# 最大20件の履歴を保持するためのキュー（FIFO）
conversation_history = deque(maxlen=20)

persona = {"role": "system", "content": "あなたはファービーというぬいぐるみのおもちゃで、魔法の力で喋るようになりました。名前はプリンです。たかひろ、ちひろ、そうた、あきとと友達です。30文字以下で話してね。普通の会話のように、ただ相槌を打つだけでもいいです。積極的に質問をしてください"}

# モーターをオンにする
def start_motor():
    print("モーターをオンにします...")
    GPIO.output(MOTOR_PIN, GPIO.HIGH)  # モーターに電力を供給

# モーターをオフにする
def stop_motor():
    print("モーターをオフにします...")
    GPIO.output(MOTOR_PIN, GPIO.LOW)  # モーターへの電力供給を停止

# 録音の開始
def start_recording():
    stream = audio.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    silence_duration = 0
    threshold_silence_frames = 80  # 例えば30フレーム以上無音であれば喋り終わりと判断

    print("Listening for voice...")

    while True:
        data = stream.read(CHUNK)
        frames.append(data)

        # VADで音声を検知（サンプルをフレームとして処理）
        try:
            is_speech = vad.is_speech(data, RATE)
        except webrtcvad.VadError as e:
            print(f"Error while processing frame: {e}")
            continue

        if is_speech:
            silence_duration = 0  # 喋りが続いている間はリセット
        else:
            silence_duration += 1

        # 一定時間の無音が続いたら録音を終了
        if silence_duration > threshold_silence_frames:
            print("Silence detected, stopping recording...")
            break

    stream.stop_stream()
    stream.close()

    return b''.join(frames)

# 録音データを保存
def save_wav_file(audio_data, filename="input.wav"):
    wf = wave.open(filename, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
    wf.setframerate(RATE)
    wf.writeframes(audio_data)
    wf.close()

# OpenAI ChatGPT APIで質問
async def get_chatgpt_response(text):
    conversation_history.append({"role": "user", "content": text})

    messages = [persona] + list(conversation_history)  # パーソナと過去の会話を合わせて送信
    client = openai.AsyncOpenAI()
    completion = await client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=100,
                                                      temperature=0.7)

    response_text = completion.choices[0].message.content
    conversation_history.append({"role": "assistant", "content": response_text})
    return response_text

# VOICEVOX Lambdaで音声を生成
def generate_voice(text):
    # Lambda関数にリクエストを送信して音声を生成
    response = requests.post(VOICEVOX_API_URL, data={"text": text})

    if response.status_code != 200:
        print("Failed to generate voice via Lambda.")
        return None

    # MP3ファイルのバイナリデータを保存
    audio_file = "output.mp3"
    with open(audio_file, "wb") as f:
        f.write(response.content)

    return audio_file

# 音声を再生
def play_voice(audio_file):
    start_motor()  # 音声再生前にモーターをオン
    subprocess.run(["mpg123", audio_file])  # Raspberry PiでMP3ファイルを再生する
    stop_motor()  # 音声再生後にモーターをオフ

# Google Speech-to-Text APIで音声をテキストに変換
def recognize_speech_google(audio_data):
    # WAVファイルとして保存された音声データを開く
    with open("input.wav", "rb") as audio_file:
        content = audio_file.read()

    # 音声認識の設定
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="ja-JP",  # 日本語認識を指定
    )

    # 音声認識リクエスト
    response = speech_client.recognize(config=config, audio=audio)

    # 音声認識の結果を返す
    for result in response.results:
        return result.alternatives[0].transcript

    return None


# Porcupineでウェイクワードを待機
def wait_for_wakeword():
    stream = audio.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=porcupine.frame_length
    )

    print("Waiting for wake word...")
    while True:
        pcm = stream.read(porcupine.frame_length)
        pcm = [int.from_bytes(pcm[i:i+2], 'little') for i in range(0, len(pcm), 2)]
        if porcupine.process(pcm) >= 0:
            print("Wake word detected!")
            break

    stream.stop_stream()
    stream.close()


# 会話ループ
async def conversation_loop():
    audio_file = generate_voice("僕はプリン。話したいときはプリンって呼んでね。")
    if audio_file:
        play_voice(audio_file)

    while True:
        conversation_history.clear()  # 会話履歴をクリア
        wait_for_wakeword()

        audio_file = generate_voice("何？")
        if audio_file:
            play_voice(audio_file)

        while True:
            # 1. 録音開始
            audio_data = start_recording()
            save_wav_file(audio_data, "input.wav")

            # 2. 音声認識（Google Speech-to-Text）
            recognized_text = recognize_speech_google(audio_data)
            print(f"Recognized Text: {recognized_text}")

            if recognized_text is None:
                response_text = "お返事がないから寝るね。また喋りたくなったら「プリン」って呼んでね。"
                audio_file = generate_voice(response_text)
                if audio_file:
                    play_voice(audio_file)
                break

            if "バイバイ" in recognized_text.lower():
                response_text = "バイバイ、またね。また喋りたくなったら「プリン」って呼んでね"
                audio_file = generate_voice(response_text)
                if audio_file:
                    play_voice(audio_file)
                break  # Wakewordを再度待つ

            # 3. ChatGPTに質問を投げる
            response = await get_chatgpt_response(recognized_text)
            print(f"ChatGPT Response: {response}")

            # 4. ChatGPTの応答をVOICEVOX Lambdaで音声生成
            audio_file = generate_voice(response)

            # 5. 生成した音声を再生
            if audio_file:
                play_voice(audio_file)

# メインフロー
if __name__ == "__main__":
    try:
        asyncio.run(conversation_loop())  # 非同期関数を実行
    finally:
        porcupine.delete()
        GPIO.cleanup()  # 終了時にGPIOをクリーンアップ
