import asyncio
import json
import time
import uuid
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import config
from browser_bridge import bridge
from models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    ChatMessage,
    UsageInfo,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ModelListResponse,
    ModelItem
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize browser in the background so API starts quickly
    asyncio.create_task(bridge.initialize())
    yield
    # Shutdown: clean up browser resources
    await bridge.close()

app = FastAPI(
    title="Monkey Bridge OpenAI API",
    description="OpenAI-compatible REST API powered by ChatGPT Web automation",
    version="1.0.0",
    lifespan=lifespan
)

# CORS enabled for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def normalize_and_log_requests(request: Request, call_next):
    import re
    # Normalize duplicate slashes in path (e.g. /v1//chat/completions -> /v1/chat/completions)
    original_path = request.url.path
    clean_path = re.sub(r"/+", "/", original_path)
    if clean_path != original_path:
        request.scope["path"] = clean_path
    
    bridge.log(f"HTTP: {request.method} {clean_path}")
    response = await call_next(request)
    bridge.log(f"HTTP: {request.method} {clean_path} -> {response.status_code}")
    return response

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    """Serves the main dashboard and interactive chat playground."""
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")

@app.get("/v1")
@app.get("/v1/")
async def v1_ping():
    return {"status": "ok", "message": "Monkey Bridge OpenAI API is running."}

@app.get("/health")
@app.get("/api/status")
async def health_check():
    """Returns the operational status of the server and browser bridge."""
    return {
        "status": "online",
        "browser": bridge.get_status()
    }

@app.get("/api/account")
async def get_account_info():
    """Returns detailed ChatGPT account status."""
    return await bridge.update_all_accounts()

@app.post("/api/new-chat")
async def api_new_chat():
    """Manually resets the browser to a clean new chat."""
    await bridge.new_chat()
    return {"status": "success", "message": "New chat initialized."}

@app.post("/api/restart-browser")
async def api_restart_browser():
    """Restarts the browser session."""
    await bridge.close()
    await bridge.initialize()
    return {"status": "success", "message": "Browser restarted."}

@app.get("/v1/models")
@app.get("/models")
async def list_models():
    """OpenAI-compatible models listing endpoint."""
    return ModelListResponse(
        data=[ModelItem(**m) for m in config.AVAILABLE_MODELS]
    )

@app.get("/v1/models/{model_id:path}")
@app.get("/models/{model_id:path}")
async def get_model(model_id: str):
    return {
        "id": model_id,
        "object": "model",
        "created": 1715367049,
        "owned_by": "openai"
    }

@app.post("/v1/chat/completions")
@app.post("/chat/completions")
@app.post("/v1/responses")
@app.post("/responses")
async def chat_completions(req: ChatCompletionRequest):
    """
    OpenAI-compatible Chat Completions endpoint.
    Supports both non-streaming (JSON) and streaming (SSE) modes.
    """
    prompt = bridge.format_messages(req.messages)
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="Messages array cannot be empty.")

    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_time = int(time.time())
    model_name = req.model or "gpt-4o"

    # Streaming mode
    if req.stream:
        async def event_generator() -> AsyncGenerator[str, None]:
            first_chunk = True
            try:
                async for text_delta in bridge.stream_chat_completion(
                    prompt=prompt,
                    model=model_name,
                    provider=req.provider,
                    new_chat=req.new_chat
                ):
                    delta_data = ChatCompletionChunkDelta(
                        role="assistant" if first_chunk else None,
                        content=text_delta
                    )
                    first_chunk = False

                    chunk = ChatCompletionChunk(
                        id=chat_id,
                        created=created_time,
                        model=model_name,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=0,
                                delta=delta_data,
                                finish_reason=None
                            )
                        ]
                    )
                    yield f"data: {chunk.model_dump_json()}\n\n"

                # Send final stop chunk
                stop_chunk = ChatCompletionChunk(
                    id=chat_id,
                    created=created_time,
                    model=model_name,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(),
                            finish_reason="stop"
                        )
                    ]
                )
                yield f"data: {stop_chunk.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"

            except Exception as e:
                error_obj = {"error": {"message": str(e), "type": "server_error"}}
                yield f"data: {json.dumps(error_obj)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream"
            }
        )

    # Non-streaming mode
    try:
        completion_text = await bridge.send_chat_completion(
            prompt=prompt,
            model=model_name,
            provider=req.provider,
            new_chat=req.new_chat
        )
        
        # Token estimation (rough estimate: ~4 chars per token)
        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(completion_text) // 4)

        response = ChatCompletionResponse(
            id=chat_id,
            created=created_time,
            model=model_name,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=completion_text
                    ),
                    finish_reason="stop"
                )
            ],
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Monkey Bridge Error: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=False)
