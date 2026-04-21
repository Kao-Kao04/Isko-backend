import pytest


@pytest.mark.asyncio
async def test_register_student(client):
    response = await client.post("/api/auth/register", json={
        "email": "test@pup.edu.ph",
        "password": "password123",
        "student_number": "2021-12345",
        "first_name": "Juan",
        "last_name": "Dela Cruz",
        "college": "CCIS",
        "program": "BSIT",
        "year_level": 2,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@pup.edu.ph"
    assert data["role"] == "student"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {
        "email": "dup@pup.edu.ph",
        "password": "password123",
        "student_number": "2021-99999",
        "first_name": "Juan",
        "last_name": "Dela Cruz",
        "college": "CCIS",
        "program": "BSIT",
        "year_level": 2,
    }
    await client.post("/api/auth/register", json=payload)
    response = await client.post("/api/auth/register", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login(client):
    await client.post("/api/auth/register", json={
        "email": "login@pup.edu.ph",
        "password": "password123",
        "student_number": "2021-11111",
        "first_name": "Maria",
        "last_name": "Santos",
        "college": "CCIS",
        "program": "BSIT",
        "year_level": 1,
    })
    response = await client.post("/api/auth/login", json={
        "email": "login@pup.edu.ph",
        "password": "password123",
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    response = await client.post("/api/auth/login", json={
        "email": "login@pup.edu.ph",
        "password": "wrongpassword",
    })
    assert response.status_code == 401
