import os
import asyncio
from dotenv import load_dotenv
from google import genai

load_dotenv()

async def list_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("No API Key found")
        return

    client = genai.Client(api_key=api_key)
    
    print("Listing models...")
    try:
        # The new SDK might have different methods for listing models.
        # Attempting standard way for new SDK (client.models.list)
        # Note: client.models.list returns a pager
        for m in client.models.list():
             name = m.name
             if "gemini" in name:
                 print(f"Model: {name} | Display: {m.display_name}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())
