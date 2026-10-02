# GoldPathArchery backend

Initial FastAPI backend with a local authentication replica.

## Local setup

```powershell
cd C:\Users\swara\Developement\GoldPathArchery\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open Swagger UI at `http://127.0.0.1:8000/docs`.

## Local authentication

Development authentication exists only when both of these are true:

- `APP_ENV=local`
- `AUTH_MODE=dev`

Available local identities:

- `archer`
- `coach`
- `guardian`
- `admin`

Create a token:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/dev/login/archer
```

Then call `/api/me` with the returned bearer token.

The local token deliberately uses the same application-facing claims expected from the future external identity provider: `sub`, `email`, `name`, `roles`, `iss`, `aud`, `iat`, and `exp`.

No passwords are stored by GoldPathArchery. The development JWT secret is local-only and must never be used in Azure.

## Tests

```powershell
pytest
```
