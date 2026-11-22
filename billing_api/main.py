from fastapi import FastAPI

from billing_api.routers.bills import router as bills_router

app = FastAPI()
app.include_router(bills_router)

@app.get("/")
async def read_root():
    return {"message": "Welcome to the Billing API!"}