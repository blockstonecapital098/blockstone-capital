"""
Root entrypoint for Hugging Face Spaces (Gradio SDK) and cloud deployments.
Runs FastAPI on port 7860 (Hugging Face default) or $PORT without requiring Docker or a credit card.
"""
import os
import uvicorn
from crypto_trading_desk.api.app import app

# Hugging Face Gradio SDK compatibility
try:
    import gradio as gr
    # Mount minimal Gradio app on /gradio so Hugging Face Space health check passes seamlessly
    io = gr.Interface(fn=lambda: "Blockstone Capital Active", inputs=None, outputs="text")
    app = gr.mount_gradio_app(app, io, path="/gradio")
except Exception:
    pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
