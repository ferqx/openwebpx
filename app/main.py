from fastapi import FastAPI

app = FastAPI()


@app.get("/custom/hello")
async def hello():
    return {"message": "Hello from custom route!"}


@app.post("/custom/webhook")
async def webhook(data: dict):
    return {"received": data, "status": "processed"}


# You can override shadowable routes like the root
@app.get("/")
async def custom_root():
    return {"message": "Custom Aegra Server", "custom": True}
