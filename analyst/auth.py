import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field

from analyst.models import StrictModel
from analyst.workspace_store import Store, configured

router = APIRouter(prefix="/api/auth")


async def auth_request(path, *, token=None, data=None):
    if not configured():
        raise HTTPException(
            503,
            "Private workspace setup required. Configure Supabase and provision the owner account.",
        )
    headers = {"apikey": os.environ["SUPABASE_ANON_KEY"]}
    if token:
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.request(
                "GET" if data is None else "POST",
                os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/" + path,
                headers=headers,
                json=data,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Sign-in service unavailable.") from exc
    if r.status_code >= 400:
        raise HTTPException(401, "Sign-in failed or session expired.")
    return r.json() if r.content else {}


async def require_owner(request: Request):
    token = request.cookies.get("sl_access")
    if not token:
        raise HTTPException(401, "Sign in to your private workspace.")
    user = await auth_request("user", token=token)
    owner = user.get("id", "")
    store = Store(owner)
    rows = await store.request(
        "GET", "/rest/v1/workspace_owners", params={"user_id": "eq." + owner}
    )
    if not rows:
        raise HTTPException(403, "This account is not the workspace owner.")
    return owner


class Login(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def cookies(response, session):
    secure = bool(os.getenv("VERCEL")) or os.getenv("COOKIE_SECURE", "true") == "true"
    for name, value, age in [
        ("sl_access", session["access_token"], session.get("expires_in", 3600)),
        ("sl_refresh", session["refresh_token"], 60 * 60 * 24 * 14),
    ]:
        response.set_cookie(
            name,
            value,
            max_age=age,
            httponly=True,
            secure=secure,
            samesite="strict",
            path="/api",
        )


@router.post("/login")
async def login(body: Login, response: Response):
    session = await auth_request("token?grant_type=password", data=body.model_dump())
    owner = session["user"]["id"]
    rows = await Store(owner).request(
        "GET", "/rest/v1/workspace_owners", params={"user_id": "eq." + owner}
    )
    if not rows:
        raise HTTPException(403, "This account is not the workspace owner.")
    cookies(response, session)
    return {"email": session["user"].get("email")}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("sl_refresh")
    if not token:
        raise HTTPException(401, "Sign in again.")
    session = await auth_request(
        "token?grant_type=refresh_token", data={"refresh_token": token}
    )
    if not await Store(session["user"]["id"]).request(
        "GET",
        "/rest/v1/workspace_owners",
        params={"user_id": "eq." + session["user"]["id"]},
    ):
        raise HTTPException(403, "Owner access required.")
    cookies(response, session)
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("sl_access")
    if token:
        try:
            await auth_request("logout", token=token, data={})
        except HTTPException:
            pass
    response.delete_cookie("sl_access", path="/api")
    response.delete_cookie("sl_refresh", path="/api")
    return {"ok": True}


@router.get("/session")
async def session(owner=Depends(require_owner)):
    return {"owner_id": owner}
