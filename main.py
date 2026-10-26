import os
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi.exceptions import RequestValidationError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
HF_API_URL = "https://router.huggingface.co/hf-inference/models"
HF_CANDIDATE_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.2-1B-Instruct",
    "HuggingFaceH4/zephyr-7b-beta",
    "mistralai/Mistral-7B-Instruct-v0.2",
]

# Active models supported by hf-inference router
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

app = FastAPI(title="AI Response Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if request.method == "POST" and request.url.path == "/api/orchestrate":
        return JSONResponse(
            status_code=422,
            content={"detail": "Che, mandame un prompt que no esté vacío y lo intento."},
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(HTTPException)
async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    if request.method == "POST" and request.url.path == "/api/orchestrate":
        if exc.status_code == 503:
            message = "Uy, me faltan unas claves para poder procesar tu pedido."
        elif exc.status_code == 502:
            message = (
                "Ups, los servicios de IA tuvieron un problema. "
                "Probá de nuevo en un ratito."
            )
        else:
            message = "Uy, no pude completar tu pedido. Probá de nuevo."
        return JSONResponse(status_code=exc.status_code, content={"detail": message})
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    if request.method == "POST" and request.url.path == "/api/orchestrate":
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "Se me complicó procesar tu pedido. "
                    "Probá de nuevo en un ratito."
                )
            },
        )
    raise exc


class OrchestrateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


@app.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest) -> dict[str, str]:
    groq_api_key = os.getenv("GROQ_API_KEY")
    hf_api_key = os.getenv("HF_API_KEY")
    
    if not groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="Missing API key: GROQ_API_KEY",
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

        refined_text = "[Hugging Face refinamiento no disponible en este momento]"
        if hf_api_key:
            for model in HF_CANDIDATE_MODELS:
                try:
                    hf_response = await client.post(
                        f"{HF_API_URL}/{model}",
                        headers={"Authorization": f"Bearer {hf_api_key}"},
                        json={
                            "inputs": (
                                "Refine the following answer for clarity and accuracy "
                                "while preserving its meaning:\n\n"
                                f"{groq_text}"
                            ),
                            "options": {"wait_for_model": True},
                        },
                    )
                    hf_response.raise_for_status()
                    hf_result: Any = hf_response.json()

                    if (
                        isinstance(hf_result, list)
                        and hf_result
                        and isinstance(hf_result[0], dict)
                    ):
                        candidate_text = hf_result[0].get("generated_text")
                    elif isinstance(hf_result, dict):
                        candidate_text = hf_result.get("generated_text")
                    else:
                        candidate_text = None

                    if isinstance(candidate_text, str) and candidate_text.strip():
                        refined_text = candidate_text
                        break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (400, 404):
                        continue
                    print(
                        f"Hugging Face returned HTTP "
                        f"{exc.response.status_code} for {model}"
                    )
                    break
                except (
                    httpx.RequestError,
                    ValueError,
                    KeyError,
                    IndexError,
                    TypeError,
                    AttributeError,
                ) as exc:
                    print(f"Hugging Face request failed for {model}: {exc}")
                    break

    return {"groq_response": groq_text, "refined_response": refined_text}