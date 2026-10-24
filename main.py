import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
HF_API_URL = "https://api-inference.huggingface.co/models"
# Active models
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")

app = FastAPI(title="AI Response Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OrchestrateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


@app.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest) -> dict[str, str]:
    groq_api_key = os.getenv("GROQ_API_KEY")
    hf_api_key = os.getenv("HF_API_KEY")
    
    missing_keys = [
        name
        for name, value in (
            ("GROQ_API_KEY", groq_api_key),
            ("HF_API_KEY", hf_api_key),
        )
        if not value
    ]
    if missing_keys:
        raise HTTPException(
            status_code=503,
            detail=f"Missing API key(s): {', '.join(missing_keys)}",
        )

    timeout = httpx.Timeout(60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            groq_response = await client.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {groq_api_key}"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": request.prompt}],
                },
            )
            groq_response.raise_for_status()
            groq_result = groq_response.json()
            groq_text = groq_result["choices"][0]["message"]["content"]
            if not isinstance(groq_text, str) or not groq_text.strip():
                raise ValueError("Groq returned an empty response")
        except httpx.HTTPStatusError as exc:
            # Print detail to console to facilitate debugging
            print("--- GROQ ERROR RESPONSE ---")
            print(exc.response.text)
            print("---------------------------")
            raise HTTPException(
                status_code=502,
                detail=f"Groq API returned HTTP {exc.response.status_code}: {exc.response.text}",
            ) from exc
        except (httpx.RequestError, KeyError, IndexError, ValueError) as exc:
            raise HTTPException(
                status_code=502, detail="Could not get a valid response from Groq"
            ) from exc

        try:
            hf_response = await client.post(
                f"{HF_API_URL}/{HF_MODEL}",
                headers={"Authorization": f"Bearer {hf_api_key}"},
                json={
                    "inputs": (
                        "Refine the following answer for clarity and accuracy while "
                        "preserving its meaning:\n\n"
                        f"{groq_text}"
                    ),
                    "options": {"wait_for_model": True},
                },
            )
            hf_response.raise_for_status()
            hf_result: Any = hf_response.json()
            if isinstance(hf_result, list) and hf_result:
                refined_text = hf_result[0].get("generated_text")
            elif isinstance(hf_result, dict):
                refined_text = hf_result.get("generated_text")
                if refined_text is None and hf_result.get("error"):
                    raise ValueError("Hugging Face returned an API error")
            else:
                refined_text = None

            if not isinstance(refined_text, str) or not refined_text.strip():
                raise ValueError("Hugging Face returned an empty response")
        except httpx.HTTPStatusError as exc:
            print("--- HF ERROR RESPONSE ---")
            print(exc.response.text)
            print("-------------------------")
            raise HTTPException(
                status_code=502,
                detail=f"Hugging Face Inference API returned HTTP {exc.response.status_code}: {exc.response.text}",
            ) from exc
        except (httpx.RequestError, KeyError, IndexError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail="Could not get a valid response from Hugging Face",
            ) from exc

    return {"groq_response": groq_text, "refined_response": refined_text}